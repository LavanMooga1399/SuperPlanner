/**
 * M9 S0 contract examples: `backend/superplanner/api/mfg/fixtures/example_m9.json` verbatim, typed against `typesM9.ts`
 * so the compiler flags drift. Regenerate when the fixture changes (docs/M9-DESIGN.md 13). Also served by the m9 e2e
 * spec as route mocks for screens whose engines are not built yet.
 */
import type {
  BulkResult,
  CountryRiskInput,
  FxRate,
  ItemTrade,
  LandedCost,
  LandedRow,
  LotContent,
  Milestone,
  MpsTarget,
  NetGrid,
  NetLane,
  NetLaneInput,
  NetNodeInfo,
  NetParams,
  NetPegging,
  NetPublishResult,
  NetRun,
  NetShortage,
  NetTransfer,
  NetUtilisation,
  NetworkCreated,
  RampCurve,
  RiskRow,
  SopAspInput,
  SopCompare,
  SopCycle,
  SopDemand,
  SopFinancial,
  SopMakeBuyRow,
  SopOverride,
  SopOverrideInput,
  SopPlan,
  SopRoughCut,
  SopScenario,
  SopScenarioInput,
  SourcingResolve,
  SourcingRule,
  SourcingRuleInput,
  TariffRate,
  TradeReport,
  TradeReportParams,
} from "./typesM9";

export const exBulkResult: BulkResult = {
  "deleted": 0,
  "inserted": 12,
  "updated": 3
};

export const exCountryRisk: CountryRiskInput & { id: string } = {
  "country": "CN",
  "id": "ckr_00000000000000000000000000000001",
  "note": "Illustrative",
  "score": 20
};

export const exFx: FxRate = {
  "from_ccy": "USD",
  "id": "fxr_00000000000000000000000000000001",
  "month": "2026-11-01",
  "rate": 1.4,
  "source": "manual",
  "to_ccy": "CAD"
};

export const exItemTrade: ItemTrade = {
  "coo": "US",
  "hts_code": "901832",
  "item_id": "itm_00000000000000000000000000000001",
  "material_class": "steel",
  "row_version": 1,
  "unit_weight_kg": 0.0039
};

export const exLanded: LandedCost = {
  "currency": "CAD",
  "customs_value": 0.14,
  "duty": [
    {
      "amount": 0.0,
      "layer": "mfn",
      "per_unit": null,
      "rate_pct": 0.0
    },
    {
      "amount": 0.035,
      "layer": "surtax",
      "per_unit": null,
      "rate_pct": 25.0
    }
  ],
  "flags": [],
  "freight": 0.005,
  "fx_rate": 1.4,
  "other": 0.0007,
  "total": 0.1807,
  "unit_price": 0.14
};

export const exLandedRow: LandedRow = {
  "coo": "CN",
  "hts_code": "901832",
  "incoterm": "FOB",
  "item_supplier_id": "isp_00000000000000000000000000000001",
  "landed": {
    "currency": "CAD",
    "customs_value": 0.14,
    "duty": [
      {
        "amount": 0.0,
        "layer": "mfn",
        "per_unit": null,
        "rate_pct": 0.0
      },
      {
        "amount": 0.035,
        "layer": "surtax",
        "per_unit": null,
        "rate_pct": 25.0
      }
    ],
    "flags": [],
    "freight": 0.005,
    "fx_rate": 1.4,
    "other": 0.0007,
    "total": 0.1807,
    "unit_price": 0.14
  },
  "preferred": false,
  "supplier_code": "ATUBE",
  "supplier_name": "A-Tube"
};

export const exLotContent: LotContent = {
  "computed_at": "2026-11-27T07:00:00.000000Z",
  "coo": "US",
  "coo_source": "plant",
  "currency": "USD",
  "estimated": true,
  "item_key": "NDL-25G",
  "lot_code": "N261120-1",
  "lot_id": "lot_00000000000000000000000000000001",
  "milestone_id": null,
  "share_value": 0.566,
  "share_weight": 0.513,
  "tree": {
    "children": [
      {
        "children": [],
        "coo": "US",
        "description": "Cannula steel",
        "domestic": 1.0,
        "estimated": false,
        "item_key": "CAN-STEEL-A",
        "kind": "bought",
        "lot_code": "K-7781",
        "lot_id": "lot_00000000000000000000000000000002",
        "material_class": "steel",
        "qty": 2.0,
        "uom": "KG",
        "value": 30.0,
        "weight_kg": 2.0
      }
    ],
    "coo": "US",
    "description": "Needle 25G",
    "domestic": 0.566,
    "estimated": true,
    "item_key": "NDL-25G",
    "kind": "made",
    "lot_code": "N261120-1",
    "lot_id": "lot_00000000000000000000000000000001",
    "material_class": null,
    "qty": 1000.0,
    "uom": "EA",
    "value": 53.0,
    "weight_kg": 3.9
  }
};

