# SPDX-License-Identifier: MIT
"""The settings page's request handling (D90): routes, sessions, CSRF,
rate limits, the admin and gate re-verifications, and the write actions
that all go through part A's store API.

Only POST changes state, and every POST is a form post carrying the
session's CSRF token; GET never writes. The request handler applies the
decided security headers to every response, and any refusal is a fixed
phrase — no submitted value is echoed back except the non-secret
endpoint and model, escaped, on a refused credentials submit."""

from __future__ import annotations

import hmac
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from atlas_reviewer import egress
from atlas_reviewer.installation_store import (
    STORE_BROKEN,
    InstallationRecord,
    InstallationStore,
    InstallationStoreError,
)
from atlas_reviewer.tenant_provider import PricingUnknownError
from atlas_settings import checks, pages
from atlas_settings.audit import AuditLog
from atlas_settings.config import SettingsConfig
from atlas_settings.github import (
    GitHubClient,
    GitHubRefused,
    GitHubUser,
    InstallationAccount,
    new_login_challenge,
)
from atlas_settings.phrases import (
    ADMIN_REFUSED,
    CONSENT_REFUSED,
    CONSENT_UNCHECKED,
    CSRF_REFUSED,
    ENDPOINT_REFUSED_PREFIX,
    GATE_REFUSED,
    GITHUB_CHECK_FAILED,
    KEY_REFUSED,
    LOGIN_FAILED,
    MODEL_REFUSED_PREFIX,
    RATE_LIMITED,
    SESSION_EXPIRED,
    STORE_REFUSED_PREFIX,
)
from atlas_settings.ratelimit import RateLimiter
from atlas_settings.sessions import (
    Session,
    SessionError,
    SessionStore,
    cookie_header,
)

# Rate limits (D90): sign-in per IP, writes per session and per IP.
LOGIN_LIMIT = 10
LOGIN_WINDOW_S = 300.0
WRITE_SESSION_LIMIT = 30
WRITE_IP_LIMIT = 120
WRITE_WINDOW_S = 300.0
# The bounded request body: the page's forms are a handful of fields.
MAX_BODY_BYTES = 8192

type Validator = Callable[[str], tuple[Decimal, Decimal]]

STYLES_ROOT = Path(__file__).resolve().parent / "static"


@dataclass(frozen=True)
class Response:
    status: int
    body: bytes
    content_type: str = "text/html; charset=utf-8"
    location: str | None = None
    set_cookie: str | None = None


class AuthorizationRefused(Exception):
    """A write or page was refused before the store was touched; the
    response carries the fixed phrase."""

    def __init__(self, response: Response) -> None:
        super().__init__(f"HTTP {response.status}")
        self.response = response


