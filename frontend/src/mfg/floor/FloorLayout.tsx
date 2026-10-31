/**
 * Tablet shell of `/mfg/floor/**` (M4 12): one column, >= 48 px targets, works at 1024x768.
 * - Scan field always focused: keyboard-wedge scanners "type" a code and Enter. Any key typed while focus is not in
 *   a text field goes to the scan field; after a button press focus returns to it.
 * - Pages can claim scans first (`useScanHandler`), e.g. the operation screen takes serial numbers; otherwise the
 *   code is resolved by #200 and opened (operation, work order, line, batch load), or an operator badge is added to
 *   the crew of this device.
 * - Logins (15 Q1): a shared station account adds operators by badge scan (`OP:<code>`); they are sent with every
 *   action. A personal login linked to an operator needs no badge.
 * - Offline: "N actions waiting to sync" and the rejected ones with their reason.
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link, Outlet, useNavigate } from "react-router";
import { Icon } from "../../components/Icon";
import { listOperators } from "../api/client";
import { floorScan } from "../api/clientM4";
import { listWoOperationsM4 } from "../api/clientM4";
import type { ScanResult } from "../api/typesM4";
import { mfgPaths } from "../lib/paths";
import { AccessProvider, useAccess } from "../lib/permissions";
import { useLoad } from "../lib/useMfg";
import { currentWorkspace } from "../lib/workspace";
import { floorErrorText } from "./floorText";
import { discardFailed, retryFailed, syncNow, useAutoSync, useFloorQueue } from "./offlineQueue";

export interface CrewMember {
  id?: string;
  code: string;
  name?: string;
  at: string;
}

/** A page's scan claim: return true when the code was handled. `resolved` is null for unknown codes. */
export type ScanHandler = (code: string, resolved: ScanResult | null) => boolean | Promise<boolean>;

interface FloorCtx {
  lineId: string | null;
  setLineId(id: string | null): void;
  crew: CrewMember[];
  addCrew(m: CrewMember): void;
  removeCrew(code: string): void;
  clearCrew(): void;
  /** operator of a personal login (operator.user_id = me), if any */
  me: { id: string; code: string; name: string } | null;
  pushHandler(h: ScanHandler): () => void;
  flash(msg: string, tone?: "ok" | "warn" | "danger"): void;
  focusScan(): void;
}

const Ctx = createContext<FloorCtx | null>(null);

export function useFloor(): FloorCtx {
  const c = useContext(Ctx);
  if (!c) throw new Error("useFloor outside FloorLayout");
  return c;
}

export function useScanHandler(h: ScanHandler, deps: unknown[]) {
  const { pushHandler } = useFloor();
  const ref = useRef(h);
  ref.current = h;
  useEffect(() => pushHandler((c, r) => ref.current(c, r)), // eslint-disable-next-line react-hooks/exhaustive-deps
  [pushHandler, ...deps]);
}

const lineKey = () => `sp.floor.line.${currentWorkspace() ?? "own"}`;
const crewKey = () => `sp.floor.crew.${currentWorkspace() ?? "own"}`;
const CREW_MAX_AGE_MS = 14 * 3600 * 1000; // a badge sign-in lasts one long shift on a shared tablet

function readJson<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

export function rememberedLine(): string | null {
  try {
    return localStorage.getItem(lineKey());
  } catch {
    return null;
  }
}

/** Operator codes / ids to send with an action (station badges; empty for a personal login, the server knows). */
export function crewForEvent(crew: CrewMember[]): { operator_codes?: string[]; operator_ids?: string[] } {
  if (!crew.length) return {};
  const ids = crew.filter((c) => c.id).map((c) => c.id!);
  if (ids.length === crew.length) return { operator_ids: ids };
  return { operator_codes: crew.map((c) => c.code) };
}

