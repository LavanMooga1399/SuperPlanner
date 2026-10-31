/** Code 128 as SVG (M4 5): crisp at any print resolution, with the human-readable text below. */
import { useMemo } from "react";
import { Code128Error, code128Modules } from "../lib/code128";

export function Barcode({ value, height = 48, module = 1.6, showText = true, testId }: { value: string; height?: number; module?: number; showText?: boolean; testId?: string }) {
  const enc = useMemo(() => {
    try {
      return { mods: code128Modules(value), error: null as string | null };
    } catch (e) {
      return { mods: [] as number[], error: e instanceof Code128Error ? e.message : "Cannot encode" };
    }
  }, [value]);
  if (enc.error) return <span className="badge danger">{enc.error}</span>;
  const quiet = 10;
  const total = enc.mods.reduce((a, b) => a + b, 0) + quiet * 2;
  const rects: { x: number; w: number }[] = [];
  let x = quiet;
  enc.mods.forEach((w, i) => {
    if (i % 2 === 0) rects.push({ x, w });
    x += w;
  });
  return (
    <span className="barcode-wrap" data-testid={testId} data-value={value}>
      <svg
        className="barcode"
        role="img"
        aria-label={`Barcode ${value}`}
        width={total * module}
        height={height}
        viewBox={`0 0 ${total} ${height}`}
        preserveAspectRatio="none"
        shapeRendering="crispEdges"
      >
        <rect x={0} y={0} width={total} height={height} fill="#fff" />
        {rects.map((r, i) => (
          <rect key={i} x={r.x} y={0} width={r.w} height={height} fill="#000" />
        ))}
      </svg>
      {showText ? <span className="barcode-text mono">{value}</span> : null}
    </span>
  );
}
