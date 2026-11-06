"""The assistant's model client (M6-DESIGN 1.1-1.2): same SDK, model, beta and fallback as intake (P2 2.10), its own
switch, timeout, retries and slots. The only assistant module that touches `anthropic` (lazily, through the intake
loader). Request / response content is never logged."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable

from ..intake.ai.client import has_credentials, load_sdk

log = logging.getLogger("superplanner.assistant")
for _name in ("anthropic", "httpx2", "httpcore2", "httpx", "httpcore"):
    logging.getLogger(_name).setLevel(logging.WARNING)

MODEL = "claude-opus-5-5"
BETAS = ["server-side-fallback-2026-07-01"]


class AssistantFallback(Exception):
    """A model call failed with a P2 2.10 code (`AI_*`)."""

    def __init__(self, code: str, status: int | None = None):
        super().__init__(code)
        self.code = code
        self.status = status


@dataclass
class ClientOptions:
    enabled: bool
    timeout_seconds: float
    max_retries: int
    factory: Callable[[], Any] | None = None


def options_of(settings: Any) -> ClientOptions:
    factory = settings.assistant_ai_client_factory
    demo = bool(getattr(settings, "assistant_ai_demo", False)) and not settings.is_production
    if factory is None and demo:
        from .fake import DemoClient

        factory = DemoClient
    return ClientOptions(enabled=bool(settings.assistant_ai_enabled) or demo,
                         timeout_seconds=float(settings.assistant_ai_timeout_seconds),
                         max_retries=int(settings.assistant_ai_max_retries), factory=factory)


def status_client(opts: ClientOptions) -> tuple[bool, str | None, Any]:
    """(available, code, client): P2 2.10 `ai_status` for the assistant switch."""
    if not opts.enabled:
        return False, "AI_DISABLED", None
    if opts.factory is None and load_sdk() is None:
        return False, "AI_SDK_MISSING", None
    try:
        if opts.factory is not None:
            client = opts.factory()
        else:
            sdk = load_sdk()
            client = sdk.Anthropic(timeout=opts.timeout_seconds, max_retries=opts.max_retries)  # type: ignore[union-attr]
    except Exception as exc:  # noqa: BLE001
        log.info("assistant AI client could not be created: %s", type(exc).__name__)
        return False, "AI_NO_CREDENTIALS", None
    if not has_credentials(client):
        return False, "AI_NO_CREDENTIALS", None
    return True, None, client


def create(client: Any, *, system: list[dict[str, Any]], tools: list[dict[str, Any]],
           messages: list[dict[str, Any]], max_tokens: int) -> Any:
    """One model round (1.2). No thinking / temperature / top_p / top_k / prefill (P2 2.10 rule)."""
    sdk = load_sdk()
    errors = _errors(sdk)
    try:
        return client.beta.messages.create(model=MODEL, max_tokens=max_tokens, betas=BETAS, fallbacks="default",
                                           system=system, tools=tools, messages=messages)
    except errors["rate"]:
        raise AssistantFallback("AI_RATE_LIMITED") from None
    except errors["auth"]:
        raise AssistantFallback("AI_AUTH_FAILED") from None
    except errors["status"] as e:
        raise AssistantFallback("AI_API_ERROR", status=getattr(e, "status_code", None)) from None
    except errors["conn"]:
        raise AssistantFallback("AI_CONNECTION_ERROR") from None
    except AssistantFallback:
        raise
    except Exception as e:  # noqa: BLE001
        log.warning("assistant model call failed unexpectedly: %s", type(e).__name__)
        raise AssistantFallback("AI_UNEXPECTED") from None


class _Never(Exception):
    pass


def _errors(sdk: Any) -> dict[str, Any]:
    if sdk is None:
        return {"rate": _Never, "auth": _Never, "status": _Never, "conn": _Never}
    return {"rate": sdk.RateLimitError, "auth": sdk.AuthenticationError, "status": sdk.APIStatusError,
            "conn": sdk.APIConnectionError}


def usage_of(resp: Any) -> tuple[int, int, int]:
    """(input incl. cache writes, output, cache reads)."""
    u = getattr(resp, "usage", None)
    if u is None:
        return 0, 0, 0
    inp = int(getattr(u, "input_tokens", 0) or 0) + int(getattr(u, "cache_creation_input_tokens", 0) or 0)
    return inp, int(getattr(u, "output_tokens", 0) or 0), int(getattr(u, "cache_read_input_tokens", 0) or 0)


def blocks_of(resp: Any) -> list[dict[str, Any]]:
    """Response content -> plain dicts (text / tool_use only; anything else is dropped)."""
    out: list[dict[str, Any]] = []
    for b in getattr(resp, "content", None) or []:
        t = getattr(b, "type", None) if not isinstance(b, dict) else b.get("type")
        g = (lambda k, b=b: b.get(k)) if isinstance(b, dict) else (lambda k, b=b: getattr(b, k, None))
        if t == "text":
            out.append({"type": "text", "text": str(g("text") or "")})
        elif t == "tool_use":
            out.append({"type": "tool_use", "id": str(g("id")), "name": str(g("name")),
                        "input": g("input") if isinstance(g("input"), dict) else {}})
    return out
