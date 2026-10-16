export interface TooltipRow {
  label: string;
  value: string;
  color?: string;
}

/** Positioned tooltip for hover and keyboard focus (x, y in container pixels). */
export function ChartTooltip({ x, y, width, title, rows }: { x: number; y: number; width: number; title: string; rows: TooltipRow[] }) {
  const left = x > width - 240 ? Math.max(0, x - 236) : x + 14;
  return (
    <div className="chart-tooltip" style={{ left, top: Math.max(0, y - 10) }} role="tooltip">
      <div className="tt-title">{title}</div>
      {rows.map((r) => (
        <div className="tt-row" key={r.label}>
          <span>
            {r.color ? <span className="swatch" style={{ background: r.color, width: 10 }} aria-hidden /> : null}
            {r.label}
          </span>
          <span>{r.value}</span>
        </div>
      ))}
    </div>
  );
}

/** Keyboard-focusable invisible point over the SVG with an accessible label. */
export function ChartPoint({
  x,
  y,
  label,
  onFocus,
  onBlur,
}: {
  x: number;
  y: number;
  label: string;
  onFocus(): void;
  onBlur(): void;
}) {
  return (
    <button
      type="button"
      className="chart-point"
      style={{ left: x, top: y }}
      aria-label={label}
      onFocus={onFocus}
      onBlur={onBlur}
      onMouseEnter={onFocus}
      onMouseLeave={onBlur}
    />
  );
}
