/**
 * Shared pieces of the M10 screens (eDHR, deviations, CoA, labels, UDI, validation): status chips (icon + text, never
 * colour alone), exception and section names, value formatting for assembled record content (dates never ISO), age
 * of a review, hash display and small helpers for downloads and previews.
 */
import { useEffect, useState, type ReactNode } from "react";
import { Icon, type IconName } from "../../components/Icon";
import { hasKey, plural, t, type StringKey } from "../../lib/i18n";
import { formatDateTime, formatDay, formatNumber } from "../../lib/locale";
import { saveBlob, type DownloadedFile } from "../api/client";
import type { DhrDisposition, DhrSectionKey, ExcSeverity } from "../api/typesM10";
import "./gxp.css";

export type Tone = "ok" | "warn" | "danger" | "info" | "accent";
export interface ChipDef {
  label: StringKey;
  tone: Tone;
  icon: IconName;
}

export function GxpChip({ def, value, testId }: { def: ChipDef | undefined; value: string; testId?: string }) {
  return (
    <span className={`badge ${def?.tone ?? "info"}`} data-status={value} data-testid={testId}>
      <Icon name={def?.icon ?? "info"} />
      {def ? t(def.label) : value}
    </span>
  );
}
export const chipText = (map: Record<string, ChipDef>, v: string | null | undefined) => (v ? (map[v] ? t(map[v].label) : v) : "");

export const DHR_STATUS: Record<string, ChipDef> = {
  open: { label: "gxp.dhr.status.open", tone: "info", icon: "circle" },
  assembled: { label: "gxp.dhr.status.assembled", tone: "warn", icon: "flag" },
  in_review: { label: "gxp.dhr.status.in_review", tone: "accent", icon: "eye" },
  released: { label: "gxp.dhr.status.released", tone: "ok", icon: "check" },
  rejected: { label: "gxp.dhr.status.rejected", tone: "danger", icon: "x" },
};
export const DhrStatusChip = ({ s }: { s: string }) => <GxpChip def={DHR_STATUS[s]} value={s} testId="dhr-status" />;

export const SEV: Record<ExcSeverity, ChipDef> = {
  major: { label: "gxp.sev.major", tone: "danger", icon: "alert" },
  minor: { label: "gxp.sev.minor", tone: "warn", icon: "flag" },
  info: { label: "gxp.sev.info", tone: "info", icon: "info" },
};
export const SevChip = ({ s }: { s: ExcSeverity }) => <GxpChip def={SEV[s]} value={s} testId="dhr-sev" />;

export const DISPOSITION: Record<DhrDisposition, ChipDef> = {
  accepted: { label: "gxp.disp.accepted", tone: "ok", icon: "check" },
  ncr: { label: "gxp.disp.ncr", tone: "accent", icon: "alert" },
  deviation: { label: "gxp.disp.deviation", tone: "accent", icon: "file" },
};
export const dispositionText = (d: string) => chipText(DISPOSITION, d);

export const DOC_STATE: Record<string, ChipDef> = {
  draft: { label: "gxp.doc.draft", tone: "warn", icon: "file" },
  in_change: { label: "gxp.doc.in_change", tone: "accent", icon: "lock" },
  approved: { label: "gxp.doc.approved", tone: "ok", icon: "check" },
  obsolete: { label: "gxp.doc.obsolete", tone: "info", icon: "ban" },
  closed: { label: "gxp.doc.closed", tone: "info", icon: "check" },
  cancelled: { label: "gxp.doc.cancelled", tone: "info", icon: "ban" },
  void: { label: "gxp.doc.void", tone: "danger", icon: "x" },
  building: { label: "gxp.doc.building", tone: "accent", icon: "loader" },
  ready: { label: "gxp.doc.ready", tone: "ok", icon: "check" },
  failed: { label: "gxp.doc.failed", tone: "danger", icon: "x" },
  queued: { label: "gxp.doc.queued", tone: "info", icon: "clock" },
  running: { label: "gxp.doc.running", tone: "accent", icon: "loader" },
  completed: { label: "gxp.doc.completed", tone: "ok", icon: "check" },
};
export const DocChip = ({ s, testId }: { s: string; testId?: string }) => <GxpChip def={DOC_STATE[s]} value={s} testId={testId ?? "gxp-status"} />;

