"""Deterministic helpers for the sample generators (M1-DESIGN 10.1): a seeded `random.Random` used only through
`random()`, `randrange()`, `choice()` and `shuffle()` on lists in a fixed order; sets are never iterated and no
clock is read. Every sample is canonicalised through `bundle_to_dataset` -> `dataset_to_bundle`."""

from __future__ import annotations

import random
from bisect import bisect_right
from datetime import date, datetime
from typing import Any

from ..bundle import SHEET_NAMES, MfgBundle, bundle_to_dataset, dataset_to_bundle

EFFECTIVE_FROM = date(2026, 1, 1)
DESC_FICTIONAL = "Fictional sample data."
ALL_WEEK = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
MON_SAT = ALL_WEEK[:6]


def shift(name: str, days: list[str], start: str, end: str, *breaks: str) -> dict[str, Any]:
    return {"name": name, "days": list(days), "start": start, "end": end, "breaks": list(breaks)}


REG = [shift("Day", MON_SAT, "09:00", "18:00", "Lunch=13:00-13:45")]
EVE = [shift("Evening", MON_SAT, "18:00", "22:00", "Tea=19:30-19:45")]
EXT = [shift("Extended", MON_SAT, "09:00", "22:00")]
THREE_SHIFT = [shift("A", MON_SAT, "06:00", "14:00", "Meal=10:00-10:30"),
               shift("B", MON_SAT, "14:00", "22:00", "Meal=18:00-18:30"),
               shift("C", MON_SAT, "22:00", "06:00", "Meal=02:00-02:30")]
H24X7 = [shift("Day", ALL_WEEK, "00:00", "00:00")]
SUN = [shift("Sunday", ["sun"], "06:00", "22:00")]


class Builder:
    """Collects bundle rows; omitted columns take the bundle/model defaults."""

    def __init__(self) -> None:
        self.b: MfgBundle = {name: [] for name in SHEET_NAMES}

    def plant(self, name: str, utc_offset: str = "+05:30", horizon: int = 90, currency: str = "INR") -> None:
        self.b["plant"] = [{"name": name, "utc_offset": utc_offset, "planning_horizon_days": horizon,
                            "currency": currency}]

    def item(self, pn: str, make_buy: str, description: str, **kw: Any) -> str:
        row = {"part_number": pn, "make_buy": make_buy, "description": description}
        attrs = kw.pop("attributes", {})
        row.update(kw)
        for k, v in attrs.items():
            row[f"attr:{k}"] = v
        self.b["items"].append(row)
        return pn

    def skill(self, code: str, name: str) -> str:
        self.b["skills"].append({"code": code, "name": name})
        return code

    def tool(self, code: str, name: str, quantity: int, kind: str | None = None) -> str:
        self.b["tool_pools"].append({"code": code, "name": name, "quantity": quantity, "kind": kind})
        return code

    def group(self, code: str, name: str, kind: str | None = None) -> str:
        self.b["groups"].append({"code": code, "name": name, "kind": kind})
        return code

    def line(self, code: str, group: str, name: str, **kw: Any) -> str:
        self.b["lines"].append({"code": code, "group_code": group, "name": name, **kw})
        return code

    def template(self, code: str, name: str, shifts: list[dict[str, Any]], description: str = "") -> str:
        self.b["shift_templates"].append({"code": code, "name": name, "description": description})
        for sh in shifts:
            self.b["shifts"].append({"template_code": code, "shift_name": sh["name"], "days": sh["days"],
                                     "start": sh["start"], "end": sh["end"], "breaks": sh["breaks"]})
        return code

    def assign(self, template: str, target_type: str, target: str, kind: str = "base",
               effective_from: date = EFFECTIVE_FROM, **kw: Any) -> None:
        self.b["shift_assignments"].append({"template_code": template, "target_type": target_type,
                                            "target_code": target, "kind": kind, "effective_from": effective_from,
                                            **kw})

    def exception(self, scope: str, target: str | None, kind: str, start: datetime | date, end: datetime | date,
                  label: str) -> None:
        self.b["calendar_exceptions"].append({"scope": scope, "target_code": target, "kind": kind, "start": start,
                                              "end": end, "label": label})

    def operator(self, code: str, name: str, skills: list[str], template: str | None,
                 shift_names: list[str] | None = None, home: str | None = None) -> None:
        self.b["operators"].append({"code": code, "name": name, "skills": list(skills),
                                    "shift_template_code": template, "shift_names": list(shift_names or []),
                                    "home_group_code": home})

    def bom(self, parent: str, lines: list[dict[str, Any]], *, version: int = 1, status: str = "released",
            effective_from: date | None = EFFECTIVE_FROM, revision: str | None = None, note: str = "") -> None:
        self.b["boms"].append({"parent_part_number": parent, "revision": revision, "version": version,
                               "effective_from": effective_from, "status": status, "note": note})
        for ln in lines:
            self.b["bom_lines"].append({"parent_part_number": parent, "revision": revision, "version": version,
                                        **ln})

    def routing(self, pn: str, ops: list[dict[str, Any]], *, code: str = "STD", priority: int = 1,
                status: str = "released", effective_from: date | None = EFFECTIVE_FROM, version: int = 1) -> None:
        self.b["routings"].append({"part_number": pn, "code": code, "version": version, "priority": priority,
                                   "effective_from": effective_from, "status": status})
        for op in ops:
            self.b["operations"].append({"part_number": pn, "code": code, "version": version, **op})

    def canonical(self) -> MfgBundle:
        return canonical(self.b)


