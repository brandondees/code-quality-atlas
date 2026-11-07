# SPDX-License-Identifier: MIT
"""The trusted Python interpreter a runner's tools use, and the probe-only
diagnostics about how the Sprite image provides Python. Pure: scripts in,
parsed values out; `runner` runs them.

The Sprite image's `python3` on its default PATH is a pyenv shim
(`/.sprite/bin/python3`), and pyenv picks the version from a
`.python-version` file in the working directory or any parent -- that is,
from the PR being reviewed. So a tool never runs a shim or a bare
`python3`. Before the source is unpacked, the controller asks the runner
for the real interpreters under `PYENV_VERSIONS` (pyenv documents running
`$(pyenv root)/versions/<v>/bin/...` directly to bypass shims), then
`/usr/bin/python3`, each run from an empty directory under the runner's
minimal environment, and picks one by absolute path. Every tool then runs
it with `-I` (isolated mode: no `PYTHON*` variables, no user site, and the
working directory is not put on `sys.path`, so PR files cannot shadow a
module the tool imports).

Sources: https://env-docs-bkmto.sprites.app/languages/python (shims in
`/.sprite/bin`, pyenv root `/.sprite/languages/python/pyenv`) and pyenv's
README (version selection by `.python-version`; shims bypassed by the
versions directory).
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass

SHIM_PATH = "/.sprite/bin/python3"
PYENV_ROOT = "/.sprite/languages/python/pyenv"
PYENV_VERSIONS = f"{PYENV_ROOT}/versions"
SYSTEM_PYTHON = "/usr/bin/python3"
NEUTRAL_DIR = "/tmp/atlas-neutral"
PYTHON_PLACEHOLDER = "{python}"
PYTHON_TAG = "atlas-python"
DIAG_TAG = "atlas-diag"
_VERSION = r"(\d+)\.(\d+)\.(\d+)"
_CANDIDATE_RE = re.compile(
    re.escape(PYTHON_TAG) + r":(/[A-Za-z0-9._/+-]{1,200}):" + _VERSION + r"\s*$",
    re.MULTILINE,
)
_PYENV_PATH_RE = re.compile(
    re.escape(PYENV_VERSIONS) + r"/[A-Za-z0-9][A-Za-z0-9._+-]{0,63}/bin/python3"
)
_DIAG_RE = re.compile(re.escape(DIAG_TAG) + r":([a-z_]+):(.*)$", re.MULTILINE)
_VERSION_NAME_RE = re.compile(r"^[A-Za-z0-9._+-]{1,64}$", re.MULTILINE)
_PRINTABLE_RE = re.compile(r"[^\x20-\x7e]")
_DIAG_CHARS = 200


@dataclass(frozen=True)
class TrustedPython:
    path: str
    version: str

    @property
    def quoted(self) -> str:
        return shlex.quote(self.path)


def resolve_script() -> str:
    """Runs each candidate's own version query from an empty directory.
    Nothing from the PR exists yet when this runs."""
    query = "import sys; print('%d.%d.%d' % sys.version_info[:3])"
    return (
        f"mkdir -p {NEUTRAL_DIR} && cd {NEUTRAL_DIR} && "
        f"for p in {PYENV_VERSIONS}/*/bin/python3 {SYSTEM_PYTHON}; do "
        f'if [ -x "$p" ] && v=$("$p" -I -c "{query}" 2>/dev/null); '
        f'then echo "{PYTHON_TAG}:$p:$v"; fi; done'
    )


def choose_python(text: str) -> TrustedPython | None:
    """The newest pyenv-installed interpreter, else the system one. Only
    paths of exactly those two shapes are accepted from the guest's answer."""
    candidates = [
        (path, (int(a), int(b), int(c)))
        for path, a, b, c in _CANDIDATE_RE.findall(text)
        if _trusted_path(path)
    ]
    pyenv = sorted((c for c in candidates if c[0] != SYSTEM_PYTHON), key=_newest)
    system = [c for c in candidates if c[0] == SYSTEM_PYTHON]
    chosen = [*pyenv, *system][:1]
    return next((TrustedPython(p, ".".join(map(str, v))) for p, v in chosen), None)


