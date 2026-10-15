/**
 * Client-side mirror of calendar expansion (ARCHITECTURE 4) used only for
 * display (shading closed time in the Gantt). The engine is authoritative.
 */
import type { Calendar, Weekday } from "../api/types";
import { hhmmToMin } from "./planEdit";
import { isoToMs, offsetMinutesOf, wallParts } from "./time";

const JS_DAY: Weekday[] = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"];

/** Minute (relative to horizonStart) of the local midnight at or before horizonStart. */
export function firstMidnight(horizonStart: string): number {
  const p = wallParts(isoToMs(horizonStart), offsetMinutesOf(horizonStart));
  return -(p.hour * 60 + p.minute);
}

/** Weekday of local day starting at minute m (m must be a local midnight). */
function weekdayAt(m: number, horizonStart: string): Weekday {
  const p = wallParts(isoToMs(horizonStart) + (m + 1) * 60000, offsetMinutesOf(horizonStart));
  return JS_DAY[p.weekday];
}

/** Open windows in [from, to) as sorted, merged minute intervals. */
export function expandWindows(cal: Calendar | null, horizonStart: string, from: number, to: number): Array<[number, number]> {
  if (!cal) return [[from, to]];
  let wins: Array<[number, number]> = [];
  if (cal.weekly === null) {
    wins = [[from, to]];
  } else {
    const m0 = firstMidnight(horizonStart);
    let day = m0 + Math.floor((from - m0) / 1440) * 1440;
    for (; day < to; day += 1440) {
      const wd = weekdayAt(day, horizonStart);
      for (const [a, b] of cal.weekly[wd] ?? []) {
        const s = day + hhmmToMin(a);
        const e = day + hhmmToMin(b);
        if (!(e > s)) continue;
        const cs = Math.max(s, from);
        const ce = Math.min(e, to);
        if (ce > cs) wins.push([cs, ce]);
      }
    }
    wins.sort((x, y) => x[0] - y[0]);
    const merged: Array<[number, number]> = [];
    for (const w of wins) {
      const last = merged[merged.length - 1];
      if (last && last[1] >= w[0]) last[1] = Math.max(last[1], w[1]);
      else merged.push([w[0], w[1]]);
    }
    wins = merged;
  }
  const h0 = isoToMs(horizonStart);
  for (const b of cal.blocked) {
    const bs = Math.floor((isoToMs(b.start) - h0) / 60000);
    const be = Math.floor((isoToMs(b.end) - h0) / 60000);
    if (!(be > bs)) continue;
    const next: Array<[number, number]> = [];
    for (const [s, e] of wins) {
      if (be <= s || bs >= e) next.push([s, e]);
      else {
        if (bs > s) next.push([s, bs]);
        if (be < e) next.push([be, e]);
      }
    }
    wins = next;
  }
  return wins.filter(([s, e]) => e > s);
}

/** Complement of windows within [from, to). */
export function closedIntervals(wins: Array<[number, number]>, from: number, to: number): Array<[number, number]> {
  const out: Array<[number, number]> = [];
  let cur = from;
  for (const [s, e] of wins) {
    if (s > cur) out.push([cur, Math.min(s, to)]);
    cur = Math.max(cur, e);
    if (cur >= to) break;
  }
  if (cur < to) out.push([cur, to]);
  return out.filter(([s, e]) => e > s);
}
