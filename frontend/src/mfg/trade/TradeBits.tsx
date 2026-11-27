/**
 * M9 8 plant pieces: the item's Trade tab (HTS code, country of origin, material class, unit weight) with the landed
 * cost per supplier and its breakdown (price, freight, duty layers, other, FX), and the lot's domestic content (share
 * by value and weight, estimated badge, input tree) used by the lot dialog and the tariff report.
 */
import { useEffect, useState } from "react";
import { Link } from "react-router";
import { mfgPaths } from "../lib/paths";
import { Banner } from "../../components/Banner";
import { Icon } from "../../components/Icon";
import { toast } from "../../components/Toast";
import { UnsavedChangesGuard } from "../../components/UnsavedChangesGuard";
import { t } from "../../lib/i18n";
import { formatDateTime, formatMoney, formatNumber, formatQty } from "../../lib/locale";
import { getItemTrade, getLanded, getLotContent, putItemTrade, putLotCoo } from "../api/clientM9";
import type { ContentNode, ItemTradeInput, LandedCost, LandedRow, LotContent } from "../api/typesM9";
import { MfgError, Spinner } from "../components/Feedback";
import { useItem } from "../pages/ItemShell";
import { needsText, useCan } from "../lib/permissions";
import { isNotFound, useLoad } from "../lib/useMfg";
import { useChangeReason } from "../qa/ChangeReason";
import { codeText9 } from "../network/shared";
import "../network/network.css";

const share = (v: number | null | undefined) => (v === null || v === undefined ? "–" : `${formatNumber(v * 100, 1)} %`);
const COO_SOURCE: Record<string, "net.coo.receipt" | "net.coo.supplier" | "net.coo.item" | "net.coo.plant" | "net.coo.transfer"> = {
  receipt: "net.coo.receipt",
  supplier: "net.coo.supplier",
  item: "net.coo.item",
  plant: "net.coo.plant",
  transfer: "net.coo.transfer",
};

