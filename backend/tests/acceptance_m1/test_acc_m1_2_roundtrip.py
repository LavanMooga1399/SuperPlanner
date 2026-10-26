"""15.3 #2: export xlsx -> import into a fresh account through the full wizard API (upload, mapping from the
suggestions without edits, preview 0 errors, commit) -> exports equal; explosion of KV-TPU-1000 identical.
Also: the CSV zip export is byte-equal after the round trip, and the re-import of the same file is a no-op."""

from __future__ import annotations

import io
import zipfile
from typing import Any

import pytest
from fastapi.testclient import TestClient

from accm1_helpers import AS_OF, Api, make_app, xlsx_sheets

EXPLOSION_KEYS = ("row", "parent_row", "subtree_end", "level", "part_number", "revision", "description", "make_buy",
                  "uom", "family", "lead_time_days", "active", "find_number", "ref_designators", "qty_per", "line_uom",
                  "scrap_pct", "operation_seq", "extended_qty", "is_phantom", "has_children", "is_shared")


def _explosion(api: Api, pn: str, **params: Any) -> list[tuple[Any, ...]]:
    it = api.item(pn)
    ex = api.get(f"/items/{it['id']}/explosion", on=AS_OF, **params)
    rows = []
    for r in ex["rows"]:
        alts = tuple((a["part_number"], a["qty_per"], a["line_uom"], a["alt_priority"]) for a in r.get("alternates", []))
        rows.append(tuple(r.get(k) for k in EXPLOSION_KEYS) + (alts, r.get("routing_id") is not None,
                                                                r.get("bom_id") is not None))
    return rows


def _no_errors(preview: dict[str, Any]) -> None:
    assert preview["error_count"] == 0, preview["row_errors"][:10]
    assert preview["ok"] is True


@pytest.mark.parametrize("fmt", ["xlsx", "zip"])
def test_export_wizard_import_into_fresh_account_round_trips(api: Api, db_url_factory, fmt: str):
    api.load("kavach")
    # make the data set exercise the non-released states too: one draft and one obsolete document
    cpu = api.released_bom("KV-PCB-CPU")
    draft = api.post(f"/boms/{cpu['id']}/copy", {"revision": None}, version=cpu["row_version"])
    assert draft["status"] == "draft"
    led = api.released_routing("KV-PCB-LED")
    led2 = api.post(f"/routings/{led['id']}/copy", {"revision": None, "code": None}, version=led["row_version"])
    rel = api.post(f"/routings/{led2['id']}/release", {"effective_from": "2026-06-01", "supersede_previous": True},
                   status=200, version=led2["row_version"])
    old = api.get(f"/routings/{led['id']}")
    api.post(f"/routings/{led['id']}/obsolete", {}, status=200, version=old["row_version"])
    assert rel["routing"]["status"] == "released"

    exp_a = api.call("GET", "/export", 200, params={"format": fmt})
    data_a = exp_a.content
    assert "attachment" in exp_a.headers["content-disposition"]
    assert exp_a.headers["content-disposition"].endswith(f'.{fmt}"')
    expl_a = _explosion(api, "KV-TPU-1000")
    expl_a_sum = _explosion(api, "KV-TPU-1000", mode="summarized")
    health_a = api.health()

    app_b = make_app(db_url_factory("accm1_b"))
    with TestClient(app_b) as cb:
        b = Api(cb)
        assert b.get("/summary")["counts"]["items"] == 0
        rec, preview = b.wizard(data_a, f"kavach-export.{fmt}")
        assert rec["status"] == "mapped"
        # every staged source sheet got a suggested target, and the import covered every data sheet
        assert all(s["suggested"] and s["suggested"]["target"] for s in rec["sheets"] if s["name"] != "README")
        _no_errors(preview)
        done = b.commit(rec)
        assert done["status"] == "committed" and done["result"]["counts"]["items"]["create"] > 1000

        exp_b = b.call("GET", "/export", 200, params={"format": fmt}).content
        if fmt == "zip":
            assert exp_b == data_a, "CSV zip export differs after the round trip"
            with zipfile.ZipFile(io.BytesIO(exp_b)) as z:
                assert all(i.date_time == (1980, 1, 1, 0, 0, 0) for i in z.infolist())
        else:
            assert xlsx_sheets(exp_b) == xlsx_sheets(data_a)
        assert _explosion(b, "KV-TPU-1000") == expl_a
        assert _explosion(b, "KV-TPU-1000", mode="summarized") == expl_a_sum
        h = b.health()
        assert h["ok"] == health_a["ok"] and h["by_code"] == health_a["by_code"]
        assert h["fingerprint"] == health_a["fingerprint"]

        # re-import of the same file into B: all unchanged, nothing written
        dv = b.get("/summary")["data_version"]
        cpu_b = b.released_bom("KV-PCB-CPU")
        rec2, preview2 = b.wizard(data_a, f"again.{fmt}")
        _no_errors(preview2)
        for sheet, cnt in preview2["counts"].items():
            assert cnt["create"] == cnt["update"] == cnt["delete"] == 0, (sheet, cnt)
        res2 = b.commit(rec2)["result"]
        for sheet, cnt in res2["counts"].items():
            assert cnt.get("create", 0) == cnt.get("update", 0) == cnt.get("delete", 0) == 0, (sheet, cnt)
        assert b.get("/summary")["data_version"] == dv
        assert b.released_bom("KV-PCB-CPU")["row_version"] == cpu_b["row_version"]
