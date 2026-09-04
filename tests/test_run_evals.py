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
    skill = Skill(
        name="hunting-silent-failures",
        description="x",
        shape="diff",
        wave=1,
        built_from=[Source(2, "tests/fixtures/research_sample.md#2")],
    )
    out = generate_skill(skill, "v0.2", docs_root=".", skills_root=str(tmp_path))
    (out / "evals" / "eval.json").write_text(_valid_eval_json())

    captured = {}

    def fake_query(
        model,
        system,
        user,
        host=run_evals.OLLAMA_HOST,
        timeout=600,
        num_ctx=run_evals.OLLAMA_NUM_CTX,
        think=None,
    ):
        captured["system"] = system
        captured["model"] = model
        captured["num_ctx"] = num_ctx
        captured["think"] = think
        captured["timeout"] = timeout
        return f"reviewed: {user}"

    monkeypatch.setattr(run_evals, "query_ollama", fake_query)
    # non-default overrides so the assertions below would catch a dropped or
    # mis-forwarded kwarg in run_skill_evals's dispatch, not just query_ollama's.
    runs = run_evals.run_skill_evals(
        out, "fake-model", num_ctx=32768, think=False, timeout=42
    )

    assert len(runs) == 3
    assert [r.response for r in runs] == [
        "reviewed: q1",
        "reviewed: q2",
        "reviewed: q3",
    ]
    assert runs[0].expected_behavior == ["b1"]
    # context is assembled from the skill's own files (SKILL.md mentions its name)
    assert "hunting-silent-failures" in captured["system"]
    assert captured["model"] == "fake-model"
    assert captured["num_ctx"] == 32768
    assert captured["think"] is False
    assert captured["timeout"] == 42


def test_run_skill_evals_openai_backend(tmp_path, monkeypatch):
    skill = Skill(
        name="hunting-silent-failures",
        description="x",
        shape="diff",
        wave=1,
        built_from=[Source(2, "tests/fixtures/research_sample.md#2")],
    )
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
    runs = run_evals.run_skill_evals(
        out, "fake-model", host="http://localhost:9999", api="openai"
    )

    assert [r.response for r in runs] == [
        "openai-reviewed: q1",
        "openai-reviewed: q2",
        "openai-reviewed: q3",
    ]
    assert calls == ["http://localhost:9999"] * 3

    # host omitted -> defaults to the chosen api's port, not Ollama's
    calls.clear()
    run_evals.run_skill_evals(out, "fake-model", api="openai")
    assert calls == [run_evals.OPENAI_HOST] * 3


# --- query_ollama / query_openai: network + response-shape robustness (#23) ---


def test_query_ollama_returns_content(monkeypatch):
    _patch_urlopen(
        monkeypatch, body=json.dumps({"message": {"content": "a finding"}}).encode()
    )
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
    assert "think" not in captured["payload"]


def test_query_ollama_num_ctx_override(monkeypatch):
    # Thinking-capable models can spend the whole default window on reasoning
    # before ever reaching the answer; num_ctx must be widenable per call.
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["payload"] = json.loads(req.data)
        return _FakeResp(json.dumps({"message": {"content": "ok"}}).encode())

    monkeypatch.setattr(run_evals.urllib.request, "urlopen", fake_urlopen)
    run_evals.query_ollama("m", "sys", "usr", num_ctx=32768)
    assert captured["payload"]["options"]["num_ctx"] == 32768


def test_query_ollama_think_flag_forwarded(monkeypatch):
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["payload"] = json.loads(req.data)
        return _FakeResp(json.dumps({"message": {"content": "ok"}}).encode())

    monkeypatch.setattr(run_evals.urllib.request, "urlopen", fake_urlopen)
    run_evals.query_ollama("m", "sys", "usr", think=False)
    assert captured["payload"]["think"] is False


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
    _patch_urlopen(
        monkeypatch, body=json.dumps({"error": "model 'x' not found"}).encode()
    )
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
    _patch_urlopen(
        monkeypatch,
        body=json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode(),
    )
    assert run_evals.query_openai("m", "sys", "usr") == "ok"


def test_query_openai_network_error_raises_runtimeerror(monkeypatch):
    _patch_urlopen(monkeypatch, exc=urllib.error.URLError("refused"))
    with pytest.raises(RuntimeError, match="OpenAI-compatible request to .* failed"):
        run_evals.query_openai("m", "sys", "usr")


def test_query_openai_surfaces_api_error_message(monkeypatch):
    _patch_urlopen(
        monkeypatch, body=json.dumps({"error": {"message": "rate limited"}}).encode()
    )
    with pytest.raises(RuntimeError, match="rate limited"):
        run_evals.query_openai("m", "sys", "usr")


def test_query_openai_unexpected_shape_raises(monkeypatch):
    _patch_urlopen(monkeypatch, body=json.dumps({"choices": []}).encode())
    with pytest.raises(
        RuntimeError, match="unexpected OpenAI-compatible response shape"
    ):
        run_evals.query_openai("m", "sys", "usr")


