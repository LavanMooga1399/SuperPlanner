"""Plant-level MRP engine (M2-DESIGN 8, WP-E): pure and deterministic.

Imports only `superplanner.mfg` (model, model_m2, dataset, bom, routing, units, workdays, limits); never the API,
the database layer or the scheduling engine.
"""

from __future__ import annotations

from .engine import preflight, run_mrp
from .explode import ComponentNeed, OrderExplosion, order_components
from .leadtime import manufacturing_lead_days, resolve_source
from .model import (MrpError, MrpParams, MrpPreflightError, MrpResult, MrpSnapshot, MrpTooLarge, canonical_json,
                    item_plan_from_jsonable, to_jsonable)
from .views import bucketize, compare, item_timeline, pegging

__all__ = ["ComponentNeed", "MrpError", "MrpParams", "MrpPreflightError", "MrpResult", "MrpSnapshot", "MrpTooLarge",
           "OrderExplosion", "bucketize", "canonical_json", "compare", "item_plan_from_jsonable", "item_timeline",
           "manufacturing_lead_days", "order_components", "pegging", "preflight", "resolve_source", "run_mrp",
           "to_jsonable"]
