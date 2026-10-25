"""Samples (M1-DESIGN 10; PLAN-M1 A3-2..A3-4): golden hashes and counts, determinism across PYTHONHASHSEED,
round trip, health content on 2026-11-02 / 90 days, Kavach size ranges."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

from superplanner.mfg import BomIndex, bundle_to_dataset, canonical_json, dataset_to_bundle, explode, samples
from superplanner.mfg import run_health_check
from superplanner.mfg.bom import split_alternates

AS_OF = date(2026, 11, 2)
BACKEND = Path(__file__).resolve().parents[2]

# Changing a generator means updating these values in the same change, deliberately (M 10.1).
GOLDEN = {
    "small": "9e7e574ea26683e1621ae7400f3179b4cad95c62abaece6a16dae386191a3345",
    "medium": "b1edb4942a81a43f000c561b0398b923580d579e006661ce80c4c6cc34823db8",
    "kavach": "f0c9eb200cafcd43cdba5bf0f10f582743a58a9c75bf444a387767f11ca71c19",
}
GOLDEN_KAVACH_X2 = "e22e172170d9f58bbe41f15bcbcf43aeba7e885bece693f8d06b7e646a53a847"
COUNTS = {
    "small": {"plant": 1, "items": 10, "skills": 2, "tool_pools": 2, "groups": 4, "lines": 4, "shift_templates": 3,
              "shifts": 3, "shift_assignments": 6, "calendar_exceptions": 1, "operators": 3, "boms": 1,
              "bom_lines": 9, "routings": 1, "operations": 4},
    "medium": {"plant": 1, "items": 171, "skills": 6, "tool_pools": 12, "groups": 10, "lines": 14,
               "shift_templates": 3, "shifts": 5, "shift_assignments": 11, "calendar_exceptions": 2, "operators": 12,
               "boms": 11, "bom_lines": 260, "routings": 10, "operations": 40},
    "kavach": {"plant": 1, "items": 1199, "skills": 14, "tool_pools": 86, "groups": 20, "lines": 50,
               "shift_templates": 6, "shifts": 8, "shift_assignments": 35, "calendar_exceptions": 8, "operators": 48,
               "boms": 63, "bom_lines": 2469, "routings": 61, "operations": 287},
}
INTENDED = {"small": {}, "medium": {"MFG_LONG_LEAD_TIME": 1},
            "kavach": {"MFG_SKILL_NOT_ON_SHIFT": 1, "MFG_DUPLICATE_COMPONENT": 1, "MFG_LONG_LEAD_TIME": 7}}


def sha(b) -> str:
    return hashlib.sha256(canonical_json(b)).hexdigest()


@pytest.mark.parametrize("sid", list(GOLDEN))
def test_golden_hash_and_counts(sid):
    b = samples.build(sid)
    assert sha(b) == GOLDEN[sid]
    assert samples.counts(sid) == COUNTS[sid]


def test_kavach_x2_golden():
    assert sha(samples.scale("kavach", 2)) == GOLDEN_KAVACH_X2


def test_identical_under_two_hash_seeds():
    code = ("import hashlib,json;from superplanner.mfg import samples, canonical_json;"
            "print(json.dumps({s: hashlib.sha256(canonical_json(samples.build(s))).hexdigest() "
            "for s in ('small','medium','kavach')}))")
    outs = []
    for seed in ("0", "12345"):
        env = {"PYTHONHASHSEED": seed, "PATH": "/usr/bin:/bin", "PYTHONPATH": str(BACKEND)}
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, cwd=BACKEND,
                           timeout=120)
        assert r.returncode == 0, r.stderr
        outs.append(json.loads(r.stdout))
    assert outs[0] == outs[1] == GOLDEN


@pytest.mark.parametrize("sid", list(GOLDEN))
def test_round_trip(sid):
    b = samples.build(sid)
    assert dataset_to_bundle(bundle_to_dataset(b)) == b


@pytest.mark.parametrize("sid", list(GOLDEN))
def test_health_has_no_errors_and_exactly_the_intended_issues(sid):
    r = run_health_check(bundle_to_dataset(samples.build(sid)), AS_OF, 90)
    assert r.ok and r.counts.error == 0
    assert r.by_code == INTENDED[sid]


def test_kavach_intended_skill_gap_is_coating_on_coat_1():
    r = run_health_check(bundle_to_dataset(samples.build("kavach")), AS_OF, 90)
    (i,) = [i for i in r.issues if i.code == "MFG_SKILL_NOT_ON_SHIFT"]
    assert i.entity.label == "COATING / COAT-1" and "EVE/Evening (optional) Mon-Sat" in i.message
    assert {x.label for x in i.related} == {"COAT-1", "COAT"}


def test_kavach_sizes_inside_the_design_ranges():
    ds = bundle_to_dataset(samples.build("kavach"))
    assert 1150 <= len(ds.items) <= 1500
    assert 2200 <= sum(len(b.lines) for b in ds.boms.values()) <= 2700
    assert len(ds.groups) == 20
    e = explode(BomIndex.from_dataset(ds, AS_OF), ds.items_by_pn["KV-TPU-1000"].id)
    assert 2300 <= e.totals.rows <= 3000 and e.totals.max_level == 4 and e.warnings == []
    shared = next(r for r in e.rows if r.part_number == "KV-CAP-0402-100N")
    assert shared.is_shared
    parents = {b.item_id for b in ds.boms.values() for ln in b.lines
               if ln.child_item_id == ds.items_by_pn["KV-CAP-0402-100N"].id}
    assert len(parents) >= 10
    alt_groups = [alts for b in ds.boms.values() if ds.items[b.item_id].part_number == "KV-PCB-DCC"
                  for _, alts in split_alternates(b.lines) if alts]
    assert len(alt_groups) == 2
    assert sum(len(b.lines) for b in bundle_to_dataset(samples.scale("kavach", 2)).boms.values()) >= 4000


def test_sample_rules():
    for sid, prefix in (("small", "SM-"), ("medium", "MD-"), ("kavach", "KV-")):
        b = samples.build(sid)
        assert all(r["part_number"].startswith(prefix) for r in b["items"])
        assert b["plant"][0]["utc_offset"] == "+05:30"
        released = [r for r in b["boms"] + b["routings"] if r["status"] == "released"]
        assert all(r["effective_from"] == date(2026, 1, 1) for r in released)
        mpns = [v for r in b["items"] for k, v in r.items() if k == "attr:mpn"]
        assert all(str(v).startswith("SYN-") for v in mpns)
    assert "not real HBL or Kavach data" in samples.SAMPLES["kavach"].description
    listing = samples.sample_list()
    assert [s["id"] for s in listing] == ["small", "medium", "kavach"] and listing[0]["counts"]["items"] == 10
    with pytest.raises(KeyError):
        samples.build("huge")


def test_build_returns_independent_copies():
    a = samples.build("small")
    a["items"].clear()
    assert len(samples.build("small")["items"]) == 10
