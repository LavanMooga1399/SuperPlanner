"""`generic_v1`: the contract itself (M5-DESIGN 4.7) - inbound JSON batches as they are, events as signed JSON."""

from __future__ import annotations

import json
from typing import Any, Iterable

from ..contract import V1Batch, V1Event
from .base import Delivery


class GenericV1:
    name = "generic_v1"

    def inbound(self, raw: bytes | dict[str, Any], filename: str | None) -> list[V1Batch]:
        data = json.loads(raw) if isinstance(raw, (bytes, str)) else raw
        items = data if isinstance(data, list) else data.get("batches", [data])
        return [V1Batch.model_validate(x) for x in items]

    def outbound(self, event: V1Event) -> list[Delivery]:
        body = json.dumps(event.model_dump(mode="json", by_alias=True), separators=(",", ":"), sort_keys=True)
        return [Delivery("webhook", body.encode())]

    def snapshot(self, entity: str) -> Iterable[Any] | None:
        return None               # no pull: snapshots come inline or as files