export const exMilestone: Milestone = {
  "code": "NDL-US-STEEL",
  "dest_country": "US",
  "effective": "2027-07-01",
  "family": "NDL",
  "hts_prefix": null,
  "id": "tms_00000000000000000000000000000001",
  "name": "Needles: US steel",
  "note": "Illustrative",
  "rule": {
    "basis": "value",
    "domestic_country": "US",
    "include_conversion": false,
    "material_classes": [
      "steel"
    ],
    "min_pct": 100.0
  }
};

export const exMpsTarget: MpsTarget = {
  "actual_qty": 380000.0,
  "attainment": 0.317,
  "cycle_id": "scy_00000000000000000000000000000001",
  "cycle_number": "SOP-2026-11",
  "family": "SYR",
  "hours": {
    "FLA": 410.0
  },
  "id": "mps_00000000000000000000000000000001",
  "month": "2026-12-01",
  "qty_target": 1200000.0
};

export const exNetGrid: NetGrid = {
  "items": [
    {
      "cells": [
        {
          "gross": 4800.0,
          "planned_in": 9600.0,
          "planned_out": 0.0,
          "projected": 6200.0,
          "receipts": 0.0,
          "ss": 2000.0,
          "week": "2026-11-30"
        }
      ],
      "description": "Syringe 3 mL Luer lock",
      "family": "SYR",
      "item_id": "itm_00000000000000000000000000000001",
      "item_key": "SYR-3ML-LL",
      "node_owner_id": "usr_0000000000000000000000000000000d",
      "uom": "EA"
    }
  ],
  "limit": 50,
  "offset": 0,
  "total": 1,
  "weeks": [
    "2026-11-30"
  ]
};

export const exNetLane: NetLane = {
  "active": true,
  "currency": "USD",
  "freight_per_kg": null,
  "freight_per_unit": 0.004,
  "from_owner_id": "usr_0000000000000000000000000000000b",
  "id": "nln_00000000000000000000000000000001",
  "mode": "road",
  "row_version": 1,
  "to_owner_id": "usr_0000000000000000000000000000000d",
  "transit_days": 3,
  "updated_at": "2026-11-27T07:00:00.000000Z"
};

export const exNetLaneInput: NetLaneInput = {
  "active": true,
  "currency": "USD",
  "freight_per_kg": null,
  "freight_per_unit": 0.004,
  "from_owner_id": "usr_0000000000000000000000000000000b",
  "mode": "road",
  "to_owner_id": "usr_0000000000000000000000000000000d",
  "transit_days": 3
};

export const exNetNode: NetNodeInfo = {
  "code": "DCUS",
  "country": "US",
  "currency": "USD",
  "kind": "dc",
  "lines": 0,
  "member": true,
  "name": "DC United States",
  "owner_id": "usr_0000000000000000000000000000000d",
  "tz": "America/Chicago"
};

export const exNetParams: NetParams = {
  "as_of": null,
  "constrained": true,
  "firm_days": 14,
  "forecast_versions": null,
  "horizon_weeks": 26,
  "label": "Weekly DRP",
  "node_ids": null,
  "prebuild_weeks": 4
};

export const exNetPegging: NetPegging = {
  "direction": "down",
  "root": {
    "cause": null,
    "children": [
      {
        "cause": null,
        "children": [
          {
            "cause": null,
            "children": [],
            "id": "p:npp_00000000000000000000000000000001",
            "item_key": "NDL-25G",
            "kind": "production",
            "link": null,
            "node_owner_id": "usr_0000000000000000000000000000000c",
            "qty": 4800.0,
            "ref": null,
            "week": "2026-12-28"
          }
        ],
        "id": "t:npt_00000000000000000000000000000002",
        "item_key": "NDL-25G",
        "kind": "transfer",
        "link": null,
        "node_owner_id": "usr_0000000000000000000000000000000c",
        "qty": 4800.0,
        "ref": null,
        "week": "2027-01-04"
      }
    ],
    "id": "d:SO-000123/1",
    "item_key": "NDL-25G",
    "kind": "demand",
    "link": null,
    "node_owner_id": "usr_0000000000000000000000000000000d",
    "qty": 4800.0,
    "ref": "SO-000123/1",
    "week": "2027-01-11"
  }
};

