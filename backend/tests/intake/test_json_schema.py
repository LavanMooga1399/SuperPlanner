"""Strict schema for structured outputs (PHASE2 2.10; plan P2-6)."""

from __future__ import annotations

from typing import Any, Iterator

import pytest
from pydantic import BaseModel

from superplanner.intake.ai.json_schema import KEPT_KEYS, strict_json_schema
from superplanner.intake.ai.schemas import AiFinanceOutput, AiScheduleOutput

DROPPED = ("title", "default", "minimum", "maximum", "minLength", "maxLength", "pattern", "format", "minItems",
           "maxItems", "examples", "$ref", "$defs", "exclusiveMinimum", "exclusiveMaximum")


def nodes(node: Any) -> Iterator[dict]:
    if isinstance(node, dict):
        yield node
        for k, v in node.items():
            if k == "properties":
                for pv in v.values():
                    yield from nodes(pv)
            else:
                yield from nodes(v)
    elif isinstance(node, list):
        for x in node:
            yield from nodes(x)


@pytest.mark.parametrize("model", [AiScheduleOutput, AiFinanceOutput])
def test_every_object_closed_and_fully_required(model):
    schema = strict_json_schema(model)
    assert schema["type"] == "object"
    objects = 0
    for n in nodes(schema):
        assert set(n) <= set(KEPT_KEYS), set(n) - set(KEPT_KEYS)
        for k in DROPPED:
            assert k not in n
        if n.get("type") == "object":
            objects += 1
            assert n["additionalProperties"] is False
            assert n["required"] == list(n["properties"])
    assert objects >= 4


@pytest.mark.parametrize("model", [AiScheduleOutput, AiFinanceOutput])
def test_no_defaults_in_ai_models(model):
    def walk(m: type[BaseModel]):
        for name, f in m.model_fields.items():
            assert f.is_required(), f"{m.__name__}.{name} has a default"
            ann = f.annotation
            for sub in getattr(ann, "__args__", ()) or (ann,):
                if isinstance(sub, type) and issubclass(sub, BaseModel):
                    walk(sub)
                for subsub in getattr(sub, "__args__", ()):
                    if isinstance(subsub, type) and issubclass(subsub, BaseModel):
                        walk(subsub)
        assert m.model_config.get("extra") == "forbid", m.__name__
    walk(model)


def test_nullable_fields_are_any_of_with_null():
    schema = strict_json_schema(AiScheduleOutput)
    wt = schema["properties"]["working_time"]
    assert "anyOf" in wt and {"type": "null"} in wt["anyOf"]
    inner = next(x for x in wt["anyOf"] if x.get("type") == "object")
    assert inner["required"] == ["days", "windows", "weekend_windows", "source_quote"]
    task = schema["properties"]["tasks"]["items"]
    assert task["properties"]["resource_mode"]["enum"] == ["any", "all"]


def test_nested_model_inlined():
    class Inner(BaseModel):
        a: int

    class Outer(BaseModel):
        x: Inner
        y: list[Inner]

    s = strict_json_schema(Outer)
    assert s["properties"]["x"]["properties"]["a"]["type"] == "integer"
    assert s["properties"]["y"]["items"]["additionalProperties"] is False
    assert "$defs" not in s
