# SPDX-License-Identifier: MIT
# tests/test_cli.py
import subprocess
import sys
from pathlib import Path

from tooling.cli import main
from tooling.generate_skill import generate_skill
from tooling.manifest import Skill, Source

ROOT = Path(__file__).resolve().parent.parent


def _touch_skill_md(skill_dir: Path) -> None:
    """`eval`'s directory-based skill enumeration requires a SKILL.md to
    exist, matching `drift`'s own definition of "a skill" (PR #412 review) —
    fixtures that don't generate one via `generate_skill` need a placeholder
    so they're still recognized as a skill directory. Content is never read
    on this path; only presence matters."""
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text("---\nname: placeholder\n---\n\nbody\n")


def test_cli_generate_then_drift_reports_clean(tmp_path, capsys):
    rc = main(
        [
            "generate",
            "--manifest",
            str(ROOT / "tests" / "fixtures" / "manifest_sample.yaml"),
            "--docs-root",
            str(ROOT),
            "--skills-root",
            str(tmp_path),
        ]
    )
    assert rc == 0
    assert (tmp_path / "hunting-silent-failures" / "SKILL.md").exists()

    rc = main(["drift", "--skills-root", str(tmp_path), "--docs-root", str(ROOT)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "No drift" in out


def test_cli_drift_detected_reports_and_returns_1(tmp_path, capsys):
    # Regression (#367): the DRIFT: reporting branch (a detected drift
    # returning rc 1) was unexercised by any test — flipping that `return 1`
    # to `return 0` left the whole 454-test suite green.
    rc = main(
        [
            "generate",
            "--manifest",
            str(ROOT / "tests" / "fixtures" / "manifest_sample.yaml"),
            "--docs-root",
            str(ROOT),
            "--skills-root",
            str(tmp_path / "skills"),
        ]
    )
    assert rc == 0

    altered = tmp_path / "docs_altered"
    (altered / "tests" / "fixtures").mkdir(parents=True)
    original = (ROOT / "tests" / "fixtures" / "research_sample.md").read_text()
    (altered / "tests" / "fixtures" / "research_sample.md").write_text(
        original.replace(
            "Does every remote call have a timeout?",
            "Does every remote call have a timeout and deadline?",
        )
    )
    rc = main(
        [
            "drift",
            "--skills-root",
            str(tmp_path / "skills"),
            "--docs-root",
            str(altered),
        ]
    )
    out = capsys.readouterr().out
    assert rc == 1
    assert "DRIFT: hunting-silent-failures" in out


def test_cli_drift_fails_loudly_on_empty_skills_root(tmp_path, capsys):
    # Regression (#367): an empty or nonexistent --skills-root previously
    # globbed to zero skills and reported "No drift" with rc 0 — a renamed
    # or mistyped --skills-root would silently turn CI's drift gate into a
    # green no-op instead of failing.
    rc = main(["drift", "--skills-root", str(tmp_path / "does-not-exist")])
    out = capsys.readouterr().out
    assert rc == 1
    assert "ERROR: no skills found under" in out
    assert "No drift" not in out


def test_cli_eval_fails_loudly_on_empty_skills_root(tmp_path, capsys):
    # Regression (#367): mirrors the drift gate above for the eval command —
    # a nonexistent/empty --skills-root previously globbed zero eval.json
    # files and printed nothing while exiting 0.
    rc = main(
        [
            "eval",
            "--skills-root",
            str(tmp_path / "does-not-exist"),
            "--manifest",
            str(ROOT / "skills" / "manifest.yaml"),
        ]
    )
    out = capsys.readouterr().out
    assert rc == 1
    assert "ERROR: no skills found under" in out


def test_cli_eval_reports_missing_eval_json(tmp_path, capsys):
    # Regression (#367): the MISSING: branch was unreachable on the default
    # (no --skill) path, since eval_files was built by globbing only
    # eval.json files that already exist — a skill directory with no
    # evals/ at all never produced a glob hit to report as missing. A
    # SKILL.md marks it as a real skill directory (PR #412 review) so it
    # isn't excluded by the same gate that filters out stray directories.
    _touch_skill_md(tmp_path / "no-evals-skill")
    manifest = str(ROOT / "skills" / "manifest.yaml")
    rc = main(["eval", "--skills-root", str(tmp_path), "--manifest", manifest])
    out = capsys.readouterr().out
    assert rc == 1
    assert "MISSING: no-evals-skill — no evals/eval.json" in out


def test_cli_eval_ignores_stray_non_skill_directory(tmp_path, capsys):
    # Regression (PR #412 review, dees-bot round 1): a directory under
    # --skills-root with no SKILL.md — a leftover cache dir, a dot-prefixed
    # tool dir, anything that isn't a generated skill — must be silently
    # ignored, not misreported as MISSING: <name> — no evals/eval.json.
    import json

    _touch_skill_md(tmp_path / "real-skill")
    (tmp_path / "real-skill" / "evals").mkdir()
    (tmp_path / "real-skill" / "evals" / "eval.json").write_text(
        json.dumps(
            {
                "skills": ["real-skill"],
                "scenarios": [
                    {"query": f"q{i}", "expected_behavior": ["b"]} for i in range(3)
                ],
            }
        )
    )
    (tmp_path / "not-a-skill").mkdir()  # no SKILL.md — a stray directory

    manifest = str(ROOT / "skills" / "manifest.yaml")
    rc = main(["eval", "--skills-root", str(tmp_path), "--manifest", manifest])
    out = capsys.readouterr().out
    assert rc == 0
    assert "OK: real-skill (3 scenarios)" in out
    assert "not-a-skill" not in out


def test_cli_generate_fails_loudly_on_missing_manifest(tmp_path, capsys):
    # Regression (#367): a nonexistent --manifest previously escaped the
    # generate command as a raw, uncaught exception instead of the clean
    # `ERROR:` + exit 1 the drift/eval branches already give.
    rc = main(
        [
            "generate",
            "--manifest",
            str(tmp_path / "does-not-exist.yaml"),
            "--docs-root",
            str(ROOT),
            "--skills-root",
            str(tmp_path / "skills"),
        ]
    )
    out = capsys.readouterr().out
    assert rc == 1
    assert "ERROR:" in out


def test_cli_generate_fails_loudly_on_malformed_manifest(tmp_path, capsys):
    # Regression (#367): a manifest that loads but fails validate() (here, an
    # invalid skill name) previously escaped as a raw ValidationError
    # traceback instead of a clean `ERROR:` + exit 1.
    bad_manifest = tmp_path / "bad_manifest.yaml"
    bad_manifest.write_text(
        "taxonomy_version: v0.2\n"
        "skills:\n"
        "  - name: BAD NAME\n"
        "    description: x\n"
        "    shape: diff\n"
        "    wave: 1\n"
        "    built_from:\n"
        "      - { category: 2, source: tests/fixtures/research_sample.md#2 }\n"
    )
    rc = main(
        [
            "generate",
            "--manifest",
            str(bad_manifest),
            "--docs-root",
            str(ROOT),
            "--skills-root",
            str(tmp_path / "skills"),
        ]
    )
    out = capsys.readouterr().out
    assert rc == 1
    assert "ERROR:" in out


def test_cli_generate_fails_loudly_on_non_utf8_manifest(tmp_path, capsys):
    # Regression (PR #412 review, CodeRabbit): a --manifest file with invalid
    # UTF-8 bytes previously escaped load_manifest's plain `open(...).read()`
    # as a raw UnicodeDecodeError, uncaught by generate's
    # `except (OSError, ValidationError)` — neither base class covers it.
    bad_manifest = tmp_path / "bad_manifest.yaml"
    bad_manifest.write_bytes(
        b"taxonomy_version: v0.2\nskills: []\n\xff\xfe not valid utf-8\n"
    )
    rc = main(
        [
            "generate",
            "--manifest",
            str(bad_manifest),
            "--docs-root",
            str(ROOT),
            "--skills-root",
            str(tmp_path / "skills"),
        ]
    )
    out = capsys.readouterr().out
    assert rc == 1
    assert "ERROR:" in out


def test_cli_runs_as_module(tmp_path):
    """Regression: `python -m tooling.cli` must actually invoke main() (needs the
    __name__ == '__main__' guard). The unit test above calls main() directly and
    would not catch a missing guard."""
    generate_skill(
        Skill(
            name="hunting-silent-failures",
            description="x",
            shape="diff",
            wave=1,
            built_from=[Source(2, "tests/fixtures/research_sample.md#2")],
        ),
        "v0.2",
        docs_root=str(ROOT),
        skills_root=str(tmp_path),
    )
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "tooling.cli",
            "drift",
            "--skills-root",
            str(tmp_path),
            "--docs-root",
            ".",
        ],
        cwd=str(Path(__file__).resolve().parent.parent),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "No drift" in result.stdout


def test_cli_eval_reports_valid_and_invalid(tmp_path, capsys):
    import json

    _touch_skill_md(tmp_path / "good-skill")
    good = tmp_path / "good-skill" / "evals"
    good.mkdir(parents=True)
    (good / "eval.json").write_text(
        json.dumps(
            {
                "skills": ["good-skill"],
                "scenarios": [
                    {"query": f"q{i}", "expected_behavior": ["b"]} for i in range(3)
                ],
            }
        )
    )
    _touch_skill_md(tmp_path / "bad-skill")
    bad = tmp_path / "bad-skill" / "evals"
    bad.mkdir(parents=True)
    (bad / "eval.json").write_text(
        json.dumps({"skills": ["bad-skill"], "scenarios": []})
    )

    manifest = str(ROOT / "skills" / "manifest.yaml")
    rc = main(["eval", "--skills-root", str(tmp_path), "--manifest", manifest])
    out = capsys.readouterr().out
    assert rc == 1  # at least one invalid
    assert "OK: good-skill (3 scenarios)" in out
    assert "INVALID: bad-skill" in out

    rc = main(
        [
            "eval",
            "--skills-root",
            str(tmp_path),
            "--skill",
            "good-skill",
            "--manifest",
            manifest,
        ]
    )
    assert rc == 0  # filtering to the valid one passes


def test_cli_eval_honors_manifest_eval_min(tmp_path, capsys):
    # Q21: a lens with a manifest `eval_min` above D8's baseline must fail the
    # eval gate below that bar and pass at or above it — while an unrelated
    # skill absent from the manifest keeps the default baseline of 3.
    import json

    _touch_skill_md(tmp_path / "skills" / "hardened-skill")
    hardened = tmp_path / "skills" / "hardened-skill" / "evals"
    hardened.mkdir(parents=True)
    (hardened / "eval.json").write_text(
        json.dumps(
            {
                "skills": ["hardened-skill"],
                "scenarios": [
                    {"query": f"q{i}", "expected_behavior": ["b"]} for i in range(5)
                ],
            }
        )
    )
    _touch_skill_md(tmp_path / "skills" / "unlisted-skill")
    unlisted = tmp_path / "skills" / "unlisted-skill" / "evals"
    unlisted.mkdir(parents=True)
    (unlisted / "eval.json").write_text(
        json.dumps(
            {
                "skills": ["unlisted-skill"],
                "scenarios": [
                    {"query": f"q{i}", "expected_behavior": ["b"]} for i in range(3)
                ],
            }
        )
    )
    manifest_path = tmp_path / "manifest.yaml"
    manifest_path.write_text(
        "taxonomy_version: v0.2\n"
        "skills:\n"
        "  - name: hardened-skill\n"
        "    description: x\n"
        "    shape: diff\n"
        "    wave: 1\n"
        "    eval_min: 10\n"
        "    built_from:\n"
        "      - { category: 2, source: tests/fixtures/research_sample.md#2 }\n"
    )

    rc = main(
        [
            "eval",
            "--skills-root",
            str(tmp_path / "skills"),
            "--manifest",
            str(manifest_path),
        ]
    )
    out = capsys.readouterr().out
    assert rc == 1  # hardened-skill's 5 < its eval_min of 10
    assert "INVALID: hardened-skill" in out
    assert "at least 10" in out
    assert (
        "OK: unlisted-skill (3 scenarios)" in out
    )  # absent from manifest -> default baseline


def test_cli_eval_fails_loudly_when_manifest_missing(tmp_path, capsys):
    # A missing --manifest path must fail the eval gate loudly, not silently
    # fall back to D8's baseline — a CI gate must refuse to report "OK" when
    # it can't confirm which eval-scenario floor it just checked against
    # (found by the atlas's own review of PR #159: a fail-open fallback here
    # would silently un-enforce every hardened lens's raised floor).
    import json

    _touch_skill_md(tmp_path / "skills" / "some-skill")
    some_skill = tmp_path / "skills" / "some-skill" / "evals"
    some_skill.mkdir(parents=True)
    (some_skill / "eval.json").write_text(
        json.dumps(
            {
                "skills": ["some-skill"],
                "scenarios": [
                    {"query": f"q{i}", "expected_behavior": ["b"]} for i in range(3)
                ],
            }
        )
    )
    rc = main(
        [
            "eval",
            "--skills-root",
            str(tmp_path / "skills"),
            "--manifest",
            str(tmp_path / "does-not-exist.yaml"),
        ]
    )
    out = capsys.readouterr().out
    assert rc == 1
    assert "ERROR" in out
    assert "OK: some-skill" not in out


def test_cli_eval_fails_loudly_on_malformed_manifest_yaml(tmp_path, capsys):
    # Regression: syntactically-invalid YAML previously escaped as an uncaught
    # yaml.parser.ParserError instead of being caught and reported. Confirms
    # load_manifest's wrapping fix and the eval command's fail-loud handling
    # together, end to end.
    import json

    _touch_skill_md(tmp_path / "skills" / "some-skill")
    some_skill = tmp_path / "skills" / "some-skill" / "evals"
    some_skill.mkdir(parents=True)
    (some_skill / "eval.json").write_text(
        json.dumps(
            {
                "skills": ["some-skill"],
                "scenarios": [
                    {"query": f"q{i}", "expected_behavior": ["b"]} for i in range(3)
                ],
            }
        )
    )
    bad_manifest = tmp_path / "bad_manifest.yaml"
    bad_manifest.write_text('taxonomy_version: v0.2\nskills: [ { name: "oops"\n')

    rc = main(
        [
            "eval",
            "--skills-root",
            str(tmp_path / "skills"),
            "--manifest",
            str(bad_manifest),
        ]
    )
    out = capsys.readouterr().out
    assert rc == 1
    assert "ERROR" in out
    assert "OK: some-skill" not in out


def test_cli_generate_emits_collapsed(tmp_path):
    from tooling.cli import main

    rc = main(
        [
            "generate",
            "--manifest",
            str(ROOT / "skills" / "manifest.yaml"),
            "--docs-root",
            str(ROOT),
            "--skills-root",
            str(tmp_path / "skills"),
            "--collapsed-root",
            str(tmp_path / "collapsed"),
        ]
    )
    assert rc == 0
    assert (
        tmp_path / "collapsed" / "skills" / "reviewing-a-change" / "SKILL.md"
    ).exists()
    assert (tmp_path / "collapsed" / ".claude-plugin" / "plugin.json").exists()


def test_cli_generate_reports_collapsed_overlap_cleanly(tmp_path, capsys):
    """The generate_collapsed overlap guard must reach the CLI as a clean
    `ERROR:` + exit 1, not a raw traceback — matching the drift/eval branches.
    collapsed_root=tmp_path makes <collapsed_root>/skills == skills_root."""
    rc = main(
        [
            "generate",
            "--manifest",
            str(ROOT / "skills" / "manifest.yaml"),
            "--docs-root",
            str(ROOT),
            "--skills-root",
            str(tmp_path / "skills"),
            "--collapsed-root",
            str(tmp_path),
        ]
    )
    out = capsys.readouterr().out
    assert rc == 1
    assert "ERROR:" in out
    assert "overlap" in out
