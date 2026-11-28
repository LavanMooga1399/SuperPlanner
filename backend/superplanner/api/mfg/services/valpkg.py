"""Validation package, IQ check and evidence uploads (M10-DESIGN 8)."""

from __future__ import annotations

from typing import Any

from . import m10_examples


async def read_evidence(request: Any) -> Any:
    """Q5 body: JSON (`EvidenceInput`) or multipart (`file` = JSON document, form fields `kind`, `title`)."""
    import json

    from ....validation.model import EvidenceInput
    from ...errors import ApiError

    ctype = request.headers.get("content-type", "")
    try:
        if ctype.startswith("multipart/"):
            form = await request.form()
            f = form.get("file")
            raw = await f.read() if f is not None and hasattr(f, "read") else b"{}"
            return EvidenceInput.model_validate({"kind": form.get("kind") or "other",
                                                 "title": form.get("title") or getattr(f, "filename", "evidence"),
                                                 "provisional": str(form.get("provisional", "")).lower() == "true",
                                                 "content": json.loads(raw or b"{}")})
        return EvidenceInput.model_validate(json.loads(await request.body() or b"{}"))
    except (ValueError, TypeError) as exc:
        raise ApiError(422, "VALIDATION_ERROR", "The evidence must be a JSON document.",
                       {"errors": [{"loc": ["body"], "msg": str(exc)[:300], "type": "value_error"}]}) from None


__getattr__ = m10_examples.module_getattr(__name__)
