# SPDX-License-Identifier: MIT
"""The installation secrets store (config slice S10, part A; D81 §7
decision 9 and the 5:51 PM CT amendment): one encrypted record per App
installation, holding the tenant-supplied model credentials plus the
installation admin's daily cap and the consent acknowledgement.

Every record is encrypted at rest under an operator-held key read from
`ATLAS_INSTALLATION_STORE_KEY` (a Fernet key, `cryptography`'s
authenticated encryption -- already locked for `PyJWT[crypto]`; nothing
hand-rolled), and lives on the state volume at
`<state root>/installations/<installation id>.json`. Writes are atomic
(temp file, fsync, rename) and private (0700 directory, 0600 file).

Every read **fails closed**: a store that is unreadable, corrupt, or
encrypted under the wrong key raises `InstallationStoreError` naming the
reason, and the caller refuses rather than falls back -- a tenant review
fails with the failure named plainly, never a clean-looking review, and
no operator-key path opens for it. A store the operator never configured
(key unset, no records on disk) is not a failure: no installation has
credentials, so no tenant path exists and no cap applies -- but a store
whose key is gone while records remain on disk **is** a failure, because
the records it cannot read may hold credentials the routing rule would
otherwise send to the operator's key.

Keys never appear in a repr, a log line, an exception message, or a
post: `InstallationRecord.__repr__` and `TenantCredentials.__repr__`
mask the key field, and no error path embeds record contents.

This module is part A's half of the surface: part B (the operator-hosted
settings page) stores and rotates credentials, revokes them, sets or
clears the cap, records the consent acknowledgement, and deletes
everything through the methods below; the review path reads records and
the daily cap through `load` and `installation_cap`; the
`installation.deleted` webhook deletes the record and the retention
sweep (`sweep`, window `ATLAS_INSTALLATION_RETENTION_DAYS`) deletes a
record whose state went unrefreshed past the window, catching a missed
event.
"""

from __future__ import annotations

import contextlib
import json
import os
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlsplit

from cryptography.fernet import Fernet, InvalidToken

from atlas_reviewer.ledger import make_private_dirs

ENV_STORE_KEY = "ATLAS_INSTALLATION_STORE_KEY"
ENV_RETENTION_DAYS = "ATLAS_INSTALLATION_RETENTION_DAYS"
# The default retention window for the sweep that catches a missed
# `installation.deleted` webhook: 30 days. Not set in any deployment
# yet; the operator raises or lowers it explicitly.
DEFAULT_RETENTION_DAYS = 30
_STORE_VERSION = 1
_MAX_ID_CHARS = 64
_MAX_URL_CHARS = 2048
_MAX_SECRET_CHARS = 4096
_MAX_MODEL_CHARS = 200
# The record document's own keys, so an unknown field fails closed
# instead of being carried silently.
_PAYLOAD_FIELDS = (
    "base_url",
    "key",
    "model",
    "daily_cap_usd",
    "consent_acknowledged_at",
    "updated_at",
)


class InstallationStoreError(RuntimeError):
    """The installation store failed and the caller must refuse: the
    message names the reason and never carries record contents."""


class ConsentNotAcknowledgedError(InstallationStoreError):
    """The installation has credentials but its admin has not yet
    acknowledged the data-policy consent (D81 §7 decision 3), so no
    tenant review may run: the PR diff would go to the installation's
    own endpoint."""


CONSENT_REQUIRED = (
    "the installation admin has not acknowledged the data-policy consent "
    "on the settings page: the PR diff would be sent to the "
    "installation's own endpoint, and no tenant review may run until it is"
)


def installation_id(raw: str) -> str:
    """The installation id validated for use as a file name: non-empty
    ASCII digits only, at most 64 of them, and a positive integer. The
    id GitHub sends is a number; anything else is refused, so a record
    path can never escape the store directory."""
    if (
        not raw
        or len(raw) > _MAX_ID_CHARS
        or not raw.isascii()
        or not raw.isdigit()
        or int(raw) < 1
    ):
        raise InstallationStoreError(
            "an installation id must be a positive integer of at most "
            f"{_MAX_ID_CHARS} digits"
        )
    return raw