export const exNetPublish: NetPublishResult = {
  "cancelled": [],
  "created": [
    {
      "dst_owner_id": "usr_0000000000000000000000000000000d",
      "lines": 2,
      "number": "TO-000041",
      "qty": 9600.0,
      "ship_date": "2026-11-30",
      "src_owner_id": "usr_0000000000000000000000000000000b",
      "to_id": "tro_00000000000000000000000000000001"
    }
  ],
  "kept": [],
  "network_demands": 38,
  "network_supplies": 38,
  "warnings": []
};

export const exNetResolve: SourcingResolve = {
  "date": "2026-12-07",
  "dest_owner_id": "usr_0000000000000000000000000000000d",
  "family": "SYR",
  "key": "SYR-3ML-LL",
  "matched_by": "family",
  "mode": "priority",
  "sources": [
    {
      "lane_id": "nln_00000000000000000000000000000001",
      "priority": 1,
      "quota_pct": null,
      "rule_id": "nsr_00000000000000000000000000000001",
      "source_kind": "plant",
      "source_owner_id": "usr_0000000000000000000000000000000b",
      "supplier_code": null,
      "transit_days": 3
    }
  ],
  "warnings": []
};

export const exNetRun: NetRun = {
  "actor_id": "usr_00000000000000000000000000000001",
  "as_of": "2026-11-27",
  "created_at": "2026-11-27T07:00:00.000000Z",
  "duration_ms": 4120,
  "error": null,
  "explanations": [
    {
      "code": "NET_SPILL",
      "detail": {
        "qty": 50.0,
        "to": "usr_0000000000000000000000000000000b"
      },
      "family": "NDL",
      "key": "NDL-25G",
      "month": null,
      "node": "usr_0000000000000000000000000000000c",
      "week": "2027-01-04"
    }
  ],
  "finished_at": "2026-11-27T07:01:12.000000Z",
  "id": "nrn_00000000000000000000000000000001",
  "input_hash": "9f2c9f2c9f2c9f2c9f2c9f2c9f2c9f2c9f2c9f2c9f2c9f2c9f2c9f2c9f2c9f2c",
  "label": "Weekly DRP",
  "number": "NR-000001",
  "params": {
    "constrained": true,
    "horizon_weeks": 26
  },
  "publish_result": {
    "cancelled": [],
    "created": [
      {
        "dst_owner_id": "usr_0000000000000000000000000000000d",
        "lines": 2,
        "number": "TO-000041",
        "qty": 9600.0,
        "ship_date": "2026-11-30",
        "src_owner_id": "usr_0000000000000000000000000000000b",
        "to_id": "tro_00000000000000000000000000000001"
      }
    ],
    "kept": [],
    "network_demands": 38,
    "network_supplies": 38,
    "warnings": []
  },
  "published": true,
  "published_at": "2026-11-27T07:01:12.000000Z",
  "published_by": "usr_00000000000000000000000000000001",
  "started_at": "2026-11-27T07:00:00.000000Z",
  "status": "completed",
  "summary": {
    "currency": "USD",
    "fill_rate": 0.987,
    "firm_transfers": 6,
    "inventory_value": 1842000.0,
    "keys": 42,
    "max_utilisation": 0.97,
    "nodes": 3,
    "shortage_units": 1200.0,
    "shortages": 2,
    "transfer_units": 912000.0,
    "transfers": 96
  },
  "validator": {
    "ok": true,
    "violations": []
  }
};

export const exNetShortage: NetShortage = {
  "cause": "NET_CAPACITY_SHORT",
  "detail": {
    "at": "usr_0000000000000000000000000000000c",
    "cap_group": "NA",
    "pegs": [
      {
        "kind": "order",
        "node": "usr_0000000000000000000000000000000d",
        "qty": 4800.0,
        "ref": "SO-000123/1"
      }
    ],
    "week": "2027-01-04"
  },
  "id": "nsh_00000000000000000000000000000001",
  "item_key": "NDL-25G",
  "node_owner_id": "usr_0000000000000000000000000000000d",
  "qty": 1200.0,
  "uom": "EA",
  "week": "2027-01-11"
};