def canonical(bundle: MfgBundle) -> MfgBundle:
    return dataset_to_bundle(bundle_to_dataset(bundle))


def line(find: Any, child: str, qty: float, **kw: Any) -> dict[str, Any]:
    return {"find_number": str(find), "child_part_number": child, "qty_per": qty, **kw}


def op(seq: int, name: str, group: str, **kw: Any) -> dict[str, Any]:
    return {"seq": seq, "name": name, "group_code": group, **kw}


class Designators:
    """Reference designators per BOM, generated to match quantities: `next("R", 4)` -> `"R1-R4"`."""

    def __init__(self) -> None:
        self.n: dict[str, int] = {}

    def next(self, prefix: str, qty: int) -> str:
        start = self.n.get(prefix, 0) + 1
        self.n[prefix] = start + qty - 1
        return f"{prefix}{start}" if qty == 1 else f"{prefix}{start}-{prefix}{start + qty - 1}"


class Weighted:
    """Weighted choice through `random()` and a cumulative list (no `choices()`, review 10.1)."""

    def __init__(self, values: list[Any], weights: list[float]):
        self.values = values
        self.cum: list[float] = []
        t = 0.0
        for w in weights:
            t += w
            self.cum.append(t)
        self.total = t

    def pick(self, rng: random.Random) -> Any:
        return self.values[min(bisect_right(self.cum, rng.random() * self.total), len(self.values) - 1)]


# ---------------------------------------------------------------- component library (lazily created buy items)

E24 = [10, 11, 12, 13, 15, 16, 18, 20, 22, 24, 27, 30, 33, 36, 39, 43, 47, 51, 56, 62, 68, 75, 82, 91]
E12 = [10, 12, 15, 18, 22, 27, 33, 39, 47, 56, 68, 82]


def _eng(mantissa: int, exp: int, units: tuple[str, ...]) -> str:
    """mantissa (10..91) x 10^exp in base units -> '4K7', '100R', '10K' / '22P', '4N7', '100N', '10U'."""
    value = mantissa * 10 ** exp                     # in tenths of a base unit
    idx = 0
    while value >= 10_000 and idx < len(units) - 1:
        value //= 1000
        idx += 1
    whole, frac = divmod(value, 10)
    return f"{whole}{units[idx]}{frac}" if frac else f"{whole}{units[idx]}"


