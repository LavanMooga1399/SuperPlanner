"""Meddev M4 master flags: every bought-in material and every made component is backflushed (first-expiry-first
lots from controlled stores, set at load), and the EtO chambers merge loads of different work orders (wait up to
8 h). The floor history is written by the sample load (`api/mfg/services/samples_meddev.py`)."""

from __future__ import annotations

from ..bundle import MfgBundle

BATCH_LINES = ("ETO-01", "ETO-02")
FINISHED_FAMILIES = ("SYRINGE", "NEEDLE", "CATHETER", "FLUSH", "TUBE", "PFS", "IVSET")


def master(b: MfgBundle) -> MfgBundle:
    for it in b["items"]:
        if it.get("family") not in FINISHED_FAMILIES:
            it["issue_method"] = "backflush"
    for ln in b["lines"]:
        if ln["code"] in BATCH_LINES:
            ln["batch_merge"] = True
            ln["batch_wait_minutes"] = 480
    return b