def retention_days(env: Mapping[str, str]) -> int:
    """The retention sweep's window, `ATLAS_INSTALLATION_RETENTION_DAYS`,
    in days: the 30-day default when unset, and a `ValueError` naming
    the variable when a set value is not a positive integer -- an
    unusable operator setting stops the deployment at boot, the way the
    other operator loaders refuse."""
    raw = env.get(ENV_RETENTION_DAYS)
    if raw is None or raw == "":
        return DEFAULT_RETENTION_DAYS
    if not raw.isascii() or not raw.isdigit() or int(raw) < 1 or len(raw) > 9:
        raise ValueError(
            f"{ENV_RETENTION_DAYS} must be a positive whole number of days, not {raw!r}"
        )
    return int(raw)


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class TenantCredentials:
    """The tenant-supplied model credentials one review runs on: the
    endpoint base URL, the key, and the chosen model. The key is never
    logged, posted, or repr'd."""

    base_url: str
    key: str
    model: str

    def __repr__(self) -> str:
        return (
            f"TenantCredentials(base_url={self.base_url!r}, "
            f"key=<redacted>, model={self.model!r})"
        )


@dataclass(frozen=True)
class InstallationRecord:
    """One installation's stored state (D81 §7 decision 9, amended
    5:51 PM CT): the tenant-supplied credentials, the installation
    admin's daily cap, and the consent acknowledgement. A record whose
    credentials were revoked carries empty credential fields and
    `has_credentials` false; its cap and consent survive the revocation."""

    installation_id: str
    base_url: str
    key: str
    model: str
    daily_cap_usd: Decimal | None
    consent_acknowledged_at: datetime | None
    updated_at: datetime

    @property
    def has_credentials(self) -> bool:
        return bool(self.base_url) and bool(self.key) and bool(self.model)

    def credentials(self) -> TenantCredentials:
        """The tenant credentials this record holds, refused when it
        does not hold them: the caller must have checked
        `has_credentials` first, and the store refuses instead of
        handing out an empty key."""
        if not self.has_credentials:
            raise InstallationStoreError("the installation has no stored credentials")
        return TenantCredentials(self.base_url, self.key, self.model)

    def __repr__(self) -> str:
        return (
            f"InstallationRecord(installation_id={self.installation_id!r}, "
            f"base_url={self.base_url!r}, key=<redacted>, "
            f"model={self.model!r}, "
            f"daily_cap_usd={self.daily_cap_usd!r}, "
            f"consent_acknowledged_at={self.consent_acknowledged_at!r}, "
            f"updated_at={self.updated_at!r})"
        )


