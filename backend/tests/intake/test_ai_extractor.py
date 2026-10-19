"""AI extractor contract with a fake client (PHASE2 2.10, 2.16; plan P2-5). No test touches the network."""

from __future__ import annotations

import builtins
import json
import logging
import threading

import anthropic
import httpx2
import pytest

from intake_helpers import (CTX, FIN_CTX, FINANCE_TEXT, SCHEDULE_TEXT, FakeClient, ai_finance_output,
                            ai_schedule_output, text_response)
from superplanner.intake import AiOptions, describe_finance, describe_schedule
from superplanner.intake.ai import client as ai_client
from superplanner.intake.ai.client import FINANCE_SCHEMA, SCHEDULE_SCHEMA, ai_status, default_client_factory
from superplanner.intake.ai.prompts import finance_prompt, schedule_prompt
from superplanner.intake.messages import FALLBACK_CODES, fallback_message

_REQ = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


def _resp(status: int) -> httpx2.Response:
    return httpx2.Response(status, request=_REQ)


def opts(client: FakeClient | None = None, *, enabled: bool = True, factory=None, **kw) -> AiOptions:
    if factory is None and client is not None:
        factory = lambda: client  # noqa: E731
    return AiOptions(requested=True, enabled=enabled, client_factory=factory, **kw)


def test_exact_call_kwargs_schedule():
    fake = FakeClient(text_response(ai_schedule_output()))
    r = describe_schedule(SCHEDULE_TEXT, CTX, ai=opts(fake))
    assert r.extractor.used == "ai+rule" and r.extractor.model == "claude-opus-5-5"
    assert r.extractor.fallback_code is None
    assert len(fake.calls) == 1
    kw = fake.calls[0]
    assert set(kw) == {"model", "max_tokens", "betas", "fallbacks", "output_config", "system", "messages"}
    assert kw["model"] == "claude-opus-5-5"
    assert kw["max_tokens"] == 16000
    assert kw["betas"] == ["server-side-fallback-2026-07-01"]
    assert kw["fallbacks"] == "default"
    assert kw["output_config"] == {"effort": "medium", "format": {"type": "json_schema", "schema": SCHEDULE_SCHEMA}}
    assert kw["system"] == schedule_prompt(CTX) and isinstance(kw["system"], str)
    assert kw["messages"] == [{"role": "user", "content": SCHEDULE_TEXT}]
    for banned in ("thinking", "temperature", "top_p", "top_k", "tool_choice", "tools"):
        assert banned not in kw
    assert all(m["role"] != "assistant" for m in kw["messages"])


def test_exact_call_kwargs_finance():
    fake = FakeClient(text_response(ai_finance_output()))
    r = describe_finance(FINANCE_TEXT, FIN_CTX, ai=opts(fake))
    assert r.extractor.used == "ai+rule"
    kw = fake.calls[0]
    assert kw["output_config"]["format"]["schema"] == FINANCE_SCHEMA
    assert kw["system"] == finance_prompt(FIN_CTX)
    assert kw["messages"] == [{"role": "user", "content": FINANCE_TEXT}]
    assert "2026-10-17" in kw["system"] and "INR" in kw["system"]


def test_default_factory_uses_timeout_and_retries(monkeypatch):
    seen = {}

    class FakeAnthropic:
        def __init__(self, **kw):
            seen.update(kw)
            self.api_key = "sk-x"

    monkeypatch.setattr(anthropic, "Anthropic", FakeAnthropic)
    o = AiOptions(requested=True, enabled=True, client_factory=None)
    default_client_factory(o)()
    assert seen == {"timeout": 60.0, "max_retries": 2}
    seen.clear()
    default_client_factory(AiOptions(requested=True, enabled=True, client_factory=None, timeout_seconds=12.5,
                                     max_retries=1))()
    assert seen == {"timeout": 12.5, "max_retries": 1}
    assert ai_status(o) == (True, None)


@pytest.mark.parametrize("response,code", [
    (text_response({}, stop_reason="refusal"), "AI_REFUSED"),
    (text_response({}, stop_reason="max_tokens"), "AI_TRUNCATED"),
    (type("R", (), {"stop_reason": "end_turn", "content": []})(), "AI_NO_TEXT"),
    (text_response(None, raw="{not json"), "AI_BAD_JSON"),
    (text_response({"kind": "project"}), "AI_SCHEMA_MISMATCH"),
    (text_response(ai_schedule_output(kind="space-opera")), "AI_SCHEMA_MISMATCH"),
])
def test_response_fallbacks(response, code):
    fake = FakeClient(response)
    rule = describe_schedule(SCHEDULE_TEXT, CTX)
    r = describe_schedule(SCHEDULE_TEXT, CTX, ai=opts(fake))
    assert r.extractor.requested == "ai" and r.extractor.used == "rule"
    assert r.extractor.fallback_code == code
    assert r.extractor.fallback_message == fallback_message(code)
    assert r.extractor.fallback_message.endswith("We used the built-in reader instead.")
    assert r.draft == rule.draft


