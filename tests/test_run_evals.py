# SPDX-License-Identifier: MIT
# tests/test_run_evals.py
import http.client
import json
import urllib.error

import pytest

from tooling import run_evals
from tooling.generate import generate_skill
from tooling.manifest import Skill, Source


class _FakeResp:
    """Minimal stand-in for the urlopen context manager."""
    def __init__(self, body: bytes):
        self._body = body
    def read(self):
        return self._body
    def __enter__(self):
        return self
    def __exit__(self, *exc):
        return False


def _patch_urlopen(monkeypatch, *, body=None, exc=None):
    def fake_urlopen(req, timeout=None):
        if exc is not None:
            raise exc
        return _FakeResp(body)
    monkeypatch.setattr(run_evals.urllib.request, "urlopen", fake_urlopen)


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

    def fake_query(model, system, user, host=run_evals.OLLAMA_HOST, timeout=600):
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


def test_run_skill_evals_openai_backend(tmp_path, monkeypatch):
    skill = Skill(name="hunting-silent-failures", description="x", shape="diff",
                  wave=1, built_from=[Source(2, "tests/fixtures/research_sample.md#2")])
    out = generate_skill(skill, "v0.2", docs_root=".", skills_root=str(tmp_path))
    (out / "evals" / "eval.json").write_text(_valid_eval_json())

    calls = []

    def fake_openai(model, system, user, host=run_evals.OPENAI_HOST, timeout=600):
        calls.append(host)
        return f"openai-reviewed: {user}"

    def fail_ollama(*a, **kw):
        raise AssertionError("ollama backend must not be used when api='openai'")

    monkeypatch.setattr(run_evals, "query_openai", fake_openai)
    monkeypatch.setattr(run_evals, "query_ollama", fail_ollama)
    runs = run_evals.run_skill_evals(out, "fake-model",
                                     host="http://localhost:9999", api="openai")

    assert [r.response for r in runs] == [
        "openai-reviewed: q1", "openai-reviewed: q2", "openai-reviewed: q3"]
    assert calls == ["http://localhost:9999"] * 3

    # host omitted -> defaults to the chosen api's port, not Ollama's
    calls.clear()
    run_evals.run_skill_evals(out, "fake-model", api="openai")
    assert calls == [run_evals.OPENAI_HOST] * 3


# --- query_ollama / query_openai: network + response-shape robustness (#23) ---

def test_query_ollama_returns_content(monkeypatch):
    _patch_urlopen(monkeypatch,
                   body=json.dumps({"message": {"content": "a finding"}}).encode())
    assert run_evals.query_ollama("m", "sys", "usr") == "a finding"


def test_query_ollama_sends_num_ctx(monkeypatch):
    # The num_ctx fix is itself silent-failure-prone: drop or misspell it and the
    # run still "works" against a truncated context. Assert it reaches the payload.
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["payload"] = json.loads(req.data)
        return _FakeResp(json.dumps({"message": {"content": "ok"}}).encode())

    monkeypatch.setattr(run_evals.urllib.request, "urlopen", fake_urlopen)
    run_evals.query_ollama("m", "sys", "usr")
    assert captured["payload"]["options"]["num_ctx"] == run_evals.OLLAMA_NUM_CTX
    assert captured["payload"]["options"]["temperature"] == 0


def test_query_ollama_network_error_raises_runtimeerror(monkeypatch):
    _patch_urlopen(monkeypatch, exc=urllib.error.URLError("connection refused"))
    with pytest.raises(RuntimeError, match="Ollama request to .* failed"):
        run_evals.query_ollama("m", "sys", "usr")


def test_query_ollama_http_exception_raises(monkeypatch):
    # HTTPException (RemoteDisconnected/BadStatusLine) is a distinct path from URLError.
    _patch_urlopen(monkeypatch, exc=http.client.RemoteDisconnected("server closed"))
    with pytest.raises(RuntimeError, match="Ollama request to .* failed"):
        run_evals.query_ollama("m", "sys", "usr")


def test_query_ollama_surfaces_api_error_message(monkeypatch):
    _patch_urlopen(monkeypatch,
                   body=json.dumps({"error": "model 'x' not found"}).encode())
    with pytest.raises(RuntimeError, match="not found"):
        run_evals.query_ollama("m", "sys", "usr")


def test_query_ollama_unexpected_shape_raises(monkeypatch):
    _patch_urlopen(monkeypatch, body=json.dumps({"message": {}}).encode())
    with pytest.raises(RuntimeError, match="unexpected Ollama response shape"):
        run_evals.query_ollama("m", "sys", "usr")


def test_query_ollama_non_json_raises(monkeypatch):
    _patch_urlopen(monkeypatch, body=b"<html>502 Bad Gateway</html>")
    with pytest.raises(RuntimeError, match="non-JSON response"):
        run_evals.query_ollama("m", "sys", "usr")


def test_query_openai_returns_content(monkeypatch):
    _patch_urlopen(monkeypatch, body=json.dumps(
        {"choices": [{"message": {"content": "ok"}}]}).encode())
    assert run_evals.query_openai("m", "sys", "usr") == "ok"


def test_query_openai_network_error_raises_runtimeerror(monkeypatch):
    _patch_urlopen(monkeypatch, exc=urllib.error.URLError("refused"))
    with pytest.raises(RuntimeError, match="OpenAI-compatible request to .* failed"):
        run_evals.query_openai("m", "sys", "usr")


def test_query_openai_surfaces_api_error_message(monkeypatch):
    _patch_urlopen(monkeypatch, body=json.dumps(
        {"error": {"message": "rate limited"}}).encode())
    with pytest.raises(RuntimeError, match="rate limited"):
        run_evals.query_openai("m", "sys", "usr")


def test_query_openai_unexpected_shape_raises(monkeypatch):
    _patch_urlopen(monkeypatch, body=json.dumps({"choices": []}).encode())
    with pytest.raises(RuntimeError, match="unexpected OpenAI-compatible response shape"):
        run_evals.query_openai("m", "sys", "usr")
