/**
 * Plant-local time for the schedule screens (M3 5): instants are UTC in the API and shown in the plant zone - the
 * IANA `time_zone` when set (DST-correct via `Intl`), else the fixed M1 `utc_offset`.
 */
import { useMemo } from "react";
import type { PlantRecord } from "../api/types";
import type { PlantM3Fields } from "../api/typesM3";
import { offsetMinutes } from "./format";
import { usePlant } from "./useMfg";

export interface PlantClock {
  zoneLabel: string;
  /** "Mon 2 Nov 09:15" */
  dateTime(iso: string | null | undefined): string;
  /** "09:15" */
  time(iso: string | null | undefined): string;
  /** local `YYYY-MM-DD` of an instant */
  day(iso: string): string;
  /** local wall-clock parts of an instant (for axis ticks) */
  parts(ms: number): { y: number; mo: number; d: number; h: number; mi: number; wd: number };
  /** local `YYYY-MM-DDTHH:MM` (datetime-local input) -> UTC ISO */
  fromLocal(local: string): string;
  /** UTC ISO -> local `YYYY-MM-DDTHH:MM` */
  toLocal(iso: string): string;
}

const WD = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MO = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const pad = (n: number) => String(n).padStart(2, "0");

export function makeClock(plant: (PlantRecord & PlantM3Fields) | null | undefined): PlantClock {
  const tz = plant?.time_zone || null;
  const off = offsetMinutes(plant?.utc_offset ?? "+00:00");
  let fmt: Intl.DateTimeFormat | null = null;
  if (tz) {
    try {
      fmt = new Intl.DateTimeFormat("en-GB", { timeZone: tz, year: "numeric", month: "numeric", day: "numeric", hour: "numeric", minute: "numeric", weekday: "short", hourCycle: "h23" });
    } catch {
      fmt = null;
    }
  }
  const parts = (ms: number) => {
    if (fmt) {
      const p: Record<string, string> = {};
      for (const x of fmt.formatToParts(new Date(ms))) p[x.type] = x.value;
      return { y: Number(p.year), mo: Number(p.month), d: Number(p.day), h: Number(p.hour) % 24, mi: Number(p.minute), wd: WD.indexOf(p.weekday) };
    }
    const d = new Date(ms + off * 60000);
    return { y: d.getUTCFullYear(), mo: d.getUTCMonth() + 1, d: d.getUTCDate(), h: d.getUTCHours(), mi: d.getUTCMinutes(), wd: d.getUTCDay() };
  };
  /** offset (minutes) of the plant zone at an instant */
  const offsetAt = (ms: number) => {
    if (!fmt) return off;
    const p = parts(ms);
    return Math.round((Date.UTC(p.y, p.mo - 1, p.d, p.h, p.mi) - Math.floor(ms / 60000) * 60000) / 60000);
  };
  return {
    zoneLabel: tz ?? `UTC${plant?.utc_offset ?? "+00:00"}`,
    parts,
    dateTime: (iso) => {
      if (!iso) return "";
      const p = parts(Date.parse(iso));
      return `${WD[p.wd]} ${p.d} ${MO[p.mo - 1]} ${pad(p.h)}:${pad(p.mi)}`;
    },
    time: (iso) => {
      if (!iso) return "";
      const p = parts(Date.parse(iso));
      return `${pad(p.h)}:${pad(p.mi)}`;
    },
    day: (iso) => {
      const p = parts(Date.parse(iso));
      return `${p.y}-${pad(p.mo)}-${pad(p.d)}`;
    },
    toLocal: (iso) => {
      const p = parts(Date.parse(iso));
      return `${p.y}-${pad(p.mo)}-${pad(p.d)}T${pad(p.h)}:${pad(p.mi)}`;
    },
    fromLocal: (local) => {
      const guess = Date.parse(`${local.length === 16 ? `${local}:00` : local}Z`);
      // two passes settle DST edges (gap moves forward, ambiguous takes the first)
      let ms = guess - offsetAt(guess) * 60000;
      ms = guess - offsetAt(ms) * 60000;
      return new Date(ms).toISOString();
    },
  };
}

export function usePlantClock(): PlantClock {
  const plant = usePlant();
  return useMemo(() => makeClock(plant.data as (PlantRecord & PlantM3Fields) | null), [plant.data]);
}

/** "3 d 4 h" / "45 min" */
export function fmtDuration(minutes: number | null | undefined): string {
  if (minutes === null || minutes === undefined || !Number.isFinite(minutes)) return "";
  const m = Math.round(Math.abs(minutes));
  const d = Math.floor(m / 1440);
  const h = Math.floor((m % 1440) / 60);
  const r = m % 60;
  if (d) return `${d} d${h ? ` ${h} h` : ""}`;
  if (h) return `${h} h${r ? ` ${r} min` : ""}`;
  return `${r} min`;
}