@pytest.mark.parametrize("exc,code", [
    (anthropic.RateLimitError("slow down", response=_resp(429), body=None), "AI_RATE_LIMITED"),
    (anthropic.AuthenticationError("bad key", response=_resp(401), body=None), "AI_AUTH_FAILED"),
    (anthropic.InternalServerError("boom", response=_resp(500), body=None), "AI_API_ERROR"),
    (anthropic.APIStatusError("teapot", response=_resp(418), body=None), "AI_API_ERROR"),
    (anthropic.APIConnectionError(request=_REQ), "AI_CONNECTION_ERROR"),
    (anthropic.APITimeoutError(request=_REQ), "AI_CONNECTION_ERROR"),
    (RuntimeError("something odd"), "AI_UNEXPECTED"),
])
def test_exception_fallbacks_most_specific_first(exc, code):
    r = describe_finance(FINANCE_TEXT, FIN_CTX, ai=opts(FakeClient(exc=exc)))
    assert r.extractor.used == "rule" and r.extractor.fallback_code == code
    if code == "AI_API_ERROR":
        assert f"(status {exc.status_code})" in r.extractor.fallback_message


def test_rate_limit_is_a_status_error_but_maps_to_rate_limited():
    exc = anthropic.RateLimitError("x", response=_resp(429), body=None)
    assert isinstance(exc, anthropic.APIStatusError)
    r = describe_schedule(SCHEDULE_TEXT, CTX, ai=opts(FakeClient(exc=exc)))
    assert r.extractor.fallback_code == "AI_RATE_LIMITED"


def test_disabled_and_not_requested():
    fake = FakeClient(text_response(ai_schedule_output()))
    r = describe_schedule(SCHEDULE_TEXT, CTX, ai=opts(fake, enabled=False))
    assert r.extractor.fallback_code == "AI_DISABLED" and r.extractor.ai_available is False
    assert fake.calls == []
    r = describe_schedule(SCHEDULE_TEXT, CTX, ai=AiOptions(requested=False, enabled=True, client_factory=lambda: fake))
    assert r.extractor.requested == "rule" and r.extractor.used == "rule" and r.extractor.ai_available is True
    assert r.extractor.fallback_code is None and fake.calls == []


@pytest.mark.parametrize("attrs,available", [
    ({"api_key": "sk-1"}, True),
    ({"api_key": None, "auth_token": "tok"}, True),
    ({"api_key": None, "credentials": object()}, True),
    ({"api_key": None}, False),
])
def test_credentials_attributes(attrs, available):
    fake = FakeClient(text_response(ai_schedule_output()), **attrs)
    assert ai_status(opts(fake)) == ((True, None) if available else (False, "AI_NO_CREDENTIALS"))
    r = describe_schedule(SCHEDULE_TEXT, CTX, ai=opts(fake))
    assert r.extractor.used == ("ai+rule" if available else "rule")
    if not available:
        assert r.extractor.fallback_code == "AI_NO_CREDENTIALS" and fake.calls == []


def test_factory_failure_means_no_credentials():
    def boom():
        raise anthropic.AnthropicError("no credentials found")
    r = describe_schedule(SCHEDULE_TEXT, CTX, ai=opts(factory=boom))
    assert r.extractor.fallback_code == "AI_NO_CREDENTIALS"


def test_sdk_missing(monkeypatch):
    real_import = builtins.__import__

    def fake_import(name, *a, **kw):
        if name == "anthropic" or name.startswith("anthropic."):
            raise ImportError("no anthropic")
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    fake = FakeClient(text_response(ai_schedule_output()))
    assert ai_status(opts(fake)) == (False, "AI_SDK_MISSING")
    r = describe_schedule(SCHEDULE_TEXT, CTX, ai=opts(fake))
    assert r.extractor.fallback_code == "AI_SDK_MISSING" and fake.calls == []


def test_busy_slot_and_release():
    fake = FakeClient(text_response(ai_schedule_output()))
    released = []
    r = describe_schedule(SCHEDULE_TEXT, CTX, ai=opts(fake, acquire_slot=lambda: False,
                                                      release_slot=lambda: released.append(1)))
    assert r.extractor.fallback_code == "AI_BUSY" and fake.calls == [] and released == []
    r = describe_schedule(SCHEDULE_TEXT, CTX, ai=opts(FakeClient(exc=RuntimeError("x")), acquire_slot=lambda: True,
                                                      release_slot=lambda: released.append(1)))
    assert r.extractor.fallback_code == "AI_UNEXPECTED" and released == [1]