export const exNetSourcing: SourcingRule = {
  "active": true,
  "dest_owner_id": "usr_0000000000000000000000000000000d",
  "family": "SYR",
  "id": "nsr_00000000000000000000000000000001",
  "item_key": null,
  "lane_id": "nln_00000000000000000000000000000001",
  "priority": 1,
  "quota_pct": null,
  "row_version": 1,
  "source_kind": "plant",
  "source_owner_id": "usr_0000000000000000000000000000000b",
  "supplier_code": null,
  "updated_at": "2026-11-27T07:00:00.000000Z",
  "valid_from": null,
  "valid_to": null
};

export const exNetSourcingInput: SourcingRuleInput = {
  "active": true,
  "dest_owner_id": "usr_0000000000000000000000000000000d",
  "family": "SYR",
  "item_key": null,
  "lane_id": "nln_00000000000000000000000000000001",
  "priority": 1,
  "quota_pct": null,
  "source_kind": "plant",
  "source_owner_id": "usr_0000000000000000000000000000000b",
  "supplier_code": null,
  "valid_from": null,
  "valid_to": null
};

export const exNetTransfer: NetTransfer = {
  "dst_owner_id": "usr_0000000000000000000000000000000d",
  "firm": true,
  "id": "npt_00000000000000000000000000000001",
  "item_key": "SYR-3ML-LL",
  "lane_id": "nln_00000000000000000000000000000001",
  "pegs": [
    {
      "kind": "order",
      "node": "usr_0000000000000000000000000000000d",
      "qty": 4800.0,
      "ref": "SO-000123/1"
    }
  ],
  "qty": 9600.0,
  "receive_date": "2026-12-03",
  "ship_date": "2026-11-30",
  "src_owner_id": "usr_0000000000000000000000000000000b",
  "to_id": "tro_00000000000000000000000000000001",
  "to_number": "TO-000041",
  "uom": "EA"
};

export const exNetUtilisation: NetUtilisation = {
  "available": 240.0,
  "cap_group": "NA",
  "node": "usr_0000000000000000000000000000000c",
  "used": 240.0,
  "week": "2027-01-04"
};

export const exNetworkCreated: NetworkCreated = {
  "code": "NET",
  "name": "Network",
  "owner_id": "usr_0000000000000000000000000000000a"
};

export const exRampCurve: RampCurve = {
  "code": "STD26",
  "name": "Standard 26-week ramp",
  "points": [
    {
      "rate_pct": 25,
      "week": 0,
      "yield_pct": 85
    },
    {
      "rate_pct": 50,
      "week": 4,
      "yield_pct": 90
    },
    {
      "rate_pct": 75,
      "week": 8,
      "yield_pct": 94
    },
    {
      "rate_pct": 90,
      "week": 13,
      "yield_pct": 97
    },
    {
      "rate_pct": 100,
      "week": 26,
      "yield_pct": 98
    }
  ]
};

export const exRiskRow: RiskRow = {
  "coo": "CN",
  "currency": "USD",
  "description": "Cannula steel (CN)",
  "duty_pct": 25.0,
  "family": "CAN",
  "flags": [
    "single_source"
  ],
  "item_id": "itm_00000000000000000000000000000005",
  "item_key": "CAN-STEEL-B",
  "lead_days": 75,
  "node_owner_id": "usr_0000000000000000000000000000000c",
  "otd_pct": 88.0,
  "part_number": "CAN-STEEL-B",
  "parts": {
    "country": 20,
    "lead_time": 15,
    "otd": 15,
    "single_source": 35,
    "tariff": 10
  },
  "score": 95,
  "spend_12m": 182000.0,
  "suggestions": [
    {
      "basis": "heading",
      "coo": "US",
      "landed_delta": -0.001,
      "node_owner_id": "usr_0000000000000000000000000000000c",
      "score": 10.0,
      "supplier_code": "KTUBE",
      "supplier_name": "K-Tube"
    }
  ],
  "supplier_code": "ATUBE",
  "supplier_name": "A-Tube"
};

export const exSopApproveInput: { scenario_id: string; signature: Record<string, unknown> } = {
  "scenario_id": "ssc_00000000000000000000000000000002",
  "signature": {
    "comment": "",
    "content_hash": "c0ffeec0ffeec0ffeec0ffeec0ffeec0ffeec0ffeec0ffeec0ffeec0ffeec0ff",
    "meaning": "approved",
    "password": "********",
    "stepup_token": null,
    "totp_code": null,
    "username": "exec@example.com"
  }
};