@dataclass
class InstallationStore:
    """The per-installation encrypted records under one state root.

    Constructed through `open`, which is `None`-equivalent only by
    returning a store in the unconfigured mode: with no key set and no
    records on disk, no installation has credentials, so `load` answers
    None and `installation_cap` answers None for every id. Any other
    broken condition -- key unset with records on disk, an invalid key,
    an unreadable or corrupt record -- makes every read raise
    `InstallationStoreError`, so a broken store never opens the tenant
    path or the budget."""

    root: Path
    fernet: Fernet | None = None
    broken_reason: str = ""
    clock: Callable[[], datetime] = field(default_factory=lambda: _utc_now)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @classmethod
    def open(cls, state_dir: Path, env: Mapping[str, str]) -> InstallationStore:
        """The store for one deployment.

        No key and no records on disk: the unconfigured store -- no
        tenant path, no caps, and nothing to fail. No key with records
        on disk, or a key that is not a valid Fernet key: the broken
        store, whose every read raises the named reason, because the
        records it cannot read may hold credentials the routing rule
        must not silently replace with the operator's key."""
        root = store_root(state_dir)
        raw = env.get(ENV_STORE_KEY, "")
        if not raw:
            if _has_records(root):
                return cls(
                    root,
                    broken_reason=(
                        f"{ENV_STORE_KEY} is not set, but the installation "
                        "store on the state volume holds records; reviews "
                        "fail closed until the key is restored"
                    ),
                )
            return cls(root)
        try:
            fernet = Fernet(raw.encode("ascii"))
        except (ValueError, InvalidToken, UnicodeEncodeError):
            return cls(
                root,
                broken_reason=(
                    f"{ENV_STORE_KEY} is set but is not a valid Fernet key; "
                    "reviews fail closed until it is corrected"
                ),
            )
        return cls(root, fernet)

    @property
    def configured(self) -> bool:
        """True when the store can actually read and write records."""
        return self.fernet is not None and not self.broken_reason

    def installation_cap(self) -> Callable[[str], Decimal | None]:
        """The cap provider `budget.DailySpend` takes (config slice S9/S10):
        an installation id in, its admin's daily cap or None when none is
        set. A store failure raises `InstallationStoreError`, which the
        budget's refusal turns into the fixed fail-closed refusal -- an
        unreadable store is not evidence that no cap applies."""
        return self._cap

    def _cap(self, installation: str) -> Decimal | None:
        record = self.load(installation)
        return None if record is None else record.daily_cap_usd

    def load(self, installation: str) -> InstallationRecord | None:
        """One installation's record, or None when it has none. A broken
        store raises `InstallationStoreError` naming the reason and
        never falls back; the unconfigured store (no key, no records on
        disk) has no records to return, so it answers None whatever id
        it is asked for."""
        if self.broken_reason:
            raise InstallationStoreError(self.broken_reason)
        if self.fernet is None:
            return None
        ident = installation_id(installation)
        with self._lock:
            return self._read(ident)

    def store_credentials(
        self, installation: str, base_url: str, key: str, model: str
    ) -> InstallationRecord:
        """Create or rotate the installation's credentials (part B's
        store and rotate calls). The base URL must be an HTTPS URL with
        a hostname and no userinfo, query, or fragment -- the full
        egress check runs per connection, not here; the key and model
        must be non-empty and bounded. A failed validation raises
        before anything is written."""
        ident = installation_id(installation)
        checked = _check_base_url(base_url)
        if not key or len(key) > _MAX_SECRET_CHARS or "\x00" in key:
            raise InstallationStoreError(
                "the installation's API key must be 1 to "
                f"{_MAX_SECRET_CHARS} characters"
            )
        checked_model = _check_model(model)
        return self._write_record(
            ident,
            lambda current: InstallationRecord(
                ident,
                checked,
                key,
                checked_model,
                current.daily_cap_usd if current is not None else None,
                (current.consent_acknowledged_at if current is not None else None),
                self.clock(),
            ),
        )

    def revoke_credentials(self, installation: str) -> InstallationRecord:
        """Remove the installation's credentials, keeping its cap and
        consent (part B's revoke). A record it has none for is a
        no-op."""
        ident = installation_id(installation)
        return self._write_record(
            ident,
            lambda current: InstallationRecord(
                ident,
                "",
                "",
                "",
                current.daily_cap_usd if current is not None else None,
                (current.consent_acknowledged_at if current is not None else None),
                self.clock(),
            ),
        )

    def set_cap(self, installation: str, cap_usd: Decimal | None) -> InstallationRecord:
        """Set or clear the installation admin's daily cap (part B's
        dial). The cap, when set, must be a positive finite dollar
        amount. A record may hold a cap with no credentials: the cap is
        installation-level state in its own right."""
        ident = installation_id(installation)
        if cap_usd is not None and (
            isinstance(cap_usd, bool)
            or not isinstance(cap_usd, Decimal)
            or not cap_usd.is_finite()
            or cap_usd <= 0
        ):
            raise InstallationStoreError(
                "the installation's daily cap must be a positive dollar "
                "amount or nothing"
            )
        return self._write_record(
            ident,
            lambda current: InstallationRecord(
                ident,
                current.base_url if current is not None else "",
                current.key if current is not None else "",
                current.model if current is not None else "",
                cap_usd,
                (current.consent_acknowledged_at if current is not None else None),
                self.clock(),
            ),
        )

    def record_consent(
        self, installation: str, at: datetime | None = None
    ) -> InstallationRecord:
        """Record the installation admin's consent acknowledgement (D81
        §7 decision 3), now unless the caller names the moment."""
        ident = installation_id(installation)
        moment = at if at is not None else self.clock()
        return self._write_record(
            ident,
            lambda current: InstallationRecord(
                ident,
                current.base_url if current is not None else "",
                current.key if current is not None else "",
                current.model if current is not None else "",
                current.daily_cap_usd if current is not None else None,
                moment,
                self.clock(),
            ),
        )

    def delete(self, installation: str) -> None:
        """Delete the installation's stored state -- the credentials,
        the cap and the consent together (D81 §7 decision 8): the
        `installation.deleted` webhook's call. An installation with no
        record is already deleted; so is every installation of an
        unconfigured store, which by definition holds nothing."""
        ident = installation_id(installation)
        if self.broken_reason:
            raise InstallationStoreError(self.broken_reason)
        if self.fernet is None:
            return
        path = self._path(ident)
        with self._lock:
            try:
                path.unlink()
            except FileNotFoundError:
                return
            except OSError as exc:
                raise InstallationStoreError(
                    f"the installation record could not be deleted: {exc}"
                ) from exc
            _sync_dir(path.parent)

    def sweep(self, now: datetime, retention_days: int) -> int:
        """Delete every record whose state went unrefreshed more than
        the retention window ago: the sweep that catches a missed
        `installation.deleted` webhook (D81 §7 decision 8). Reviews
        refresh nothing -- the window measures the record's own
        `updated_at`, so an installation that keeps being configured
        stays and a silent uninstall ages out. A record that cannot be
        read is left alone: its age cannot be established, and it is
        already unusable. Returns the number of records deleted."""
        if retention_days < 1:
            raise ValueError("the retention window must be at least one day")
        if not self.configured:
            return 0
        horizon = now - timedelta(days=retention_days)
        removed = 0
        with self._lock:
            for path in self._record_paths():
                ident = installation_id(path.stem)
                try:
                    record = self._read(ident)
                except InstallationStoreError:
                    continue
                if record is None:
                    continue
                if record.updated_at < horizon:
                    try:
                        path.unlink()
                        _sync_dir(path.parent)
                    except OSError as exc:
                        raise InstallationStoreError(
                            f"the installation record could not be deleted "
                            f"during the retention sweep: {exc}"
                        ) from exc
                    removed += 1
        return removed

    def _record_paths(self) -> tuple[Path, ...]:
        try:
            entries = sorted(self.root.iterdir())
        except FileNotFoundError:
            return ()
        except OSError as exc:
            raise InstallationStoreError(
                f"the installation store could not be listed: {exc}"
            ) from exc
        return tuple(path for path in entries if path.is_file())

    def _path(self, ident: str) -> Path:
        name = f"{ident}.json"
        # Path safety by construction: `ident` is ASCII digits only, so
        # the name cannot traverse. The assertion keeps a future change
        # to `installation_id` from silently reopening this.
        assert (self.root / name).name == name
        return self.root / name

    def _read(self, ident: str) -> InstallationRecord | None:
        """The decrypted record, or None when the installation has no
        file. Every failure is named and no caller ever sees a
        fallback."""
        assert self.fernet is not None
        path = self._path(ident)
        try:
            raw = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise InstallationStoreError(
                f"the installation record for {ident} could not be read: {exc}"
            ) from exc
        try:
            envelope = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise _corrupt(ident) from exc
        if (
            not isinstance(envelope, dict)
            or envelope.get("version") != _STORE_VERSION
            or not isinstance(envelope.get("record"), str)
        ):
            raise _corrupt(ident)
        token = envelope["record"]
        try:
            payload = json.loads(self.fernet.decrypt(token.encode("ascii")))
        except InvalidToken:
            raise InstallationStoreError(
                f"the installation record for {ident} did not decrypt under "
                f"{ENV_STORE_KEY}: the key is wrong or the record is corrupt"
            ) from None
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise _corrupt(ident) from exc
        except OSError as exc:
            raise InstallationStoreError(
                f"the installation record for {ident} could not be read: {exc}"
            ) from exc
        return _decode(ident, payload)

    def _write_record(
        self,
        ident: str,
        compose: Callable[[InstallationRecord | None], InstallationRecord],
    ) -> InstallationRecord:
        """Read-modify-write one record under the store's lock: the
        composed record replaces the stored one atomically. The
        read-modify-write is not serialized against another process, but
        every writer of this store is this process (the settings surface
        and the service share the state volume through this module), so
        the in-process lock is the whole story for part A. A store that
        cannot encrypt -- unconfigured or broken -- refuses the write
        with the named reason."""
        if self.broken_reason:
            raise InstallationStoreError(self.broken_reason)
        if self.fernet is None:
            raise InstallationStoreError(STORE_BROKEN)
        with self._lock:
            current = self._read(ident)
            record = compose(current)
            path = self._path(ident)
            make_private_dirs(path.parent)
            payload = {
                "base_url": record.base_url,
                "key": record.key,
                "model": record.model,
                "daily_cap_usd": (
                    None if record.daily_cap_usd is None else str(record.daily_cap_usd)
                ),
                "consent_acknowledged_at": _iso_or_none(record.consent_acknowledged_at),
                "updated_at": record.updated_at.isoformat(),
            }
            envelope = json.dumps(
                {
                    "version": _STORE_VERSION,
                    "record": self.fernet.encrypt(
                        json.dumps(payload).encode("utf-8")
                    ).decode("ascii"),
                }
            )
            tmp = path.with_name(f"{path.name}.writing")
            try:
                fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    fh.write(envelope)
                    fh.flush()
                    os.fsync(fh.fileno())
                os.replace(tmp, path)
            except OSError as exc:
                with contextlib.suppress(OSError):
                    tmp.unlink(missing_ok=True)
                raise InstallationStoreError(
                    f"the installation record for {ident} could not be written: {exc}"
                ) from exc
            _sync_dir(path.parent)
            return record


