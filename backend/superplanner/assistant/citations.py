"""Verifiable citations (M6-DESIGN 1.5): references are numbered per conversation by the server (R1, R2, ...) and
stored in `assistant_refs`; the answer may cite only references issued in this conversation (others are stripped);
links are server-built internal paths (never a URL taken from data)."""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..api.db import new_id, utcnow
from ..api.mfg.db_models_m6 import AssistantRefRow

MARKER = re.compile(r"\[(R[0-9]{1,4})\]")
SAFE_LINK = re.compile(r"^/(mfg|integration|m)(/[A-Za-z0-9_.:\-]*)*(\?[A-Za-z0-9_.:=&\-]*)?$")
MAX_REFS_PER_CONVERSATION = 2000
LINK_TYPES = (("/mfg/demand/", "demand_order"), ("/mfg/work-orders/", "work_order"),
              ("/mfg/purchasing/orders/", "purchase_order"), ("/mfg/purchasing/requests/", "purchase_request"),
              ("/mfg/schedule/runs/", "aps_run"), ("/mfg/mrp/runs/", "mrp_record"), ("/mfg/serials/", "serial"),
              ("/mfg/inventory/lots/", "lot"), ("/mfg/lots", "lot"), ("/mfg/items/", "item"),
              ("/mfg/suppliers/", "supplier"), ("/mfg/floor", "line"), ("/mfg/eco/", "eco"),
              ("/mfg/recalls/", "recall"), ("/mfg/transfers/", "transfer_order"),
              ("/mfg/inventory/locations/", "location"))


def safe_link(link: Any) -> str | None:
    if not isinstance(link, str) or len(link) > 300 or "//" in link or not SAFE_LINK.match(link):
        return None
    return link


def type_of_link(link: str) -> str:
    for prefix, t in LINK_TYPES:
        if link.startswith(prefix):
            return t
    return "record"


class RefRegistry:
    """Issues references of one conversation; the same (type, id) keeps its number."""

    def __init__(self, conversation_id: str, owner_id: str):
        self.conversation_id = conversation_id
        self.owner_id = owner_id
        self.by_key: dict[tuple[str, str], str] = {}
        self.records: dict[str, dict[str, Any]] = {}
        self.new: list[dict[str, Any]] = []
        self.next_no = 1

    def load(self, s: Session) -> "RefRegistry":
        for r in s.execute(select(AssistantRefRow).where(AssistantRefRow.conversation_id == self.conversation_id)
                           .order_by(AssistantRefRow.ref_no)).scalars():
            ref = f"R{r.ref_no}"
            self.by_key[(r.ref_type, r.record_id)] = ref
            self.records[ref] = {"ref": ref, "type": r.ref_type, "id": r.record_id, "label": r.label, "link": r.link}
            self.next_no = max(self.next_no, r.ref_no + 1)
        return self

    def issue(self, type_: str, id_: str, label: str, link: str) -> str | None:
        link_ok = safe_link(link)
        if link_ok is None or not id_:
            return None
        key = (str(type_)[:32], str(id_)[:64])
        if key in self.by_key:
            return self.by_key[key]
        if self.next_no > MAX_REFS_PER_CONVERSATION:
            return None
        ref = f"R{self.next_no}"
        self.next_no += 1
        rec = {"ref": ref, "type": key[0], "id": key[1], "label": str(label or key[1])[:200], "link": link_ok}
        self.by_key[key] = ref
        self.records[ref] = rec
        self.new.append(rec)
        return ref

    def flush(self, s: Session) -> None:
        now = utcnow()
        for rec in self.new:
            s.add(AssistantRefRow(id=new_id("asr_"), owner_id=self.owner_id, conversation_id=self.conversation_id,
                                  ref_no=int(rec["ref"][1:]), ref_type=rec["type"], record_id=rec["id"],
                                  label=rec["label"], link=rec["link"], created_at=now))
        self.new = []
        s.flush()


def resolve(answer: str, registry: RefRegistry) -> tuple[str, list[dict[str, Any]]]:
    """Strip markers not issued in this conversation; return (answer, citations in first-use order)."""
    cited: list[dict[str, Any]] = []
    seen: set[str] = set()

    def repl(m: re.Match[str]) -> str:
        ref = m.group(1)
        rec = registry.records.get(ref)
        if rec is None:
            return ""
        if ref not in seen:
            seen.add(ref)
            cited.append(dict(rec))
        return m.group(0)

    out = MARKER.sub(repl, answer or "")
    out = re.sub(r"[ \t]+([.,;:])", r"\1", out)          # "late [R9]." -> "late ." -> "late."
    return out, cited


def count_refs(s: Session, conversation_id: str) -> int:
    return int(s.execute(select(func.count()).select_from(AssistantRefRow).where(
        AssistantRefRow.conversation_id == conversation_id)).scalar() or 0)


#: markdown subset (1.5): HTML tags, images and links are removed from answers
_HTML = re.compile(r"<[^>]{0,200}>")
_IMAGE = re.compile(r"!\[([^\]]{0,200})\]\([^)]{0,500}\)")
_LINK = re.compile(r"(?<!\!)\[([^\]]{0,200})\]\([^)]{0,500}\)")
_AUTOLINK = re.compile(r"\b(?:https?|ftp|javascript|data):[^\s)\]]+", re.IGNORECASE)


def sanitize(answer: str) -> str:
    a = _IMAGE.sub(r"\1", answer or "")
    a = _LINK.sub(r"\1", a)
    a = _HTML.sub("", a)
    a = _AUTOLINK.sub("[link removed]", a)
    return a[:20000]
