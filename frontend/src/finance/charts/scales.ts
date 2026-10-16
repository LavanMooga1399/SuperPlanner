/** Small scale helpers for the hand-written SVG charts (FINANCE.md 20.2). */
import { useEffect, useRef, useState, type RefObject } from "react";

export type Scale = (v: number) => number;

export function linearScale(d0: number, d1: number, r0: number, r1: number): Scale {
  const span = d1 - d0 || 1;
  return (v: number) => r0 + ((v - d0) / span) * (r1 - r0);
}

/** "Nice" tick values covering [min, max]. */
export function niceTicks(min: number, max: number, count = 5): number[] {
  if (!Number.isFinite(min) || !Number.isFinite(max)) return [0];
  if (min === max) max = min + 1;
  const raw = (max - min) / Math.max(1, count);
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const norm = raw / mag;
  const step = (norm >= 5 ? 10 : norm >= 2 ? 5 : norm >= 1 ? 2 : 1) * mag;
  const start = Math.floor(min / step) * step;
  const ticks: number[] = [];
  for (let v = start; v <= max + step * 0.5; v += step) ticks.push(Math.round(v / step) * step);
  return ticks;
}

export function niceMax(max: number): number {
  const t = niceTicks(0, max > 0 ? max : 1);
  return t[t.length - 1];
}

/** Indices of month labels for the x axis: January of every k-th year (or the first month). */
export function monthTickIndices(months: string[], maxTicks = 8): number[] {
  const n = months.length;
  if (n === 0) return [];
  if (n <= 24) {
    const step = Math.max(1, Math.ceil(n / maxTicks));
    const out: number[] = [];
    for (let i = 0; i < n; i += step) out.push(i);
    return out;
  }
  const years = Math.ceil(n / 12);
  const stepYears = Math.max(1, Math.ceil(years / maxTicks));
  const out: number[] = [];
  for (let i = 0; i < n; i++) {
    if (months[i].endsWith("-01")) {
      const y = Number(months[i].slice(0, 4));
      if (y % stepYears === 0) out.push(i);
    }
  }
  return out.length ? out : [0];
}

/** Measured width of a container (ResizeObserver), for responsive SVG. */
export function useWidth<T extends HTMLElement>(fallback = 720): [RefObject<T>, number] {
  const ref = useRef<T>(null);
  const [w, setW] = useState(fallback);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const measure = () => setW(Math.max(280, Math.floor(el.clientWidth || fallback)));
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [fallback]);
  return [ref, w];
}

/** Chart palette (CSS variables only, so dark mode works). */
export const PALETTE = ["var(--fin-c1)", "var(--fin-c2)", "var(--fin-c3)", "var(--fin-c4)", "var(--fin-c5)", "var(--fin-c6)", "var(--fin-c7)", "var(--fin-c8)"];
export const paletteColor = (i: number) => PALETTE[((i % PALETTE.length) + PALETTE.length) % PALETTE.length];