// ---------------------------------------------------------------- item Trade tab
export function ItemTradeTab() {
  const { item } = useItem();
  const canEdit = useCan("master_edit");
  const reason = useChangeReason();
  const tr = useLoad((s) => getItemTrade(item.id, s).catch((e: unknown) => (isNotFound(e) ? null : Promise.reject(e))), [item.id]);
  const landed = useLoad((s) => (item.make_buy === "buy" ? getLanded(item.id, s) : null), [item.id, item.make_buy]);
  const [f, setF] = useState<ItemTradeInput>({ hts_code: null, coo: null, material_class: null, unit_weight_kg: null });
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  useEffect(() => {
    if (tr.data && !dirty) setF({ hts_code: tr.data.hts_code, coo: tr.data.coo, material_class: tr.data.material_class, unit_weight_kg: tr.data.unit_weight_kg });
  }, [tr.data, dirty]);
  const set = <K extends keyof ItemTradeInput>(k: K, v: ItemTradeInput[K]) => (setF((x) => ({ ...x, [k]: v })), setDirty(true));
  const htsOk = !f.hts_code || /^\d{6,10}$/.test(f.hts_code);
  const cooOk = !f.coo || /^[A-Z]{2}$/.test(f.coo);
  const save = async () => {
    const why = await reason.ask(t("net.it.what", { p: item.part_number }));
    if (why === null) return;
    setBusy(true);
    setErr(null);
    try {
      tr.setData(await putItemTrade(item.id, f, tr.data?.row_version ?? 0, why));
      setDirty(false);
      toast(t("net.src.toast.saved"));
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };
  if (tr.error) return <MfgError error={tr.error} onRetry={tr.reload} />;
  return (
    <div className="col pl-gap net-page" data-testid="item-trade">
      <section className="card col pl-gap" aria-labelledby="it-h">
        <div className="pl-card-header">
          <h2 className="pl-h2" id="it-h">
            {t("net.it.title")}
          </h2>
          <button type="button" className="btn primary sm" disabled={!canEdit || !dirty || !htsOk || !cooOk || busy} title={canEdit ? undefined : needsText("master_edit")} onClick={() => void save()} data-testid="item-trade-save">
            <Icon name="save" /> {t("net.btn.save")}
          </button>
        </div>
        <MfgError error={err} />
        <div className="row wrap" style={{ gap: 12 }}>
          <div className="field">
            <label htmlFor="it-hts">{t("net.chg.hts")}</label>
            <input id="it-hts" className="input mono" style={{ width: 130 }} maxLength={10} inputMode="numeric" value={f.hts_code ?? ""} disabled={!canEdit} aria-invalid={!htsOk} onChange={(e) => set("hts_code", e.target.value.replace(/\D/g, "") || null)} data-testid="item-hts" />
            <span className="hint">{t("net.it.hint.hts")}</span>
          </div>
          <div className="field">
            <label htmlFor="it-coo">{t("net.chg.coo")}</label>
            <input id="it-coo" className="input mono" style={{ width: 70 }} maxLength={2} value={f.coo ?? ""} disabled={!canEdit} aria-invalid={!cooOk} onChange={(e) => set("coo", e.target.value.toUpperCase().replace(/[^A-Z]/g, "") || null)} data-testid="item-coo" />
            <span className="hint">{item.make_buy === "make" ? t("net.it.hint.cooMake") : t("net.it.hint.cooBuy")}</span>
          </div>
          <div className="field">
            <label htmlFor="it-mc">{t("net.it.materialClass")}</label>
            <input id="it-mc" className="input mono" style={{ width: 130 }} maxLength={16} value={f.material_class ?? ""} disabled={!canEdit} onChange={(e) => set("material_class", e.target.value.toLowerCase() || null)} />
            <span className="hint">{t("net.it.hint.materialClass")}</span>
          </div>
          <div className="field">
            <label htmlFor="it-w">{t("net.it.weight")}</label>
            <input id="it-w" className="input" style={{ width: 130 }} type="number" min={0} step="0.0001" value={f.unit_weight_kg ?? ""} disabled={!canEdit} onChange={(e) => set("unit_weight_kg", e.target.value === "" ? null : Number(e.target.value))} />
            <span className="hint">{t("net.it.hint.weight", { u: item.uom })}</span>
          </div>
        </div>
        {!f.hts_code ? <p className="pl-note" style={{ margin: 0 }}><Icon name="alert" size={14} /> {codeText9("HTS_MISSING")}</p> : null}
      </section>
      {item.make_buy === "buy" ? (
        <section className="card col pl-gap" aria-labelledby="it-landed-h">
          <h2 className="pl-h2" id="it-landed-h">
            {t("net.it.landed")}
          </h2>
          <p className="small muted" style={{ margin: 0 }}>{t("net.it.landedHint")}</p>
          <MfgError error={landed.error} onRetry={landed.reload} />
          {!landed.data ? <Spinner /> : landed.data.items.length ? <LandedTable rows={landed.data.items} /> : <p className="muted small">{t("net.it.noSuppliers")}</p>}
        </section>
      ) : null}
      <UnsavedChangesGuard when={dirty} what={t("net.it.what", { p: item.part_number })} />
      {reason.dialog}
    </div>
  );
}

/** The plant has no country (attribute `country`): origin and duty cannot be decided - say where to set it. */
export function CountryMissing() {
  return (
    <Banner tone="warn" title={codeText9("COUNTRY_MISSING")} testId="country-missing" actions={<Link className="btn sm" to={mfgPaths.settings()}>{t("net.plant.setCountry")}</Link>}>
      {t("net.plant.countryMissingBody")}
    </Banner>
  );
}

function LandedTable({ rows }: { rows: LandedRow[] }) {
  const [open, setOpen] = useState<string | null>(null);
  const noCountry = rows.some((r) => r.landed.flags.includes("COUNTRY_MISSING"));
  return (
    <div className="pl-pivot-wrap">
      {noCountry ? <CountryMissing /> : null}
      <table className="pl-pivot" aria-label={t("net.it.landed")} data-testid="landed-table">
        <thead>
          <tr>
            <th scope="col">{t("net.src.supplier")}</th>
            <th scope="col">{t("net.chg.coo")}</th>
            <th scope="col">{t("net.chg.hts")}</th>
            <th scope="col">{t("net.landed.price")}</th>
            <th scope="col">{t("net.landed.freight")}</th>
            <th scope="col">{t("net.landed.duty")}</th>
            <th scope="col">{t("net.landed.other")}</th>
            <th scope="col">{t("net.landed.total")}</th>
            <th scope="col">
              <span className="sr-only">{t("net.landed.breakdown")}</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.flatMap((r) => {
            const l = r.landed;
            const duty = l.duty.reduce((a, d) => a + d.amount, 0);
            const m = (v: number | null) => formatMoney(v, l.currency, { digits: 4 });
            return [
              <tr key={r.item_supplier_id} data-testid="landed-row">
                <th scope="row">
                  <span className="row" style={{ gap: 6 }}>
                    <span className="mono">{r.supplier_code}</span> <span className="muted">{r.supplier_name}</span>
                    {r.preferred ? (
                      <span className="badge info">
                        <Icon name="star" /> {t("net.landed.preferred")}
                      </span>
                    ) : null}
                  </span>
                </th>
                <td>{r.coo ?? <span className="badge warn"><Icon name="alert" /> {t("net.landed.cooMissing")}</span>}</td>
                <td className="mono">{r.hts_code ?? "–"}</td>
                <td>{m(l.unit_price)}</td>
                <td>{m(l.freight)}</td>
                <td>{m(duty)}</td>
                <td>{m(l.other)}</td>
                <td>
                  <strong>{l.total === null ? <span className="badge danger"><Icon name="alert" /> {codeText9("FX_MISSING")}</span> : m(l.total)}</strong>
                </td>
                <td>
                  <button type="button" className="btn ghost sm" aria-expanded={open === r.item_supplier_id} onClick={() => setOpen(open === r.item_supplier_id ? null : r.item_supplier_id)} data-testid="landed-toggle">
                    <Icon name={open === r.item_supplier_id ? "chevron-down" : "chevron-right"} /> {t("net.landed.breakdown")}
                  </button>
                </td>
              </tr>,
              open === r.item_supplier_id ? (
                <tr key={`${r.item_supplier_id}-d`}>
                  <td colSpan={9} style={{ textAlign: "left", height: "auto", padding: 8 }}>
                    <LandedBreakdown l={l} />
                  </td>
                </tr>
              ) : null,
            ];
          })}
        </tbody>
      </table>
    </div>
  );
}

