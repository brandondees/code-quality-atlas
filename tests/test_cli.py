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
