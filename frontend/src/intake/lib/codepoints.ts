/**
 * Spans from the server are offsets in Unicode code points (PHASE2.md 2.3), while JavaScript strings index
 * UTF-16 code units. Everything here works on `Array.from(text)` so "₹" and emoji count as one character.
 */

export function codePoints(text: string): string[] {
  return Array.from(text);
}

export function cpLength(text: string): number {
  let n = 0;
  for (const _ of text) n++;
  return n;
}

export function cpSlice(text: string | string[], start: number, end?: number): string {
  const cps = typeof text === "string" ? Array.from(text) : text;
  return cps.slice(start, end).join("");
}

export interface SpanRef {
  start: number;
  end: number;
  /** provenance path or note id the span belongs to */
  id: string;
  label: string;
}

export interface TextSegment {
  text: string;
  span: SpanRef | null;
}

/**
 * Split `text` into plain and highlighted segments. Where spans nest (a whole list line and the "2-3 days"
 * inside it), each character belongs to the shortest span covering it, so inner phrases stay visible and
 * the rest of the outer phrase is still highlighted. Every character is shown exactly once.
 */
export function segmentText(text: string, spans: SpanRef[]): TextSegment[] {
  const cps = Array.from(text);
  const n = cps.length;
  const valid = spans
    .map((s) => ({ ...s, end: Math.min(s.end, n) }))
    .filter((s) => s.end > s.start && s.start < n);
  const cuts = new Set<number>([0, n]);
  for (const s of valid) {
    cuts.add(s.start);
    cuts.add(s.end);
  }
  const points = [...cuts].sort((a, b) => a - b);
  const out: TextSegment[] = [];
  for (let i = 0; i < points.length - 1; i++) {
    const a = points[i];
    const b = points[i + 1];
    let best: SpanRef | null = null;
    for (const s of valid) {
      if (s.start <= a && s.end >= b && (!best || s.end - s.start < best.end - best.start)) best = s;
    }
    const last = out[out.length - 1];
    const piece = cps.slice(a, b).join("");
    if (last && last.span === best) last.text += piece;
    else out.push({ text: piece, span: best });
  }
  return out;
}