export const exSopAspInput: SopAspInput = {
  "reason": "Price list 2027",
  "rows": [
    {
      "asp": 0.21,
      "currency": "USD",
      "family": "SYR",
      "node_owner_id": "usr_0000000000000000000000000000000d"
    }
  ]
};

export const exSopCompare: SopCompare = {
  "currency": "USD",
  "items": [
    {
      "delta": null,
      "kpis": {
        "currency": "USD",
        "domestic": [
          {
            "code": "NDL-US-STEEL",
            "family": "NDL",
            "first_missed_month": "2027-07-01",
            "milestone_id": "tms_00000000000000000000000000000001",
            "min_pct": 100.0,
            "share_pct": 64.0
          }
        ],
        "horizon": {
          "capex": 0.0,
          "cogs": 2910000.0,
          "consensus_units": 21600000.0,
          "days_of_cover": 21.5,
          "delivered_units": 21400000.0,
          "gm_pct": 32.0,
          "gross_margin": 1370000.0,
          "inventory_value": 820000.0,
          "revenue": 4280000.0,
          "service_pct": 99.07,
          "unmet_units": 200000.0
        },
        "next3": {
          "capex": 0.0,
          "cogs": 2910000.0,
          "consensus_units": 21600000.0,
          "days_of_cover": 21.5,
          "delivered_units": 21400000.0,
          "gm_pct": 32.0,
          "gross_margin": 1370000.0,
          "inventory_value": 820000.0,
          "revenue": 4280000.0,
          "service_pct": 99.07,
          "unmet_units": 200000.0
        },
        "utilisation": [
          {
            "avg_pct": 88.0,
            "cap_group": "NA",
            "max_pct": 104.0,
            "node": "usr_0000000000000000000000000000000c"
          }
        ],
        "year": {
          "capex": 0.0,
          "cogs": 2910000.0,
          "consensus_units": 21600000.0,
          "days_of_cover": 21.5,
          "delivered_units": 21400000.0,
          "gm_pct": 32.0,
          "gross_margin": 1370000.0,
          "inventory_value": 820000.0,
          "revenue": 4280000.0,
          "service_pct": 99.07,
          "unmet_units": 200000.0
        }
      },
      "scenario": {
        "baseline": false,
        "id": "ssc_00000000000000000000000000000002",
        "name": "Expansion NA-03",
        "number": "SC-000002",
        "status": "completed",
        "validator_ok": true
      }
    }
  ]
};

export const exSopCycle: SopCycle = {
  "approved_scenario_id": null,
  "content_hash": null,
  "created_at": "2026-11-27T07:00:00.000000Z",
  "demand_sources": {
    "usr_0000000000000000000000000000000b": "fcv_00000000000000000000000000000004",
    "usr_0000000000000000000000000000000d": "fcv_00000000000000000000000000000003"
  },
  "horizon_months": 18,
  "id": "scy_00000000000000000000000000000002",
  "number": "SOP-2026-12",
  "people": {
    "usr_00000000000000000000000000000001": "Ana Planner"
  },
  "period": "2026-12-01",
  "publish_job_status": null,
  "publish_result": null,
  "recommend_note": null,
  "recommended_scenario_id": null,
  "reopen_reason": null,
  "report_currency": "USD",
  "row_version": 5,
  "signatures": [],
  "status": "pre_sop",
  "steps": [
    {
      "done_at": null,
      "done_by": null,
      "due": null,
      "note": null,
      "overdue": false,
      "owner_id": "usr_00000000000000000000000000000001",
      "owner_name": "Ana Planner",
      "step": "draft"
    },
    {
      "done_at": null,
      "done_by": null,
      "due": "2026-12-07",
      "note": null,
      "overdue": false,
      "owner_id": "usr_00000000000000000000000000000001",
      "owner_name": "Ana Planner",
      "step": "demand_review"
    },
    {
      "done_at": null,
      "done_by": null,
      "due": "2026-12-10",
      "note": null,
      "overdue": false,
      "owner_id": "usr_00000000000000000000000000000001",
      "owner_name": "Ana Planner",
      "step": "supply_review"
    },
    {
      "done_at": null,
      "done_by": null,
      "due": "2026-12-14",
      "note": null,
      "overdue": false,
      "owner_id": "usr_00000000000000000000000000000001",
      "owner_name": "Ana Planner",
      "step": "pre_sop"
    },
    {
      "done_at": null,
      "done_by": null,
      "due": "2026-12-16",
      "note": null,
      "overdue": false,
      "owner_id": "usr_00000000000000000000000000000001",
      "owner_name": "Ana Planner",
      "step": "executive"
    },
    {
      "done_at": null,
      "done_by": null,
      "due": null,
      "note": null,
      "overdue": false,
      "owner_id": "usr_00000000000000000000000000000001",
      "owner_name": "Ana Planner",
      "step": "approved"
    },
    {
      "done_at": null,
      "done_by": null,
      "due": null,
      "note": null,
      "overdue": false,
      "owner_id": "usr_00000000000000000000000000000001",
      "owner_name": "Ana Planner",
      "step": "published"
    }
  ],
  "updated_at": "2026-11-27T07:01:12.000000Z"
};

