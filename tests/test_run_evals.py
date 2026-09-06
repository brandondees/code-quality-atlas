# SPDX-License-Identifier: MIT
# tests/test_run_evals.py
import http.client
import json
import urllib.error
from pathlib import Path

import pytest

from tooling import run_evals
from tooling.generate import generate_skill
from tooling.manifest import Skill, Source

ROOT = Path(__file__).resolve().parent.parent


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
    out = generate_skill(skill, "v0.2", docs_root=str(ROOT), skills_root=str(tmp_path))
    (out / "evals" / "eval.json").write_text(_valid_eval_json())

    captured = {}

    def fake_query(
        model,
        system,
        user,
        host=run_evals.OLLAMA_HOST,
        timeout=run_evals.DEFAULT_TIMEOUT_SECONDS,
        num_ctx=run_evals.OLLAMA_NUM_CTX,
        think=None,
        max_tokens=None,
    ):
        captured["system"] = system
        captured["model"] = model
        captured["num_ctx"] = num_ctx
        captured["think"] = think
        captured["timeout"] = timeout
        captured["max_tokens"] = max_tokens
        return f"reviewed: {user}"

    monkeypatch.setattr(run_evals, "query_ollama", fake_query)
    # non-default overrides so the assertions below would catch a dropped or
    # mis-forwarded kwarg in run_skill_evals's dispatch, not just query_ollama's.
    runs = run_evals.run_skill_evals(
        out, "fake-model", num_ctx=32768, think=False, timeout=42, max_tokens=512
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
    assert captured["max_tokens"] == 512


def test_assemble_context_includes_artifact_shaped_reference_file(tmp_path):
    """An artifact-shaped lens (e.g. reviewing-artifact-conventions) has no
    reference/heuristics.md at all -- its checklist lives in one bundled
    rubric file per artifact, reference/<slug>.md. Before #371's fix,
    assemble_context hardcoded reference/heuristics.md and silently skipped
    a missing file, so this shape was evaluated with an empty checklist."""
    skill_dir = tmp_path / "reviewing-artifact-conventions"
    (skill_dir / "reference").mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("# reviewing-artifact-conventions\n")
    (skill_dir / "reference" / "skill-md.md").write_text(
        "UNIQUE_ARTIFACT_RUBRIC_CONTENT"
    )

    context = run_evals.assemble_context(skill_dir)

    assert "UNIQUE_ARTIFACT_RUBRIC_CONTENT" in context


def test_assemble_context_excludes_deeper_reference_files(tmp_path):
    """tool-rules.md and sources.md are deliberately deeper, on-demand
    disclosure levels a model with the skill loaded wouldn't have in
    context by default -- assemble_context must not bundle them in."""
    skill_dir = tmp_path / "hunting-silent-failures"
    (skill_dir / "reference").mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("# hunting-silent-failures\n")
    (skill_dir / "reference" / "heuristics.md").write_text("UNIQUE_HEURISTICS_CONTENT")
    (skill_dir / "reference" / "tool-rules.md").write_text("UNIQUE_TOOL_RULES_CONTENT")
    (skill_dir / "reference" / "sources.md").write_text("UNIQUE_SOURCES_CONTENT")

    context = run_evals.assemble_context(skill_dir)

    assert "UNIQUE_HEURISTICS_CONTENT" in context
    assert "UNIQUE_TOOL_RULES_CONTENT" not in context
    assert "UNIQUE_SOURCES_CONTENT" not in context


def test_assemble_context_raises_when_nothing_beyond_skill_md(tmp_path):
    skill_dir = tmp_path / "empty-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("# empty-skill\n")

    with pytest.raises(RuntimeError, match="no checklist content"):
        run_evals.assemble_context(skill_dir)


def test_assemble_context_raises_when_reference_dir_is_only_deeper_files(tmp_path):
    """A reference/ dir that exists but contains only tool-rules.md/sources.md
    must still trip the empty-context guard -- those files are excluded from
    the assembled context, so their mere presence on disk doesn't count as
    checklist content."""
    skill_dir = tmp_path / "only-deeper-files"
    (skill_dir / "reference").mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("# only-deeper-files\n")
    (skill_dir / "reference" / "tool-rules.md").write_text("x")
    (skill_dir / "reference" / "sources.md").write_text("x")

    with pytest.raises(RuntimeError, match="no checklist content"):
        run_evals.assemble_context(skill_dir)


@pytest.mark.parametrize(
    "text",
    [
        "**No findings**",
        "## No findings",
        "No findings: the change looks correct and no defects were spotted.",
        "no findings",
        "  No findings  ",
    ],
)
def test_is_no_findings_true_for_observed_formattings(text):
    """docs/runbooks/cross-model-re-gate.md records the three headline shapes
    models actually use, plus the two bugs a naive check fell into: a bare
    `startswith` misses the `**`/`##` markup, and stripping markup with
    `re.sub(r'[*_#\\s]+', ' ', t)` alone leaves a leading space that breaks
    `startswith` a second time."""
    assert run_evals.is_no_findings(text)


@pytest.mark.parametrize(
    "text",
    [
        "Found one issue: the retry loop has no backoff.",
        "Not no findings, just kidding -- here's a real one.",
        "",
        "Findings: none of the above apply, but see the note below.",
    ],
)
def test_is_no_findings_false_for_real_findings(text):
    assert not run_evals.is_no_findings(text)


def test_run_skill_evals_openai_backend(tmp_path, monkeypatch):
    skill = Skill(
        name="hunting-silent-failures",
        description="x",
        shape="diff",
        wave=1,
        built_from=[Source(2, "tests/fixtures/research_sample.md#2")],
    )
    out = generate_skill(skill, "v0.2", docs_root=str(ROOT), skills_root=str(tmp_path))
    (out / "evals" / "eval.json").write_text(_valid_eval_json())

    calls = []

    def fake_openai(
        model,
        system,
        user,
        host=run_evals.OPENAI_HOST,
        timeout=run_evals.DEFAULT_TIMEOUT_SECONDS,
        max_tokens=None,
    ):
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


def test_query_ollama_string_message_raises_cleanly(monkeypatch):
    # #371: `data.get("message", {}).get("content")` raised a raw AttributeError
    # on this shape (a proxy error body with `message` as a bare string, not a
    # dict) instead of the module's RuntimeError-only contract -- aborting the
    # whole eval suite instead of being recorded as one failed scenario.
    _patch_urlopen(monkeypatch, body=json.dumps({"message": "<string>"}).encode())
    with pytest.raises(RuntimeError, match="unexpected Ollama response shape"):
        run_evals.query_ollama("m", "sys", "usr")


def test_query_ollama_truncated_generation_raises(monkeypatch):
    # #371: done_reason=length means the generation was cut off mid-answer by
    # num_ctx or num_predict -- HTTP 200 with syntactically valid but truncated
    # content, indistinguishable from a genuine short answer by content alone.
    _patch_urlopen(
        monkeypatch,
        body=json.dumps(
            {"message": {"content": "partial answer cut off"}, "done_reason": "length"}
        ).encode(),
    )
    with pytest.raises(RuntimeError, match="truncated"):
        run_evals.query_ollama("m", "sys", "usr")


def test_query_ollama_non_length_done_reason_does_not_raise(monkeypatch):
    _patch_urlopen(
        monkeypatch,
        body=json.dumps(
            {"message": {"content": "a complete finding"}, "done_reason": "stop"}
        ).encode(),
    )
    assert run_evals.query_ollama("m", "sys", "usr") == "a complete finding"


def test_query_ollama_sends_num_predict_when_max_tokens_set(monkeypatch):
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["payload"] = json.loads(req.data)
        return _FakeResp(json.dumps({"message": {"content": "ok"}}).encode())

    monkeypatch.setattr(run_evals.urllib.request, "urlopen", fake_urlopen)
    run_evals.query_ollama("m", "sys", "usr", max_tokens=256)
    assert captured["payload"]["options"]["num_predict"] == 256


def test_query_ollama_omits_num_predict_by_default(monkeypatch):
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["payload"] = json.loads(req.data)
        return _FakeResp(json.dumps({"message": {"content": "ok"}}).encode())

    monkeypatch.setattr(run_evals.urllib.request, "urlopen", fake_urlopen)
    run_evals.query_ollama("m", "sys", "usr")
    assert "num_predict" not in captured["payload"]["options"]


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


def test_query_openai_truncated_generation_raises(monkeypatch):
    # #371: mirror of query_ollama's done_reason check for the
    # OpenAI-compatible shape (choices[0].finish_reason).
    _patch_urlopen(
        monkeypatch,
        body=json.dumps(
            {
                "choices": [
                    {
                        "message": {"content": "partial answer cut off"},
                        "finish_reason": "length",
                    }
                ]
            }
        ).encode(),
    )
    with pytest.raises(RuntimeError, match="truncated"):
        run_evals.query_openai("m", "sys", "usr")


def test_query_openai_non_length_finish_reason_does_not_raise(monkeypatch):
    _patch_urlopen(
        monkeypatch,
        body=json.dumps(
            {
                "choices": [
                    {
                        "message": {"content": "a complete finding"},
                        "finish_reason": "stop",
                    }
                ]
            }
        ).encode(),
    )
    assert run_evals.query_openai("m", "sys", "usr") == "a complete finding"


def test_query_openai_sends_max_tokens_when_set(monkeypatch):
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["payload"] = json.loads(req.data)
        return _FakeResp(
            json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode()
        )

    monkeypatch.setattr(run_evals.urllib.request, "urlopen", fake_urlopen)
    run_evals.query_openai("m", "sys", "usr", max_tokens=256)
    assert captured["payload"]["max_tokens"] == 256


def test_query_openai_omits_max_tokens_by_default(monkeypatch):
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["payload"] = json.loads(req.data)
        return _FakeResp(
            json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode()
        )

    monkeypatch.setattr(run_evals.urllib.request, "urlopen", fake_urlopen)
    run_evals.query_openai("m", "sys", "usr")
    assert "max_tokens" not in captured["payload"]


# --- model digest recording (#434) ---


def test_query_ollama_show_returns_response_dict(monkeypatch):
    _patch_urlopen(
        monkeypatch,
        body=json.dumps({"digest": "sha256:abc123", "parameters": "..."}).encode(),
    )
    assert run_evals.query_ollama_show("m")["digest"] == "sha256:abc123"


def test_query_ollama_show_sends_model_field(monkeypatch):
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["payload"] = json.loads(req.data)
        return _FakeResp(json.dumps({"digest": "sha256:abc123"}).encode())

    monkeypatch.setattr(run_evals.urllib.request, "urlopen", fake_urlopen)
    run_evals.query_ollama_show("m")
    assert captured["payload"] == {"model": "m"}


def test_query_ollama_show_surfaces_api_error_message(monkeypatch):
    _patch_urlopen(
        monkeypatch, body=json.dumps({"error": "model 'x' not found"}).encode()
    )
    with pytest.raises(RuntimeError, match="model 'x' not found"):
        run_evals.query_ollama_show("m")


def test_query_ollama_show_unexpected_shape_raises(monkeypatch):
    _patch_urlopen(monkeypatch, body=json.dumps(["not", "a", "dict"]).encode())
    with pytest.raises(RuntimeError, match="unexpected Ollama /api/show response"):
        run_evals.query_ollama_show("m")


def test_resolve_ollama_digest_returns_digest(monkeypatch):
    _patch_urlopen(monkeypatch, body=json.dumps({"digest": "sha256:abc123"}).encode())
    assert run_evals.resolve_ollama_digest("m") == "sha256:abc123"


def test_resolve_ollama_digest_none_when_field_absent(monkeypatch):
    def fake_show(model, host=None, timeout=None):
        return {"parameters": "..."}

    monkeypatch.setattr(run_evals, "query_ollama_show", fake_show)
    assert run_evals.resolve_ollama_digest("m") is None


def test_resolve_ollama_digest_none_on_lookup_failure(monkeypatch):
    # An older Ollama server without /api/show, or any network failure, must
    # not raise out of a provenance lookup and abort an otherwise-good run.
    _patch_urlopen(monkeypatch, exc=urllib.error.URLError("connection refused"))
    assert run_evals.resolve_ollama_digest("m") is None


def test_cli_prints_model_and_digest_for_ollama(tmp_path, monkeypatch, capsys):
    out = _skill_with_evals(tmp_path)
    monkeypatch.setattr(run_evals, "query_ollama", lambda *a, **kw: "No findings")
    captured = {}

    def fake_resolve_digest(model, **kw):
        captured["model"] = model
        captured.update(kw)
        return "sha256:abc123"

    monkeypatch.setattr(run_evals, "resolve_ollama_digest", fake_resolve_digest)
    rc = run_evals.main(
        ["--skill", out.name, "--skills-root", str(tmp_path), "--model", "fake-model"]
    )
    assert rc == 0
    printed = capsys.readouterr().out
    assert "MODEL: fake-model" in printed
    assert "DIGEST: sha256:abc123" in printed
    # main() wires host/timeout into the digest lookup, not just the model
    # name -- an argument-agnostic stub here wouldn't catch a dropped
    # `or OLLAMA_HOST` fallback or the wrong timeout reaching this call.
    assert captured == {
        "model": "fake-model",
        "host": run_evals.OLLAMA_HOST,
        "timeout": run_evals.DEFAULT_TIMEOUT_SECONDS,
    }


def test_cli_reports_digest_unavailable_when_lookup_returns_none(
    tmp_path, monkeypatch, capsys
):
    out = _skill_with_evals(tmp_path)
    monkeypatch.setattr(run_evals, "query_ollama", lambda *a, **kw: "No findings")
    monkeypatch.setattr(run_evals, "resolve_ollama_digest", lambda *a, **kw: None)
    rc = run_evals.main(
        ["--skill", out.name, "--skills-root", str(tmp_path), "--model", "fake-model"]
    )
    assert rc == 0
    assert "DIGEST: unavailable" in capsys.readouterr().out


def test_cli_skips_digest_lookup_for_openai_backend(tmp_path, monkeypatch, capsys):
    # No standardized digest endpoint exists across OpenAI-compatible servers
    # (llama-server, vLLM, ...) -- must not even attempt the lookup.
    out = _skill_with_evals(tmp_path)
    monkeypatch.setattr(run_evals, "query_openai", lambda *a, **kw: "No findings")

    def fail_any(*a, **kw):
        raise AssertionError("digest lookup must not run for --api openai")

    monkeypatch.setattr(run_evals, "resolve_ollama_digest", fail_any)
    rc = run_evals.main(
        [
            "--skill",
            out.name,
            "--skills-root",
            str(tmp_path),
            "--model",
            "fake-model",
            "--api",
            "openai",
        ]
    )
    assert rc == 0
    assert "DIGEST" not in capsys.readouterr().out


def test_cli_rejects_missing_skill_before_attempting_digest_lookup(
    tmp_path, monkeypatch, capsys
):
    # dees-bot round 1 (PR #460): the digest lookup used to run before
    # skill_dir was validated, so a typo'd --skill blocked on a real network
    # call (up to --timeout) before ever reaching this cheap local check.
    def fail_any(*a, **kw):
        raise AssertionError("digest lookup must not run before skill_dir is validated")

    monkeypatch.setattr(run_evals, "resolve_ollama_digest", fail_any)
    rc = run_evals.main(
        [
            "--skill",
            "no-such-skill",
            "--skills-root",
            str(tmp_path),
            "--model",
            "fake-model",
        ]
    )
    assert rc == 1
    assert "no-such-skill" in capsys.readouterr().out


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
    out = generate_skill(skill, "v0.2", docs_root=str(ROOT), skills_root=str(tmp_path))
    (out / "evals" / "eval.json").write_text(_valid_eval_json())

    def fail_any(*a, **kw):
        raise AssertionError("no backend should be called for an unknown api")

    monkeypatch.setattr(run_evals, "query_ollama", fail_any)
    monkeypatch.setattr(run_evals, "query_openai", fail_any)
    with pytest.raises(ValueError, match="unknown api"):
        run_evals.run_skill_evals(
            out, "fake-model", host="http://localhost:9999", api="bogus"
        )


def test_run_skill_evals_rejects_think_with_openai_backend(tmp_path, monkeypatch):
    # #371: --think has no OpenAI-compatible equivalent at all; silently
    # dropping it previously left an operator believing they'd forced
    # thinking mode when nothing was actually sent.
    skill = Skill(
        name="hunting-silent-failures",
        description="x",
        shape="diff",
        wave=1,
        built_from=[Source(2, "tests/fixtures/research_sample.md#2")],
    )
    out = generate_skill(skill, "v0.2", docs_root=str(ROOT), skills_root=str(tmp_path))
    (out / "evals" / "eval.json").write_text(_valid_eval_json())

    def fail_any(*a, **kw):
        raise AssertionError("no backend should be called on a rejected combination")

    monkeypatch.setattr(run_evals, "query_ollama", fail_any)
    monkeypatch.setattr(run_evals, "query_openai", fail_any)
    with pytest.raises(ValueError, match="ollama-only"):
        run_evals.run_skill_evals(out, "fake-model", api="openai", think=True)


# --- CLI argument validation (#23) ---


def test_cli_think_and_no_think_are_mutually_exclusive(tmp_path, capsys):
    with pytest.raises(SystemExit):
        run_evals.main(
            ["--skill", "x", "--skills-root", str(tmp_path), "--think", "--no-think"]
        )
    assert "not allowed with argument" in capsys.readouterr().err


@pytest.mark.parametrize("flag", ["--num-ctx", "--timeout", "--max-tokens"])
def test_cli_rejects_non_positive_int_options(flag, tmp_path, capsys):
    with pytest.raises(SystemExit):
        run_evals.main(["--skill", "x", "--skills-root", str(tmp_path), flag, "0"])
    assert "positive integer" in capsys.readouterr().err


def test_cli_rejects_explicit_num_ctx_with_openai_backend(tmp_path, capsys):
    # #371: OLLAMA_NUM_CTX has no OpenAI-compatible request field at all (that
    # server sets its window at startup via -c) -- an explicit --num-ctx with
    # --api openai would silently be a no-op rather than actually widening
    # anything, leaving an operator believing they'd changed the window.
    with pytest.raises(SystemExit):
        run_evals.main(
            [
                "--skill",
                "x",
                "--skills-root",
                str(tmp_path),
                "--api",
                "openai",
                "--num-ctx",
                "16384",
            ]
        )
    assert "ollama-only" in capsys.readouterr().err


def test_cli_rejects_explicit_num_ctx_matching_the_default_with_openai_backend(
    tmp_path, capsys
):
    """Round-1 review finding: comparing args.num_ctx against OLLAMA_NUM_CTX
    to detect "was --num-ctx explicitly passed" is defeated the instant an
    operator's explicit value happens to equal the current default (e.g.
    passing today's OLLAMA_NUM_CTX because that's what they intend, or
    because they don't realize this default just changed) -- that combination
    must still be rejected, not silently accepted as "the untouched default"."""
    with pytest.raises(SystemExit):
        run_evals.main(
            [
                "--skill",
                "x",
                "--skills-root",
                str(tmp_path),
                "--api",
                "openai",
                "--num-ctx",
                str(run_evals.OLLAMA_NUM_CTX),
            ]
        )
    assert "ollama-only" in capsys.readouterr().err


# --- partial-run resilience (the 2026-08-08 cross-model re-gate) ---


def _skill_with_evals(tmp_path):
    skill = Skill(
        name="hunting-silent-failures",
        description="x",
        shape="diff",
        wave=1,
        built_from=[Source(2, "tests/fixtures/research_sample.md#2")],
    )
    out = generate_skill(skill, "v0.2", docs_root=str(ROOT), skills_root=str(tmp_path))
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
    # #434's digest lookup is a separate network call from query_ollama above;
    # stub it too so this test stays hermetic (no real socket attempt).
    monkeypatch.setattr(run_evals, "resolve_ollama_digest", lambda *a, **kw: None)
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
    monkeypatch.setattr(run_evals, "resolve_ollama_digest", lambda *a, **kw: None)
    rc = run_evals.main(
        ["--skill", out.name, "--skills-root", str(tmp_path), "--model", "fake-model"]
    )
    assert rc == 1
    assert "do not grade it" in capsys.readouterr().out
