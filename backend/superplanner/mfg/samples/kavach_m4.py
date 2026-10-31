"""Kavach M4 master flags (M4-DESIGN 14, 15 Q2/Q3): passives, wire, sleeving and labels backflushed (from the SMT
line-side location, set at load); unit serials captured at each PCB's ICT and at KV-TPU-1000 final test; the
burn-in racks and cure ovens merge batches of different WOs (wait up to 4 h). The floor history is written by the
sample load (`api/mfg/services/samples_m4.py`)."""

from __future__ import annotations

from ..bundle import MfgBundle

BACKFLUSH_PREFIXES = ("KV-RES-", "KV-CAP-", "KV-WIR-", "KV-SLV-", "KV-LBL-")
BATCH_LINES = ("BI-1", "BI-2", "OVEN-1", "OVEN-2")


def master(b: MfgBundle) -> MfgBundle:
    for it in b["items"]:
        if it["part_number"].startswith(BACKFLUSH_PREFIXES) and it.get("make_buy") == "buy":
            it["issue_method"] = "backflush"
    for op in b["operations"]:
        if (op.get("group_code") == "ICT" and op["part_number"].startswith("KV-PCB-")) or \
                (op["part_number"] == "KV-TPU-1000" and op["seq"] == 30):
            op["capture_serial"] = True
    for ln in b["lines"]:
        if ln["code"] in BATCH_LINES:
            ln["batch_merge"] = True
            ln["batch_wait_minutes"] = 240
    return b
