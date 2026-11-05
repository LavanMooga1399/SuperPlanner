"""ERP adapter protocol (M5-DESIGN 4.7): maps an ERP's formats to and from `superplanner.v1`."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Protocol

from ..contract import V1Batch, V1Event


@dataclass
class Delivery:
    """One outbound call or file of an adapter (`kind` webhook | file)."""
    kind: str
    body: bytes
    headers: dict[str, str] = field(default_factory=dict)
    name: str | None = None


class ErpAdapter(Protocol):
    name: str

    def inbound(self, raw: bytes | dict[str, Any], filename: str | None) -> list[V1Batch]: ...

    def outbound(self, event: V1Event) -> list[Delivery]: ...

    def snapshot(self, entity: str) -> Iterable[Any] | None: ...
