# tests/test_cli.py
import subprocess
import sys
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
        cwd="/Users/dees/code/code-quality-atlas",
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "No drift" in result.stdout