export const sectionText = (s: DhrSectionKey | string) => (hasKey(`gxp.sec.${s}`) ? t(`gxp.sec.${s}` as StringKey) : s);
export const excText = (code: string) => (hasKey(`gxp.exc.${code}`) ? t(`gxp.exc.${code}` as StringKey) : code.replace(/^DHR_/, "").replace(/_/g, " ").toLowerCase());
/** Error / blocking codes of the M10 API in words (falls back to the server message). */
export const codeText10 = (code: string, fallback?: string | null) => (hasKey(`gxp.code.${code}`) ? t(`gxp.code.${code}` as StringKey) : fallback || code);

/** Column / fact labels of assembled sections: known keys translated, others humanised. */
export function colText(key: string, label?: string | null): string {
  if (hasKey(`gxp.col.${key}`)) return t(`gxp.col.${key}` as StringKey);
  if (label) return label;
  const w = key.replace(/_id$/, "").replace(/_/g, " ");
  return w.charAt(0).toUpperCase() + w.slice(1);
}

const ISO_DAY = /^\d{4}-\d{2}-\d{2}$/;
const ISO_TS = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/;
/** A value of assembled content as text: dates in the app format, numbers grouped, booleans as words. */
export function valueText(v: unknown, unit?: string | null): string {
  if (v === null || v === undefined || v === "") return "–";
  if (typeof v === "boolean") return v ? t("gxp.str.yes") : t("gxp.str.no");
  if (typeof v === "number") return unit ? `${formatNumber(v)} ${unit}` : formatNumber(v);
  if (typeof v === "string") {
    if (ISO_DAY.test(v)) return formatDay(v);
    if (ISO_TS.test(v)) return formatDateTime(v);
    return unit ? `${v} ${unit}` : v;
  }
  if (Array.isArray(v)) return v.map((x) => valueText(x)).join(", ");
  if (typeof v === "object") {
    const o = v as Record<string, unknown>;
    if ("number" in o && typeof o.number === "string") return o.number;
    if (typeof o.part_number === "string") return [o.part_number, o.name].filter(Boolean).join(" ");
    if (typeof o.lot_code === "string") return o.lot_code;
    if ("code" in o && typeof o.code === "string") return [o.code, o.name].filter(Boolean).join(" ");
    return Object.entries(o)
      .filter(([k]) => !k.endsWith("_id") && k !== "id")
      .map(([k, x]) => `${colText(k)}: ${valueText(x)}`)
      .join("; ");
  }
  return String(v);
}

export const shortHash = (h: string | null | undefined, n = 12) => (h ? h.slice(0, n) : "–");
export function HashText({ h, n = 12 }: { h: string | null | undefined; n?: number }) {
  return (
    <span className="mono small" title={h ?? undefined}>
      {shortHash(h, n)}
    </span>
  );
}

/** Age since an instant: "5 h", "3 d" - with a word marker after the review target (never colour alone). */
export function AgeCell({ since, warnDays = 3 }: { since: string | null | undefined; warnDays?: number }) {
  if (!since) return <span className="faint">–</span>;
  const h = Math.max(0, (Date.now() - new Date(since).getTime()) / 3_600_000);
  const text = h < 24 ? t("gxp.tpl.hours", { n: Math.floor(h) }) : t("gxp.tpl.days", { n: Math.floor(h / 24) });
  const late = h / 24 >= warnDays;
  return (
    <span className={late ? "row" : undefined} style={late ? { gap: 4 } : undefined} title={formatDateTime(since)}>
      <span className="pl-num">{text}</span>
      {late ? (
        <span className="badge warn">
          <Icon name="clock" /> {t("gxp.str.aging")}
        </span>
      ) : null}
    </span>
  );
}

