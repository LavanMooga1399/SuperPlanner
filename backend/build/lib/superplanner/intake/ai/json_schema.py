"""Strict JSON schema for structured outputs (PHASE2 2.10).

`model_json_schema()` with every `$ref` inlined, `$defs` removed, every object node closed
(`additionalProperties: false`, all properties required) and only the supported keywords kept.
"""

from __future__ import annotations

import copy
from typing import Any

from pydantic import BaseModel

KEPT_KEYS = ("type", "properties", "required", "additionalProperties", "items", "enum", "anyOf", "const",
             "description")


def strict_json_schema(model: type[BaseModel]) -> dict[str, Any]:
    raw = model.model_json_schema()
    defs = raw.get("$defs", {})

    def walk(node: Any, depth: int = 0) -> Any:
        if depth > 50:  # AI models are not recursive; this only guards against a bug
            raise ValueError("schema too deep")
        if isinstance(node, list):
            return [walk(x, depth + 1) for x in node]
        if not isinstance(node, dict):
            return node
        if "$ref" in node:
            name = node["$ref"].rsplit("/", 1)[-1]
            target = copy.deepcopy(defs[name])
            extra = {k: v for k, v in node.items() if k != "$ref"}
            target.update(extra)
            return walk(target, depth + 1)
        out: dict[str, Any] = {}
        for k, v in node.items():
            if k not in KEPT_KEYS:
                continue
            if k == "properties":
                out[k] = {pk: walk(pv, depth + 1) for pk, pv in v.items()}
            elif k in ("items",):
                out[k] = walk(v, depth + 1)
            elif k == "anyOf":
                out[k] = [walk(x, depth + 1) for x in v]
            else:
                out[k] = copy.deepcopy(v)
        if out.get("type") == "object" or "properties" in out:
            out["type"] = "object"
            props = out.setdefault("properties", {})
            out["additionalProperties"] = False
            out["required"] = list(props)
        return out

    return walk({k: v for k, v in raw.items() if k != "$defs"})