STORE_BROKEN = "the installation store is not configured"


def store_root(state_dir: Path) -> Path:
    """The store's directory on the state volume:
    `<state root>/installations/`."""
    return state_dir / "installations"


def _has_records(root: Path) -> bool:
    try:
        return any(path.is_file() for path in root.iterdir())
    except (FileNotFoundError, NotADirectoryError):
        return False
    except OSError:
        return False


def _check_base_url(raw: str) -> str:
    """The tenant-supplied base URL as the store keeps it: HTTPS, a
    hostname, no userinfo, query or fragment, and within the length
    bound. The per-connection egress check (`egress.py`) is the other
    half; this check keeps an unusable URL out of the store."""
    if not raw or len(raw) > _MAX_URL_CHARS:
        raise InstallationStoreError(
            f"the installation's endpoint base URL must be 1 to "
            f"{_MAX_URL_CHARS} characters"
        )
    parts = urlsplit(raw)
    if parts.scheme != "https":
        raise InstallationStoreError(
            "the installation's endpoint base URL must be an https:// URL"
        )
    if not parts.hostname:
        raise InstallationStoreError(
            "the installation's endpoint base URL must name a host"
        )
    if parts.username is not None or parts.password is not None:
        raise InstallationStoreError(
            "the installation's endpoint base URL must not carry userinfo"
        )
    if parts.query or parts.fragment:
        raise InstallationStoreError(
            "the installation's endpoint base URL must not carry a query or a fragment"
        )
    return raw