# --- run_skill_evals: unrecognized api fails fast, even with host set (#23) ---


def test_run_skill_evals_rejects_unknown_api_even_with_host(tmp_path, monkeypatch):
    # The dict-lookup dispatch this replaced (`{"ollama": ..., "openai": ...}[api]`)
    # raised KeyError immediately; the if/ollama-else/openai branch it became must
    # not silently misroute an unrecognized api to the openai backend just because
    # `host` was also passed explicitly (which otherwise short-circuits `host or
    # DEFAULT_HOSTS[api]`'s own fail-fast check).
    skill = Skill(
        name="hunting-silent-failures",
        description="x",
        shape="diff",
        wave=1,
        built_from=[Source(2, "tests/fixtures/research_sample.md#2")],
    )
    out = generate_skill(skill, "v0.2", docs_root=".", skills_root=str(tmp_path))
    (out / "evals" / "eval.json").write_text(_valid_eval_json())

    def fail_any(*a, **kw):
        raise AssertionError("no backend should be called for an unknown api")

    monkeypatch.setattr(run_evals, "query_ollama", fail_any)
    monkeypatch.setattr(run_evals, "query_openai", fail_any)
    with pytest.raises(ValueError, match="unknown api"):
        run_evals.run_skill_evals(
            out, "fake-model", host="http://localhost:9999", api="bogus"
        )


# --- CLI argument validation (#23) ---


def test_cli_think_and_no_think_are_mutually_exclusive(tmp_path, capsys):
    with pytest.raises(SystemExit):
        run_evals.main(
            ["--skill", "x", "--skills-root", str(tmp_path), "--think", "--no-think"]
        )
    assert "not allowed with argument" in capsys.readouterr().err


@pytest.mark.parametrize("flag", ["--num-ctx", "--timeout"])
def test_cli_rejects_non_positive_int_options(flag, tmp_path, capsys):
    with pytest.raises(SystemExit):
        run_evals.main(["--skill", "x", "--skills-root", str(tmp_path), flag, "0"])
    assert "positive integer" in capsys.readouterr().err


# --- partial-run resilience (the 2026-08-08 cross-model re-gate) ---


def _skill_with_evals(tmp_path):
    skill = Skill(
        name="hunting-silent-failures",
        description="x",
        shape="diff",
        wave=1,
        built_from=[Source(2, "tests/fixtures/research_sample.md#2")],
    )
    out = generate_skill(skill, "v0.2", docs_root=".", skills_root=str(tmp_path))
    (out / "evals" / "eval.json").write_text(_valid_eval_json())
    return out


def test_run_skill_evals_records_a_failed_scenario_and_keeps_going(
    tmp_path, monkeypatch
):
    # A re-gate is 20+ slow requests; one transient must not discard the rest.
    # The failed scenario carries `error` and an empty `response` — the caller
    # needs `error` to tell "the request died" from "the model found nothing".
    out = _skill_with_evals(tmp_path)
    calls = []

    def flaky(model, system, user, **kw):
        calls.append(user)
        if len(calls) == 2:
            raise RuntimeError("Ollama request failed: HTTP Error 500")
        return "No findings"

    monkeypatch.setattr(run_evals, "query_ollama", flaky)
    runs = run_evals.run_skill_evals(out, "fake-model")

    assert len(runs) == len(calls) > 2, "the suite ran past the failing scenario"
    assert runs[1].error is not None and runs[1].response == ""
    assert [r.error for r in runs if r is not runs[1]] == [None] * (len(runs) - 1)


def test_cli_exits_non_zero_on_an_empty_message_failure(tmp_path, monkeypatch, capsys):
    # `str(RuntimeError())` is "", so a truthiness check on `error` reads a failed
    # scenario as a clean one — the guard failing silently in exactly the way it
    # exists to prevent. `error` is a presence flag: only None means "no failure".
    out = _skill_with_evals(tmp_path)
    monkeypatch.setattr(
        run_evals,
        "query_ollama",
        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError()),
    )
    rc = run_evals.main(
        ["--skill", out.name, "--skills-root", str(tmp_path), "--model", "fake-model"]
    )
    assert rc == 1
    printed = capsys.readouterr().out
    assert "do not grade it" in printed
    # and the operator still gets something nameable, not a blank line
    assert "RuntimeError()" in printed


def test_cli_exits_non_zero_when_any_scenario_failed(tmp_path, monkeypatch, capsys):
    # The load-bearing half: a partial run must not look like a complete one.
    # An unfailed exit would let 15 dead scenarios be graded as 15 "no findings"
    # misses — a broken run reported as a bad model.
    out = _skill_with_evals(tmp_path)
    monkeypatch.setattr(
        run_evals,
        "query_ollama",
        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    rc = run_evals.main(
        ["--skill", out.name, "--skills-root", str(tmp_path), "--model", "fake-model"]
    )
    assert rc == 1
    assert "do not grade it" in capsys.readouterr().out
