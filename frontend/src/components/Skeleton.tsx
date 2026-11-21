/** Skeleton placeholders (UX-STANDARD 4): reserve the layout while data loads, so nothing jumps on arrival. */
export function SkeletonLine({ width = "100%", height = 12 }: { width?: number | string; height?: number }) {
  return <span className="skel" style={{ width, height }} aria-hidden />;
}

/** A page-level loading block: header line, a filter-bar line and `rows` table rows. Announces `label`. */
export function SkeletonPage({ label = "Loading…", rows = 8 }: { label?: string; rows?: number }) {
  return (
    <div className="skel-page" role="status" aria-live="polite">
      <span className="sr-only">{label}</span>
      <SkeletonLine width="32%" height={14} />
      <div className="skel-rows">
        {Array.from({ length: rows }, (_, i) => (
          <div key={i} className="skel-row">
            <SkeletonLine width="14%" />
            <SkeletonLine width={`${30 + ((i * 17) % 30)}%`} />
            <SkeletonLine width="12%" />
            <SkeletonLine width="10%" />
          </div>
        ))}
      </div>
    </div>
  );
}
