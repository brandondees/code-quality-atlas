# tests/test_run_evals.py
from tooling import run_evals
from tooling.manifest import Skill, Source
from tooling.generate import generate_skill


def _valid_eval_json():
    return (
        '{"skills":["hunting-silent-failures"],"scenarios":['
        '{"query":"q1","expected_behavior":["b1"]},'
        '{"query":"q2","expected_behavior":["b2"]},'
        '{"query":"q3","expected_behavior":["b3"]}]}'
    )


def test_run_skill_evals_assembles_context_and_collects(tmp_path, monkeypatch):
    skill = Skill(name="hunting-silent-failures", description="x", shape="diff",
                  wave=1, built_from=[Source(2, "tests/fixtures/research_sample.md#2")])
    out = generate_skill(skill, "v0.2", docs_root=".", skills_root=str(tmp_path))
    (out / "evals" / "eval.json").write_text(_valid_eval_json())

    captured = {}

    def fake_query(model, system, user, host=run_evals.OLLAMA_HOST, timeout=180):
        captured["system"] = system
        captured["model"] = model
        return f"reviewed: {user}"

    monkeypatch.setattr(run_evals, "query_ollama", fake_query)
    runs = run_evals.run_skill_evals(out, "fake-model")

    assert len(runs) == 3
    assert [r.response for r in runs] == ["reviewed: q1", "reviewed: q2", "reviewed: q3"]
    assert runs[0].expected_behavior == ["b1"]
    # context is assembled from the skill's own files (SKILL.md mentions its name)
    assert "hunting-silent-failures" in captured["system"]
    assert captured["model"] == "fake-model"
