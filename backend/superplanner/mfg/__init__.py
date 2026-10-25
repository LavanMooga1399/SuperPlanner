"""Manufacturing master data, pure core (M1-DESIGN 2, 5). Imports only pydantic and the standard library here
(`mfg.io` adds openpyxl); never FastAPI, SQLAlchemy, `superplanner.api` or `superplanner.engine`."""

from __future__ import annotations

from .bom import (ExplosionTooLarge, bom_edges, effective_bom, explode, find_cycles, refdes_count, where_used,
                  would_create_cycle)
from .bundle import (SHEETS, BundleError, MfgBundle, bundle_to_dataset, canonical_json, dataset_to_bundle)
from .calendar import (expand_template_week, group_capacity, line_windows, operator_windows, validate_template)
from .dataset import BomIndex, MfgDataset, ParentIndex, fingerprint, link
from .health import run_health_check
from .release import (ReleaseError, bom_release_issues, routing_release_issues, validate_bom_document,
                      validate_routing_document)
from .routing import (cumulative_yield, effective_routings, eligible_lines, lot_inputs, operation_minutes,
                      primary_routing, time_preview, to_engine_minutes)
from .units import UnitMismatch, convert, normalize_uom

__all__ = [
    "BomIndex", "BundleError", "ExplosionTooLarge", "MfgBundle", "MfgDataset", "ParentIndex", "ReleaseError",
    "SHEETS", "UnitMismatch", "bom_edges", "bom_release_issues", "bundle_to_dataset", "canonical_json", "convert",
    "cumulative_yield", "dataset_to_bundle", "effective_bom", "effective_routings", "eligible_lines",
    "expand_template_week", "explode", "find_cycles", "fingerprint", "group_capacity", "line_windows", "link",
    "lot_inputs", "normalize_uom", "operation_minutes", "operator_windows", "primary_routing", "refdes_count",
    "routing_release_issues", "run_health_check", "time_preview", "to_engine_minutes", "validate_bom_document",
    "validate_routing_document", "validate_template", "where_used", "would_create_cycle",
]
