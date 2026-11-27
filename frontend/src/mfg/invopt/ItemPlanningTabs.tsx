/**
 * Item editor tabs (M8 3, 12): Planning - how the item is replenished (MRP, rate plan, kanban), forecasting, service
 * level, order pack level, campaign settings for flow lines and sterilisation / release - and Packaging levels
 * (each, inner, case, pallet; each level an integer multiple of the one before). ABC / XYZ are computed by the
 * safety stock run and shown read-only. Saves carry If-Match and, in Part 11 plants, a change reason.
 */
import { useEffect, useState } from "react";
import { Icon } from "../../components/Icon";
import { toast } from "../../components/Toast";
import { UnsavedChangesGuard } from "../../components/UnsavedChangesGuard";
import { t, type StringKey } from "../../lib/i18n";
import { formatNumber } from "../../lib/locale";
import { getItem } from "../api/client";
import type { ItemRef } from "../api/types";
import { getItemPackaging, getItemPlanning, updateItemPackaging, updateItemPlanning } from "../api/clientM8";
import type { ItemPlanning, ItemPlanningInput, PackagingLevelInput, PackLevel, ReleaseMode, Replenishment } from "../api/typesM8";
import { ConflictBanner, MfgError, Spinner } from "../components/Feedback";
import { FormErrors } from "../components/Field";
import { ItemPicker } from "../components/ItemPicker";
import { needsText, useCan } from "../lib/permissions";
import { isConflict, useLoad } from "../lib/useMfg";
import { useItem } from "../pages/ItemShell";
import { useChangeReason } from "../qa/ChangeReason";
import { ClassTag } from "../forecast/shared";

const LEVELS: PackLevel[] = ["each", "inner", "case", "pallet"];
const LEVEL_KEY = { each: "plan.pack.level.each", inner: "plan.pack.level.inner", case: "plan.pack.level.case", pallet: "plan.pack.level.pallet" } as const;
const REPL: { v: Replenishment; label: StringKey; help: StringKey }[] = [
  { v: "mrp", label: "plan.ip.repl.mrp", help: "plan.ip.repl.mrpHelp" },
  { v: "rate", label: "plan.ip.repl.rate", help: "plan.ip.repl.rateHelp" },
  { v: "kanban", label: "plan.ip.repl.kanban", help: "plan.ip.repl.kanbanHelp" },
  { v: "transfer", label: "net.ip.repl.transfer", help: "net.ip.repl.transferHelp" },
];

const toInput = (p: ItemPlanning): ItemPlanningInput => ({
  replenishment: p.replenishment,
  forecast: p.forecast,
  like_item_id: p.like_item_id,
  like_factor: p.like_factor,
  service_level: p.service_level,
  order_pack_level: p.order_pack_level,
  campaign_key: p.campaign_key,
  campaign_min_hours: p.campaign_min_hours,
  campaign_max_hours: p.campaign_max_hours,
  target_cover_days: p.target_cover_days,
  ster_cycle_code: p.ster_cycle_code,
  aeration_hours: p.aeration_hours,
  release_mode: p.release_mode,
  release_days: p.release_days,
  post_days: p.post_days,
});
const txt = (v: number | null | undefined) => (v === null || v === undefined ? "" : String(v));
const numOrNull = (s: string) => (s.trim() === "" || !Number.isFinite(Number(s)) ? null : Number(s));

function NumField({ id, label, value, onChange, hint, disabled, unit, step = "any", testId }: { id: string; label: string; value: string; onChange(v: string): void; hint?: string; disabled?: boolean; unit?: string; step?: string; testId?: string }) {
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <div className="pl-unit-input">
        <input id={id} className="input" type="number" step={step} min={0} value={value} onChange={(e) => onChange(e.target.value)} disabled={disabled} data-testid={testId} name={id.replace(/^ip-/, "")} />
        {unit ? <span className="muted small">{unit}</span> : null}
      </div>
      {hint ? <span className="hint">{hint}</span> : null}
    </div>
  );
}