class Library:
    """Buy items created on first use (so a sample never has orphan items). Part numbers are derived from the
    drawn attributes, so repeated draws of the same value share one item (natural sharing between boards)."""

    PACKAGES = ["0402", "0603", "0805"]

    def __init__(self, b: Builder, rng: random.Random, prefix: str):
        self.b = b
        self.rng = rng
        self.p = prefix
        self.made: dict[str, None] = {}
        self.serial = 0

    def _mpn(self) -> str:
        self.serial += 1
        return f"SYN-{self.p.rstrip('-')}-{self.serial:05d}"

    def get(self, pn: str, description: str, **kw: Any) -> str:
        if pn not in self.made:
            self.made[pn] = None
            kw.setdefault("attributes", {"manufacturer": "Synthetic", "mpn": self._mpn()})
            self.b.item(pn, "buy", description, **kw)
        return pn

    def lead(self, lo: int, hi: int, step: int = 7) -> int:
        return self.rng.randrange(lo, hi + 1, step)

    def resistor(self, pkg: str | None = None, value: str | None = None) -> str:
        pkg = pkg or self.rng.choice(self.PACKAGES)
        value = value or _eng(self.rng.choice(E24), self.rng.randrange(1, 7), ("R", "K", "M"))
        return self.get(f"{self.p}RES-{pkg}-{value}", f"Resistor {value} {pkg} 1%", lead_time_days=self.lead(28, 56),
                        min_order_qty=5000, order_multiple=5000)

    def capacitor(self, pkg: str | None = None, value: str | None = None) -> str:
        pkg = pkg or self.rng.choice(self.PACKAGES)
        value = value or _eng(self.rng.choice(E12), self.rng.randrange(1, 7), ("P", "N", "U"))
        return self.get(f"{self.p}CAP-{pkg}-{value}", f"Capacitor {value} {pkg} X7R",
                        lead_time_days=self.lead(28, 56), min_order_qty=5000, order_multiple=5000)

    def inductor(self) -> str:
        pkg, val = self.rng.choice(self.PACKAGES), self.rng.choice(["1U", "2U2", "4U7", "10U", "22U", "47U", "100U"])
        return self.get(f"{self.p}IND-{pkg}-{val}", f"Inductor {val} {pkg}", lead_time_days=self.lead(42, 70))

    def diode(self) -> str:
        kind, n = self.rng.choice(["SCH", "TVS", "ZEN", "LED", "SIG"]), self.rng.randrange(1, 13)
        return self.get(f"{self.p}DIO-{kind}-{n:02d}", f"Diode {kind} type {n}", lead_time_days=self.lead(42, 84))

    def transistor(self) -> str:
        kind, n = self.rng.choice(["NMOS", "PMOS", "NPN", "PNP"]), self.rng.randrange(1, 11)
        return self.get(f"{self.p}TRN-{kind}-{n:02d}", f"Transistor {kind} type {n}",
                        lead_time_days=self.lead(42, 84))

    def ic(self, max_lead: int = 168) -> str:
        kind = self.rng.choice(["LDO", "OPA", "CMP", "LOG", "CAN", "RS485", "ETH", "DCDC", "ADC", "DAC", "MEM",
                                "SUP", "ISO", "DRV", "MUX"])
        n = self.rng.randrange(1, 25)
        return self.get(f"{self.p}IC-{kind}-{n:03d}", f"IC {kind} variant {n}", lead_time_days=self.lead(56, max_lead),
                        handling_class=self.rng.choice(["MSL3", "MSL1", "ESD"]))

    def connector(self, kind: str | None = None, pins: int | None = None) -> str:
        kind = kind or self.rng.choice(["HDR", "IDC", "DSUB", "M12", "FFC", "TB"])
        pins = pins or self.rng.choice([2, 3, 4, 6, 8, 10, 16, 20, 26, 40, 50])
        return self.get(f"{self.p}CON-{kind}-{pins}", f"Connector {kind} {pins}-pin", lead_time_days=self.lead(42, 84))

    def crystal(self) -> str:
        f = self.rng.choice(["8M", "12M", "16M", "20M", "24M", "25M", "32K768", "48M", "50M", "100M"])
        return self.get(f"{self.p}XTL-{f}", f"Crystal {f}Hz", lead_time_days=self.lead(56, 84))

    def ferrite(self) -> str:
        pkg, n = self.rng.choice(self.PACKAGES), self.rng.randrange(1, 7)
        return self.get(f"{self.p}FB-{pkg}-{n}", f"Ferrite bead {pkg} type {n}", lead_time_days=self.lead(28, 56))

    def fuse(self) -> str:
        r = self.rng.choice(["0A5", "1A", "2A", "3A15", "5A"])
        return self.get(f"{self.p}FUS-{r}", f"Fuse {r}", lead_time_days=self.lead(28, 56))

    def relay(self) -> str:
        kind, v = self.rng.choice(["SIG", "PWR", "SAFE", "LATCH"]), self.rng.choice(["5V", "12V", "24V", "110V"])
        return self.get(f"{self.p}RLY-{kind}-{v}", f"Relay {kind} {v} coil", lead_time_days=self.lead(56, 112))


#: (category, refdes prefix, weight) for random PCB component slots
SLOT_KINDS = Weighted([("resistor", "R"), ("capacitor", "C"), ("inductor", "L"), ("diode", "D"),
                       ("transistor", "Q"), ("ic", "U"), ("connector", "J"), ("crystal", "Y"), ("ferrite", "FB"),
                       ("fuse", "F"), ("relay", "K")],
                      [36, 30, 4, 5, 5, 10, 5, 1, 2, 1, 1])
QTY_PASSIVE = Weighted([1, 2, 3, 4, 6, 8, 12], [30, 25, 8, 15, 8, 6, 3])


def fill_components(lib: Library, rng: random.Random, des: Designators, used: set[str], n: int, *,
                    popular: Weighted | None = None, popular_share: float = 0.35, tht_seq: int | None = None,
                    ic_max_lead: int = 168) -> list[dict[str, Any]]:
    """`n` random component lines (child, qty, ref designators) without repeating a child already in `used`.
    Connectors are consumed at `tht_seq` (through-hole step). `used` is only used for membership tests."""
    out: list[dict[str, Any]] = []
    tries = 0
    while len(out) < n and tries < n * 50:
        tries += 1
        kind, prefix = SLOT_KINDS.pick(rng)
        if kind in ("resistor", "capacitor") and popular is not None and rng.random() < popular_share:
            k2, args = popular.pick(rng)
            if k2 != kind:
                continue
            pn = getattr(lib, kind)(*args)
        elif kind == "ic":
            pn = lib.ic(ic_max_lead)
        else:
            pn = getattr(lib, kind)()
        if pn in used:
            continue
        used.add(pn)
        qty = QTY_PASSIVE.pick(rng) if kind in ("resistor", "capacitor") else rng.choice([1, 1, 1, 2])
        row: dict[str, Any] = {"child": pn, "qty": qty, "ref_designators": des.next(prefix, qty)}
        if kind in ("connector", "relay") and tht_seq is not None:
            row["operation_seq"] = tht_seq
        if kind in ("resistor", "capacitor"):
            row["scrap_pct"] = 1.0
        out.append(row)
    return out
