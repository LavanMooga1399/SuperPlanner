"""Build and validate `example_m9.json` (M9-DESIGN 11 S0): one typed example per M9 record and input, validated
against `mfg/network|sop|trade/model.py`. The UI's `contractExamplesM9.ts` mirrors this file.

    python -m superplanner.api.mfg.fixtures.build_example_m9        # rewrite example_m9.json
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ....mfg.network import model as N
from ....mfg.sop import model as S
from ....mfg.trade import model as T

OUT = Path(__file__).resolve().parent / "example_m9.json"
TS = "2026-11-27T07:00:00.000000Z"
TS2 = "2026-11-27T07:01:12.000000Z"


def _id(prefix: str, n: int) -> str:
    return f"{prefix}{n:032x}"


QC, US1, DCUS, NET = _id("usr_", 11), _id("usr_", 12), _id("usr_", 13), _id("usr_", 10)
USER, EXEC = _id("usr_", 1), _id("usr_", 2)
LANE = {"id": _id("nln_", 1), "from_owner_id": QC, "to_owner_id": DCUS, "mode": "road", "transit_days": 3,
        "freight_per_unit": 0.004, "freight_per_kg": None, "currency": "USD", "active": True, "row_version": 1,
        "updated_at": TS}
RULE = {"id": _id("nsg_", 1), "dest_owner_id": DCUS, "item_key": None, "family": "SYR", "source_kind": "plant",
        "source_owner_id": QC, "supplier_code": None, "priority": 1, "quota_pct": None, "lane_id": LANE["id"],
        "valid_from": None, "valid_to": None, "active": True, "row_version": 1, "updated_at": TS}
PEG = {"node": DCUS, "kind": "order", "ref": "SO-000123/1", "qty": 4800.0}
PUB = {"created": [{"to_id": _id("tro_", 1), "number": "TO-000041", "src_owner_id": QC, "dst_owner_id": DCUS,
                    "ship_date": "2026-11-30", "lines": 2, "qty": 9600.0}], "kept": [], "cancelled": [],
       "network_demands": 38, "network_supplies": 38, "warnings": []}
RUN = {"id": _id("nrn_", 1), "number": "NR-000001", "label": "Weekly DRP", "status": "completed",
       "as_of": "2026-11-27", "params": {"horizon_weeks": 26, "constrained": True},
       "input_hash": "9f2c" * 16,
       "summary": {"fill_rate": 0.987, "shortage_units": 1200.0, "inventory_value": 1_842_000.0,
                   "transfer_units": 912_000.0, "currency": "USD", "nodes": 3, "keys": 42, "transfers": 96,
                   "firm_transfers": 6, "shortages": 2, "max_utilisation": 0.97},
       "validator": {"ok": True, "violations": []},
       "explanations": [{"code": "NET_SPILL", "node": US1, "key": "NDL-25G", "family": "NDL", "week": "2027-01-04",
                         "month": None, "detail": {"to": QC, "qty": 50.0}}],
       "published": True, "published_at": TS2, "published_by": USER, "publish_result": PUB, "error": None,
       "actor_id": USER, "created_at": TS, "started_at": TS, "finished_at": TS2, "duration_ms": 4120}
CELL = {"week": "2026-11-30", "gross": 4800.0, "receipts": 0.0, "planned_in": 9600.0, "planned_out": 0.0,
        "projected": 6200.0, "ss": 2000.0}
CHANGE_LINE = {"kind": "add_line", "id": "c1", "label": "US1 line NA-03", "note": "", "node": US1,
               "cap_group": "NA", "name": "NA-03", "start": "2027-03-01", "hours_per_week": 120.0,
               "hpu_by_family": None, "uph_by_family": {"NDL": 9000.0}, "oee": 0.8, "curve": "STD26", "points": None,
               "capex": 45_000_000.0, "capex_currency": "USD", "fixed_cost_per_month": 60_000.0}
CHANGE_ALLOC = {"kind": "supplier_allocation", "id": "c2", "label": "Dual-source cannula 60/40 KTUBE", "note": "",
                "node": US1, "family": "CAN",
                "suppliers": [{"code": "KTUBE", "min_share": 0.6, "max_share": 0.6, "cap_per_month": None},
                              {"code": "ATUBE", "min_share": 0.4, "max_share": 0.4, "cap_per_month": None}]}
KSET = {"delivered_units": 21_400_000.0, "consensus_units": 21_600_000.0, "unmet_units": 200_000.0,
        "service_pct": 99.07, "revenue": 4_280_000.0, "cogs": 2_910_000.0, "gross_margin": 1_370_000.0,
        "gm_pct": 32.0, "inventory_value": 820_000.0, "days_of_cover": 21.5, "capex": 0.0}
KPIS = {"currency": "USD", "horizon": KSET, "year": KSET, "next3": KSET,
        "utilisation": [{"node": US1, "cap_group": "NA", "max_pct": 104.0, "avg_pct": 88.0}],
        "domestic": [{"milestone_id": _id("tms_", 1), "code": "NDL-US-STEEL", "family": "NDL", "min_pct": 100.0,
                      "share_pct": 64.0, "first_missed_month": "2027-07-01"}]}
SCEN = {"id": _id("ssc_", 2), "row_version": 3, "number": "SC-000002", "cycle_id": _id("scy_", 2), "baseline": False,
        "name": "Expansion NA-03", "changes": [CHANGE_LINE], "capex_note": "45 M USD, 2027 budget",
        "enforce_milestones": False, "status": "completed", "input_hash": "ab12" * 16, "kpis": KPIS,
        "validator": {"ok": True, "violations": []}, "warnings": [], "error": None, "run_at": TS2, "updated_at": TS2}
STEPS = [{"step": s, "due": d, "owner_id": USER, "owner_name": "Ana Planner", "done_at": None, "done_by": None,
          "note": None, "overdue": False}
         for s, d in (("draft", None), ("demand_review", "2026-12-07"), ("supply_review", "2026-12-10"),
                      ("pre_sop", "2026-12-14"), ("executive", "2026-12-16"), ("approved", None), ("published", None))]
CYCLE = {"id": _id("scy_", 2), "row_version": 5, "number": "SOP-2026-12", "period": "2026-12-01", "horizon_months": 18,
         "status": "pre_sop", "steps": STEPS, "demand_sources": {DCUS: _id("fcv_", 3), QC: _id("fcv_", 4)},
         "recommended_scenario_id": None, "recommend_note": None, "approved_scenario_id": None,
         "content_hash": None, "publish_result": None, "publish_job_status": None, "reopen_reason": None,
         "report_currency": "USD", "signatures": [], "people": {USER: "Ana Planner"}, "created_at": TS,
         "updated_at": TS2}
DROW = {"id": _id("sdm_", 1), "node_owner_id": DCUS, "family": "SYR", "month": "2027-01-01", "stat_qty": 1_100_000.0,
        "order_qty": 420_000.0, "base_qty": 1_150_000.0, "prior_consensus": 1_080_000.0, "consensus_qty": 1_265_000.0,
        "asp": 0.21, "asp_currency": "USD", "asp_source": "history"}
OVR = {"id": _id("sdo_", 1), "node_owner_id": None, "family": "SYR", "month_from": "2027-01-01",
       "month_to": "2027-03-01", "mode": "pct", "value": 10.0, "reason": "Flu season pre-buy", "seq": 1,
       "created_by": USER, "created_at": TS, "removed_at": None}
LANDED = {"unit_price": 0.14, "freight": 0.005, "customs_value": 0.14,
          "duty": [{"layer": "mfn", "rate_pct": 0.0, "per_unit": None, "amount": 0.0},
                   {"layer": "surtax", "rate_pct": 25.0, "per_unit": None, "amount": 0.035}],
          "other": 0.0007, "total": 0.1807, "currency": "CAD", "fx_rate": 1.4, "flags": []}
TREE = {"kind": "made", "lot_id": _id("lot_", 1), "lot_code": "N261120-1", "item_key": "NDL-25G",
        "description": "Needle 25G", "coo": "US", "material_class": None, "qty": 1000.0, "uom": "EA", "value": 53.0,
        "weight_kg": 3.9, "domestic": 0.566, "estimated": True,
        "children": [{"kind": "bought", "lot_id": _id("lot_", 2), "lot_code": "K-7781", "item_key": "CAN-STEEL-A",
                      "description": "Cannula steel", "coo": "US", "material_class": "steel", "qty": 2.0,
                      "uom": "KG", "value": 30.0, "weight_kg": 2.0, "domestic": 1.0, "estimated": False,
                      "children": []}]}
MILESTONE = {"id": _id("tms_", 1), "code": "NDL-US-STEEL", "name": "Needles: US steel", "dest_country": "US",
             "family": "NDL", "hts_prefix": None,
             "rule": {"domestic_country": "US", "basis": "value", "material_classes": ["steel"],
                      "include_conversion": False, "min_pct": 100.0},
             "effective": "2027-07-01", "note": "Illustrative"}
REPORT = {"id": _id("trp_", 1), "number": "TR-000001",
          "params": {"milestone_ids": [MILESTONE["id"]], "from": "2026-06-01", "to": "2027-12-01", "nodes": None,
                     "group_by": "family", "projection": {"scenario_id": SCEN["id"]}},
          "status": "completed",
          "result": {"months": ["2027-06-01", "2027-07-01"], "projection_from": "2026-12-01",
                     "projection_source": "SC-000002",
                     "milestones": [{"milestone_id": MILESTONE["id"], "code": "NDL-US-STEEL", "name": "Needles: US steel",
                                     "min_pct": 100.0, "effective": "2027-07-01", "basis": "value",
                                     "groups": [{"key": "NDL", "label": "NDL", "cells": [
                                         {"month": "2027-07-01", "share_pct": 97.0, "status": "at_risk",
                                          "projected": True, "lots": 0, "lots_below": 0, "qty_below_pct": None,
                                          "estimated_pct": None}]}],
                                     "first_missed_month": None,
                                     "lots_below": [{"plant_owner_id": US1, "lot_id": _id("lot_", 1),
                                                     "lot_code": "N261120-1", "item_key": "NDL-25G",
                                                     "month": "2026-11-01", "qty": 1000.0, "share_pct": 75.0,
                                                     "estimated": True}]}]},
          "error": None, "actor_id": USER, "started_at": TS, "finished_at": TS2, "created_at": TS}


def examples() -> dict[str, tuple[Any, Any]]:
    """name -> (model or None, example)."""
    return {
        # network
        "net_node": (N.NodeRecord, {"owner_id": DCUS, "code": "DCUS", "name": "DC United States", "kind": "dc",
                                    "country": "US", "currency": "USD", "tz": "America/Chicago", "member": True,
                                    "lines": 0}),
        "net_lane_input": (N.LaneInput, {k: LANE[k] for k in ("from_owner_id", "to_owner_id", "mode", "transit_days",
                                                             "freight_per_unit", "freight_per_kg", "currency",
                                                             "active")}),
        "net_lane": (N.LaneRecord, LANE),
        "net_sourcing_input": (N.SourcingInput, {k: v for k, v in RULE.items()
                                                 if k not in ("id", "row_version", "updated_at")}),
        "net_sourcing": (N.SourcingRecord, RULE),
        "net_resolve": (N.ResolveResult, {"dest_owner_id": DCUS, "key": "SYR-3ML-LL", "date": "2026-12-07",
                                          "family": "SYR", "matched_by": "family", "mode": "priority",
                                          "sources": [{"rule_id": RULE["id"], "source_kind": "plant",
                                                       "source_owner_id": QC, "supplier_code": None, "priority": 1,
                                                       "quota_pct": None, "lane_id": LANE["id"], "transit_days": 3}],
                                          "warnings": []}),
        "ramp_curve": (N.RampCurve, {"code": "STD26", "name": "Standard 26-week ramp",
                                     "points": [{"week": 0, "rate_pct": 25, "yield_pct": 85},
                                                {"week": 4, "rate_pct": 50, "yield_pct": 90},
                                                {"week": 8, "rate_pct": 75, "yield_pct": 94},
                                                {"week": 13, "rate_pct": 90, "yield_pct": 97},
                                                {"week": 26, "rate_pct": 100, "yield_pct": 98}]}),
        "net_params": (N.NetParams, {"as_of": None, "horizon_weeks": 26, "constrained": True, "prebuild_weeks": 4,
                                     "firm_days": 14, "node_ids": None, "forecast_versions": None,
                                     "label": "Weekly DRP"}),
        "net_run": (N.NetRunRecord, RUN),
        "net_publish": (N.NetPublishResult, PUB),
        "net_grid": (N.GridPage, {"items": [{"node_owner_id": DCUS, "item_key": "SYR-3ML-LL", "item_id": _id("itm_", 1),
                                             "description": "Syringe 3 mL Luer lock", "family": "SYR", "uom": "EA",
                                             "cells": [CELL]}], "total": 1, "limit": 50, "offset": 0,
                                  "weeks": ["2026-11-30"]}),
        "net_transfer": (N.TransferRecord, {"id": _id("npt_", 1), "src_owner_id": QC, "dst_owner_id": DCUS,
                                            "item_key": "SYR-3ML-LL", "lane_id": LANE["id"], "ship_date": "2026-11-30",
                                            "receive_date": "2026-12-03", "qty": 9600.0, "uom": "EA", "firm": True,
                                            "to_id": _id("tro_", 1), "to_number": "TO-000041", "pegs": [PEG]}),
        "net_shortage": (N.ShortageRecord, {"id": _id("nsh_", 1), "node_owner_id": DCUS, "item_key": "NDL-25G",
                                            "week": "2027-01-11", "qty": 1200.0, "uom": "EA",
                                            "cause": "NET_CAPACITY_SHORT",
                                            "detail": {"at": US1, "cap_group": "NA", "week": "2027-01-04",
                                                       "pegs": [PEG]}}),
        "net_utilisation": (N.UtilisationRecord, {"node": US1, "cap_group": "NA", "week": "2027-01-04",
                                                  "available": 240.0, "used": 240.0}),
        "net_pegging": (N.PeggingResult, {"direction": "down", "root": {
            "id": "d:SO-000123/1", "kind": "demand", "node_owner_id": DCUS, "item_key": "NDL-25G",
            "week": "2027-01-11", "qty": 4800.0, "ref": "SO-000123/1", "cause": None, "link": None,
            "children": [{"id": f"t:{_id('npt_', 2)}", "kind": "transfer", "node_owner_id": US1, "item_key": "NDL-25G",
                          "week": "2027-01-04", "qty": 4800.0, "ref": None, "cause": None, "link": None,
                          "children": [{"id": f"p:{_id('npp_', 1)}", "kind": "production", "node_owner_id": US1,
                                        "item_key": "NDL-25G", "week": "2026-12-28", "qty": 4800.0, "ref": None,
                                        "cause": None, "link": None, "children": []}]}]}}),
        "network_created": (N.NetworkCreated, {"owner_id": NET, "code": "NET", "name": "Network"}),
        # S&OP
        "sop_cycle_input": (S.CycleInput, {"period": "2026-12-01", "horizon_months": 18, "forecast_versions": None}),
        "sop_cycle": (S.CycleRecord, CYCLE),
        "sop_demand": (S.DemandView, {"months": ["2027-01-01"], "families": ["SYR"], "items": [DROW],
                                      "overrides": [OVR]}),
        "sop_override_input": (S.OverrideInput, {k: OVR[k] for k in ("node_owner_id", "family", "month_from",
                                                                    "month_to", "mode", "value", "reason")}),
        "sop_override": (S.OverrideRecord, OVR),
        "sop_asp_input": (S.AspInput, {"rows": [{"node_owner_id": DCUS, "family": "SYR", "asp": 0.21,
                                                 "currency": "USD"}], "reason": "Price list 2027"}),
        "sop_scenario_input": (S.ScenarioInput, {"cycle_id": CYCLE["id"], "name": "Expansion NA-03",
                                                 "changes": [CHANGE_LINE, CHANGE_ALLOC], "capex_note": "",
                                                 "enforce_milestones": False}),
        "sop_scenario": (S.ScenarioRecord, SCEN),
        "sop_approve_input": (S.ApproveInput, {"scenario_id": SCEN["id"], "signature": {
            "meaning": "approved", "content_hash": "c0ffee" * 10 + "c0ff", "username": "exec@example.com",
            "password": "********", "totp_code": None, "stepup_token": None, "comment": ""}}),
        "sop_plan": (S.PlanView, {"months": ["2027-01-01"], "items": [{
            "node_owner_id": US1, "family": "NDL", "month": "2027-01-01", "consensus": 0.0, "make": 2_400_000.0,
            "buy": {}, "ship_in": 0.0, "ship_out": 2_380_000.0, "inv": 410_000.0, "delivered": 0.0, "unmet": 0.0,
            "ss_short": 0.0, "ss_target": 400_000.0}]}),
        "sop_rough_cut": (S.RoughCutView, {"months": ["2027-03-01"], "items": [{
            "node_owner_id": US1, "cap_group": "NA", "month": "2027-03-01", "available": 1120.0, "required": 1180.0,
            "planned": 1120.0, "util": 1.054, "factor": 0.62}]}),
        "sop_financial": (S.FinancialView, {"currency": "USD", "group_by": "total", "months": ["2027-01-01"],
                                            "rows": [{"key": "total", "month": "2027-01-01", "revenue": 356_000.0,
                                                      "cogs": 241_000.0, "freight": 6_100.0, "gross_margin": 115_000.0,
                                                      "gm_pct": 32.3, "inventory_value": 820_000.0,
                                                      "days_of_cover": 21.5, "capex": 0.0}],
                                            "totals": {p: {"key": "total", "month": None, "revenue": 4_280_000.0,
                                                           "cogs": 2_910_000.0, "freight": 73_000.0,
                                                           "gross_margin": 1_370_000.0, "gm_pct": 32.0,
                                                           "inventory_value": 820_000.0, "days_of_cover": 21.5,
                                                           "capex": 45_000_000.0} for p in ("horizon", "year", "next3")},
                                            "warnings": []}),
        "sop_make_buy": (S.MakeBuyRow, {"node_owner_id": US1, "family": "CAN", "currency": "USD",
                                        "make_unit_cost": 0.012,
                                        "buy": [{"supplier_code": "KTUBE", "coo": "US", "landed_unit_cost": 0.011,
                                                 "duty_share": 0.0}],
                                        "split_make": 0.4, "split_buy": 0.6, "hours_freed": 310.0}),
        "sop_compare": (S.CompareView, {"currency": "USD", "items": [
            {"scenario": {"id": SCEN["id"], "number": "SC-000002", "name": "Expansion NA-03", "status": "completed",
                          "baseline": False, "validator_ok": True}, "kpis": KPIS, "delta": None}]}),
        # trade
        "item_trade": (T.ItemTradeRecord, {"item_id": _id("itm_", 1), "hts_code": "901832", "coo": "US",
                                           "material_class": "steel", "unit_weight_kg": 0.0039, "row_version": 1}),
        "tariff": (T.TariffRateRecord, {"id": _id("trf_", 1), "dest_country": "CA", "hts_prefix": "9018", "coo": "CN",
                                        "layer": "surtax", "rate_pct": 25.0, "per_unit": None, "per_unit_currency": None,
                                        "valid_from": "2026-01-01", "valid_to": None, "note": "Fictional"}),
        "fx": (T.FxRateRecord, {"id": _id("fxr_", 1), "from_ccy": "USD", "to_ccy": "CAD", "month": "2026-11-01",
                                "rate": 1.4, "source": "manual"}),
        "milestone": (T.MilestoneRecord, MILESTONE),
        "country_risk": (T.CountryRiskRecord, {"id": _id("ckr_", 1), "country": "CN", "score": 20,
                                               "note": "Illustrative"}),
        "bulk_result": (T.BulkResult, {"inserted": 12, "updated": 3, "deleted": 0}),
        "trade_report_input": (T.ReportInput, REPORT["params"]),
        "trade_report": (T.ReportRecord, REPORT),
        "lot_content": (T.LotContentRecord, {"lot_id": _id("lot_", 1), "lot_code": "N261120-1", "item_key": "NDL-25G",
                                             "coo": "US", "coo_source": "plant", "share_value": 0.566,
                                             "share_weight": 0.513, "estimated": True, "computed_at": TS,
                                             "milestone_id": None, "currency": "USD", "tree": TREE}),
        "landed": (T.LandedCost, LANDED),
        "landed_row": (T.LandedRow, {"item_supplier_id": _id("isp_", 1), "supplier_code": "ATUBE",
                                     "supplier_name": "A-Tube", "coo": "CN", "hts_code": "901832", "incoterm": "FOB",
                                     "preferred": False, "landed": LANDED}),
        "risk_row": (T.RiskRow, {"node_owner_id": US1, "item_id": _id("itm_", 5), "item_key": "CAN-STEEL-B",
                                 "part_number": "CAN-STEEL-B", "description": "Cannula steel (CN)", "family": "CAN",
                                 "supplier_code": "ATUBE", "supplier_name": "A-Tube", "coo": "CN", "score": 95,
                                 "parts": {"single_source": 35, "country": 20, "lead_time": 15, "otd": 15,
                                           "tariff": 10},
                                 "flags": ["single_source"], "spend_12m": 182_000.0, "currency": "USD",
                                 "otd_pct": 88.0, "lead_days": 75, "duty_pct": 25.0,
                                 "suggestions": [{"supplier_code": "KTUBE", "supplier_name": "K-Tube",
                                                  "node_owner_id": US1, "coo": "US", "landed_delta": -0.001,
                                                  "score": 10.0, "basis": "heading"}]}),
        "mps_target": (T.MpsTargetRecord, {"id": _id("mps_", 1), "cycle_id": _id("scy_", 1),
                                           "cycle_number": "SOP-2026-11", "family": "SYR", "month": "2026-12-01",
                                           "qty_target": 1_200_000.0, "hours": {"FLA": 410.0},
                                           "actual_qty": 380_000.0, "attainment": 0.317}),
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
