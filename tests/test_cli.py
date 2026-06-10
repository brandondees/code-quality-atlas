# tests/test_cli.py
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