def _check_model(raw: str) -> str:
    if (
        not raw
        or len(raw) > _MAX_MODEL_CHARS
        or any(char.isspace() or ord(char) < 0x21 or ord(char) == 0x7F for char in raw)
    ):
        raise InstallationStoreError(
            "the installation's chosen model must be a model id of 1 to "
            f"{_MAX_MODEL_CHARS} visible characters"
        )
    return raw


def _iso_or_none(moment: datetime | None) -> str | None:
    return None if moment is None else moment.isoformat()


def _corrupt(ident: str) -> InstallationStoreError:
    return InstallationStoreError(
        f"the installation record for {ident} is corrupt: not a document "
        "this store wrote"
    )


def _decode(ident: str, payload: object) -> InstallationRecord:
    """The decrypted payload as a record, refusing a document whose
    shape the store does not write."""
    if not isinstance(payload, dict) or set(payload) != set(_PAYLOAD_FIELDS):
        raise InstallationStoreError(
            f"the installation record for {ident} is corrupt: not a "
            "document this store wrote"
        )
    cap = _decode_cap(payload["daily_cap_usd"])
    consent = _decode_time(payload["consent_acknowledged_at"], ident, "consent")
    updated = _decode_time(payload["updated_at"], ident, "updated_at")
    if updated is None:
        # updated_at is written on every record; its absence is corruption.
        raise _corrupt(ident)
    for field_name in ("base_url", "key", "model"):
        value = payload[field_name]
        if not isinstance(value, str):
            raise InstallationStoreError(
                f"the installation record for {ident} is corrupt: not a "
                "document this store wrote"
            )
    return InstallationRecord(
        ident,
        payload["base_url"],
        payload["key"],
        payload["model"],
        cap,
        consent,
        updated,
    )


def _decode_cap(raw: object) -> Decimal | None:
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise InstallationStoreError(
            "the installation record is corrupt: not a document this store wrote"
        )
    try:
        cap = Decimal(raw)
    except InvalidOperation:
        raise InstallationStoreError(
            "the installation record is corrupt: not a document this store wrote"
        ) from None
    if not cap.is_finite() or cap <= 0:
        raise InstallationStoreError(
            "the installation record is corrupt: not a document this store wrote"
        )
    return cap


def _decode_time(raw: object, ident: str, what: str) -> datetime | None:
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise InstallationStoreError(
            f"the installation record for {ident} is corrupt: not a "
            "document this store wrote"
        )
    try:
        moment = datetime.fromisoformat(raw)
    except ValueError:
        raise InstallationStoreError(
            f"the installation record for {ident} is corrupt: not a "
            "document this store wrote"
        ) from None
    if moment.tzinfo is None:
        raise InstallationStoreError(
            f"the installation record for {ident} is corrupt: not a "
            "document this store wrote"
        )
    return moment


def _sync_dir(path: Path) -> None:
    """The rename's directory entry, synced so a crash cannot lose a
    record the caller was told was stored."""
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