export function ItemPlanningTab() {
  const { item } = useItem();
  const canEdit = useCan("master_edit");
  // sterilisation and release fields are maintained by quality (review 7: qa_plan_edit)
  const canSter = useCan("qa_plan_edit");
  const reason = useChangeReason();
  const rec = useLoad((s) => getItemPlanning(item.id, s), [item.id]);
  const pack = useLoad((s) => getItemPackaging(item.id, s), [item.id]);
  const [f, setF] = useState<ItemPlanningInput | null>(null);
  const [sl, setSl] = useState("");
  const [like, setLike] = useState<ItemRef | null>(null);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const p = rec.data;
  useEffect(() => {
    document.title = `${item.part_number} - ${t("plan.ip.title")}`;
  }, [item.part_number]);
  useEffect(() => {
    if (!p) return;
    setF(toInput(p));
    setSl(p.service_level === null ? "" : String(Math.round(p.service_level * 1000) / 10));
    setDirty(false);
    if (p.like_item_id) {
      const ctl = new AbortController();
      getItem(p.like_item_id, ctl.signal).then((it) => setLike(it as unknown as ItemRef), () => setLike(null));
      return () => ctl.abort();
    }
    setLike(null);
  }, [p]);
  if (rec.error && !p) return <MfgError error={rec.error} onRetry={rec.reload} />;
  if (!p || !f) return <Spinner />;
  const set = (x: Partial<ItemPlanningInput>) => {
    setF({ ...f, ...x });
    setDirty(true);
  };
  const levels = pack.data?.levels ?? [];
  const slNum = numOrNull(sl);
  const slValid = sl.trim() === "" || (slNum !== null && slNum > 50 && slNum < 100);
  const save = async () => {
    const r = await reason.ask(t("plan.ip.what", { item: item.part_number }));
    if (r === null) return;
    setBusy(true);
    setErr(null);
    try {
      const next = await updateItemPlanning(item.id, { ...f, service_level: slNum === null ? null : slNum / 100 }, p.row_version, r);
      rec.setData(next);
      toast(t("plan.ip.toast.saved"));
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };
  const ro = !canEdit;
  return (
    <div className="col gap-lg" data-testid="item-planning-tab">
      <UnsavedChangesGuard when={dirty} what={t("plan.ip.what", { item: item.part_number })} />
      {isConflict(err) ? <ConflictBanner onReload={rec.reload} /> : <MfgError error={err} />}
      <FormErrors error={err}>
        <section className="card">
          <div className="card-header pl-card-header">
            <h2 className="pl-h2">{t("plan.ip.sec.repl")}</h2>
            <span className="row" style={{ gap: 8 }}>
              <span className="muted small">{t("plan.ip.class")}</span>
              <ClassTag abc={p.abc} xyz={p.xyz} />
            </span>
          </div>
          <div className="card-body col pl-gap">
            <fieldset className="pl-choice" disabled={ro}>
              <legend className="sr-only">{t("plan.ip.sec.repl")}</legend>
              {REPL.map((o) => (
                <label key={o.v} className={`pl-choice-opt${f.replenishment === o.v ? " on" : ""}`}>
                  <input type="radio" name="ip-repl" checked={f.replenishment === o.v} onChange={() => set({ replenishment: o.v })} data-testid={`ip-repl-${o.v}`} />
                  <span>
                    <strong>{t(o.label)}</strong>
                    <span className="muted small">{t(o.help)}</span>
                  </span>
                </label>
              ))}
            </fieldset>
            <div className="pl-form-grid">
              <div className="field">
                <label htmlFor="ip-pack">{t("plan.ip.packLevel")}</label>
                <select id="ip-pack" className="select" value={f.order_pack_level ?? ""} disabled={ro} onChange={(e) => set({ order_pack_level: (e.target.value || null) as PackLevel | null })} data-testid="ip-pack-level">
                  <option value="">{t("plan.ip.packNone")}</option>
                  {levels.filter((l) => l.level !== "each").map((l) => (
                    <option key={l.level} value={l.level}>
                      {t("plan.ip.packOption", { level: t(LEVEL_KEY[l.level]), qty: formatNumber(l.qty_base), uom: item.uom })}
                    </option>
                  ))}
                </select>
                <span className="hint">{levels.length ? t("plan.ip.packHint") : t("plan.ip.packNoLevels")}</span>
              </div>
              <NumField id="ip-post" label={t("plan.ip.postDays")} value={txt(f.post_days)} onChange={(v) => set({ post_days: numOrNull(v) })} hint={t("plan.ip.postDaysHint")} unit={t("plan.unit.days")} step="1" disabled={ro} />
            </div>
          </div>
        </section>
        <section className="card">
          <div className="card-header pl-card-header">
            <h2 className="pl-h2">{t("plan.ip.sec.forecast")}</h2>
          </div>
          <div className="card-body col pl-gap">
            <label className="row" style={{ gap: 8 }}>
              <input type="checkbox" checked={f.forecast} disabled={ro} onChange={(e) => set({ forecast: e.target.checked })} data-testid="ip-forecast" />
              <span>
                {t("plan.ip.forecast")} <span className="muted small">{t("plan.ip.forecastHelp")}</span>
              </span>
            </label>
            <div className="pl-form-grid">
              <div className="field">
                <span className="field-label">{t("plan.ip.likeItem")}</span>
                <ItemPicker label={t("plan.ip.likeItem")} hideLabel value={like} excludeId={item.id} disabled={ro || !f.forecast} onChange={(it) => {
                  setLike(it);
                  set({ like_item_id: it.id });
                }} testId="ip-like" />
                <span className="hint">
                  {t("plan.ip.likeHint")}{" "}
                  {f.like_item_id && !ro ? (
                    <button type="button" className="btn ghost sm" onClick={() => {
                      setLike(null);
                      set({ like_item_id: null });
                    }}>
                      {t("plan.ip.likeClear")}
                    </button>
                  ) : null}
                </span>
              </div>
              <NumField id="ip-like-factor" label={t("plan.ip.likeFactor")} value={txt(f.like_factor)} onChange={(v) => set({ like_factor: numOrNull(v) ?? 1 })} hint={t("plan.ip.likeFactorHint")} disabled={ro || !f.like_item_id} />
              <div className="field">
                <label htmlFor="ip-sl">{t("plan.ip.sl")}</label>
                <div className="pl-unit-input">
                  <input id="ip-sl" className="input" type="number" step="0.1" min={50.1} max={99.9} value={sl} placeholder={t("plan.ip.slMatrix")} disabled={ro} aria-invalid={!slValid} onChange={(e) => {
                    setSl(e.target.value);
                    setDirty(true);
                  }} data-testid="ip-sl" />
                  <span className="muted small">%</span>
                </div>
                <span className="hint">{slValid ? t("plan.ip.slHint") : t("plan.ip.slInvalid")}</span>
              </div>
            </div>
          </div>
        </section>
        <section className="card">
          <div className="card-header pl-card-header">
            <h2 className="pl-h2">{t("plan.ip.sec.campaign")}</h2>
            {f.replenishment !== "rate" ? <span className="muted small">{t("plan.ip.campaignOnlyRate")}</span> : null}
          </div>
          <div className="card-body pl-form-grid">
            <div className="field">
              <label htmlFor="ip-ckey">{t("plan.ip.campaignKey")}</label>
              <input id="ip-ckey" name="campaign_key" className="input" maxLength={32} value={f.campaign_key ?? ""} disabled={ro} onChange={(e) => set({ campaign_key: e.target.value.trim() ? e.target.value : null })} />
              <span className="hint">{t("plan.ip.campaignKeyHint")}</span>
            </div>
            <NumField id="ip-cmin" label={t("plan.ip.campaignMin")} value={txt(f.campaign_min_hours)} onChange={(v) => set({ campaign_min_hours: numOrNull(v) ?? 0 })} unit={t("plan.unit.hours")} disabled={ro} />
            <NumField id="ip-cmax" label={t("plan.ip.campaignMax")} value={txt(f.campaign_max_hours)} onChange={(v) => set({ campaign_max_hours: numOrNull(v) })} unit={t("plan.unit.hours")} hint={t("plan.ip.campaignMaxHint")} disabled={ro} />
            <NumField id="ip-cover" label={t("plan.ip.cover")} value={txt(f.target_cover_days)} onChange={(v) => set({ target_cover_days: numOrNull(v) ?? 0 })} unit={t("plan.unit.days")} step="1" hint={t("plan.ip.coverHint")} disabled={ro} />
          </div>
        </section>
        <section className="card">
          <div className="card-header pl-card-header">
            <h2 className="pl-h2">{t("plan.ip.sec.ster")}</h2>
            {!canSter ? <span className="muted small" data-testid="ip-ster-ro"><Icon name="lock" size={12} /> {t("plan.ip.sterQa")}</span> : null}
          </div>
          <div className="card-body pl-form-grid">
            <div className="field">
              <label htmlFor="ip-cycle">{t("plan.ip.cycle")}</label>
              <input id="ip-cycle" name="ster_cycle_code" className="input" maxLength={16} value={f.ster_cycle_code ?? ""} disabled={ro || !canSter} onChange={(e) => set({ ster_cycle_code: e.target.value.trim() ? e.target.value : null })} data-testid="ip-cycle" />
              <span className="hint">{t("plan.ip.cycleHint")}</span>
            </div>
            <NumField id="ip-aer" label={t("plan.ip.aeration")} value={txt(f.aeration_hours)} onChange={(v) => set({ aeration_hours: numOrNull(v) })} unit={t("plan.unit.hours")} disabled={ro || !canSter || !f.ster_cycle_code} />
            <div className="field">
              <label htmlFor="ip-rel">{t("plan.ip.release")}</label>
              <select id="ip-rel" className="select" value={f.release_mode} disabled={ro || !canSter} onChange={(e) => set({ release_mode: e.target.value as ReleaseMode })}>
                <option value="none">{t("plan.ip.release.none")}</option>
                <option value="bi">{t("plan.ip.release.bi")}</option>
                <option value="parametric">{t("plan.ip.release.parametric")}</option>
              </select>
            </div>
            <NumField id="ip-reldays" label={t("plan.ip.releaseDays")} value={txt(f.release_days)} onChange={(v) => set({ release_days: numOrNull(v) ?? 0 })} unit={t("plan.unit.days")} hint={t("plan.ip.releaseDaysHint")} disabled={ro || !canSter || f.release_mode === "none"} />
          </div>
        </section>
      </FormErrors>
      <div className="row pl-form-actions">
        {canEdit ? (
          <>
            <button type="button" className="btn primary" disabled={!dirty || busy || !slValid} onClick={() => void save()} data-testid="ip-save">
              {busy ? <span className="spinner" aria-hidden /> : <Icon name="save" />} {t("plan.ip.save")}
            </button>
            <button type="button" className="btn" disabled={!dirty || busy} onClick={() => {
              setF(toInput(p));
              setSl(p.service_level === null ? "" : String(Math.round(p.service_level * 1000) / 10));
              setDirty(false);
            }}>
              {t("plan.ip.discard")}
            </button>
          </>
        ) : (
          <span className="muted small">{needsText("master_edit")}</span>
        )}
      </div>
      {reason.dialog}
    </div>
  );
}

// ---------------------------------------------------------------- packaging
interface Row {
  used: boolean;
  code: string;
  qty: string;
  gtin: string;
  weight: string;
}

export function ItemPackagingTab() {
  const { item } = useItem();
  const canEdit = useCan("master_edit");
  const reason = useChangeReason();
  const rec = useLoad((s) => getItemPackaging(item.id, s), [item.id]);
  const [rows, setRows] = useState<Record<PackLevel, Row> | null>(null);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const d = rec.data;
  useEffect(() => {
    document.title = `${item.part_number} - ${t("plan.pack.title")}`;
  }, [item.part_number]);
  useEffect(() => {
    if (!d) return;
    const next = {} as Record<PackLevel, Row>;
    for (const lv of LEVELS) {
      const l = d.levels.find((x) => x.level === lv);
      next[lv] = l ? { used: true, code: l.code, qty: String(l.qty_base), gtin: l.gtin ?? "", weight: l.weight_kg === null ? "" : String(l.weight_kg) } : { used: lv === "each", code: lv === "each" ? item.uom : "", qty: lv === "each" ? "1" : "", gtin: "", weight: "" };
    }
    setRows(next);
    setDirty(false);
  }, [d, item.uom]);
  if (rec.error && !d) return <MfgError error={rec.error} onRetry={rec.reload} />;
  if (!d || !rows) return <Spinner />;
  const upd = (lv: PackLevel, x: Partial<Row>) => {
    setRows({ ...rows, [lv]: { ...rows[lv], ...x } });
    setDirty(true);
  };
  // validation (3): qty strictly increasing and an integer multiple of the previous used level; each = 1
  const problems: Partial<Record<PackLevel, string>> = {};
  let prev: number | null = null;
  for (const lv of LEVELS) {
    const r = rows[lv];
    if (!r.used) continue;
    const q = Number(r.qty);
    if (!r.code.trim()) problems[lv] = t("plan.pack.err.code");
    else if (!(q > 0)) problems[lv] = t("plan.pack.err.qty");
    else if (lv === "each" && q !== 1) problems[lv] = t("plan.pack.err.each");
    else if (prev !== null && (q <= prev || Math.abs(q / prev - Math.round(q / prev)) > 1e-9)) problems[lv] = t("plan.pack.err.multiple", { prev: formatNumber(prev) });
    else if (r.gtin && !/^[0-9]{8,14}$/.test(r.gtin)) problems[lv] = t("plan.pack.err.gtin");
    if (q > 0) prev = q;
  }
  const ok = Object.keys(problems).length === 0;
  const save = async () => {
    const r = await reason.ask(t("plan.pack.what", { item: item.part_number }));
    if (r === null) return;
    setBusy(true);
    setErr(null);
    try {
      const levels: PackagingLevelInput[] = LEVELS.filter((lv) => rows[lv].used).map((lv) => ({
        level: lv,
        code: rows[lv].code.trim(),
        qty_base: Number(rows[lv].qty),
        gtin: rows[lv].gtin.trim() || null,
        weight_kg: rows[lv].weight.trim() === "" ? null : Number(rows[lv].weight),
      }));
      rec.setData(await updateItemPackaging(item.id, levels, d.row_version, r));
      toast(t("plan.pack.toast.saved"));
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };
  let prevUsed: number | null = null;
  return (
    <div className="col gap-lg" data-testid="item-packaging-tab">
      <UnsavedChangesGuard when={dirty} what={t("plan.pack.what", { item: item.part_number })} />
      {isConflict(err) ? <ConflictBanner onReload={rec.reload} /> : <MfgError error={err} />}
      <section className="card">
        <div className="card-header pl-card-header">
          <h2 className="pl-h2">{t("plan.pack.title")}</h2>
          <span className="muted small">{t("plan.pack.hint", { uom: item.uom })}</span>
        </div>
        <div className="pl-pivot-wrap">
          <table className="pl-edit-table" data-testid="pack-table">
            <thead>
              <tr>
                <th scope="col">{t("plan.pack.head.level")}</th>
                <th scope="col">{t("plan.pack.head.code")}</th>
                <th scope="col">{t("plan.pack.head.qty", { uom: item.uom })}</th>
                <th scope="col">{t("plan.pack.head.per")}</th>
                <th scope="col">{t("plan.pack.head.gtin")}</th>
                <th scope="col">{t("plan.pack.head.weight")}</th>
              </tr>
            </thead>
            <tbody>
              {LEVELS.map((lv) => {
                const r = rows[lv];
                const q = Number(r.qty);
                const per = r.used && prevUsed && q > 0 ? q / prevUsed : null;
                const perText = per !== null ? t("plan.pack.per", { n: formatNumber(per, 2) }) : "";
                if (r.used && q > 0) prevUsed = q;
                const ro = !canEdit;
                return (
                  <tr key={lv} data-level={lv} className={r.used ? undefined : "pl-row-off"}>
                    <th scope="row">
                      <label className="row" style={{ gap: 6 }}>
                        <input type="checkbox" checked={r.used} disabled={!canEdit || lv === "each"} onChange={(e) => upd(lv, { used: e.target.checked })} data-testid={`pack-use-${lv}`} />
                        {t(LEVEL_KEY[lv])}
                      </label>
                    </th>
                    <td>
                      <input className="input" aria-label={t("plan.pack.aria.code", { level: t(LEVEL_KEY[lv]) })} maxLength={32} value={r.code} disabled={ro || !r.used} onChange={(e) => upd(lv, { code: e.target.value })} />
                    </td>
                    <td>
                      <input className="input pl-w-140" type="number" min={1} step="any" aria-label={t("plan.pack.aria.qty", { level: t(LEVEL_KEY[lv]) })} aria-invalid={Boolean(problems[lv])} value={r.qty} disabled={ro || !r.used || lv === "each"} onChange={(e) => upd(lv, { qty: e.target.value })} data-testid={`pack-qty-${lv}`} />
                      {problems[lv] ? (
                        <div className="pl-field-err" role="alert">
                          <Icon name="alert" size={12} /> {problems[lv]}
                        </div>
                      ) : null}
                    </td>
                    <td className="muted pl-num">{perText}</td>
                    <td>
                      <input className="input" inputMode="numeric" aria-label={t("plan.pack.aria.gtin", { level: t(LEVEL_KEY[lv]) })} maxLength={14} value={r.gtin} disabled={ro || !r.used} onChange={(e) => upd(lv, { gtin: e.target.value })} />
                    </td>
                    <td>
                      <input className="input pl-w-100" type="number" min={0} step="any" aria-label={t("plan.pack.aria.weight", { level: t(LEVEL_KEY[lv]) })} value={r.weight} disabled={ro || !r.used} onChange={(e) => upd(lv, { weight: e.target.value })} />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>
      <div className="row pl-form-actions">
        {canEdit ? (
          <>
            <button type="button" className="btn primary" disabled={!dirty || busy || !ok} onClick={() => void save()} data-testid="pack-save">
              {busy ? <span className="spinner" aria-hidden /> : <Icon name="save" />} {t("plan.pack.save")}
            </button>
            <button type="button" className="btn" disabled={!dirty || busy} onClick={() => rec.setData({ ...d })}>
              {t("plan.ip.discard")}
            </button>
          </>
        ) : (
          <span className="muted small">{needsText("master_edit")}</span>
        )}
      </div>
      {reason.dialog}
    </div>
  );
}