/** "2 major · 1 minor open" with icons; "All dispositioned" when none. */
export function OpenCounts({ major, minor, testId }: { major: number; minor: number; testId?: string }) {
  if (!major && !minor)
    return (
      <span className="badge ok" data-testid={testId}>
        <Icon name="check" /> {t("gxp.str.noneOpen")}
      </span>
    );
  return (
    <span className="row" style={{ gap: 4 }} data-testid={testId} data-major={major} data-minor={minor}>
      {major ? (
        <span className="badge danger">
          <Icon name="alert" /> {t("gxp.tpl.major", { n: major })}
        </span>
      ) : null}
      {minor ? (
        <span className="badge warn">
          <Icon name="flag" /> {t("gxp.tpl.minor", { n: minor })}
        </span>
      ) : null}
    </span>
  );
}

/** Run a download and save it; returns [busy, run, error]. */
export function useDownload(): { busy: string | null; error: unknown; run(key: string, fn: () => Promise<DownloadedFile>): Promise<void> } {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  return {
    busy,
    error,
    run: async (key, fn) => {
      setBusy(key);
      setError(null);
      try {
        saveBlob(await fn());
      } catch (e) {
        setError(e);
      } finally {
        setBusy(null);
      }
    },
  };
}

/** A server PDF shown in an iframe (blob URL, revoked on unmount). */
export function PdfFrame({ load, title, deps }: { load(): Promise<DownloadedFile>; title: string; deps: unknown[] }) {
  const [url, setUrl] = useState<string | null>(null);
  const [err, setErr] = useState<unknown>(null);
  useEffect(() => {
    let u: string | null = null;
    let live = true;
    setErr(null);
    load().then(
      (f) => {
        if (!live) return;
        u = URL.createObjectURL(f.blob.type ? f.blob : new Blob([f.blob], { type: "application/pdf" }));
        setUrl(u);
      },
      (e: unknown) => live && setErr(e),
    );
    return () => {
      live = false;
      if (u) URL.revokeObjectURL(u);
    };
  }, deps); // eslint-disable-line react-hooks/exhaustive-deps
  if (err) return <p className="muted small" role="status">{t("gxp.str.previewUnavailable")}</p>;
  if (!url) return <div className="gxp-pdf skeleton" aria-busy="true" aria-label={t("gxp.str.loadingPreview")} />;
  return <iframe className="gxp-pdf" src={url} title={title} data-testid="gxp-pdf" />;
}

/** Key facts as a definition grid (short records, dialogs). */
export function KV({ rows, testId }: { rows: [string, ReactNode][]; testId?: string }) {
  return (
    <dl className="qa-facts gxp-kv" data-testid={testId}>
      {rows.map(([k, v]) => (
        <div key={k}>
          <dt>{k}</dt>
          <dd>{v === null || v === undefined || v === "" ? <span className="faint">—</span> : v}</dd>
        </div>
      ))}
    </dl>
  );
}

export const countNoun = (n: number, one: StringKey, other: StringKey) => plural(n, t(one), t(other));
export const fmtN = (v: number | null | undefined) => (v === null || v === undefined ? "–" : formatNumber(v));
export const today = () => new Date().toISOString().slice(0, 10);

/** M10 item refs carry nullable fields; the quality item cell expects strings. */
export const qaItem = (i: { id: string; part_number?: string | null; revision?: string | null; name?: string | null } | null | undefined) =>
  i ? { id: i.id, part_number: i.part_number ?? "", revision: i.revision ?? "", name: i.name ?? "" } : null;

/** Age given in days by the server: "5 h", "3 d", with an "Aging" marker at the review target. */
export function AgeDays({ days, warnDays = 3 }: { days: number | null | undefined; warnDays?: number }) {
  if (days === null || days === undefined) return <span className="faint">–</span>;
  const text = days < 1 ? t("gxp.tpl.hours", { n: Math.floor(days * 24) }) : t("gxp.tpl.days", { n: Math.floor(days) });
  const late = days >= warnDays;
  return (
    <span className={late ? "row" : undefined} style={late ? { gap: 4 } : undefined}>
      <span className="pl-num">{text}</span>
      {late ? (
        <span className="badge warn">
          <Icon name="clock" /> {t("gxp.str.aging")}
        </span>
      ) : null}
    </span>
  );
}
