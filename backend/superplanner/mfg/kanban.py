"""Kanban loops (M8-DESIGN 6.2; pure): card codes, the card state machine, consumption counting and sizing.

Card states: `full` -(scan / consumption)-> `empty` (a replenishment signal is created and linked to the card) ->
`full` (receipt of the item at the loop location). `in_process` is accepted for imported states but never set by
the engine. Sizing suggestion: cards = ceil(d x LT x 1.2 / container) + 1.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

PREFIX = "KB:"
CARD_FLOW: dict[str, tuple[str, ...]] = {"full": ("empty",), "empty": ("full", "in_process"),
                                         "in_process": ("full",)}


class KanbanError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def card_code(card_id: str) -> str:
    return f"{PREFIX}{card_id}"


def parse_code(code: str) -> str | None:
    c = code.strip()
    if c[:3].upper() != PREFIX:
        return None
    rest = c[3:].strip()
    return rest or None


def transition(state: str, to: str) -> str:
    if to not in CARD_FLOW.get(state, ()):
        raise KanbanError("KANBAN_CARD_STATE", f"A {state} card cannot become {to}.")
    return to


def suggested_cards(daily_demand: float, lead_time_days: float, container_qty: float) -> int:
    if container_qty <= 0:
        return 1
    return math.ceil(max(daily_demand, 0.0) * max(lead_time_days, 0.0) * 1.2 / container_qty - 1e-9) + 1


def undersized(daily_demand: float, lead_time_days: float, cards: int, container_qty: float) -> bool:
    return daily_demand * max(lead_time_days, 1.0) * 1.2 > (cards - 1) * container_qty + 1e-9


@dataclass
class ConsumptionResult:
    counter: float           # consumed since the last emptied card
    cards_to_empty: int


def consume(counter: float, qty: float, container_qty: float) -> ConsumptionResult:
    """Consumption trigger: every `container_qty` issued from the loop location empties one card."""
    total = counter + max(qty, 0.0)
    n = int(math.floor(total / container_qty + 1e-9)) if container_qty > 0 else 0
    return ConsumptionResult(round(total - n * container_qty, 6), n)