function FloorShell({ children }: { children: ReactNode }) {
  const navigate = useNavigate();
  const access = useAccess();
  const { online } = useAutoSync();
  const queue = useFloorQueue();
  const [lineId, setLineIdState] = useState<string | null>(() => rememberedLine());
  const [crew, setCrew] = useState<CrewMember[]>(() => readJson<CrewMember[]>(crewKey(), []).filter((c) => Date.now() - Date.parse(c.at) < CREW_MAX_AGE_MS));
  const [msg, setMsg] = useState<{ text: string; tone: string } | null>(null);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [showQueue, setShowQueue] = useState(false);
  const scanRef = useRef<HTMLInputElement>(null);
  const handlers = useRef<ScanHandler[]>([]);
  const ops = useLoad((signal) => listOperators({ active: true }, signal), []);
  const meOp = useMemo(() => {
    const uid = access.me?.user_id;
    if (!uid) return null;
    const o = (ops.data?.items ?? []).find((x) => (x as { user_id?: string | null }).user_id === uid);
    return o ? { id: o.id, code: o.code, name: o.name } : null;
  }, [ops.data, access.me]);

  const setLineId = useCallback((id: string | null) => {
    setLineIdState(id);
    try {
      if (id) localStorage.setItem(lineKey(), id);
      else localStorage.removeItem(lineKey());
    } catch {
      /* ignore */
    }
  }, []);
  const saveCrew = (next: CrewMember[]) => {
    setCrew(next);
    try {
      localStorage.setItem(crewKey(), JSON.stringify(next));
    } catch {
      /* ignore */
    }
  };
  const flash = useCallback((text: string, tone: "ok" | "warn" | "danger" = "ok") => setMsg({ text, tone }), []);
  useEffect(() => {
    if (!msg) return;
    const t = window.setTimeout(() => setMsg(null), msg.tone === "danger" ? 9000 : 4000);
    return () => window.clearTimeout(t);
  }, [msg]);
  const focusScan = useCallback(() => scanRef.current?.focus({ preventScroll: true }), []);
  const pushHandler = useCallback((h: ScanHandler) => {
    handlers.current = [h, ...handlers.current];
    return () => {
      handlers.current = handlers.current.filter((x) => x !== h);
    };
  }, []);

  // keep the scan field focused: printable keys typed outside text fields go there; refocus after clicks
  useEffect(() => {
    const isText = (el: Element | null) =>
      !!el && (el.tagName === "TEXTAREA" || el.tagName === "SELECT" || (el.tagName === "INPUT" && !["checkbox", "radio", "button", "submit"].includes((el as HTMLInputElement).type)) || (el as HTMLElement).isContentEditable);
    const onKey = (e: KeyboardEvent) => {
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      if (document.querySelector("[role=dialog]")) return;
      if (isText(document.activeElement)) return;
      if (e.key.length === 1) focusScan();
    };
    const onFocusOut = () =>
      window.setTimeout(() => {
        const a = document.activeElement;
        if (document.querySelector("[role=dialog]")) return;
        if (!a || a === document.body || (!isText(a) && a.tagName !== "A")) focusScan();
      }, 0);
    document.addEventListener("keydown", onKey, true);
    document.addEventListener("focusout", onFocusOut);
    focusScan();
    return () => {
      document.removeEventListener("keydown", onKey, true);
      document.removeEventListener("focusout", onFocusOut);
    };
  }, [focusScan]);

  const addCrew = (m: CrewMember) => {
    if (crew.some((c) => c.code.toUpperCase() === m.code.toUpperCase())) {
      flash(`${m.name ?? m.code} is already signed in on this tablet`, "warn");
      return;
    }
    saveCrew([...crew, m]);
    flash(`${m.name ?? m.code} signed in on this tablet`);
  };

  const openWo = async (woId: string) => {
    const ops = await listWoOperationsM4(woId);
    const real = ops.items.filter((o) => o.id);
    const next = real.find((o) => o.status === "running" || o.status === "setup" || o.status === "paused") ?? real.find((o) => o.status === "ready" || o.status === "pending");
    if (next) navigate(mfgPaths.floorOp(next.id));
    else navigate(mfgPaths.floorWo(woId));
  };

  const handleScan = async (raw: string) => {
    const text = raw.trim();
    if (!text) return;
    setBusy(true);
    try {
      let resolved: ScanResult | null = null;
      let unknown = false;
      // badge codes are cheap to recognise locally; everything else asks the server
      try {
        resolved = await floorScan(text);
      } catch (e) {
        if ((e as { code?: string }).code === "FLR_SCAN_UNKNOWN" || (e as { status?: number }).status === 404) unknown = true;
        else throw e;
      }
      for (const h of handlers.current) if (await h(text, resolved)) return;
      if (unknown || !resolved) {
        flash(`Unknown barcode "${text}"`, "danger");
        return;
      }
      switch (resolved.type) {
        case "operator":
          addCrew({ id: resolved.id, code: String(resolved.context?.code ?? text.replace(/^OP:/i, "")), name: resolved.label, at: new Date().toISOString() });
          return;
        case "line":
          setLineId(resolved.id);
          navigate(mfgPaths.floorLine(resolved.id));
          return;
        case "operation":
          navigate(mfgPaths.floorOp(resolved.id));
          return;
        case "work_order":
          await openWo(resolved.id);
          return;
        case "batch_load": {
          const lid = resolved.context?.line_id ?? lineId;
          if (lid) navigate(`${mfgPaths.floorBatch(lid)}?load=${encodeURIComponent(resolved.id)}`);
          return;
        }
        default:
          flash(`${resolved.label}${resolved.link ? "" : ""}`, "warn");
      }
    } catch (e) {
      flash(floorErrorText(e), "danger");
    } finally {
      setBusy(false);
      setCode("");
      focusScan();
    }
  };

  const ctx: FloorCtx = {
    lineId,
    setLineId,
    crew,
    addCrew,
    removeCrew: (c) => saveCrew(crew.filter((x) => x.code !== c)),
    clearCrew: () => saveCrew([]),
    me: meOp,
    pushHandler,
    flash,
    focusScan,
  };
  const waiting = queue.pending.length;
  const canSupervise = access.can("floor_supervise") || access.can("replan_manage");

  return (
    <Ctx.Provider value={ctx}>
      <div className="floor" data-testid="floor-shell">
        <header className="floor-head">
          <Link to={lineId ? mfgPaths.floorLine(lineId) : mfgPaths.floor()} className="floor-home" aria-label="Floor home">
            <Icon name="factory" size={22} />
            <span>Floor</span>
          </Link>
          <form
            className="floor-scan-form"
            onSubmit={(e) => {
              e.preventDefault();
              void handleScan(code);
            }}
          >
            <label htmlFor="floor-scan" className="sr-only">
              Scan a barcode
            </label>
            <Icon name="zoom-in" size={20} />
            <input
              id="floor-scan"
              ref={scanRef}
              className="floor-scan"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              placeholder="Scan or type a traveller, operation, badge or line"
              autoComplete="off"
              autoCapitalize="characters"
              spellCheck={false}
              enterKeyHint="go"
              disabled={busy}
              data-testid="floor-scan"
            />
          </form>
          <div className="floor-head-side">
            {!online ? (
              <span className="badge warn" role="status">
                <Icon name="alert" /> Offline
              </span>
            ) : null}
            {waiting || queue.failed.length ? (
              <button type="button" className={`btn floor-sync ${queue.failed.length ? "danger" : ""}`} onClick={() => setShowQueue((v) => !v)} data-testid="floor-sync-pending" data-count={waiting} data-failed={queue.failed.length} aria-expanded={showQueue}>
                <Icon name={queue.syncing ? "loader" : "refresh"} />
                {waiting ? `${waiting} action${waiting === 1 ? "" : "s"} waiting to sync` : ""}
                {waiting && queue.failed.length ? " · " : ""}
                {queue.failed.length ? `${queue.failed.length} need${queue.failed.length === 1 ? "s" : ""} attention` : ""}
              </button>
            ) : null}
            {canSupervise ? (
              <Link className="btn ghost" to={mfgPaths.floorOverview()}>
                Overview
              </Link>
            ) : null}
          </div>
        </header>
        <CrewBar />
        {msg ? (
          <div className={`floor-flash ${msg.tone}`} role={msg.tone === "danger" ? "alert" : "status"} data-testid="floor-flash">
            <Icon name={msg.tone === "ok" ? "check" : "alert"} /> {msg.text}
          </div>
        ) : null}
        {showQueue ? (
          <section className="floor-card" data-testid="floor-sync-list">
            <div className="row wrap" style={{ justifyContent: "space-between" }}>
              <h2 style={{ margin: 0 }}>Actions on this tablet</h2>
              <button type="button" className="btn floor-btn" onClick={() => void syncNow()} disabled={!waiting || queue.syncing}>
                <Icon name="refresh" /> Sync now
              </button>
            </div>
            {queue.pending.map((a) => (
              <div key={a.id} className="floor-sync-item">
                <Icon name="clock" /> {a.label} <span className="faint small">saved {new Date(a.created_at).toLocaleTimeString()}</span>
              </div>
            ))}
            {queue.failed.map((a) => (
              <div key={a.id} className="floor-sync-item danger" data-testid="floor-sync-failed">
                <Icon name="alert" /> {a.label}: <strong>{a.error?.message}</strong>
                <span className="row" style={{ marginLeft: "auto" }}>
                  <button type="button" className="btn" onClick={() => retryFailed(a.id)}>
                    Try again
                  </button>
                  <button type="button" className="btn ghost" onClick={() => discardFailed(a.id)}>
                    Discard
                  </button>
                </span>
              </div>
            ))}
          </section>
        ) : null}
        <main className="floor-main">{children}</main>
      </div>
    </Ctx.Provider>
  );
}

