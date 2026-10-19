import { useMemo } from "react";
import type { AnyDraft, IntakeNote, Question } from "../api/types";
import { segmentText, type SpanRef } from "../lib/codepoints";
import { pathLabel } from "../lib/paths";
import { useIntake } from "../state/IntakeContext";

/**
 * The original text with the phrases the draft was read from highlighted (PHASE2.md 3.3). Each highlight is
 * a focusable `mark`; hovering or focusing it highlights the matching draft field, and the reverse.
 * Offsets are code points (lib/codepoints).
 */
export function SourceText({ text, draft, notes, questions }: { text: string; draft: AnyDraft; notes: IntakeNote[]; questions: Question[] }) {
  const { activePath, setActivePath } = useIntake();
  const segments = useMemo(() => {
    const spans: SpanRef[] = [];
    for (const [path, p] of Object.entries(draft.provenance)) {
      if (p.span) spans.push({ start: p.span.start, end: p.span.end, id: path, label: pathLabel(draft, path) });
    }
    notes.forEach((n, i) => {
      if (n.span) spans.push({ start: n.span.start, end: n.span.end, id: `note:${i}`, label: n.message });
    });
    for (const q of questions) {
      if (q.span && q.path) spans.push({ start: q.span.start, end: q.span.end, id: q.path, label: q.prompt });
    }
    return segmentText(text, spans);
  }, [text, draft, notes, questions]);

  const focusField = (path: string) => {
    const el = document.querySelector(`[data-intake-path="${CSS.escape(path)}"]`);
    if (el && "scrollIntoView" in el) (el as HTMLElement).scrollIntoView({ block: "nearest", behavior: "smooth" });
  };

  return (
    <section className="card" aria-labelledby="intake-source-title">
      <div className="card-header">
        <h3 id="intake-source-title" style={{ margin: 0 }}>
          Your text
        </h3>
        <span className="small muted">Highlighted parts were used in the draft</span>
      </div>
      <div className="card-body source-text" data-testid="intake-source">
        {segments.map((s, i) =>
          s.span ? (
            <mark
              key={i}
              tabIndex={0}
              className={activePath === s.span.id ? "active" : ""}
              data-path={s.span.id}
              aria-label={`"${s.text}", used for ${s.span.label}`}
              title={s.span.label}
              onMouseEnter={() => setActivePath(s.span!.id)}
              onMouseLeave={() => setActivePath(null)}
              onFocus={() => {
                setActivePath(s.span!.id);
                focusField(s.span!.id);
              }}
              onBlur={() => setActivePath(null)}
            >
              {s.text}
            </mark>
          ) : (
            <span key={i}>{s.text}</span>
          ),
        )}
      </div>
    </section>
  );
}
