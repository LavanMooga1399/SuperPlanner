/**
 * Small shared pieces of the quality screens: people and supplier names (records carry ids), item cells, the
 * signature-dialog state of a record page, and formatting of quality values.
 */
import { useEffect, useState, useSyncExternalStore } from "react";
import { Link } from "react-router";
import { listMembers, listSuppliers } from "../api/clientM2";
import type { QaItemRef } from "../api/typesM7";
import { useAccess } from "../lib/permissions";
import { mfgPaths } from "../lib/paths";
import { fmtDate } from "../lib/format";
import { formatDateTime, formatNumber } from "../../lib/locale";
import { t } from "../../lib/i18n";

// ---------------------------------------------------------------- names (module caches, one request per page load)
let people: Map<string, string> | null = null;
let suppliers: Map<string, string> | null = null;
let ver = 0;
const listeners = new Set<() => void>();
const bump = () => {
  ver++;
  listeners.forEach((l) => l());
};
let peopleStarted = false;
let suppliersStarted = false;

function loadPeople(_owner: boolean) {
  // members are readable by owners and plant admins; other roles fall back to the names records carry (`people`)
  if (peopleStarted) return;
  peopleStarted = true;
  listMembers()
    .then((r) => {
      people = new Map([...(people ?? new Map<string, string>()), ...r.items.map((m) => [m.user.id, m.user.display_name || m.user.email] as [string, string])]);
      bump();
    })
    .catch(() => undefined);
}
function loadSuppliers() {
  if (suppliersStarted) return;
  suppliersStarted = true;
  listSuppliers({})
    .then((r) => {
      suppliers = new Map(r.items.map((s) => [s.id, `${s.code} ${s.name}`]));
      bump();
    })
    .catch(() => undefined);
}
const subscribe = (l: () => void) => {
  listeners.add(l);
  return () => listeners.delete(l);
};

/** Names that a record or list carries (`people` map, `actor_name`): kept for every person-name lookup. */
export function rememberPeople(map: Record<string, string | null | undefined> | null | undefined): void {
  if (!map) return;
  const next = new Map(people ?? []);
  let changed = false;
  for (const [id, name] of Object.entries(map))
    if (name && next.get(id) !== name) {
      next.set(id, name);
      changed = true;
    }
  if (changed) {
    people = next;
    bump();
  }
}

/** Name of a person by user id: "You", a member's name (owners see the member list), else the id. */
export function usePersonName(): (id: string | null | undefined) => string {
  const access = useAccess();
  useSyncExternalStore(subscribe, () => ver);
  useEffect(() => loadPeople(access.isOwner), [access.isOwner]);
  const me = access.me?.user_id;
  return (id) => (!id ? "" : id === me ? t("qa.common.str.you") : (people?.get(id) ?? id));
}

export function useSupplierName(): (id: string | null | undefined) => string {
  useSyncExternalStore(subscribe, () => ver);
  useEffect(() => loadSuppliers(), []);
  return (id) => (!id ? "" : (suppliers?.get(id) ?? id));
}

export function useSuppliersList(): { id: string; label: string }[] {
  useSyncExternalStore(subscribe, () => ver);
  useEffect(() => loadSuppliers(), []);
  return suppliers ? [...suppliers.entries()].map(([id, label]) => ({ id, label })) : [];
}

// ---------------------------------------------------------------- cells
export function ItemCell({ item, id }: { item: QaItemRef | null | undefined; id?: string | null }) {
  if (!item) return id ? <span className="mono faint">{id}</span> : <span className="faint">—</span>;
  return (
    <span className="mfg-ellipsis" title={`${item.part_number} ${item.revision ? `rev ${item.revision}` : ""} ${item.name}`}>
      <Link to={mfgPaths.item(item.id)} className="mono" onClick={(e) => e.stopPropagation()} tabIndex={-1}>
        {item.part_number}
      </Link>{" "}
      <span className="muted">{item.name}</span>
    </span>
  );
}
export const itemText = (item: QaItemRef | null | undefined) => (item ? `${item.part_number} ${item.name}` : "");

/** Due time with an overdue marker in words (never colour alone). */
export function DueCell({ at, overdue }: { at: string | null | undefined; overdue?: boolean }) {
  if (!at) return <span className="faint">—</span>;
  return (
    <span className={overdue ? "row" : undefined} style={overdue ? { gap: 4 } : undefined}>
      <span>{at.length <= 10 ? formatDay10(at) : formatDateTime(at)}</span>
      {overdue ? <span className="badge danger">{t("qa.common.str.overdue")}</span> : null}
    </span>
  );
}
const formatDay10 = (d: string) => fmtDate(d);

export const fmtQ = (v: number | null | undefined) => formatNumber(v ?? null);

/** New client batch id for results (5.2: replay-safe). */
export function batchId(prefix: string): string {
  return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

/** Re-render each minute (due / overdue states). */
export function useMinuteTick(): number {
  const [n, setN] = useState(0);
  useEffect(() => {
    const id = window.setInterval(() => setN((x) => x + 1), 60_000);
    return () => window.clearInterval(id);
  }, []);
  return n;
}
