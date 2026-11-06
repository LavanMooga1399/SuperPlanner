/**
 * Assistant answers (M6 1.5): a markdown subset - paragraphs, `-`/`*`/`1.` lists, **bold**, `code` and fenced code
 * blocks - rendered as React text nodes only (no HTML parsing, no `dangerouslySetInnerHTML`, no images). Links are
 * never taken from the text: markdown links, bare URLs and HTML stay plain text. `[R7]` markers become internal
 * links only when the server returned citation R7 (Q2 for quick explanations) for this answer with an internal path (`/mfg/...`); markers the
 * server did not issue are dropped (the server strips them too, T-A4).
 */
import type { ReactNode } from "react";
import { Link } from "react-router";
import type { Citation, QuickExplanation } from "../api/typesM6";

/** Only same-origin app paths (no scheme, no `//host`, no backslash tricks). */
export function safeInternalLink(link: string | null | undefined): string | null {
  if (typeof link !== "string") return null;
  if (!link.startsWith("/") || link.startsWith("//") || link.includes("\\")) return null;
  if (/[\u0000-\u001f\s]/.test(link)) return null;
  if (/^\/api\//.test(link)) return null;
  return link;
}

const MARKER = /\[([RQ]\d{1,4})\]/g;

function CitationLink({ c, onNavigate }: { c: Citation; onNavigate?: () => void }) {
  const to = safeInternalLink(c.link);
  const text = `${c.ref}`;
  if (!to)
    return (
      <span className="asst-cite" title={c.label} data-testid="asst-cite" data-ref={c.ref}>
        [{text}]
      </span>
    );
  return (
    <Link to={to} className="asst-cite" title={`${c.label} (opens the record)`} aria-label={`Source ${c.ref}: ${c.label}`} data-testid="asst-cite" data-ref={c.ref} onClick={onNavigate}>
      [{text}]
    </Link>
  );
}

/** Inline: **bold**, `code`, [Rn] markers; everything else literal text. */
function inline(text: string, cites: Map<string, Citation>, key: string, onNavigate?: () => void): ReactNode[] {
  const out: ReactNode[] = [];
  // split by code spans first (markers inside code stay literal)
  const parts = text.split(/(`[^`\n]+`)/g);
  parts.forEach((part, i) => {
    if (part.startsWith("`") && part.endsWith("`") && part.length > 2) {
      out.push(<code key={`${key}c${i}`}>{part.slice(1, -1)}</code>);
      return;
    }
    const bolds = part.split(/(\*\*[^*\n]+\*\*)/g);
    bolds.forEach((b, j) => {
      const isBold = b.startsWith("**") && b.endsWith("**") && b.length > 4;
      const body = isBold ? b.slice(2, -2) : b;
      const nodes: ReactNode[] = [];
      let last = 0;
      for (const m of body.matchAll(MARKER)) {
        const at = m.index ?? 0;
        if (at > last) nodes.push(body.slice(last, at));
        const c = cites.get(m[1]);
        if (c) nodes.push(<CitationLink key={`${key}r${i}-${j}-${at}`} c={c} onNavigate={onNavigate} />);
        last = at + m[0].length;
      }
      if (last < body.length) nodes.push(body.slice(last));
      if (isBold) out.push(<strong key={`${key}b${i}-${j}`}>{nodes}</strong>);
      else out.push(...nodes.map((n, k) => (typeof n === "string" ? <span key={`${key}t${i}-${j}-${k}`}>{n}</span> : n)));
    });
  });
  return out;
}

type Block = { kind: "p"; text: string } | { kind: "ul" | "ol"; items: string[] } | { kind: "code"; text: string };

export function parseBlocks(src: string): Block[] {
  const lines = src.replace(/\r\n?/g, "\n").split("\n");
  const blocks: Block[] = [];
  let para: string[] = [];
  let list: { kind: "ul" | "ol"; items: string[] } | null = null;
  const flush = () => {
    if (para.length) blocks.push({ kind: "p", text: para.join(" ") });
    para = [];
    if (list) blocks.push(list);
    list = null;
  };
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (/^\s*```/.test(line)) {
      flush();
      const code: string[] = [];
      i++;
      while (i < lines.length && !/^\s*```/.test(lines[i])) code.push(lines[i++]);
      blocks.push({ kind: "code", text: code.join("\n") });
      continue;
    }
    const ul = line.match(/^\s*[-*]\s+(.*)$/);
    const ol = line.match(/^\s*\d+[.)]\s+(.*)$/);
    if (ul || ol) {
      const kind = ul ? "ul" : "ol";
      if (para.length) {
        blocks.push({ kind: "p", text: para.join(" ") });
        para = [];
      }
      if (!list || list.kind !== kind) {
        if (list) blocks.push(list);
        list = { kind, items: [] };
      }
      list.items.push((ul ?? ol)![1]);
      continue;
    }
    if (!line.trim()) {
      flush();
      continue;
    }
    if (list && /^\s{2,}\S/.test(line)) {
      list.items[list.items.length - 1] += ` ${line.trim()}`;
      continue;
    }
    if (list) {
      blocks.push(list);
      list = null;
    }
    // headings are shown as bold paragraphs (not in the subset, but harmless)
    para.push(line.replace(/^#{1,6}\s+/, ""));
  }
  flush();
  return blocks;
}

export function AnswerText({ text, citations, onNavigate, testId = "asst-answer" }: { text: string; citations: Citation[]; onNavigate?: () => void; testId?: string }) {
  const cites = new Map(citations.map((c) => [c.ref, c]));
  const blocks = parseBlocks(text);
  return (
    <div className="asst-answer" data-testid={testId}>
      {blocks.map((b, i) => {
        if (b.kind === "code") return <pre key={i}><code>{b.text}</code></pre>;
        if (b.kind === "p") return <p key={i}>{inline(b.text, cites, `p${i}`, onNavigate)}</p>;
        const items = b.items.map((it, j) => <li key={j}>{inline(it, cites, `l${i}-${j}`, onNavigate)}</li>);
        return b.kind === "ul" ? <ul key={i}>{items}</ul> : <ol key={i}>{items}</ol>;
      })}
    </div>
  );
}

/** The sources list under an answer: label as text, link only when internal. */
export function CitationList({ citations, onNavigate }: { citations: Citation[]; onNavigate?: () => void }) {
  if (!citations.length) return null;
  return (
    <details className="asst-sources" data-testid="asst-sources">
      <summary>Sources ({citations.length})</summary>
      <ol>
        {citations.map((c) => {
          const to = safeInternalLink(c.link);
          return (
            <li key={c.ref} data-testid="asst-source" data-ref={c.ref}>
              <span className="mono small">{c.ref}</span>{" "}
              {to ? (
                <Link to={to} onClick={onNavigate}>
                  {c.label}
                </Link>
              ) : (
                <span>{c.label}</span>
              )}{" "}
              <span className="muted small">({c.type.replace(/_/g, " ")})</span>
            </li>
          );
        })}
      </ol>
    </details>
  );
}

/** A quick explanation (1.7): sections of plain-text items, each with its citation refs as internal links. */
export function QuickView({ q, onNavigate }: { q: QuickExplanation; onNavigate?: () => void }) {
  const cites = new Map(q.citations.map((c) => [c.ref, c]));
  const sections = q.sections.filter((s) => s.items.length);
  if (!sections.length)
    return (
      <p className="muted" style={{ margin: 0 }} data-testid="asst-quick-empty">
        {q.empty_message || "Nothing to explain here."}
      </p>
    );
  return (
    <div className="asst-answer" data-testid="asst-quick-answer">
      {sections.map((s, i) => (
        <section key={i}>
          <strong className="small">{s.title}</strong>
          <ul>
            {s.items.map((it, j) => (
              <li key={j}>
                {it.text}{" "}
                {it.refs.map((r) => {
                  const c = cites.get(r);
                  return c ? <CitationLink key={r} c={c} onNavigate={onNavigate} /> : null;
                })}
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}