@dataclass
class SettingsApp:
    """The page's application logic, one instance per process.

    The egress resolver and the model validator are constructor seams:
    production passes nothing (the real guard and the real price-table
    read run), tests pass fakes, and neither seam can widen what the
    page accepts — a fake can only refuse."""

    config: SettingsConfig
    store: InstallationStore
    github: GitHubClient
    sessions: SessionStore
    limiter: RateLimiter
    audit: AuditLog
    resolve: Callable[[str, int], egress.Pinned] | None = None
    validate_model_fn: Validator | None = None
    # The named seam for part B2 (the per-repo pre-approved command list,
    # D88's 12:05 PM CT update): part B2's management actions slot into
    # this dispatch beside these actions, on the same page and the same
    # session/admin/gate machinery, when #775 merges. The third argument
    # is the allowlist coverage `post` verified for the request.
    write_actions: dict[str, Callable[[Session, dict[str, str], int], Response]] = (
        field(default_factory=dict)
    )

    # ---- GET -------------------------------------------------------

    def get(self, path: str, query: str, cookie: str, remote_addr: str) -> Response:
        if path in ("/", "/index.html"):
            session = self.sessions.get(cookie)
            if session is not None and session.signed_in:
                return self._redirect("/settings")
            return self._page(pages.login_page(), 200)
        if path == "/login":
            return self._start_login(remote_addr)
        if path == "/callback":
            return self._callback(query, cookie, remote_addr)
        if path == "/settings":
            return self._settings_page(cookie)
        if path == "/static/styles.css":
            return self._stylesheet()
        return self._not_found()

    # ---- POST ------------------------------------------------------

    def post(
        self,
        path: str,
        form: dict[str, str],
        cookie: str,
        remote_addr: str,
    ) -> Response:
        if not path.startswith("/settings/") or path.count("/") != 2:
            return self._not_found()
        action = path.removeprefix("/settings/")
        session = self.sessions.get(cookie)
        if session is None or not session.signed_in:
            return self._page(pages.error_page("Session expired", SESSION_EXPIRED), 403)
        if not self.limiter.allow(
            f"write-session:{session.sid}", WRITE_SESSION_LIMIT, WRITE_WINDOW_S
        ) or not self.limiter.allow(
            f"write-ip:{remote_addr}", WRITE_IP_LIMIT, WRITE_WINDOW_S
        ):
            return self._page(pages.error_page("Refused", RATE_LIMITED), 429)
        submitted = form.get("csrf", "")
        # Compared as encoded bytes: `compare_digest` refuses non-ASCII
        # `str` outright, and a hostile token is not allowed to become
        # a 500 — it is just a mismatch (#794's review's sibling check).
        if not submitted or not hmac.compare_digest(
            submitted.encode("utf-8"), session.csrf.encode("utf-8")
        ):
            return self._page(pages.error_page("Refused", CSRF_REFUSED), 403)
        handler = self._action_handler(action)
        if handler is None:
            return self._not_found()
        try:
            # The admin check and the gate are re-verified on every
            # write, fail closed: any GitHub error refuses, never waves
            # the write through.
            self._require_admin_user(
                GitHubUser(session.user_id or 0, session.login or "")
            )
            covered = self._require_gate()
        except AuthorizationRefused as refused:
            return refused.response
        try:
            # The gate's just-verified coverage rides along: a refusal
            # re-render shows the real count, not a hardcoded zero.
            return handler(session, form, covered)
        except AuthorizationRefused as refused:
            return refused.response

    def _action_handler(
        self, action: str
    ) -> Callable[[Session, dict[str, str], int], Response] | None:
        # The `covered` argument is the allowlist count `post` verified
        # moments before the handler ran; part B2's actions take it too.
        builtins: dict[str, Callable[[Session, dict[str, str], int], Response]] = {
            "consent": self._post_consent,
            "credentials": self._post_credentials,
        }
        return builtins.get(action, self.write_actions.get(action))

    # ---- actions ---------------------------------------------------

    def _post_consent(
        self, session: Session, form: dict[str, str], covered: int
    ) -> Response:
        if form.get("acknowledge", "") != "1":
            return self._settings_render(session, CONSENT_UNCHECKED, 400, covered)
        self._write(
            session,
            "record-consent",
            lambda: self.store.record_consent(self.config.installation_id),
            covered,
        )
        return self._redirect("/settings")

    def _post_credentials(
        self, session: Session, form: dict[str, str], covered: int
    ) -> Response:
        try:
            record = self._load_record()
        except InstallationStoreError as exc:
            return self._store_refused(session, exc, covered)
        if record is None or record.consent_acknowledged_at is None:
            # Saving credentials without consent stores nothing and says
            # why (D90): the refusal names the consent, never the form's
            # values.
            return self._settings_render(session, CONSENT_REFUSED, 403, covered)
        base_url = form.get("base_url", "").strip()
        key = form.get("key", "")
        model = form.get("model", "").strip()
        # The prefill shows the endpoint the admin typed, minus anything
        # credential-bearing: userinfo in the URL is a credential, and a
        # refusal page must not return one. The raw `base_url` stays
        # what the egress check judges.
        prefill_url = _prefill_endpoint(base_url)
        if not base_url or not key or not model:
            return self._settings_render(
                session,
                "the endpoint, the key and the model are all required",
                400,
                covered,
                prefill_base_url=prefill_url,
                prefill_model=model,
            )
        try:
            checks.validate_endpoint(base_url, resolve=self.resolve)
        except egress.EgressRefused as exc:
            return self._settings_render(
                session,
                f"{ENDPOINT_REFUSED_PREFIX}{exc}",
                400,
                covered,
                prefill_base_url=prefill_url,
                prefill_model=model,
            )
        try:
            model_fn = self.validate_model_fn or checks.validate_model
            model_fn(model)
        except PricingUnknownError as exc:
            return self._settings_render(
                session,
                f"{MODEL_REFUSED_PREFIX}{exc}",
                400,
                covered,
                prefill_base_url=prefill_url,
                prefill_model=model,
            )
        try:
            checks.check_key_against_controller_text(key)
        except InstallationStoreError:
            # The page's own intake check, not a store condition: the
            # refusal is a 400 with its own phrase and the same prefill
            # as the other intake refusals, not a store-attributed 503
            # with a blank form.
            return self._settings_render(
                session,
                KEY_REFUSED,
                400,
                covered,
                prefill_base_url=prefill_url,
                prefill_model=model,
            )
        try:
            # Every write goes through `_write`: the store refusal, the
            # unconfigured store, and the audit line are one path, so a
            # stored key can never be answered with a bare 500 as if
            # nothing happened, and an audit gap is answered with the
            # phrase that says the write landed.
            self._write(
                session,
                "store-credentials",
                lambda: self.store.store_credentials(
                    self.config.installation_id, base_url, key, model
                ),
                covered,
                prefill_base_url=prefill_url,
                prefill_model=model,
            )
        except AuthorizationRefused as refused:
            return refused.response
        return self._redirect("/settings")

    def _write(
        self,
        session: Session,
        action: str,
        write: Callable[[], object],
        covered: int,
        prefill_base_url: str = "",
        prefill_model: str = "",
    ) -> None:
        """The store write first, then the audit line for it. An audit
        failure after a successful store write is answered with the
        fixed phrase that says the write was applied — never a message
        that could read as if nothing happened. A store that is not
        configured refuses the write before anything is touched: an
        unconfigured store reports success for nothing (its `delete` is
        a no-op by design for the webhook path), and the page must never
        tell an admin a write landed when it cannot have."""
        if not self.store.configured:
            raise AuthorizationRefused(
                self._store_refused(
                    session,
                    InstallationStoreError(STORE_BROKEN),
                    covered,
                    prefill_base_url,
                    prefill_model,
                )
            )
        try:
            write()
        except InstallationStoreError as exc:
            raise AuthorizationRefused(
                self._store_refused(
                    session, exc, covered, prefill_base_url, prefill_model
                )
            ) from exc
        try:
            self.audit.record(action, self.config.installation_id, session.user_id or 0)
        except OSError as exc:
            raise AuthorizationRefused(
                Response(
                    500,
                    pages.error_page(
                        "Audit gap",
                        "the change was applied but could not be recorded "
                        "in the audit log",
                    ).encode("utf-8"),
                )
            ) from exc

    def _store_refused(
        self,
        session: Session,
        exc: InstallationStoreError,
        covered: int,
        prefill_base_url: str = "",
        prefill_model: str = "",
    ) -> Response:
        """The store's refusal, its reason carried as data: the store's
        messages are fixed text that never embed record contents. The
        render carries the coverage count `post` verified for this
        request, like every other refusal render, and — for a refused
        credentials save — the typed endpoint and model, so the admin
        re-types only the key."""
        return self._settings_render(
            session,
            f"{STORE_REFUSED_PREFIX}{exc}",
            503,
            covered,
            prefill_base_url=prefill_base_url,
            prefill_model=prefill_model,
        )

    # ---- authorization ----------------------------------------------

    def _require_admin_user(self, user: GitHubUser) -> InstallationAccount:
        """The issue's admin rule, fail closed: for a user-account
        installation the signed-in user's id equals the installation
        account's id; for an organization the user's membership in that
        org is `admin` and `active`, checked with the App's installation
        token minted for Organization "Members: read". Any API error,
        timeout, or unexpected shape refuses."""
        try:
            admin, account = self.github.admin_status(user)
        except GitHubRefused as exc:
            raise AuthorizationRefused(self._github_error_page()) from exc
        if not admin:
            raise AuthorizationRefused(
                self._page(pages.error_page("Refused", ADMIN_REFUSED), 403)
            )
        return account

    def _require_gate(self) -> int:
        """The invite-only gate, fail closed, re-checked wherever the
        admin check is: the installation must cover at least one repo on
        the allowlist, and a read that cannot establish the coverage
        refuses the request rather than satisfying the gate."""
        try:
            repos = self.github.installation_repositories()
        except GitHubRefused as exc:
            raise AuthorizationRefused(self._github_error_page()) from exc
        covered = sum(1 for name in repos if name in self.config.allowlist)
        if covered == 0:
            raise AuthorizationRefused(
                self._page(pages.error_page("Refused", GATE_REFUSED), 403)
            )
        return covered

    def _github_error_page(self) -> Response:
        return self._page(pages.error_page("Refused", GITHUB_CHECK_FAILED), 502)

    # ---- flows ------------------------------------------------------

    def _start_login(self, remote_addr: str) -> Response:
        if not self.limiter.allow(
            f"login-ip:{remote_addr}", LOGIN_LIMIT, LOGIN_WINDOW_S
        ):
            return self._page(pages.error_page("Refused", RATE_LIMITED), 429)
        challenge = new_login_challenge()
        _session, value = self.sessions.start_login(challenge.state, challenge.verifier)
        url = self.github.authorize_url(challenge, self._redirect_uri())
        # Lax, not Strict: the binding's only job is to survive the
        # round trip through GitHub's authorize page, and the redirect
        # back is a cross-site top-level GET navigation — a Strict
        # cookie is not sent on one, so the callback would never see
        # the binding it issued.
        return Response(
            302, b"", location=url, set_cookie=cookie_header(value, samesite="Lax")
        )

    def _callback(self, query: str, cookie: str, remote_addr: str) -> Response:
        if not self.limiter.allow(
            f"login-ip:{remote_addr}", LOGIN_LIMIT, LOGIN_WINDOW_S
        ):
            return self._page(pages.error_page("Refused", RATE_LIMITED), 429)
        params = urllib.parse.parse_qs(query, keep_blank_values=True)
        state = (params.get("state") or [""])[0]
        code = (params.get("code") or [""])[0]
        session = self.sessions.get(cookie)
        if (
            session is None
            or session.signed_in
            or session.state is None
            or not state
            # Compared as encoded bytes: `compare_digest` refuses
            # non-ASCII `str` outright, and a hostile state is not
            # allowed to become a 500 — it is just a mismatch.
            or not hmac.compare_digest(
                state.encode("utf-8"), session.state.encode("utf-8")
            )
        ):
            return self._page(pages.error_page("Refused", LOGIN_FAILED), 403)
        if not code:
            return self._page(pages.error_page("Refused", LOGIN_FAILED), 400)
        assert session.verifier is not None
        try:
            user = self.github.exchange_code(
                code, session.verifier, self._redirect_uri()
            )
        except GitHubRefused:
            return self._page(pages.error_page("Refused", LOGIN_FAILED), 502)
        try:
            self._require_admin_user(user)
            self._require_gate()
        except AuthorizationRefused as refused:
            return refused.response
        try:
            signed_in, value = self.sessions.upgrade(session, user.id, user.login)
        except SessionError:
            # An overlapping callback consumed this pre-login session
            # first; the loser answers the same fixed refusal a forged
            # state gets, never a 500.
            return self._page(pages.error_page("Refused", LOGIN_FAILED), 403)
        try:
            self.audit.record("login", self.config.installation_id, user.id)
        except OSError:
            # A sign-in without its audit line is an untracked identity
            # holding an authenticated session; the session just created
            # is destroyed so none survives unrecorded.
            self.sessions.destroy(signed_in)
            return self._page(
                pages.error_page(
                    "Audit gap",
                    "the sign-in could not be recorded in the audit log; "
                    "you were not signed in",
                ),
                500,
            )
        return self._redirect("/settings", set_cookie=cookie_header(value))

    def _settings_page(self, cookie: str) -> Response:
        session = self.sessions.get(cookie)
        if session is None or not session.signed_in:
            return self._redirect("/login")
        assert session.user_id is not None and session.login is not None
        try:
            account = self._require_admin_user(
                GitHubUser(session.user_id, session.login)
            )
            covered = self._require_gate()
        except AuthorizationRefused as refused:
            return refused.response
        try:
            record = self._load_record()
        except InstallationStoreError as exc:
            return self._page(
                pages.error_page("Store unavailable", f"{STORE_REFUSED_PREFIX}{exc}"),
                503,
            )
        body = self._render_settings(account, covered, record, session.csrf, flash=None)
        return self._page(body, 200)

    def _settings_render(
        self,
        session: Session,
        flash: str,
        status: int,
        covered: int,
        prefill_base_url: str = "",
        prefill_model: str = "",
    ) -> Response:
        """A refused write re-rendered as the settings page with the
        fixed phrase. The authorization checks already ran in `post`;
        this render only reads the store, the audit, and the
        installation's account, and anything that cannot be read renders
        the plain error page instead. On a GitHub failure the account
        row renders with placeholder dashes — the refusal's own phrase
        is the message, and the render must not fail trying to name the
        account. `covered` is the allowlist count `post` verified for
        this request, so the coverage row shows the verified fact."""
        try:
            account = self.github.installation_account()
        except GitHubRefused:
            account = InstallationAccount(0, "-", "-")
        try:
            record = self._load_record()
        except InstallationStoreError as exc:
            return self._page(
                pages.error_page("Store unavailable", f"{STORE_REFUSED_PREFIX}{exc}"),
                503,
            )
        body = self._render_settings(
            account,
            covered,
            record,
            session.csrf,
            flash=flash,
            prefill_base_url=prefill_base_url,
            prefill_model=prefill_model,
        )
        return self._page(body, status)

    # ---- rendering and record helpers -------------------------------

    def _render_settings(
        self,
        account: InstallationAccount,
        covered: int,
        record: InstallationRecord | None,
        csrf: str,
        flash: str | None,
        prefill_base_url: str = "",
        prefill_model: str = "",
    ) -> str:
        """The settings page from the record: the stored-credentials fact
        as the one value the page takes (or None), and — on a refused
        credentials submit — the endpoint and model the admin typed,
        refilled into the form."""
        credentials = (
            pages.StoredCredentials(
                saved_at=self._credentials_saved_at(record),
                base_url=record.base_url,
                model=record.model,
            )
            if record is not None and record.has_credentials
            else None
        )
        return pages.settings_page(
            installation_id=self.config.installation_id,
            account_login=account.login,
            account_type=account.type,
            allowlisted_repo_count=covered,
            credentials=credentials,
            consent_acknowledged_at=(
                record.consent_acknowledged_at if record is not None else None
            ),
            daily_cap_usd=(
                None
                if record is None or record.daily_cap_usd is None
                else _cap_text(record.daily_cap_usd)
            ),
            csrf=csrf,
            flash=flash,
            prefill_base_url=prefill_base_url,
            prefill_model=prefill_model,
        )

    def _load_record(self) -> InstallationRecord | None:
        return self.store.load(self.config.installation_id)

    def _credentials_saved_at(
        self, record: InstallationRecord | None
    ) -> datetime | None:
        """When the credentials were last saved: the audit's own record
        of the last store-credentials write, falling back to the
        record's `updated_at` (shown as "not on record" when neither
        answers — a lost audit line loses only the shown time)."""
        audited = self.audit.last_credentials_at(self.config.installation_id)
        if audited is not None:
            return audited
        return record.updated_at if record is not None else None

    def _redirect_uri(self) -> str:
        return self.config.base_url.rstrip("/") + "/callback"

    def _redirect(self, location: str, set_cookie: str | None = None) -> Response:
        return Response(303, b"", location=location, set_cookie=set_cookie)

    def _page(self, body: str, status: int, set_cookie: str | None = None) -> Response:
        return Response(status, body.encode("utf-8"), set_cookie=set_cookie)

    def _stylesheet(self) -> Response:
        css = (STYLES_ROOT / "styles.css").read_bytes()
        return Response(200, css, content_type="text/css; charset=utf-8")

    def _not_found(self) -> Response:
        return self._page(pages.error_page("Not found", "there is no such page"), 404)


