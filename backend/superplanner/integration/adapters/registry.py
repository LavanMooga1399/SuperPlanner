"""Adapter registry (M5-DESIGN 4.7): a new ERP is one module registered here plus tests."""

from __future__ import annotations

from .base import ErpAdapter
from .generic_v1 import GenericV1

ADAPTERS: dict[str, ErpAdapter] = {"generic_v1": GenericV1()}


def get(name: str) -> ErpAdapter:
    return ADAPTERS.get(name) or ADAPTERS["generic_v1"]


def names() -> list[str]:
    return sorted(ADAPTERS)
