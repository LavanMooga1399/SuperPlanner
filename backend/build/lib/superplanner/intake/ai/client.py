"""AI assist through the official `anthropic` SDK 1.15.0 (PHASE2 2.10) - the exact contract.

This is the only module that imports `anthropic`, and only lazily. The output is untrusted: it is parsed as
JSON, validated by Pydantic, converted with clipping, merged (typed numbers win) and then goes through the same
questions, builders and preflight as manual input. Request and response text is never logged.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import ValidationError

from ..extractors import AiFallback, AiOptions, FinanceExtraction, ScheduleExtraction
from ..messages import MODEL
from ..models import ExtractContext
from . import prompts
from .convert import ai_to_finance_draft, ai_to_schedule_draft
from .json_schema import strict_json_schema
from .schemas import AiFinanceOutput, AiScheduleOutput

log = logging.getLogger("superplanner.intake.ai")

# SDK and transport loggers are capped at WARNING so request or response bodies never reach the server log,
# even with ANTHROPIC_LOG=debug or a DEBUG root logger.
for _name in ("anthropic", "httpx2", "httpcore2"):
    logging.getLogger(_name).setLevel(logging.WARNING)

MAX_TOKENS = 16000
BETAS = ["server-side-fallback-2026-07-01"]
SCHEDULE_SCHEMA = strict_json_schema(AiScheduleOutput)
FINANCE_SCHEMA = strict_json_schema(AiFinanceOutput)


def load_sdk() -> Any | None:
    try:
        import anthropic  # noqa: PLC0415 - lazy by design
    except ImportError:
        return None
    return anthropic


def default_client_factory(options: AiOptions):
    sdk = load_sdk()

    def factory():
        assert sdk is not None
        return sdk.Anthropic(timeout=options.timeout_seconds, max_retries=options.max_retries)
    return factory


def has_credentials(client: Any) -> bool:
    return bool(getattr(client, "api_key", None) or getattr(client, "auth_token", None)
                or getattr(client, "credentials", None))


def ai_status_client(options: AiOptions) -> tuple[bool, str | None, Any]:
    """(available, fallback code, client) evaluated per request; the client is reused for the call."""
    if not options.enabled:
        return False, "AI_DISABLED", None
    if load_sdk() is None:
        return False, "AI_SDK_MISSING", None
    factory = options.client_factory or default_client_factory(options)
    try:
        client = factory()
    except Exception as exc:  # noqa: BLE001 - any construction failure means "not set up"
        log.info("AI client could not be created: %s", type(exc).__name__)
        return False, "AI_NO_CREDENTIALS", None
    if not has_credentials(client):
        return False, "AI_NO_CREDENTIALS", None
    return True, None, client


def ai_status(options: AiOptions) -> tuple[bool, str | None]:
    ok, code, _ = ai_status_client(options)
    return ok, code


class AnthropicExtractor:
    name = "ai"

    def __init__(self, options: AiOptions, client: Any | None = None):
        self.options = options
        self._client = client

    def _client_or_new(self) -> Any:
        if self._client is None:
            factory = self.options.client_factory or default_client_factory(self.options)
            self._client = factory()
        return self._client

    def _call(self, system: str, schema: dict[str, Any], text: str) -> Any:
        sdk = load_sdk()
        if sdk is None:
            raise AiFallback("AI_SDK_MISSING")
        client = self._client_or_new()
        try:
            resp = client.beta.messages.create(
                model=MODEL, max_tokens=MAX_TOKENS,
                betas=BETAS, fallbacks="default",
                output_config={"effort": "medium", "format": {"type": "json_schema", "schema": schema}},
                system=system, messages=[{"role": "user", "content": text}])
        except sdk.RateLimitError:
            raise AiFallback("AI_RATE_LIMITED") from None
        except sdk.AuthenticationError:
            raise AiFallback("AI_AUTH_FAILED") from None
        except sdk.APIStatusError as e:
            raise AiFallback("AI_API_ERROR", status=e.status_code) from None
        except sdk.APIConnectionError:
            raise AiFallback("AI_CONNECTION_ERROR") from None
        except Exception as e:  # noqa: BLE001
            log.warning("AI assist failed unexpectedly: %s", type(e).__name__)
            raise AiFallback("AI_UNEXPECTED") from None
        stop = getattr(resp, "stop_reason", None)
        if stop == "refusal":
            raise AiFallback("AI_REFUSED")
        if stop == "max_tokens":
            raise AiFallback("AI_TRUNCATED")
        block = next((b for b in (getattr(resp, "content", None) or []) if getattr(b, "type", None) == "text"), None)
        if block is None:
            raise AiFallback("AI_NO_TEXT")
        try:
            return json.loads(block.text)
        except (json.JSONDecodeError, TypeError):
            raise AiFallback("AI_BAD_JSON") from None

    def extract_schedule(self, text: str, ctx: ExtractContext) -> ScheduleExtraction:
        obj = self._call(prompts.schedule_prompt(ctx), SCHEDULE_SCHEMA, text)
        try:
            out = AiScheduleOutput.model_validate(obj)
        except ValidationError:
            raise AiFallback("AI_SCHEMA_MISMATCH") from None
        try:
            draft, notes = ai_to_schedule_draft(out, text, ctx)
        except (ValidationError, ValueError):
            raise AiFallback("AI_SCHEMA_MISMATCH") from None
        return ScheduleExtraction(draft=draft, notes=notes)

    def extract_finance(self, text: str, ctx: ExtractContext) -> FinanceExtraction:
        obj = self._call(prompts.finance_prompt(ctx), FINANCE_SCHEMA, text)
        try:
            out = AiFinanceOutput.model_validate(obj)
        except ValidationError:
            raise AiFallback("AI_SCHEMA_MISMATCH") from None
        try:
            draft, notes = ai_to_finance_draft(out, text, ctx)
        except (ValidationError, ValueError):
            raise AiFallback("AI_SCHEMA_MISMATCH") from None
        return FinanceExtraction(draft=draft, notes=notes)