export const exSopCycleInput: { period: string; horizon_months: number; forecast_versions: Record<string, string> | null } = {
  "forecast_versions": null,
  "horizon_months": 18,
  "period": "2026-12-01"
};

export const exSopDemand: SopDemand = {
  "families": [
    "SYR"
  ],
  "items": [
    {
      "asp": 0.21,
      "asp_currency": "USD",
      "asp_source": "history",
      "base_qty": 1150000.0,
      "consensus_qty": 1265000.0,
      "family": "SYR",
      "id": "sdm_00000000000000000000000000000001",
      "month": "2027-01-01",
      "node_owner_id": "usr_0000000000000000000000000000000d",
      "order_qty": 420000.0,
      "prior_consensus": 1080000.0,
      "stat_qty": 1100000.0
    }
  ],
  "months": [
    "2027-01-01"
  ],
  "overrides": [
    {
      "created_at": "2026-11-27T07:00:00.000000Z",
      "created_by": "usr_00000000000000000000000000000001",
      "family": "SYR",
      "id": "sdo_00000000000000000000000000000001",
      "mode": "pct",
      "month_from": "2027-01-01",
      "month_to": "2027-03-01",
      "node_owner_id": null,
      "reason": "Flu season pre-buy",
      "removed_at": null,
      "seq": 1,
      "value": 10.0
    }
  ]
};

export const exSopFinancial: SopFinancial = {
  "currency": "USD",
  "group_by": "total",
  "months": [
    "2027-01-01"
  ],
  "rows": [
    {
      "capex": 0.0,
      "cogs": 241000.0,
      "days_of_cover": 21.5,
      "freight": 6100.0,
      "gm_pct": 32.3,
      "gross_margin": 115000.0,
      "inventory_value": 820000.0,
      "key": "total",
      "month": "2027-01-01",
      "revenue": 356000.0
    }
  ],
  "totals": {
    "horizon": {
      "capex": 45000000.0,
      "cogs": 2910000.0,
      "days_of_cover": 21.5,
      "freight": 73000.0,
      "gm_pct": 32.0,
      "gross_margin": 1370000.0,
      "inventory_value": 820000.0,
      "key": "total",
      "month": null,
      "revenue": 4280000.0
    },
    "next3": {
      "capex": 45000000.0,
      "cogs": 2910000.0,
      "days_of_cover": 21.5,
      "freight": 73000.0,
      "gm_pct": 32.0,
      "gross_margin": 1370000.0,
      "inventory_value": 820000.0,
      "key": "total",
      "month": null,
      "revenue": 4280000.0
    },
    "year": {
      "capex": 45000000.0,
      "cogs": 2910000.0,
      "days_of_cover": 21.5,
      "freight": 73000.0,
      "gm_pct": 32.0,
      "gross_margin": 1370000.0,
      "inventory_value": 820000.0,
      "key": "total",
      "month": null,
      "revenue": 4280000.0
    }
  },
  "warnings": []
};

export const exSopMakeBuy: SopMakeBuyRow = {
  "buy": [
    {
      "coo": "US",
      "duty_share": 0.0,
      "landed_unit_cost": 0.011,
      "supplier_code": "KTUBE"
    }
  ],
  "currency": "USD",
  "family": "CAN",
  "hours_freed": 310.0,
  "make_unit_cost": 0.012,
  "node_owner_id": "usr_0000000000000000000000000000000c",
  "split_buy": 0.6,
  "split_make": 0.4
};