def test_app_slots_time_out_to_busy():
    from superplanner.api.intake.service import AiSlots

    slots = AiSlots(1, wait_seconds=0.05)
    assert slots.acquire()
    fake = FakeClient(text_response(ai_schedule_output()))
    r = describe_schedule(SCHEDULE_TEXT, CTX, ai=opts(fake, acquire_slot=slots.acquire, release_slot=slots.release))
    assert r.extractor.fallback_code == "AI_BUSY"
    slots.release()
    r = describe_schedule(SCHEDULE_TEXT, CTX, ai=opts(fake, acquire_slot=slots.acquire, release_slot=slots.release))
    assert r.extractor.used == "ai+rule"
    assert slots.acquire()   # released again after the call
    slots.release()


def test_concurrent_calls_limited_per_app():
    from superplanner.api.intake.service import AiSlots

    slots = AiSlots(2, wait_seconds=0.2)
    gate = threading.Event()
    inside = []

    class Slow(FakeClient):
        pass

    slow = Slow(text_response(ai_schedule_output()))
    orig = slow.beta.messages.create

    def create(**kw):
        inside.append(1)
        gate.wait(2)
        return orig(**kw)

    slow.beta.messages.create = create
    results = []

    def go():
        results.append(describe_schedule(SCHEDULE_TEXT, CTX, ai=opts(slow, acquire_slot=slots.acquire,
                                                                     release_slot=slots.release)))

    threads = [threading.Thread(target=go) for _ in range(3)]
    for t in threads:
        t.start()
    threads[0].join(0.6)
    gate.set()
    for t in threads:
        t.join()
    codes = sorted(r.extractor.fallback_code or "ok" for r in results)
    assert codes == ["AI_BUSY", "ok", "ok"]


def test_every_fallback_code_has_a_message():
    for code in FALLBACK_CODES:
        assert fallback_message(code, status=500).endswith("We used the built-in reader instead.")


def test_sdk_loggers_capped_and_no_text_logged(caplog):
    for name in ("anthropic", "httpx2", "httpcore2"):
        assert logging.getLogger(name).level == logging.WARNING
    caplog.set_level(logging.DEBUG)
    fake = FakeClient(text_response(ai_schedule_output()))
    describe_schedule(SCHEDULE_TEXT, CTX, ai=opts(fake))
    describe_finance(FINANCE_TEXT, FIN_CTX, ai=opts(FakeClient(exc=RuntimeError(FINANCE_TEXT))))
    logged = "\n".join(r.getMessage() for r in caplog.records)
    for fragment in ("Gather requirements", "Ravi", "1.2 lakh", "mutual funds", "Launch date looks fixed"):
        assert fragment not in logged
    assert "AI_UNEXPECTED" in logged or "RuntimeError" in logged


def test_ai_output_spans_and_confidence():
    fake = FakeClient(text_response(ai_schedule_output()))
    r = describe_schedule(SCHEDULE_TEXT, CTX, ai=opts(fake))
    added = next(t for t in r.draft.tasks if t.name == "Write release notes")
    p = r.draft.provenance[f"/tasks/{added.key}/name"]
    assert p.source == "ai" and p.span is None and p.confidence == 0.5      # quote not in the text
    for path, prov in r.draft.provenance.items():
        if prov.source == "ai":
            assert prov.confidence <= 0.8, path
            if prov.span is not None:
                assert SCHEDULE_TEXT[prov.span.start:prov.span.end] == prov.span.text


def test_ai_values_are_clipped_and_untrusted():
    out = ai_schedule_output()
    out["tasks"][0]["duration"] = {"low": 1e9, "likely": None, "high": 2e9, "unit": "days"}
    out["tasks"][0]["confidence"] = 7.0
    out["resources"][0]["count"] = 10_000
    out["name"] = "x" * 5000
    fake = FakeClient(text_response(out))
    r = describe_schedule("Plan: write docs\nship it by 2026-12-01", CTX, ai=opts(fake))
    assert r.extractor.used == "ai+rule"
    json.dumps(r.model_dump(mode="json"))   # always a valid response
    assert len(r.draft.name) <= 200
    assert all(res.count <= 50 for res in r.draft.resources)
    assert all(t.duration.pessimistic <= 10000 for t in r.draft.tasks if t.duration)


def test_client_module_is_the_only_sdk_importer():
    import pathlib
    import re

    root = pathlib.Path(ai_client.__file__).resolve().parents[2]
    hits = []
    for f in root.rglob("*.py"):
        for line in f.read_text().splitlines():
            if re.match(r"^\s*(import anthropic|from anthropic)", line):
                hits.append(f.relative_to(root).as_posix())
    assert set(hits) == {"intake/ai/client.py"}
    intake_dir = root / "intake"
    for f in intake_dir.rglob("*.py"):
        assert not re.search(r"thinking|temperature|top_p|top_k|tool_choice", f.read_text()), f


def test_locate_quotes_case_insensitively_on_code_points():
    from superplanner.intake.ai.convert import locate

    text = "İstanbul trip 🚀 Gather Requirements now"
    sp = locate("gather requirements", text)
    assert sp is not None and text[sp.start:sp.end] == "Gather Requirements" == sp.text
    assert locate("not here", text) is None and locate("", text) is None