function CrewBar() {
  const { crew, removeCrew, clearCrew, me } = useFloor();
  return (
    <div className="floor-crew" data-testid="floor-crew" data-count={crew.length}>
      <Icon name="briefcase" />
      {me && !crew.length ? (
        <span>
          Signed in as <strong>{me.name}</strong> ({me.code})
        </span>
      ) : crew.length ? (
        <>
          <span className="faint">Working:</span>
          {crew.map((c) => (
            <span key={c.code} className="floor-crew-chip" data-code={c.code}>
              {c.name ?? c.code}
              <button type="button" className="btn ghost icon" aria-label={`Sign out ${c.name ?? c.code}`} onClick={() => removeCrew(c.code)}>
                <Icon name="x" />
              </button>
            </span>
          ))}
          {crew.length > 1 ? (
            <button type="button" className="btn ghost" onClick={clearCrew}>
              Sign out all
            </button>
          ) : null}
        </>
      ) : (
        <span className="faint">Scan your operator badge to sign your actions (or sign in with your own account).</span>
      )}
    </div>
  );
}

/** `/mfg/floor/**` tablet routes. */
export function FloorLayout() {
  useEffect(() => {
    document.title = "Floor - SuperPlanner";
    document.body.classList.add("floor-mode");
    return () => {
      document.title = "SuperPlanner Studio";
      document.body.classList.remove("floor-mode");
    };
  }, []);
  return (
    <AccessProvider>
      <FloorShell>
        <Outlet />
      </FloorShell>
    </AccessProvider>
  );
}