def _cap_text(cap: object) -> str:
    """The stored cap as the page shows it — a schema-validated decimal
    the store already accepted, formatted plainly."""
    assert isinstance(cap, Decimal)
    return f"{cap:f}"


def parse_form(body: bytes) -> dict[str, str]:
    """The submitted form as single-value fields. The body is decoded
    leniently (a hostile byte sequence renders to replacement
    characters) and parsed with the stdlib parser; the values are
    untrusted everywhere they travel, which is why nothing renders them
    unescaped."""
    parsed = urllib.parse.parse_qs(
        body.decode("utf-8", errors="replace"), keep_blank_values=True
    )
    return {name: values[0] for name, values in parsed.items() if values}


def remote_address(client_address: tuple[str, int] | str) -> str:
    return client_address[0] if isinstance(client_address, tuple) else client_address


def _prefill_endpoint(url: str) -> str:
    """The endpoint as the refusal prefill may show it. Userinfo in the
    URL — `user:password@host` — is a credential, and the page never
    returns a credential: the host side of the authority is kept, the
    userinfo is dropped. A URL the parser cannot read at all is not
    echoed either; the refusal's phrase names the problem anyway."""
    try:
        parts = urllib.parse.urlsplit(url)
    except ValueError:
        return ""
    if "@" not in parts.netloc:
        return url
    return urllib.parse.urlunsplit(
        (
            parts.scheme,
            parts.netloc.rpartition("@")[2],
            parts.path,
            parts.query,
            parts.fragment,
        )
    )
