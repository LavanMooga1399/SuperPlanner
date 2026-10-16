export interface LegendItem {
  label: string;
  color: string;
  kind?: "box" | "line" | "dashed" | "band";
}

export function Legend({ items, label = "Legend" }: { items: LegendItem[]; label?: string }) {
  return (
    <ul className="legend" aria-label={label} style={{ listStyle: "none", margin: 0, padding: 0 }}>
      {items.map((it) => (
        <li key={it.label} className="legend-item">
          <svg width="18" height="10" aria-hidden>
            {it.kind === "line" ? (
              <line x1="0" y1="5" x2="18" y2="5" stroke={it.color} strokeWidth="2.5" />
            ) : it.kind === "dashed" ? (
              <line x1="0" y1="5" x2="18" y2="5" stroke={it.color} strokeWidth="2" strokeDasharray="4 3" />
            ) : it.kind === "band" ? (
              <rect x="0" y="0" width="18" height="10" rx="2" fill={it.color} stroke="var(--fin-band-line)" />
            ) : (
              <rect x="0" y="0" width="18" height="10" rx="2" fill={it.color} />
            )}
          </svg>
          {it.label}
        </li>
      ))}
    </ul>
  );
}