/** One landed cost as a short calculation: price, freight, customs value, each duty layer, other, total, FX and flags. */
export function LandedBreakdown({ l }: { l: LandedCost }) {
  const m = (v: number | null) => formatMoney(v, l.currency, { digits: 4 });
  return (
    <dl className="dash-details" style={{ maxWidth: 520 }} data-testid="landed-breakdown">
      <div>
        <dt>{t("net.landed.price")}</dt>
        <dd>{m(l.unit_price)}</dd>
      </div>
      <div>
        <dt>{t("net.landed.freight")}</dt>
        <dd>{m(l.freight)}</dd>
      </div>
      <div>
        <dt>{t("net.landed.customs")}</dt>
        <dd>{m(l.customs_value)}</dd>
      </div>
      {l.duty.map((d) => (
        <div key={d.layer}>
          <dt>{t("net.landed.dutyLayer", { l: d.layer, r: formatNumber(d.rate_pct, 2) })}</dt>
          <dd>{m(d.amount)}</dd>
        </div>
      ))}
      <div>
        <dt>{t("net.landed.other")}</dt>
        <dd>{m(l.other)}</dd>
      </div>
      <div>
        <dt>
          <strong>{t("net.landed.total")}</strong>
        </dt>
        <dd>
          <strong>{m(l.total)}</strong>
        </dd>
      </div>
      <div>
        <dt>{t("net.landed.fx")}</dt>
        <dd>{l.fx_rate === null ? "–" : formatNumber(l.fx_rate, 6)}</dd>
      </div>
      {l.flags.length ? (
        <div>
          <dt>{t("net.landed.flags")}</dt>
          <dd>{l.flags.map(codeText9).join(", ")}</dd>
        </div>
      ) : null}
    </dl>
  );
}