export const exSopOverride: SopOverride = {
  "created_at": "2026-11-27T07:00:00.000000Z",
  "created_by": "usr_00000000000000000000000000000001",
  "family": "SYR",
  "id": "sdo_00000000000000000000000000000001",
  "mode": "pct",
  "month_from": "2027-01-01",
  "month_to": "2027-03-01",
  "node_owner_id": null,
  "reason": "Flu season pre-buy",
  "removed_at": null,
  "seq": 1,
  "value": 10.0
};

export const exSopOverrideInput: SopOverrideInput = {
  "family": "SYR",
  "mode": "pct",
  "month_from": "2027-01-01",
  "month_to": "2027-03-01",
  "node_owner_id": null,
  "reason": "Flu season pre-buy",
  "value": 10.0
};

export const exSopPlan: SopPlan = {
  "items": [
    {
      "buy": {},
      "consensus": 0.0,
      "delivered": 0.0,
      "family": "NDL",
      "inv": 410000.0,
      "make": 2400000.0,
      "month": "2027-01-01",
      "node_owner_id": "usr_0000000000000000000000000000000c",
      "ship_in": 0.0,
      "ship_out": 2380000.0,
      "ss_short": 0.0,
      "ss_target": 400000.0,
      "unmet": 0.0
    }
  ],
  "months": [
    "2027-01-01"
  ]
};

export const exSopRoughCut: SopRoughCut = {
  "items": [
    {
      "available": 1120.0,
      "cap_group": "NA",
      "factor": 0.62,
      "month": "2027-03-01",
      "node_owner_id": "usr_0000000000000000000000000000000c",
      "planned": 1120.0,
      "required": 1180.0,
      "util": 1.054
    }
  ],
  "months": [
    "2027-03-01"
  ]
};

export const exSopScenario: SopScenario = {
  "baseline": false,
  "capex_note": "45 M USD, 2027 budget",
  "changes": [
    {
      "cap_group": "NA",
      "capex": 45000000.0,
      "capex_currency": "USD",
      "curve": "STD26",
      "fixed_cost_per_month": 60000.0,
      "hours_per_week": 120.0,
      "hpu_by_family": null,
      "id": "c1",
      "kind": "add_line",
      "label": "US1 line NA-03",
      "name": "NA-03",
      "node": "usr_0000000000000000000000000000000c",
      "note": "",
      "oee": 0.8,
      "points": null,
      "start": "2027-03-01",
      "uph_by_family": {
        "NDL": 9000.0
      }
    }
  ],
  "cycle_id": "scy_00000000000000000000000000000002",
  "enforce_milestones": false,
  "error": null,
  "id": "ssc_00000000000000000000000000000002",
  "input_hash": "ab12ab12ab12ab12ab12ab12ab12ab12ab12ab12ab12ab12ab12ab12ab12ab12",
  "kpis": {
    "currency": "USD",
    "domestic": [
      {
        "code": "NDL-US-STEEL",
        "family": "NDL",
        "first_missed_month": "2027-07-01",
        "milestone_id": "tms_00000000000000000000000000000001",
        "min_pct": 100.0,
        "share_pct": 64.0
      }
    ],
    "horizon": {
      "capex": 0.0,
      "cogs": 2910000.0,
      "consensus_units": 21600000.0,
      "days_of_cover": 21.5,
      "delivered_units": 21400000.0,
      "gm_pct": 32.0,
      "gross_margin": 1370000.0,
      "inventory_value": 820000.0,
      "revenue": 4280000.0,
      "service_pct": 99.07,
      "unmet_units": 200000.0
    },
    "next3": {
      "capex": 0.0,
      "cogs": 2910000.0,
      "consensus_units": 21600000.0,
      "days_of_cover": 21.5,
      "delivered_units": 21400000.0,
      "gm_pct": 32.0,
      "gross_margin": 1370000.0,
      "inventory_value": 820000.0,
      "revenue": 4280000.0,
      "service_pct": 99.07,
      "unmet_units": 200000.0
    },
    "utilisation": [
      {
        "avg_pct": 88.0,
        "cap_group": "NA",
        "max_pct": 104.0,
        "node": "usr_0000000000000000000000000000000c"
      }
    ],
    "year": {
      "capex": 0.0,
      "cogs": 2910000.0,
      "consensus_units": 21600000.0,
      "days_of_cover": 21.5,
      "delivered_units": 21400000.0,
      "gm_pct": 32.0,
      "gross_margin": 1370000.0,
      "inventory_value": 820000.0,
      "revenue": 4280000.0,
      "service_pct": 99.07,
      "unmet_units": 200000.0
    }
  },
  "name": "Expansion NA-03",
  "number": "SC-000002",
  "row_version": 3,
  "run_at": "2026-11-27T07:01:12.000000Z",
  "status": "completed",
  "updated_at": "2026-11-27T07:01:12.000000Z",
  "validator": {
    "ok": true,
    "violations": []
  },
  "warnings": []
};

