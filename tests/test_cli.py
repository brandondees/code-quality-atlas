# SPDX-License-Identifier: MIT
# tests/test_cli.py
import subprocess
import sys
from pathlib import Path
from tooling.cli import main

def test_cli_generate_then_drift_reports_clean(tmp_path, capsys):
    rc = main(["generate", "--manifest", "tests/fixtures/manifest_sample.yaml",
               "--docs-root", ".", "--skills-root", str(tmp_path)])
    assert rc == 0
    assert (tmp_path / "hunting-silent-failures" / "SKILL.md").exists()

    rc = main(["drift", "--skills-root", str(tmp_path), "--docs-root", "."])
    out = capsys.readouterr().out
    assert rc == 0
    assert "No drift" in out


def test_cli_runs_as_module(tmp_path):
    """Regression: `python -m tooling.cli` must actually invoke main() (needs the
    __name__ == '__main__' guard). The unit test above calls main() directly and
    would not catch a missing guard."""
    result = subprocess.run(
        [sys.executable, "-m", "tooling.cli", "drift",
         "--skills-root", str(tmp_path), "--docs-root", "."],
        cwd=str(Path(__file__).resolve().parent.parent),
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "No drift" in result.stdout


def test_cli_eval_reports_valid_and_invalid(tmp_path, capsys):
    import json
    good = tmp_path / "good-skill" / "evals"
    good.mkdir(parents=True)
    (good / "eval.json").write_text(json.dumps({
        "skills": ["good-skill"],
        "scenarios": [{"query": f"q{i}", "expected_behavior": ["b"]} for i in range(3)],
    }))
    bad = tmp_path / "bad-skill" / "evals"
    bad.mkdir(parents=True)
    (bad / "eval.json").write_text(json.dumps({"skills": ["bad-skill"], "scenarios": []}))

    rc = main(["eval", "--skills-root", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 1                      # at least one invalid
    assert "OK: good-skill (3 scenarios)" in out
    assert "INVALID: bad-skill" in out

    rc = main(["eval", "--skills-root", str(tmp_path), "--skill", "good-skill"])
    assert rc == 0                      # filtering to the valid one passes


def test_cli_eval_honors_manifest_eval_min(tmp_path, capsys):
    # Q21: a lens with a manifest `eval_min` above D8's baseline must fail the
    # eval gate below that bar and pass at or above it — while an unrelated
    # skill absent from the manifest keeps the default baseline of 3.
    import json
    hardened = tmp_path / "skills" / "hardened-skill" / "evals"
    hardened.mkdir(parents=True)
    (hardened / "eval.json").write_text(json.dumps({
        "skills": ["hardened-skill"],
        "scenarios": [{"query": f"q{i}", "expected_behavior": ["b"]} for i in range(5)],
    }))
    unlisted = tmp_path / "skills" / "unlisted-skill" / "evals"
    unlisted.mkdir(parents=True)
    (unlisted / "eval.json").write_text(json.dumps({
        "skills": ["unlisted-skill"],
        "scenarios": [{"query": f"q{i}", "expected_behavior": ["b"]} for i in range(3)],
    }))
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
        "      - { category: 2, source: tests/fixtures/research_sample.md#2 }\n")

    rc = main(["eval", "--skills-root", str(tmp_path / "skills"), "--manifest", str(manifest_path)])
    out = capsys.readouterr().out
    assert rc == 1                                   # hardened-skill's 5 < its eval_min of 10
    assert "INVALID: hardened-skill" in out
    assert "at least 10" in out
    assert "OK: unlisted-skill (3 scenarios)" in out  # absent from manifest -> default baseline


def test_cli_eval_falls_back_when_manifest_unreadable(tmp_path, capsys):
    # A missing/bad --manifest path must not crash the eval gate; every skill
    # falls back to D8's baseline of 3.
    import json
    ok = tmp_path / "skills" / "some-skill" / "evals"
    ok.mkdir(parents=True)
    (ok / "eval.json").write_text(json.dumps({
        "skills": ["some-skill"],
        "scenarios": [{"query": f"q{i}", "expected_behavior": ["b"]} for i in range(3)],
    }))
    rc = main(["eval", "--skills-root", str(tmp_path / "skills"),
               "--manifest", str(tmp_path / "does-not-exist.yaml")])
    out = capsys.readouterr().out
    assert rc == 0
    assert "OK: some-skill (3 scenarios)" in out


def test_cli_generate_emits_collapsed(tmp_path):
    from tooling.cli import main
    rc = main(["generate", "--manifest", "skills/manifest.yaml", "--docs-root", ".",
               "--skills-root", str(tmp_path / "skills"),
               "--collapsed-root", str(tmp_path / "collapsed")])
    assert rc == 0
    assert (tmp_path / "collapsed" / "skills" / "reviewing-a-change" / "SKILL.md").exists()
    assert (tmp_path / "collapsed" / ".claude-plugin" / "plugin.json").exists()


def test_cli_generate_reports_collapsed_overlap_cleanly(tmp_path, capsys):
    """The generate_collapsed overlap guard must reach the CLI as a clean
    `ERROR:` + exit 1, not a raw traceback — matching the drift/eval branches.
    collapsed_root=tmp_path makes <collapsed_root>/skills == skills_root."""
    rc = main(["generate", "--manifest", "skills/manifest.yaml", "--docs-root", ".",
               "--skills-root", str(tmp_path / "skills"),
               "--collapsed-root", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 1
    assert "ERROR:" in out
    assert "overlap" in out
