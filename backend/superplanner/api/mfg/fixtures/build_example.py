"""Build and validate `example_m8.json` (M8-DESIGN 13 S0): one typed example per M8 record and input, validated
against `mfg/forecast|invopt|rate|ster/model.py` and `mfg/model_m8.py`. The UI's `contractExamplesM8.ts` mirrors
this file.

    python -m superplanner.api.mfg.fixtures.build_example        # rewrite example_m8.json
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ....mfg import model_m8 as M
from ....mfg.forecast import model as F
from ....mfg.invopt import model as I
from ....mfg.mrp.model import MrpParams
from ....mfg.rate import model as R
from ....mfg.ster import model as S

OUT = Path(__file__).resolve().parent / "example_m8.json"
TS = "2026-11-25T07:00:00.000000Z"
TS2 = "2026-11-25T07:04:31.000000Z"


def _id(prefix: str, n: int) -> str:
    return f"{prefix}{n:032x}"


ITEM = {"id": _id("itm_", 1), "part_number": "SYR-3ML-LL", "revision": "A", "name": "Syringe 3 mL Luer lock"}
ITEM2 = _id("itm_", 2)
USER = _id("usr_", 1)
LINE = _id("lin_", 1)
CHAMBER = _id("lin_", 9)
MONTHS = ["2026-12-01", "2027-01-01", "2027-02-01"]
RESULT = {"item_id": ITEM["id"], "part_number": ITEM["part_number"], "demand_class": "smooth", "adi": 1.0,
          "cv2": 0.04, "method": "hw_add", "params": {"alpha": 0.2, "beta": 0.05, "gamma": 0.1},
          "holdout_wape": 0.084, "bias": -0.012, "rmse1": 3120.5, "mean": 41250.0, "n_periods": 30, "abc": "A",
          "flags": [], "fitted_tail": [40100.0, 39800.5, 44120.0], "forecast": [52000.0, 55200.0, 47800.0],
          "candidates": {"snaive": 0.131, "ma": 0.172, "ses": 0.155, "holt_damped": 0.149, "hw_add": 0.084,
                         "hw_mul": 0.091}}
RUN = {"id": _id("fcr_", 1), "number": "FC-000001", "params": {"label": "Monthly", "bucket": "m"},
       "status": "completed", "as_of": "2026-11-25", "bucket": "m", "first_period": "2026-12-01", "item_count": 182,
       "summary": {"wape": 0.142, "bias": -0.008, "by_abc": {"A": {"wape": 0.096, "bias": -0.01, "items": 24},
                                                            "B": {"wape": 0.181, "bias": 0.02, "items": 41},
                                                            "C": {"wape": 0.35, "bias": 0.05, "items": 117}},
                   "method_mix": {"hw_add": 31, "hw_mul": 9, "holt_damped": 22, "ses": 48, "ma": 40, "sba": 20,
                                  "croston": 8, "zero": 4},
                   "flags": {"FC_HISTORY_SHORT": 4, "FC_OUTLIER": 7, "FC_HIGH_ERROR": 1}},
       "version_id": _id("fcv_", 1), "error": None, "started_at": TS, "finished_at": TS2, "actor_id": USER}
VERSION = {"id": _id("fcv_", 1), "number": "FCV-000001", "name": "Nov 2026 consensus", "run_id": RUN["id"],
           "status": "active", "bucket": "m", "start": "2026-12-01", "periods": 18, "item_count": 182,
           "total_stat": 9_120_000.0, "total_final": 9_480_000.0, "override_count": 3, "activated_by": USER,
           "activated_at": TS2, "note": "", "row_version": 2, "created_at": TS, "updated_at": TS2}
OVERRIDE = {"id": _id("fco_", 1), "version_id": VERSION["id"], "item_id": None, "item_family": "SYRINGE",
            "period_from": "2026-12-01", "period_to": "2027-02-01", "mode": "pct", "value": 8.0,
            "reason": "Flu season: distributor pre-buy", "seq": 1, "created_by": USER, "created_at": TS,
            "removed_at": None, "changes": [{"item_id": ITEM["id"], "period_start": "2026-12-01", "old": 52000.0,
                                             "new": 56160.0}]}
HISTORY = {"id": _id("dhi_", 1), "item_id": ITEM["id"], "period_start": "2026-10-01", "bucket": "m", "qty": 412000.0,
           "cleaned_qty": 61500.0, "source": "ledger", "outlier": True, "updated_at": TS}
SS_LINE = {"id": _id("ssl_", 1), "run_id": _id("ssp_", 1), "item_id": ITEM["id"], "part_number": "SYR-3ML-LL",
           "abc": "A", "xyz": "X", "service_level": 0.99, "z": 2.326, "d_day": 1950.0, "sigma_d_day": 680.2,
           "lt_days": 10.0, "sigma_lt_days": 1.2, "current_ss": 4000.0, "proposed_ss": 6000.0, "delta_value": 420.0,
           "cover_days": 3.08, "flags": [], "decision": "pending", "decided_by": None, "decided_at": None}
BLOCK = {"id": _id("rbk_", 1), "line_id": LINE, "line_code": "ASM-01", "kind": "production", "item_id": ITEM["id"],
         "part_number": "SYR-3ML-LL", "campaign_no": 3, "start": "2026-11-26T06:00:00Z", "end": "2026-11-26T22:00:00Z",
         "qty": 96000.0, "cases": 48, "prod_date": "2026-11-26", "wo_id": _id("wko_", 1)}
LOAD = {"id": _id("stl_", 1), "number": "SL-000001", "run_id": _id("rrn_", 1), "chamber_line_id": CHAMBER,
        "chamber_code": "ETO-01", "cycle_code": "ETO-STD", "status": "awaiting_release", "pallets": 22,
        "planned_start": "2026-11-27T02:00:00Z", "planned_end": "2026-11-27T16:00:00Z",
        "aeration_end": "2026-11-29T16:00:00Z", "release_due": "2026-12-06", "actual_start": "2026-11-27T02:10:00Z",
        "actual_end": "2026-11-27T16:05:00Z", "actual_aeration_end": None, "batch_load_id": _id("bld_", 1),
        "release_signature_id": None, "ncr_id": None, "flags": [],
        "members": [{"id": _id("slm_", 1), "wo_id": _id("wko_", 1), "wo_number": "WO-000412", "rate_block_id":
                     BLOCK["id"], "lot_id": _id("lot_", 1), "lot_code": "L261126-A1", "item_id": ITEM["id"],
                     "part_number": "SYR-3ML-LL", "qty": 96000.0, "pallets": 2.0}],
        "lots": [{"lot_id": _id("lot_", 1), "lot_code": "L261126-A1"}],
        "signatures": [], "row_version": 4, "created_at": TS, "updated_at": TS2}
CARD = {"id": _id("kbc_", 1), "loop_id": _id("kbl_", 1), "card_no": 2, "code": f"KB:{_id('kbc_', 1)}",
        "state": "empty", "doc_type": "pr", "doc_id": _id("prq_", 1), "doc_number": "PR-000231", "changed_at": TS}
LOOP = {"id": _id("kbl_", 1), "number": "KB-000001", "item_id": ITEM2, "location_id": _id("loc_", 1),
        "source": "buy", "supplier_id": _id("sup_", 1), "line_id": None, "cards": 4, "container_qty": 5000.0,
        "lead_time_days": 5, "trigger": "scan", "status": "active",
        "item": {"id": ITEM2, "part_number": "TIP-CAP-LL", "revision": "A", "name": "Tip cap Luer"},
        "location_code": "LS-ASM", "card_counts": {"full": 3, "empty": 1, "in_process": 0},
        "consumed_since_signal": 0.0,
        "sizing": {"daily_demand": 2400.0, "suggested_cards": 4, "undersized": False},
        "row_version": 1, "created_at": TS, "updated_at": TS}


def examples() -> dict[str, tuple[Any, Any]]:
    """name -> (model or None, example)."""
    return {
        # forecasting
        "history": (F.HistoryRecord, HISTORY),
        "history_update": (F.HistoryUpdate, {"cleaned_qty": None, "reason": "Real tender, keep raw value"}),
        "history_refresh": (F.HistoryRefreshResult, {"rows_written": 5460, "items": 182, "periods": 30,
                                                     "outliers": 7}),
        "forecast_params": (F.ForecastParams, {"label": "Monthly", "as_of": None, "bucket": None,
                                               "horizon_periods": 18, "item_ids": None, "methods": None,
                                               "create_version": True}),
        "forecast_run": (F.ForecastRunRecord, RUN),
        "forecast_run_detail": (F.ForecastRunDetail, {**RUN, "results": {"items": [RESULT], "total": 1, "limit": 50,
                                                                          "offset": 0}}),
        "item_result": (F.ItemResult, RESULT),
        "version_input": (F.VersionInput, {"run_id": RUN["id"], "name": "Nov 2026 consensus",
                                           "copy_overrides": True, "note": ""}),
        "forecast_version": (F.VersionRecord, VERSION),
        "forecast_line": (F.LineRecord, {"item_id": ITEM["id"], "part_number": "SYR-3ML-LL", "family": "SYRINGE",
                                         "abc": "A", "xyz": "X", "method": "hw_add", "periods": MONTHS,
                                         "stat": [52000.0, 55200.0, 47800.0], "final": [56160.0, 59616.0, 51624.0],
                                         "overridden": [True, True, True]}),
        "override_input": (F.OverrideInput, {"item_id": None, "item_family": "SYRINGE", "period_from": MONTHS[0],
                                             "period_to": MONTHS[2], "mode": "pct", "value": 8.0,
                                             "reason": "Flu season: distributor pre-buy"}),
        "forecast_override": (F.OverrideRecord, OVERRIDE),
        "forecast_item": (F.ItemForecastView, {
            "item": ITEM, "planning": {"replenishment": "rate", "forecast": True, "abc": "A", "xyz": "X"},
            "history": [HISTORY], "result": RESULT,
            "versions": [{"version_id": VERSION["id"], "number": "FCV-000001", "status": "active",
                          "periods": MONTHS, "final": [56160.0, 59616.0, 51624.0]}],
            "consumption": [{"item_id": ITEM["id"], "period_start": "2026-12-01", "forecast": 56160.0,
                             "consumed": 21000.0, "open": 35160.0, "orders": 21000.0, "overconsumed": 0.0}],
            "accuracy": {"lag1": {"wape": 0.091, "bias": -0.02, "periods": 6},
                         "lag3": {"wape": 0.12, "bias": -0.03, "periods": 6}}}),
        "accuracy": (F.AccuracyReport, {"lag": 1, "group_by": "abc", "rows": [
            {"key": "A", "label": "A", "periods": 6, "actual": 1_240_000.0, "forecast": 1_198_000.0, "wape": 0.096,
             "bias": -0.034}], "backtest": RUN["summary"]}),
        # inventory optimisation
        "ss_params": (I.SsParams, {"label": "", "forecast_version_id": None, "item_ids": None}),
        "ss_run": (I.SsRunRecord, {"id": _id("ssp_", 1), "number": "SSP-000001", "params": {},
                                   "status": "completed", "forecast_version_id": VERSION["id"],
                                   "summary": {"lines": 182, "pending": 182, "delta_value": 18250.0, "capped": 3,
                                               "matrix": {"AX": {"count": 14, "value": 520000.0}}},
                                   "error": None, "created_at": TS, "finished_at": TS2}),
        "ss_line": (I.SsLineRecord, SS_LINE),
        "ss_decide_input": (I.DecideInput, {"line_ids": [SS_LINE["id"]], "decision": "approved",
                                            "reason": "Quarterly SS review"}),
        "ss_decide": (I.DecideResult, {"decided": 1, "skipped": 0, "items_updated": 1}),
        # master data
        "item_planning": (M.ItemPlanningRecord, {
            "id": _id("ipn_", 1), "item_id": ITEM["id"], "replenishment": "rate", "forecast": True,
            "like_item_id": None, "like_factor": 1.0, "service_level": None, "order_pack_level": "case",
            "campaign_key": "SYR-3ML", "campaign_min_hours": 8.0, "campaign_max_hours": 72.0, "target_cover_days": 10,
            "ster_cycle_code": "ETO-STD", "aeration_hours": 48.0, "release_mode": "bi", "release_days": 7.0,
            "post_days": None, "abc": "A", "xyz": "X", "row_version": 3}),
        "packaging": (M.PackagingRecord, {"item_id": ITEM["id"], "row_version": 3, "levels": [
            {"id": _id("pkg_", 1), "seq": 1, "level": "each", "code": "EA", "qty_base": 1.0, "gtin": None,
             "weight_kg": None},
            {"id": _id("pkg_", 2), "seq": 2, "level": "inner", "code": "BX100", "qty_base": 100.0,
             "gtin": "10380000000017", "weight_kg": 0.9},
            {"id": _id("pkg_", 3), "seq": 3, "level": "case", "code": "CS2000", "qty_base": 2000.0,
             "gtin": "20380000000014", "weight_kg": 19.0},
            {"id": _id("pkg_", 4), "seq": 4, "level": "pallet", "code": "PL48", "qty_base": 96000.0, "gtin": None,
             "weight_kg": 930.0}]}),
        "line_rates": (M.LineRatesRecord, {"line_id": LINE, "line_code": "ASM-01", "row_version": 2,
                                           "line": {"planning": "flow", "oee": 0.85, "clearance_minutes": 45,
                                                    "clean_every_hours": 72.0, "clean_minutes": 120,
                                                    "chamber_pallets": None, "cycle_hours": None},
                                           "rates": [{"id": _id("lrt_", 1), "item_id": None, "item_family": "SYRINGE",
                                                      "units_per_hour": 7000.0, "oee": None}]}),
        "changeover_matrix": (M.ChangeoverMatrixRecord, {"version": 1, "rows": [
            {"id": _id("chg_", 1), "line_setup_family": "ASM", "from_key": "*", "to_key": "*", "minutes": 90,
             "cost": 300.0, "kind": "changeover"},
            {"id": _id("chg_", 2), "line_setup_family": "ASM", "from_key": "SYR-3ML", "to_key": "NDL-21G",
             "minutes": 240, "cost": 900.0, "kind": "cleaning"}]}),
        "planning_settings": (M.PlanningSettingsRecord, {**M.PlanningSettings().model_dump(), "row_version": 1}),
        "nightly": (M.NightlyRunResult, {"run_id": _id("mnt_", 1), "status": "queued", "started_at": None,
                                         "steps": [{"step": "history_refresh", "status": "queued", "ref_id": None,
                                                    "error": None}]}),
        "mrp_params": (MrpParams, {"label": "nightly-1", "rate_supply": False, "forecast_version_id": None}),
        # rate engine
        "rate_params": (R.RateParams, {"label": "", "mrp_run_id": None, "horizon_days": 30, "line_ids": None,
                                       "overtime": "suggest", "time_budget_s": 240, "keep_firm": True}),
        "rate_run": (R.RateRunRecord, {
            "id": _id("rrn_", 1), "number": "RR-000001", "label": "nightly", "params": {"horizon_days": 30},
            "status": "completed", "mrp_run_id": _id("mrr_", 1), "as_of": "2026-11-25", "horizon_days": 30,
            "published": True, "published_at": TS2, "published_by": USER,
            "objective": {"shortage_unit_days": 0.0, "changeover_cost": 5400.0, "changeover_hours": 21.5,
                          "excess_cover_unit_days": 120000.0, "overtime_cost": 0.0},
            "summary": {"lines": 6, "blocks": 212, "campaigns": 64, "production_qty": 8_400_000.0,
                        "shortage_qty": 0.0, "utilisation": {LINE: 0.82}},
            "explanations": [{"code": "RATE_CAPACITY", "severity": "warning", "item_id": ITEM["id"], "line_id": LINE,
                              "message": "ASM-01 is 104 % loaded in week 49.", "detail": {"load_pct": 104}}],
            "validator": {"ok": True, "violations": []},
            "shortages": [{"item_id": ITEM["id"], "due": "2026-12-04", "qty": 12000.0, "cause": "RATE_CAPACITY",
                           "detail": {"load_pct": 104}}],
            "duration_ms": 41230, "error": None, "created_at": TS, "finished_at": TS2}),
        "rate_block": (R.RateBlockRecord, BLOCK),
        "rate_grid": (R.RateGrid, {"bucket": "day", "buckets": ["2026-11-26"],
                                   "lines": [{"line_id": LINE, "code": "ASM-01", "utilisation": {"2026-11-26": 0.9}}],
                                   "cells": [{"line_id": LINE, "bucket": "2026-11-26", "item_id": ITEM["id"],
                                              "part_number": "SYR-3ML-LL", "qty": 96000.0, "cases": 48,
                                              "hours": 16.0}]}),
        "rate_publish": (R.PublishResult, {"run_id": _id("rrn_", 1), "created_wo_ids": [_id("wko_", 1)],
                                           "cancelled_wo_ids": [], "kept_wo_ids": [], "rate_supplies": 180}),
        "rate_compare": (R.RateCompare, {"a": _id("rrn_", 1), "b": _id("rrn_", 2),
                                         "objective": {"changeover_cost": {"a": 5400.0, "b": 6100.0,
                                                                           "delta": 700.0}},
                                         "lines": [{"line_id": LINE, "code": "ASM-01", "a_qty": 1.0e6,
                                                    "b_qty": 1.1e6, "a_changeovers": 9, "b_changeovers": 11}],
                                         "items": [{"item_id": ITEM["id"], "a_qty": 4.0e5, "b_qty": 4.2e5,
                                                    "a_short": 0.0, "b_short": 0.0}]}),
        # sterilisation
        "ster_plan_input": (S.SterPlanInput, {"from_date": None, "days": 30, "chamber_line_ids": None}),
        "ster_plan": (S.SterPlanResult, {"loads": 18, "pallets": 402, "skipped": [], "warnings": [
            {"code": "STER_AERATION_BOUND", "load_ix": 4, "detail": {"delay_hours": 6.0}}], "load_ids": [LOAD["id"]]}),
        "ster_load": (S.SterLoadRecord, LOAD),
        "ster_advance": (S.AdvanceInput, {"to": "aerating", "at": None}),
        "ster_release": (S.ReleaseInput, {"signature": None, "note": "BI negative, 7-day"}),
        "ster_fail": (S.FailInput, {"reason": "BI positive"}),
        # kanban
        "kanban_loop": (M.KanbanLoopRecord, LOOP),
        "kanban_card": (M.KanbanCardRecord, CARD),
        "kanban_scan": (M.KanbanScanResult, {"card": CARD, "loop_id": LOOP["id"],
                                             "signal": {"doc_type": "pr", "doc_id": _id("prq_", 1),
                                                        "number": "PR-000231", "qty": 5000.0}}),
        # validation
        "trace_matrix": (M.TraceMatrixInfo, {"generated_at": TS, "requirements": 52, "covered": 51,
                                             "gaps": [{"id": "M8-SAP-02", "title": "SAP round trip", "risk": "medium"}],
                                             "high_risk_gaps": 0,
                                             "rows": [{"id": "M8-RATE-05", "title": "Validator mutation tests",
                                                       "risk": "high", "tests": ["tests/rate/test_validator.py::"
                                                                                 "test_mutations"],
                                                       "last_result": "passed"}],
                                             "csv_url": "/api/v1/mfg/validation/trace-matrix?format=csv"}),
        "baseline": (M.BaselineRecord, {"id": _id("vbl_", 1), "label": "Before go-live", "sha256": "b" * 64,
                                        "created_by": USER, "created_at": TS, "content": None}),
        "baseline_diff": (M.BaselineDiff, {"a": _id("vbl_", 1), "b": _id("vbl_", 2), "a_sha256": "b" * 64,
                                           "b_sha256": "c" * 64, "same": False,
                                           "changes": [{"path": "esig_policies.ncr.approve.auth", "kind": "changed",
                                                        "a": "password", "b": "password_totp"}]}),
        # SAP
        "sap_settings": (M.SapSettingsRecord, {**M.SapSettings(base_url="https://s4.example.com/sap/opu/odata/sap",
                                                               plant="1000", username="SP_TECH").model_dump(),
                                               "password_set": True, "client_secret_set": False,
                                               "cursors": {"product": "2026-11-24T22:00:00Z"},
                                               "last_sync": {"product": {"at": TS, "status": "completed",
                                                                         "records": 182, "error": None}},
                                               "row_version": 2}),
        "sap_sync": (M.SapSyncResult, {"run_id": _id("mnt_", 2), "status": "queued", "entities": ["product"]}),
    }


def build() -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, (model, ex) in examples().items():
        if model is not None:
            model.model_validate(ex)
        out[name] = ex
    return out


def main() -> None:
    OUT.write_text(json.dumps(build(), indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