export const exSopScenarioInput: SopScenarioInput & { cycle_id: string | null } = {
  "capex_note": "",
  "changes": [
    {
      "cap_group": "NA",
      "capex": 45000000.0,
      "capex_currency": "USD",
      "curve": "STD26",
      "fixed_cost_per_month": 60000.0,
      "hours_per_week": 120.0,
      "hpu_by_family": null,
      "id": "c1",
      "kind": "add_line",
      "label": "US1 line NA-03",
      "name": "NA-03",
      "node": "usr_0000000000000000000000000000000c",
      "note": "",
      "oee": 0.8,
      "points": null,
      "start": "2027-03-01",
      "uph_by_family": {
        "NDL": 9000.0
      }
    },
    {
      "family": "CAN",
      "id": "c2",
      "kind": "supplier_allocation",
      "label": "Dual-source cannula 60/40 KTUBE",
      "node": "usr_0000000000000000000000000000000c",
      "note": "",
      "suppliers": [
        {
          "cap_per_month": null,
          "code": "KTUBE",
          "max_share": 0.6,
          "min_share": 0.6
        },
        {
          "cap_per_month": null,
          "code": "ATUBE",
          "max_share": 0.4,
          "min_share": 0.4
        }
      ]
    }
  ],
  "cycle_id": "scy_00000000000000000000000000000002",
  "enforce_milestones": false,
  "name": "Expansion NA-03"
};

export const exTariff: TariffRate = {
  "coo": "CN",
  "dest_country": "CA",
  "hts_prefix": "9018",
  "id": "trf_00000000000000000000000000000001",
  "layer": "surtax",
  "note": "Fictional",
  "per_unit": null,
  "per_unit_currency": null,
  "rate_pct": 25.0,
  "valid_from": "2026-01-01",
  "valid_to": null
};

export const exTradeReport: TradeReport = {
  "actor_id": "usr_00000000000000000000000000000001",
  "created_at": "2026-11-27T07:00:00.000000Z",
  "error": null,
  "finished_at": "2026-11-27T07:01:12.000000Z",
  "id": "trp_00000000000000000000000000000001",
  "number": "TR-000001",
  "params": {
    "from": "2026-06-01",
    "group_by": "family",
    "milestone_ids": [
      "tms_00000000000000000000000000000001"
    ],
    "nodes": null,
    "projection": {
      "scenario_id": "ssc_00000000000000000000000000000002"
    },
    "to": "2027-12-01"
  },
  "result": {
    "milestones": [
      {
        "basis": "value",
        "code": "NDL-US-STEEL",
        "effective": "2027-07-01",
        "first_missed_month": null,
        "groups": [
          {
            "cells": [
              {
                "estimated_pct": null,
                "lots": 0,
                "lots_below": 0,
                "month": "2027-07-01",
                "projected": true,
                "qty_below_pct": null,
                "share_pct": 97.0,
                "status": "at_risk"
              }
            ],
            "key": "NDL",
            "label": "NDL"
          }
        ],
        "lots_below": [
          {
            "estimated": true,
            "item_key": "NDL-25G",
            "lot_code": "N261120-1",
            "lot_id": "lot_00000000000000000000000000000001",
            "month": "2026-11-01",
            "plant_owner_id": "usr_0000000000000000000000000000000c",
            "qty": 1000.0,
            "share_pct": 75.0
          }
        ],
        "milestone_id": "tms_00000000000000000000000000000001",
        "min_pct": 100.0,
        "name": "Needles: US steel"
      }
    ],
    "months": [
      "2027-06-01",
      "2027-07-01"
    ],
    "projection_from": "2026-12-01",
    "projection_source": "SC-000002"
  },
  "started_at": "2026-11-27T07:00:00.000000Z",
  "status": "completed"
};

export const exTradeReportInput: TradeReportParams = {
  "from": "2026-06-01",
  "group_by": "family",
  "milestone_ids": [
    "tms_00000000000000000000000000000001"
  ],
  "nodes": null,
  "projection": {
    "scenario_id": "ssc_00000000000000000000000000000002"
  },
  "to": "2027-12-01"
};