// ---------------------------------------------------------------- lot domestic content
export function LotContentPanel({ lotId, load, version }: { lotId: string; load?: (signal: AbortSignal) => Promise<LotContent>; version?: number }) {
  const c = useLoad((s) => (load ? load(s) : getLotContent(lotId, s)).catch((e: unknown) => (isNotFound(e) ? null : Promise.reject(e))), [lotId]);
  if (c.error) return <MfgError error={c.error} onRetry={c.reload} />;
  if (c.loading && !c.data) return <Spinner />;
  if (!c.data) return null;
  return <LotContentView c={c.data} onCooEdit={load ? undefined : { version, onDone: c.reload }} />;
}

export function LotContentView({ c, onCooEdit }: { c: LotContent; onCooEdit?: { version?: number; onDone(): void } }) {
  const [tree, setTree] = useState(false);
  const [edit, setEdit] = useState(false);
  const canEdit = useCan("master_edit");
  return (
    <section className="col pl-gap" aria-label={t("net.lc.title")} data-testid="lot-content">
      <div className="row wrap" style={{ gap: 12 }}>
        <strong className="small">{t("net.lc.title")}</strong>
        <span className="small">
          {t("net.chg.coo")} <span className="mono">{c.coo ?? "–"}</span>
          {c.coo_source ? <span className="muted"> ({t(COO_SOURCE[c.coo_source] ?? "net.coo.item")})</span> : null}
        </span>
        {!c.coo ? (
          <span className="badge warn">
            <Icon name="alert" /> {codeText9("TRADE_COO_MISSING")}
          </span>
        ) : null}
        {onCooEdit && !edit ? (
          <button type="button" className="btn ghost sm" disabled={!canEdit} title={canEdit ? undefined : needsText("master_edit")} onClick={() => setEdit(true)} data-testid="lot-coo-edit">
            <Icon name="settings" /> {t("net.lc.editCoo")}
          </button>
        ) : null}
      </div>
      {edit && onCooEdit ? <CooEditor lotId={c.lot_id} current={c.coo} version={onCooEdit.version} onClose={() => setEdit(false)} onDone={() => (setEdit(false), onCooEdit.onDone())} /> : null}
      <dl className="pl-facts">
        <div>
          <dt>{t("net.lc.byValue")}</dt>
          <dd data-testid="lot-dom-value">{share(c.share_value)}</dd>
        </div>
        <div>
          <dt>{t("net.lc.byWeight")}</dt>
          <dd>{share(c.share_weight)}</dd>
        </div>
        <div>
          <dt>{t("net.lc.computed")}</dt>
          <dd>{c.computed_at ? formatDateTime(c.computed_at) : "–"}</dd>
        </div>
      </dl>
      {c.estimated ? (
        <Banner tone="warn" icon="info">
          {t("net.lc.estimated")}
        </Banner>
      ) : null}
      <button type="button" className="btn ghost sm" style={{ alignSelf: "flex-start" }} aria-expanded={tree} onClick={() => setTree((v) => !v)} data-testid="lot-content-tree-toggle">
        <Icon name={tree ? "chevron-down" : "chevron-right"} /> {t("net.lc.inputs")}
      </button>
      {tree ? (
        <ul className="net-tree" role="tree" aria-label={t("net.lc.inputs")}>
          <ContentTree n={c.tree} ccy={c.currency} level={1} />
        </ul>
      ) : null}
    </section>
  );
}

