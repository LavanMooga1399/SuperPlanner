"""Build and validate `example_m10.json` (M10-DESIGN 12 S0): one typed example per M10 record, validated against
`dhr/model.py`, `udi/model.py`, `qa/model_m10.py` and `validation/model.py`. The UI's `contractExamplesM10.ts`
mirrors this file; the route table is the docstring of `api/mfg/router_m10.py`. Fictional data only.

    python -m superplanner.api.mfg.fixtures.build_example_m10        # rewrite example_m10.json
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ....dhr import model as D
from ....qa import model_m10 as Q
from ....udi import model as U
from ....validation import model as V

OUT = Path(__file__).resolve().parent / "example_m10.json"
TS = "2026-11-23T19:05:12.000000Z"
TS2 = "2026-11-23T19:20:40.000000Z"


def _id(prefix: str, n: int) -> str:
    return f"{prefix}{n:032x}"


H = "3f1a" * 16
ITEM = {"id": _id("itm_", 1), "part_number": "SYR-3ML-LL", "revision": "C", "name": "Syringe 3 mL Luer lock"}
LOT, WO, WO2 = _id("lot_", 7), _id("wor_", 1), _id("wor_", 2)
REC_ID, NCR_ID, DEV_ID = _id("dhr_", 1), _id("ncr_", 8), _id("dev_", 1)
SIG = {"id": _id("esg_", 1), "meaning": "released", "meaning_label": "Released",
       "signer_legal_name": "Marie Tremblay", "signer_username": "mtremblay@example.com", "signed_at": TS2,
       "signed_at_local": "2026-11-23 14:20:40 EST (UTC-05:00)", "auth_method": "password_totp",
       "action": "release", "step": 2, "status": "valid", "record_version": 3, "comment": "Reviewed by exception",
       "content_matches_current": True}
SIG_REVIEW = {**SIG, "id": _id("esg_", 2), "meaning": "reviewed", "meaning_label": "Reviewed",
              "signer_legal_name": "Luc Gagnon", "signer_username": "lgagnon@example.com", "step": 1,
              "auth_method": "password_totp", "signed_at_local": "2026-11-23 14:10:02 EST (UTC-05:00)"}
EXC = {"id": _id("dhx_", 1), "record_id": REC_ID, "code": "DHR_TIME_WINDOW", "severity": "major",
       "section": "operations", "ref_type": "wo_operation", "ref_id": _id("wop_", 3), "ref_number": "WO-000412/30",
       "message": "Operation 30 Assembly ran 135 min; the routing allows 120 min.",
       "data": {"seq": 30, "minutes": 135, "max_minutes": 120, "kind": "duration"}, "fingerprint": "a1" * 32,
       "disposition": "deviation", "disposition_ref": DEV_ID, "disposition_ref_number": "DEV-000001",
       "comment": "Covered by the planned deviation for the alternate plunger resin.", "carried": False,
       "reviewed_by": _id("usr_", 2), "reviewed_at": TS, "allowed": ["accepted", "deviation", "ncr"],
       "needs_disposition": False, "row_version": 2}
EXC_INFO = {**EXC, "id": _id("dhx_", 2), "code": "DHR_GENEALOGY_POSSIBLE", "severity": "info", "section": "genealogy",
            "ref_type": "item", "ref_id": _id("itm_", 4), "ref_number": "PLG-RES",
            "message": "Plunger resin lots are linked as possible (backflush across lots).", "data": {"edges": 2},
            "fingerprint": "b2" * 32, "disposition": None, "disposition_ref": None, "disposition_ref_number": None,
            "comment": None, "reviewed_by": None, "reviewed_at": None, "allowed": [], "needs_disposition": False,
            "row_version": 1}
CONTENT = {
    "header": {"plant": {"name": "Quebec City (sample)", "time_zone": "America/Toronto"}, "item": ITEM,
               "subject_kind": "lot", "lot": {"id": LOT, "lot_code": "A2611QC07", "expires_on": "2029-11-30"},
               "wos": [{"id": WO, "number": "WO-000412", "qty": 24000.0, "qty_completed": 23880.0,
                        "qty_scrapped": 120.0, "status": "closed"}],
               "item_revision": {"bom_id": _id("bom_", 1), "bom_version": 3, "routing_id": _id("rtg_", 1),
                                 "routing_version": 2, "ecos": ["ECO-000014"]},
               "dis": [{"level": "each", "gtin": "09521234500018", "status": "approved"}],
               "qty_planned": 24000.0, "qty_received": 23880.0, "qty_scrapped": 120.0,
               "first_start": "2026-11-20T11:02:00.000000Z", "last_receipt": "2026-11-21T22:40:00.000000Z",
               "expiry": "2029-11-30", "sterile": True, "dhr_required": True},
    "materials": {"lines": [{"item": {"id": _id("itm_", 3), "part_number": "BRL-3ML", "name": "Barrel 3 mL"},
                             "lot_id": _id("lot_", 31), "lot_code": "BRL2611-04", "supplier_lot": "K-88231",
                             "supplier": "Barrel supplier (fictional)", "qty": 24120.0, "uom": "EA",
                             "location": "LINE-A", "posting": "TXN-000981", "posting_id": _id("pst_", 9),
                             "txn_type": "wo_issue", "incoming": {"inspection_lot": "IL-000077",
                                                                   "decision": "accept"},
                             "held_at_issue": False, "possible": False}], "possible_edges": 2},
    "operations": {"operations": [{"wo_number": "WO-000412", "seq": 30, "name": "Assembly", "line": "FLA-01",
                                   "status": "completed", "operators": ["Op 14", "Op 22"], "started_at":
                                   "2026-11-20T13:00:00.000000Z", "ended_at": "2026-11-20T15:15:00.000000Z",
                                   "minutes": 135.0, "max_minutes": 120, "wait_minutes": 40.0,
                                   "max_wait_minutes": 240, "qty_in": 24000.0, "qty_good": 23880.0,
                                   "qty_scrap": 120.0, "qty_rework": 0.0, "qty_nc": 0.0, "events": 6,
                                   "corrections": 0}], "events_total": 18},
    "equipment": {"equipment": [{"code": "FG-07", "name": "Force gauge 07", "use_date": "2026-11-21",
                                 "calibration_due": "2027-03-01", "valid": True, "certificate": "CAL-2026-0712"}]},
    "inspections": {"lots": [{"number": "IL-000091", "scope": "final", "plan": "IP-000012", "plan_version": 4,
                              "status": "accepted", "decision": "accept", "lot_size": 23880.0, "results": 48,
                              "defects": 0, "signatures": 1}]},
    "nonconformance": {"ncrs": [], "deviations": [{"number": "DEV-000001", "kind": "planned", "status": "approved",
                                                   "title": "Alternate plunger resin lot", "in_scope": True}]},
    "sterilisation": {"required": True, "loads": [{"number": "SL-000033", "chamber": "EO-01", "cycle_code": "EO-STD",
                                                   "status": "released", "planned_start": "2026-11-22T06:00:00.000000Z",
                                                   "actual_end": "2026-11-22T20:00:00.000000Z", "release_mode": "parametric",
                                                   "release_signature": "Approved by Luc Gagnon", "co_lots": ["A2611QC06"]}]},
    "labels": {"jobs": [{"number": "LP-000021", "template": "SYR-EACH", "template_version": 2,
                         "gtin": "09521234500018", "status": "reconciled",
                         "totals": {"issued": 24000, "printed": 24000, "reprinted": 0, "used": 23880,
                                    "destroyed": 100, "retained": 20, "diff": 0},
                         "verify": {"first": True, "last": True, "mismatches": 0}}]},
    "serials": {"count": 0, "ranges": [], "list_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"},
    "genealogy": {"backward": [{"item": "BRL-3ML", "lot_code": "BRL2611-04", "kind": "exact"},
                               {"item": "PLG-RES", "lot_code": "R-5521", "kind": "possible"}],
                  "forward": [{"kind": "shipment", "ref": "DO-000310/1", "qty": 12000.0}]},
    "holds": {"holds": [{"source": "sterility", "placed_at": "2026-11-21T22:40:00.000000Z",
                         "released_at": "2026-11-22T21:00:00.000000Z", "signature": "Approved by Luc Gagnon"},
                        {"source": "dhr", "placed_at": "2026-11-21T22:40:00.000000Z", "released_at": None,
                         "signature": None}]},
    "review": {"exceptions": [{"code": "DHR_TIME_WINDOW", "fingerprint": "a1" * 32, "disposition": "deviation",
                               "ref": "DEV-000001"}]},
}
SECTION_HASHES = {k: H for k in D.SECTIONS}
SUMMARY = {"id": REC_ID, "number": "DHR-000007", "version": 1, "subject_kind": "lot", "lot_id": LOT,
           "lot_code": "A2611QC07", "wo_ids": [WO], "wo_numbers": ["WO-000412"], "item": ITEM, "status": "released",
           "changed_after_release": False, "superseded_by_id": None, "assembled_at": TS, "age_days": 0.6,
           "counts": {"major": 1, "minor": 0, "info": 1, "open": 0}, "released_at": TS2, "decision": "released",
           "row_version": 3}
RENDITION = {"id": _id("rnd_", 1), "kind": "pdf", "filename": "DHR-000007-v1.pdf", "sha256": H, "size": 182_344,
             "renderer_version": "sp-pdf/1", "created_at": TS2, "warnings": []}
RECORD = {**SUMMARY, "item_revision": CONTENT["header"]["item_revision"], "content": CONTENT, "content_sha256": H,
          "section_hashes": SECTION_HASHES, "exceptions": [EXC, EXC_INFO], "signatures": [SIG_REVIEW, SIG],
          "versions": [{"id": REC_ID, "version": 1, "status": "released", "content_sha256": H,
                        "section_hashes": SECTION_HASHES, "assembled_at": TS, "changed_after_release": False,
                        "reassemble_reason": None}],
          "supersedes_id": None, "hold_id": _id("hld_", 9), "hold_open": False, "dhr_required": True,
          "releasable": {"ok": True, "blocking": []}, "renditions": [RENDITION, {**RENDITION, "id": _id("rnd_", 2),
                                                                                 "kind": "json",
                                                                                 "filename": "DHR-000007-v1.json",
                                                                                 "size": 41_220}],
          "renderer_version": "sp-pdf/1", "reassemble_reason": None}
BLOCKED = {"ok": False, "blocking": [
    {"code": "EXCEPTION_OPEN", "message": "DHR_CORRECTION on WO-000413/20 has no disposition.",
     "ref_type": "dhr_exception", "ref_id": _id("dhx_", 5), "ref_number": None},
    {"code": "NCR_OPEN", "message": "NCR-000008 is not closed.", "ref_type": "ncr", "ref_id": NCR_ID,
     "ref_number": "NCR-000008"},
    {"code": "LABEL_NOT_RECONCILED", "message": "Print job LP-000022 is not reconciled.", "ref_type": "print_job",
     "ref_id": _id("lpj_", 22), "ref_number": "LP-000022"},
    {"code": "STERILITY_HOLD", "message": "The sterility hold of the lot is open.", "ref_type": "hold",
     "ref_id": _id("hld_", 10), "ref_number": None}]}
DEVIATION = {"id": DEV_ID, "number": "DEV-000001", "kind": "planned", "title": "Alternate plunger resin lot",
             "description": "Use resin lot R-5521 from the qualified alternate grade for up to 50,000 units.",
             "scope": {"item_ids": [ITEM["id"]], "lot_ids": [], "wo_ids": [], "valid_from": "2026-11-15",
                       "valid_to": "2026-12-31", "max_qty": 50000.0},
             "risk": {"severity": 2, "occurrence": 2, "rationale": "Same resin family; tensile data equivalent."},
             "risk_score": 4, "status": "approved", "ncr_id": None, "capa_id": None, "author_id": _id("usr_", 2),
             "approved_at": TS, "closed_at": None, "outcome": None, "external_ref": None, "sor": "superplanner",
             "used_qty": 23880.0, "signatures": [{**SIG_REVIEW, "action": "approve", "meaning": "reviewed"},
                                                 {**SIG, "action": "approve", "meaning": "approved",
                                                  "meaning_label": "Approved", "auth_method": "password"}],
             "links": [], "people": {_id("usr_", 2): "Luc Gagnon"}, "row_version": 3, "created_at": TS,
             "updated_at": TS2}
AGREEMENT = {"id": _id("cqa_", 1), "number": "QA-AG-000001", "version": 1, "customer": "PHARMACO",
             "title": "Prefillable syringe supply quality agreement", "external_ref": "PQA-2026-014",
             "item_ids": [_id("itm_", 9)],
             "coa": {"characteristics": [
                 {"item_id": None, "code": "BLF", "label": "Plunger break-loose force", "label_fr":
                  "Force de décollement du piston", "report": "value", "spec": {"nominal": None, "lsl": None,
                                                                                 "usl": 10.0, "unit": "N"}},
                 {"item_id": None, "code": "GLF", "label": "Glide force", "label_fr": "Force de glissement",
                  "report": "value", "spec": {"nominal": None, "lsl": None, "usl": 4.0, "unit": "N"}},
                 {"item_id": None, "code": "PART", "label": "Particulate", "label_fr": "Particules",
                  "report": "summary", "spec": None}],
                 "statement": "The lot was manufactured and tested according to the agreed specifications.",
                 "statement_fr": "Le lot a été fabriqué et contrôlé selon les spécifications convenues.",
                 "language": "en_fr"},
             "pack": {"documents": ["coa", "coc", "ster_cert", "dhr_summary"], "per": "lot"},
             "effective_from": "2026-11-01", "status": "approved", "supersedes_id": None,
             "signatures": [{**SIG, "action": "approve", "meaning": "approved", "meaning_label": "Approved",
                             "step": 1, "auth_method": "password"}],
             "row_version": 2, "created_at": TS, "updated_at": TS2}
COA_LINE = {"code": "GLF", "label": "Glide force", "label_fr": "Force de glissement", "report": "value",
            "spec": {"nominal": None, "lsl": None, "usl": 4.0, "unit": "N"}, "spec_source": "customer", "n": 32,
            "defects": 0, "mean": 3.42, "min": 3.1, "max": 3.8, "conforms": True,
            "result_text": "mean 3.42 N (3.10 - 3.80), n = 32"}
COA = {"id": _id("coa_", 1), "number": "COA-000001", "agreement_id": AGREEMENT["id"],
       "agreement_number": "QA-AG-000001", "agreement_version": 1, "lot_id": _id("lot_", 17),
       "lot_code": "P2611QC03", "item_id": _id("itm_", 9), "dhr_id": REC_ID, "dhr_number": "DHR-000009",
       "customer": "PHARMACO", "demand_line_id": None,
       "content": {"lines": [COA_LINE], "statement": AGREEMENT["coa"]["statement"], "language": "en_fr",
                   "lot": {"lot_code": "P2611QC03", "expires_on": "2029-11-30"},
                   "item": {"part_number": "PFS-1ML", "name": "Prefillable syringe 1 mL"},
                   "dhr": {"number": "DHR-000009", "version": 1, "content_sha256": H}},
       "content_sha256": H, "status": "approved", "void_reason": None,
       "rendition": {**RENDITION, "id": _id("rnd_", 3), "filename": "COA-000001.pdf", "size": 22_410},
       "signatures": [{**SIG, "action": "approve", "meaning": "approved", "meaning_label": "Approved", "step": 1,
                       "auth_method": "password"}], "row_version": 2, "created_at": TS, "updated_at": TS2}
PACK = {"id": _id("bpk_", 1), "number": "BP-000001", "agreement_id": AGREEMENT["id"], "lot_ids": [_id("lot_", 17)],
        "customer": "PHARMACO", "demand_line_id": None, "status": "ready",
        "documents": [{"kind": "coa", "lot_id": _id("lot_", 17), "ref_id": COA["id"],
                       "filename": "P2611QC03/COA-000001.pdf", "sha256": H, "size": 22_410},
                      {"kind": "coc", "lot_id": _id("lot_", 17), "ref_id": REC_ID,
                       "filename": "P2611QC03/CoC-P2611QC03.pdf", "sha256": H, "size": 14_002}],
        "rendition": {**RENDITION, "id": _id("rnd_", 4), "kind": "zip", "filename": "BP-000001.zip",
                      "size": 51_200}, "manifest_sha256": H, "error": None, "row_version": 2, "created_at": TS,
        "updated_at": TS2}
UDI = {"id": _id("udi_", 1), "packaging_id": _id("pkg_", 1), "item_id": ITEM["id"], "item_part_number": "SYR-3ML-LL",
       "level": "each", "gtin": "09521234500018", "gtin_locked": True, "di_kind": "base", "qty_per_package": 1,
       "contains_gtin": None, "pi_flags": {"lot": True, "serial": False, "expiry": True, "mfg_date": False},
       "attrs": {"brand": "SampleCare", "version_model": "3 mL LL", "catalog_no": "SC-303", "description":
                 "Sterile single-use syringe 3 mL, Luer lock", "gmdn_code": "47017", "gmdn_term":
                 "General-purpose syringe, single-use", "fda_product_codes": ["FMF"], "fda_class": "II",
                 "premarket_nos": ["K000000"], "hc_licence_no": "00000", "hc_class": "II", "sterile": True,
                 "ster_method": "Ethylene oxide", "single_use": True, "rx": True, "kit": False,
                 "combination": False, "mri_safety": "not_evaluated", "latex": False, "storage": []},
       "status": "approved", "commercial_distribution_date": "2026-12-01",
       "signatures": [{**SIG, "action": "approve", "meaning": "approved", "meaning_label": "Approved", "step": 1,
                       "auth_method": "password"}], "row_version": 3, "created_at": TS, "updated_at": TS2}
PARSE = {"ok": True, "symbology": "]d2", "ais": {"01": "09521234500018", "17": "281130", "10": "A2611QC07",
                                               "21": "SN0001"}, "gtin_check_ok": True, "expiry": "2028-11-30",
         "production_date": None, "data": "010952123450001817281130" "10A2611QC07\x1d21SN0001",
         "hri": "(01)09521234500018(17)281130(10)A2611QC07(21)SN0001", "errors": []}
EXPORT = {"id": _id("uex_", 1), "number": "UX-000001", "kind": "gudid", "params": {"format": "xlsx", "item_ids": None},
          "status": "completed", "rule_version": "gudid-2026.1",
          "result": {"rows": 3, "errors": [], "warnings": [{"gtin": "19521234500015", "element": "deviceCount",
                                                             "message": "Package DI: device count 10 from qty_per_package."}]},
          "rendition": {**RENDITION, "id": _id("rnd_", 5), "kind": "xlsx", "filename": "UX-000001-gudid.xlsx",
                        "size": 7_311}, "row_version": 2, "created_at": TS}
TEMPLATE = {"id": _id("lbt_", 2), "code": "SYR-EACH", "version": 2, "name": "Syringe unit label (bilingual)",
            "level": "each", "width_mm": 50.0, "height_mm": 30.0, "dpi": 300, "languages": ["en", "fr"],
            "elements": [
                {"kind": "field", "x_mm": 2, "y_mm": 2, "w_mm": 46, "h_mm": 4, "rotation": 0, "font_pt": 7,
                 "bold": True, "lang": None, "text": None, "field": "udi.brand", "barcode": None, "path": None},
                {"kind": "barcode", "x_mm": 2, "y_mm": 8, "w_mm": 14, "h_mm": 14, "rotation": 0, "font_pt": 6,
                 "bold": False, "lang": None, "text": None, "field": None,
                 "barcode": {"symbology": "gs1_datamatrix", "module_mm": 0.5, "ais": ["01", "17", "10"],
                             "hri": True}, "path": None},
                {"kind": "text", "x_mm": 18, "y_mm": 8, "w_mm": 30, "h_mm": 4, "rotation": 0, "font_pt": 6,
                 "bold": False, "lang": "fr", "text": "Stérile - usage unique", "field": None, "barcode": None,
                 "path": None}],
            "status": "approved", "eco_id": _id("ecr_", 14), "eco_number": "ECO-000014", "approved_at": TS,
            "supersedes_id": _id("lbt_", 1), "issues": [], "row_version": 4, "created_at": TS, "updated_at": TS2}
PRINTER = {"id": _id("lpr_", 1), "code": "ZPL-FLA", "name": "Line A label printer", "kind": "zpl_raw",
           "host": "10.20.0.41", "port": 9100, "dpi": 300, "line_id": None, "active": True, "row_version": 1,
           "created_at": TS, "updated_at": TS}
EVENT = {"id": _id("lpe_", 1), "job_id": _id("lpj_", 21), "kind": "verify", "qty": 0, "serials": None,
         "position": "first", "scan": "]d2010952123450001817281130" "10A2611QC07", "result": "match",
         "mismatch": None, "reason": None, "actor_id": _id("usr_", 5), "at": TS, "client_event_id": "tab-7-0001"}
JOB = {"id": _id("lpj_", 21), "number": "LP-000021", "item_id": ITEM["id"], "item_part_number": "SYR-3ML-LL",
       "level": "each", "udi_id": UDI["id"], "gtin": "09521234500018", "lot_id": LOT, "lot_code": "A2611QC07",
       "wo_id": WO, "template_id": TEMPLATE["id"], "template_code": "SYR-EACH", "template_version": 2,
       "qty": 24000, "serials": None,
       "data": {"udi.gtin": "09521234500018", "lot.number": "A2611QC07", "lot.expiry": "2029-11-30",
                "udi.brand": "SampleCare"}, "data_sha256": H,
       "element_string": "010952123450001817291130" "10A2611QC07",
       "hri": "(01)09521234500018(17)291130(10)A2611QC07", "output": "zpl", "target": "printer",
       "printer_id": PRINTER["id"], "status": "reconciled",
       "totals": {"issued": 24000, "printed": 24000, "reprinted": 0, "used": 23880, "destroyed": 100, "retained": 20,
                  "diff": 0}, "recon_explanation": None, "reconciled_at": TS2,
       "verify": {"first": True, "last": True, "mismatches": 0}, "events": [EVENT], "signatures": [],
       "row_version": 6, "created_at": TS, "updated_at": TS2}
PACKAGE = {"id": _id("vpk_", 1), "number": "VP-000001", "kind": "oq", "params": {"label": "OQ sample environment"},
           "status": "approved", "baseline_id": _id("vbl_", 2), "prev_baseline_id": _id("vbl_", 1),
           "manifest": {"package": "VP-000001", "kind": "oq", "files": [{"path": "trace/matrix.csv", "sha256": H,
                                                                          "size": 18_220, "kind": "trace"}]},
           "sha256": H, "size": 412_008, "error": None,
           "signatures": [{**SIG, "action": "approve", "meaning": "approved", "meaning_label": "Approved"}],
           "row_version": 3, "created_at": TS, "updated_at": TS2}
IQ = {"plant": "QC", "at": TS, "ok": False, "checks": [
    {"code": "IQ_APP_VERSION", "label": "Application version", "status": "pass", "detail": "",
     "observed": "1.10.0", "expected": None},
    {"code": "IQ_ARCHIVE_DIR", "label": "ARCHIVE_DIR writable", "status": "fail",
     "detail": "/srv/archive is not writable", "observed": False, "expected": True},
    {"code": "IQ_CLOCK_SKEW", "label": "App / database clock skew", "status": "pass", "detail": "",
     "observed": 12.0, "expected": "<= 1000 ms"}]}
RESIDENCY = {"org_id": _id("org_", 1), "data_region": "ca", "deployment_region": "ca", "ok": False,
             "mismatches": [{"kind": "ai", "name": "Assistant model endpoint", "region": "us", "ok": False,
                             "detail": "The assistant stays off in Part 11 plants unless signed on.",
                             "exception_signature_id": None}],
             "items": [{"kind": "deployment", "name": "SP_REGION", "region": "ca", "ok": True, "detail": "",
                        "exception_signature_id": None},
                       {"kind": "archive", "name": "ARCHIVE_DIR", "region": "ca", "ok": True, "detail": "",
                        "exception_signature_id": None}]}
AUDIT_ROW = {"id": 88123, "plant": "QC", "owner_id": _id("usr_", 11), "entity_type": "mfg_dhr", "entity_id": REC_ID,
             "action": "release", "actor_id": _id("usr_", 3), "created_at": TS2, "reason": "Reviewed by exception",
             "signature_id": SIG["id"], "details": {"decision": "released"}}


def examples() -> dict[str, tuple[Any, Any]]:
    return {
        "dhr_summary": (D.DhrSummary, SUMMARY),
        "dhr_record": (D.DhrRecord, RECORD),
        "dhr_live": (D.DhrRecord, {**RECORD, "id": "live", "number": "-", "status": "open", "row_version": 0,
                                   "released_at": None, "decision": None, "versions": [], "signatures": [],
                                   "renditions": [], "hold_open": True, "releasable": BLOCKED}),
        "dhr_exception": (D.DhrException, EXC),
        "dhr_section": (D.SectionPage, {"record_id": REC_ID, "section": "serials", "sha256": H,
                                        "data": CONTENT["serials"], "items": ["SN0001", "SN0002"], "total": 2,
                                        "page": 1, "limit": 500}),
        "dhr_blocked": (D.Releasable, BLOCKED),
        "review_queue_row": (D.ReviewQueueRow, {"id": _id("dhr_", 8), "number": "DHR-000008", "version": 1,
                                                "status": "in_review", "item": ITEM, "lot_code": "A2611QC08",
                                                "line_codes": ["FLA-01"], "open_major": 1, "open_minor": 2,
                                                "oldest_exception_age_days": 1.4, "age_days": 1.4,
                                                "changed_after_release": False, "reviewer_ids": [_id("usr_", 2)]}),
        "deviation": (Q.DeviationRecord, DEVIATION),
        "agreement": (Q.AgreementRecord, AGREEMENT),
        "coa": (Q.CoaRecord, COA),
        "coa_line": (Q.CoaLine, COA_LINE),
        "batch_pack": (Q.BatchPackRecord, PACK),
        "udi_device": (U.UdiDeviceRecord, UDI),
        "udi_parse": (U.ParseResult, PARSE),
        "udi_export": (U.UdiExportRecord, EXPORT),
        "label_template": (U.LabelTemplateRecord, TEMPLATE),
        "label_assignment": (U.AssignmentRow, {"item_id": ITEM["id"], "level": "each", "customer": None,
                                               "template_code": "SYR-EACH"}),
        "printer": (U.PrinterRecord, PRINTER),
        "print_job": (U.PrintJobRecord, JOB),
        "print_event": (U.PrintEventRecord, EVENT),
        "verify_result": (U.VerifyResult, {"result": "mismatch", "mismatch": {"lot": {"expected": "A2611QC07",
                                                                                      "scanned": "A2611QC08"}},
                                           "parsed": {**PARSE, "ais": {**PARSE["ais"], "10": "A2611QC08"}},
                                           "job": {**JOB, "status": "blocked"}}),
        "iq_result": (V.IqResult, IQ),
        "val_package": (V.PackageRecord, PACKAGE),
        "residency": (V.ResidencyReport, RESIDENCY),
        "org_audit_row": (V.OrgAuditRow, AUDIT_ROW),
        "pending_signatures": (None, {"status": "pending_signatures", "record_type": "dhr", "record_id": REC_ID,
                                      "signatures": [SIG_REVIEW], "next_step": {
                                          "step": 2, "meanings": ["released"], "roles": ["qa_approver"],
                                          "auth": "password_totp", "can_sign": False,
                                          "blocked_reason": "ESIG_SAME_SIGNER"}}),
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