def _newest(candidate: tuple[str, tuple[int, int, int]]) -> tuple[int, ...]:
    return tuple(-n for n in candidate[1])


def _trusted_path(path: str) -> bool:
    return path == SYSTEM_PYTHON or bool(_PYENV_PATH_RE.fullmatch(path))


def with_python(command: str, python: TrustedPython) -> str:
    return command.replace(PYTHON_PLACEHOLDER, python.quoted)


# --- probe-only diagnostics -------------------------------------------------


@dataclass(frozen=True)
class DiagnosticSpec:
    """One probe-only check. `expectation` is shown next to its result so a
    reader knows what each outcome would mean."""

    name: str
    expectation: str
    script: str
    sprite_env: bool = False
    bound_s: int | None = None


def shim_script(shim: str = SHIM_PATH) -> str:
    """Reads the shim as text; never runs it."""
    return (
        f"s={shlex.quote(shim)}; "
        'if [ -e "$s" ]; then '
        f'echo "{DIAG_TAG}:target:$(readlink -f "$s")"; '
        f'echo "{DIAG_TAG}:bytes:$(wc -c < "$s")"; '
        f'echo "{DIAG_TAG}:shebang:$(head -n 1 "$s")"; '
        f'echo "{DIAG_TAG}:exec_line:$(grep -m 1 \'exec \' "$s")"; '
        f'else echo "{DIAG_TAG}:absent:$s"; fi'
    )


def versions_script() -> str:
    return f"ls -1 {PYENV_VERSIONS} 2>/dev/null || true"


def bounded(command: str, seconds: int) -> str:
    return f"/usr/bin/timeout -k 2 {seconds} {command}"


def diagnostics_before_unpack() -> tuple[DiagnosticSpec, ...]:
    return (
        DiagnosticSpec(
            "shim",
            "a pyenv shim: a shell script, its target itself, exec'ing pyenv",
            shim_script(),
        ),
        DiagnosticSpec(
            "pyenv versions",
            "the installed versions; the PR pins 3.12",
            versions_script(),
        ),
    )


def diagnostics_after_unpack(
    python: TrustedPython | None, workdir: str, bound_s: int
) -> tuple[DiagnosticSpec, ...]:
    trusted = (
        ()
        if python is None
        else (
            DiagnosticSpec(
                "trusted python after unpack",
                "the same version as before unpack, from inside the checkout",
                f"cd {workdir} && {python.quoted} -I --version",
            ),
        )
    )
    pinned_off = (
        ()
        if python is None
        else (
            DiagnosticSpec(
                "shim with PYENV_VERSION",
                "answers quickly if the PR's .python-version pin is the cause",
                f"cd {workdir} && PYENV_VERSION={shlex.quote(_pyenv_name(python))} "
                + bounded(f"{SHIM_PATH} --version", bound_s),
                sprite_env=True,
                bound_s=bound_s,
            ),
        )
    )
    bare = DiagnosticSpec(
        "bare python3 in the checkout",
        f"expected-may-hang: exit 124 after {bound_s}s confirms the pin hypothesis",
        f"cd {workdir} && " + bounded("python3 --version", bound_s),
        sprite_env=True,
        bound_s=bound_s,
    )
    return (*trusted, *pinned_off, bare)


def _pyenv_name(python: TrustedPython) -> str:
    """`versions/<name>/bin/python3` -> `<name>`; the system interpreter
    has no pyenv name, so its version is used."""
    parts = python.path.split("/")
    return parts[-3] if python.path != SYSTEM_PYTHON else python.version


def summarize(text: str) -> str:
    """Untrusted guest output, reduced to one printable line for telemetry."""
    tagged = [f"{k}={_printable(v)}" for k, v in _DIAG_RE.findall(text)]
    if tagged:
        return "; ".join(tagged)
    names = _VERSION_NAME_RE.findall(text)
    return ",".join(names) if names else _printable(text) or "(no output)"


def _printable(text: str) -> str:
    return _PRINTABLE_RE.sub(" ", text).strip()[:_DIAG_CHARS]