/** Regulated correction of a lot's country of origin: new value and a required reason (audit trail, Part 11). */
function CooEditor({ lotId, current, version, onClose, onDone }: { lotId: string; current: string | null; version?: number; onClose(): void; onDone(): void }) {
  const [coo, setCoo] = useState(current ?? "");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const valid = (coo === "" || /^[A-Z]{2}$/.test(coo)) && coo !== (current ?? "") && reason.trim().length > 0;
  return (
    <div className="pl-expert col pl-gap" data-testid="lot-coo-form">
      <MfgError error={err} />
      <div className="row wrap" style={{ gap: 12, alignItems: "flex-end" }}>
        <div className="field">
          <label htmlFor="lot-coo-v">{t("net.chg.coo")}</label>
          <input id="lot-coo-v" className="input sm mono" style={{ width: 70 }} maxLength={2} value={coo} onChange={(e) => setCoo(e.target.value.toUpperCase().replace(/[^A-Z]/g, ""))} data-testid="lot-coo-input" />
        </div>
        <div className="field" style={{ flex: 1, minWidth: 220 }}>
          <label htmlFor="lot-coo-why">
            {t("plan.label.reason")} <span className="req" aria-hidden />
          </label>
          <input id="lot-coo-why" className="input sm" maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} data-testid="lot-coo-reason" />
        </div>
        <button type="button" className="btn sm" onClick={onClose}>
          {t("common.cancel")}
        </button>
        <button
          type="button"
          className="btn sm primary"
          disabled={!valid || busy}
          onClick={() => {
            setBusy(true);
            setErr(null);
            putLotCoo(lotId, coo || null, reason.trim(), version)
              .then(() => {
                toast(t("net.lc.cooSaved"));
                onDone();
              })
              .catch((e: unknown) => setErr(e))
              .finally(() => setBusy(false));
          }}
          data-testid="lot-coo-save"
        >
          <Icon name="save" /> {t("net.btn.save")}
        </button>
      </div>
      <span className="hint">{t("net.lc.cooHint")}</span>
    </div>
  );
}

function ContentTree({ n, ccy, level }: { n: ContentNode; ccy: string; level: number }) {
  const dom = n.domestic;
  return (
    <li role="treeitem" aria-level={level} aria-expanded={n.children.length ? true : undefined}>
      <div className="net-tree-row">
        <Icon name={n.kind === "made" ? "factory" : n.kind === "conversion" ? "settings" : "box"} size={14} />
        <span className="mono">{n.lot_code ?? n.item_key}</span>
        {n.description ? <span className="muted">{n.description}</span> : null}
        {n.material_class ? <span className="small muted">{n.material_class}</span> : null}
        <span className="small">{n.coo ?? "–"}</span>
        {n.estimated || n.kind === "possible" ? (
          <span className="badge warn">
            <Icon name="info" /> {t("net.lc.est")}
          </span>
        ) : null}
        <span className="small muted pl-num">{formatQty(n.qty, n.uom)} {n.uom}</span>
        <span className="small pl-num">{formatMoney(n.value, ccy, { digits: 2 })}</span>
        <span className="small pl-num">{n.weight_kg === null ? "" : t("net.lc.kg", { v: formatNumber(n.weight_kg, 3) })}</span>
        <span className={`pl-num small ${dom === 1 ? "" : dom === 0 ? "net-neg" : ""}`}>{t("net.lc.dom", { v: share(dom) })}</span>
      </div>
      {n.children.length ? (
        <ul role="group">
          {n.children.map((x, i) => (
            <ContentTree key={`${x.item_key}-${x.lot_id ?? i}`} n={x} ccy={ccy} level={level + 1} />
          ))}
        </ul>
      ) : null}
    </li>
  );
}
