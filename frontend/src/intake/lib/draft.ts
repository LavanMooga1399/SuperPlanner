/** Small pure helpers for editing drafts in the browser (keys, provenance, client-side checks). */
import type { AnyDraft, DraftAmount, DraftDuration, FinanceDraft, Provenance, Question, ScheduleDraft } from "../api/types";

const KEY_RE = /^[a-z][a-z0-9_]{0,31}$/;

/** Next free key "<prefix><n>" (e.g. t6) for a collection; always matches the draft key pattern. */
export function nextKey(prefix: string, used: Iterable<string>): string {
  const set = new Set(used);
  let n = set.size + 1;
  while (set.has(`${prefix}${n}`)) n++;
  const key = `${prefix}${n}`;
  return KEY_RE.test(key) ? key : `x${n}`;
}

/** Resource key from a name: r_<slug>, unique. */
export function resourceKey(name: string, used: Iterable<string>): string {
  const set = new Set(used);
  const slug = name
    .toLowerCase()
    .normalize("NFKD")
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 24);
  let base = slug ? `r_${slug}` : "r_new";
  if (!KEY_RE.test(base)) base = "r_new";
  if (!set.has(base)) return base;
  let i = 2;
  while (set.has(`${base}_${i}`)) i++;
  return `${base}_${i}`;
}

export const EDIT_PROVENANCE: Provenance = { source: "edit", confidence: 1 };

/** Mark paths as edited by the user (PHASE2.md 2.3: the UI sets source "edit", confidence 1). */
export function markEdited<D extends AnyDraft>(draft: D, paths: string[]): D {
  if (!paths.length) return draft;
  const provenance = { ...draft.provenance };
  for (const p of paths) provenance[p] = { ...EDIT_PROVENANCE };
  return { ...draft, provenance };
}

/** Drop provenance entries of a removed item (paths under `/<collection>/<key>/`). */
export function dropProvenance<D extends AnyDraft>(draft: D, prefix: string): D {
  const provenance: Record<string, Provenance> = {};
  for (const [k, v] of Object.entries(draft.provenance)) if (!k.startsWith(prefix)) provenance[k] = v;
  return { ...draft, provenance };
}

export interface DraftProblem {
  path: string;
  message: string;
}

function checkDuration(d: DraftDuration | null, path: string, out: DraftProblem[]) {
  if (!d) return;
  const vals = [d.optimistic, d.likely, d.pessimistic];
  if (vals.some((v) => !Number.isFinite(v) || v <= 0 || v > 10000)) {
    out.push({ path, message: "Each duration must be a number above 0 (at most 10,000)." });
  } else if (!(d.optimistic <= d.likely && d.likely <= d.pessimistic)) {
    out.push({ path, message: "Shortest must not be above likely, and likely not above longest." });
  }
}

function checkAmount(a: DraftAmount | null, path: string, out: DraftProblem[]) {
  if (!a) return;
  if (!Number.isFinite(a.low) || !Number.isFinite(a.high) || a.low < 0 || a.high < 0) {
    out.push({ path, message: "Enter an amount of 0 or more." });
  } else if (a.low > a.high) {
    out.push({ path, message: "The first amount of a range must not be above the second." });
  }
}

/** Checks the server would reject with 422; the editor shows them next to the field and waits. */
export function draftProblems(draft: AnyDraft): DraftProblem[] {
  const out: DraftProblem[] = [];
  if (!draft.name.trim()) out.push({ path: "/name", message: "Give the plan a name." });
  if (draft.domain === "schedule") {
    for (const t of draft.tasks) {
      if (!t.name.trim()) out.push({ path: `/tasks/${t.key}/name`, message: "Give every step a name." });
      checkDuration(t.duration, `/tasks/${t.key}/duration`, out);
    }
    for (const r of draft.resources) {
      if (!r.name.trim()) out.push({ path: `/resources/${r.key}/name`, message: "Give every resource a name." });
    }
  } else {
    const f = draft as FinanceDraft;
    const lists: [string, { key: string; name: string }[]][] = [
      ["incomes", f.incomes],
      ["expenses", f.expenses],
      ["debts", f.debts],
      ["holdings", f.holdings],
      ["goals", f.goals],
    ];
    for (const [c, items] of lists) {
      for (const i of items) if (!i.name.trim()) out.push({ path: `/${c}/${i.key}/name`, message: "Give every row a name." });
    }
    f.incomes.forEach((i) => checkAmount(i.amount, `/incomes/${i.key}/amount`, out));
    f.expenses.forEach((i) => checkAmount(i.amount, `/expenses/${i.key}/amount`, out));
    f.debts.forEach((i) => {
      checkAmount(i.balance, `/debts/${i.key}/balance`, out);
      checkAmount(i.emi, `/debts/${i.key}/emi`, out);
    });
    f.holdings.forEach((i) => checkAmount(i.amount, `/holdings/${i.key}/amount`, out));
    f.goals.forEach((i) => checkAmount(i.target, `/goals/${i.key}/target`, out));
  }
  return out;
}

export function requiredOpen(questions: Question[]): Question[] {
  return questions.filter((q) => q.required);
}

export function isScheduleDraft(d: AnyDraft): d is ScheduleDraft {
  return d.domain === "schedule";
}
