/**
 * `/mfg/trade/:tab?` (M9 8, 10): the network's trade tables - tariff rows (bulk paste from a spreadsheet, preview
 * with validation, upsert), FX rates (month x currency pair grid), tariff milestones (domestic-content rules) and the
 * country risk table - plus the tariff-milestone reports. Only fictional example rates ship; the customer owns its
 * tariff data. Edits need `trade_admin` and carry the Part 11 reason.
 */
import { useEffect, useMemo, useState } from "react";
import { Link, NavLink, useNavigate, useParams } from "react-router";
import { Banner } from "../../components/Banner";
import { DateInput } from "../../components/DateInput";
import { Dialog } from "../../components/Dialog";
import { FilterBar } from "../../components/FilterBar";
import { Icon } from "../../components/Icon";
import { PageHeader } from "../../components/PageHeader";
import { toast } from "../../components/Toast";
import { plural, t } from "../../lib/i18n";
import { formatDateRange, formatDateTime, formatNumber } from "../../lib/locale";
import { createTradeReport, getCountryRisk, getFx, getMilestones, getTariffs, listScenarios, listTradeReports, putCountryRisk, putFx, putMilestones, putTariffs } from "../api/clientM9";
import type { CountryRiskInput, FxRateInput, Milestone, MilestoneInput, TariffRate, TariffRateInput, TradeReport } from "../api/typesM9";
import { DataTable } from "../components/DataTable";
import { MfgError, Spinner } from "../components/Feedback";
import type { Column } from "../components/VirtualTable";
import { mfgPaths } from "../lib/paths";
import { needsText, useCan } from "../lib/permissions";
import { usePolling } from "../lib/usePolling";
import { useLoad } from "../lib/useMfg";
import { useChangeReason } from "../qa/ChangeReason";
import { isRunning, JobChip, monthLabel, monthShort, pct100, Segmented, todayIso } from "../network/shared";

const TABS = ["tariffs", "fx", "milestones", "risk", "reports"] as const;
type Tab = (typeof TABS)[number];

export function TradePage() {
  const { tab: tabParam } = useParams();
  const tab: Tab = TABS.includes(tabParam as Tab) ? (tabParam as Tab) : "tariffs";
  useEffect(() => {
    document.title = t("net.trd.title");
  }, []);
  return (
    <div className="col gap-lg net-page" data-testid="trade-page">
      <PageHeader title={t("net.trd.title")} description={t("net.trd.desc")} />
      <nav className="tabs" aria-label={t("net.trd.aria.tabs")}>
        {TABS.map((k) => (
          <NavLink key={k} to={mfgPaths.trade(k === "tariffs" ? undefined : k)} end className={() => `tab${tab === k ? " active" : ""}`} aria-current={tab === k ? "page" : undefined} data-testid={`trd-tab-${k}`}>
            {t(`net.trd.tab.${k}` as const)}
          </NavLink>
        ))}
      </nav>
      {tab === "tariffs" ? <TariffsTab /> : tab === "fx" ? <FxTab /> : tab === "milestones" ? <MilestonesTab /> : tab === "risk" ? <CountryRiskTab /> : <ReportsTab />}
    </div>
  );
}

// ---------------------------------------------------------------- paste parsing
type Parsed<T> = { rows: T[]; errors: string[] };
/** Tab- or semicolon-separated text (a spreadsheet copy); a first line with letters only in the date column is a header. */
function splitRows(text: string): string[][] {
  const lines = text.split(/\r?\n/).filter((l) => l.trim());
  const rows = lines.map((l) => l.split(l.includes("\t") ? "\t" : l.includes(";") ? ";" : ",").map((c) => c.trim()));
  return rows.length && /[a-z]/i.test(rows[0].join("")) && !/^\d/.test(rows[0][1] ?? "") ? rows.slice(1) : rows;
}
const num = (s: string | undefined) => (s === undefined || s === "" ? null : Number(s.replace(",", ".")));
const isDate = (s: string) => /^\d{4}-\d{2}-\d{2}$/.test(s);

function parseTariffs(text: string): Parsed<TariffRateInput> {
  const rows: TariffRateInput[] = [];
  const errors: string[] = [];
  splitRows(text).forEach((c, i) => {
    const [dest, prefix, coo, layer, rate, perUnit, perCcy, from, to, note] = c;
    const r: TariffRateInput = { dest_country: (dest ?? "").toUpperCase(), hts_prefix: (prefix ?? "").replace(/\D/g, ""), coo: (coo || "*").toUpperCase(), layer: (layer ?? "").toLowerCase(), rate_pct: num(rate) ?? NaN, per_unit: num(perUnit), per_unit_currency: perCcy ? perCcy.toUpperCase() : null, valid_from: from ?? "", valid_to: to || null, note: note ?? "" };
    const bad = !/^[A-Z]{2}$/.test(r.dest_country) || !/^\d{2,10}$/.test(r.hts_prefix) || !/^([A-Z]{2}|\*)$/.test(r.coo) || !r.layer || !Number.isFinite(r.rate_pct) || !isDate(r.valid_from) || (r.valid_to !== null && !isDate(r.valid_to));
    if (bad) errors.push(t("net.trd.paste.badRow", { n: i + 1 }));
    else rows.push(r);
  });
  return { rows, errors };
}
function parseFx(text: string): Parsed<FxRateInput> {
  const rows: FxRateInput[] = [];
  const errors: string[] = [];
  splitRows(text).forEach((c, i) => {
    const [from, to, month, rate, source] = c;
    const m = (month ?? "").length === 7 ? `${month}-01` : month ?? "";
    const r: FxRateInput = { from_ccy: (from ?? "").toUpperCase(), to_ccy: (to ?? "").toUpperCase(), month: m, rate: num(rate) ?? NaN, source: source || "manual" };
    if (!/^[A-Z]{3}$/.test(r.from_ccy) || !/^[A-Z]{3}$/.test(r.to_ccy) || !/^\d{4}-\d{2}-01$/.test(r.month) || !(r.rate > 0)) errors.push(t("net.trd.paste.badRow", { n: i + 1 }));
    else rows.push(r);
  });
  return { rows, errors };
}

function PasteDialog<T>({ title, columns, parse, preview, onClose, save }: { title: string; columns: string; parse(text: string): Parsed<T>; preview(rows: T[]): string[]; onClose(): void; save(rows: T[], reason: string | null): Promise<void> }) {
  const reason = useChangeReason();
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const p = useMemo(() => parse(text), [text, parse]);
  const go = async () => {
    const why = await reason.ask(title);
    if (why === null) return;
    setBusy(true);
    setErr(null);
    try {
      await save(p.rows, why);
      onClose();
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog
      title={title}
      wide
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose} data-dialog-close>
            {t("common.cancel")}
          </button>
          <button type="button" className="btn primary" disabled={!p.rows.length || p.errors.length > 0 || busy} onClick={() => void go()} data-testid="trd-paste-save">
            <Icon name="upload" /> {t("net.trd.paste.save", { n: p.rows.length })}
          </button>
        </>
      }
    >
      <div className="col pl-gap">
        <MfgError error={err} />
        <p className="small" style={{ margin: 0 }}>
          {t("net.trd.paste.body")} <span className="mono small">{columns}</span>
        </p>
        <textarea className="textarea trd-paste" rows={10} aria-label={t("net.trd.paste.aria")} value={text} onChange={(e) => setText(e.target.value)} data-testid="trd-paste" data-autofocus />
        {p.errors.length ? (
          <Banner tone="danger" title={t("net.trd.paste.errors", { n: plural(p.errors.length, t("noun.row"), t("noun.rows")) })}>
            {p.errors.slice(0, 6).join(" · ")}
          </Banner>
        ) : p.rows.length ? (
          <p className="pl-note ok small" style={{ margin: 0 }}>
            <Icon name="check" size={14} /> {t("net.trd.paste.ok", { n: plural(p.rows.length, t("noun.row"), t("noun.rows")) })}: {preview(p.rows).slice(0, 4).join(" · ")}
          </p>
        ) : null}
      </div>
      {reason.dialog}
    </Dialog>
  );
}

// ---------------------------------------------------------------- tariffs
function TariffsTab() {
  const canEdit = useCan("trade_admin");
  const res = useLoad((s) => getTariffs(s), []);
  const [q, setQ] = useState("");
  const [dest, setDest] = useState("");
  const [paste, setPaste] = useState(false);
  const all = res.data?.items ?? [];
  const today = todayIso();
  const rows = all.filter((r) => (!dest || r.dest_country === dest) && (!q || `${r.hts_prefix} ${r.coo} ${r.layer} ${r.note}`.toLowerCase().includes(q.toLowerCase())));
  const dests = [...new Set(all.map((r) => r.dest_country))].sort();
  const columns = useMemo<Column<TariffRate>[]>(
    () => [
      { key: "dest", header: t("net.trd.dest"), width: "80px", sortValue: (r) => r.dest_country, render: (r) => <span className="mono">{r.dest_country}</span> },
      { key: "prefix", header: t("net.trd.prefix"), width: "120px", sortValue: (r) => r.hts_prefix, render: (r) => <span className="mono">{r.hts_prefix}</span> },
      { key: "coo", header: t("net.chg.coo"), width: "90px", sortValue: (r) => r.coo, render: (r) => (r.coo === "*" ? <span className="muted">{t("net.trd.anyCoo")}</span> : <span className="mono">{r.coo}</span>) },
      { key: "layer", header: t("net.trd.layer"), width: "110px", sortValue: (r) => r.layer, render: (r) => <span className="mono">{r.layer}</span> },
      { key: "rate", header: t("net.trd.rate"), width: "100px", align: "right", sortValue: (r) => r.rate_pct, exportValue: (r) => r.rate_pct, render: (r) => <span className="pl-num">{pct100(r.rate_pct, 2)}</span> },
      { key: "unit", header: t("net.trd.perUnit"), width: "120px", align: "right", drop: 2, render: (r) => <span className="pl-num">{r.per_unit === null ? "–" : `${formatNumber(r.per_unit, 4)} ${r.per_unit_currency ?? ""}`}</span> },
      { key: "valid", header: t("net.src.valid"), width: "190px", sortValue: (r) => r.valid_from, render: (r) => (
        <span className="row" style={{ gap: 6 }}>
          {formatDateRange(r.valid_from, r.valid_to) || "–"}
          {r.valid_from <= today && (!r.valid_to || r.valid_to >= today) ? <span className="badge ok"><Icon name="check" /> {t("net.trd.current")}</span> : null}
        </span>
      ) },
      { key: "note", header: t("net.label.note"), width: "minmax(160px, 1fr)", drop: 1, wrap: true, render: (r) => <span className="small">{r.note}</span> },
    ],
    [today],
  );
  return (
    <div className="col pl-gap" data-testid="trd-tariffs">
      <Banner tone="info">{t("net.trd.fictional")}</Banner>
      <FilterBar
        search={{ id: "trd-q", value: q, onChange: setQ, placeholder: t("net.trd.searchPh") }}
        chips={dest ? [{ key: "dest", label: t("net.trd.dest"), value: dest, onClear: () => setDest("") }] : []}
        end={
          <button type="button" className="btn primary sm" disabled={!canEdit} title={canEdit ? undefined : needsText("trade_admin")} onClick={() => setPaste(true)} data-testid="trd-tariff-paste">
            <Icon name="upload" /> {t("net.trd.btn.paste")}
          </button>
        }
      >
        <div className="field">
          <label htmlFor="trd-dest">{t("net.trd.dest")}</label>
          <select id="trd-dest" className="select sm" value={dest} onChange={(e) => setDest(e.target.value)}>
            <option value="">{t("net.trd.allDest")}</option>
            {dests.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </select>
        </div>
      </FilterBar>
      <MfgError error={res.error} onRetry={res.reload} />
      <section className="card card-table">
        <DataTable<TariffRate> rows={rows} columns={columns} rowKey={(r) => r.id} label={t("net.trd.tab.tariffs")} testId="trd-tariff-table" loading={res.loading && !res.data} exportName="tariffs" empty={t("net.trd.tariffEmpty")} />
      </section>
      {paste ? (
        <PasteDialog<TariffRateInput>
          title={t("net.trd.paste.tariffTitle")}
          columns={t("net.trd.paste.colsTariff")}
          parse={parseTariffs}
          preview={(r) => r.map((x) => `${x.dest_country} ${x.hts_prefix} ${x.coo} ${x.layer} ${x.rate_pct} %`)}
          onClose={() => setPaste(false)}
          save={async (rows, why) => {
            const r = await putTariffs(rows, why);
            toast(t("net.trd.toast.bulk", { i: r.inserted, u: r.updated }));
            res.reload();
          }}
        />
      ) : null}
    </div>
  );
}

// ---------------------------------------------------------------- FX
function FxTab() {
  const canEdit = useCan("trade_admin");
  const res = useLoad((s) => getFx(s), []);
  const [paste, setPaste] = useState(false);
  const items = res.data?.items ?? [];
  const pairs = [...new Set(items.map((r) => `${r.from_ccy}/${r.to_ccy}`))].sort();
  const months = [...new Set(items.map((r) => r.month))].sort().reverse();
  const by = new Map(items.map((r) => [`${r.from_ccy}/${r.to_ccy}|${r.month}`, r]));
  return (
    <div className="col pl-gap" data-testid="trd-fx">
      <div className="row wrap" style={{ justifyContent: "space-between", gap: 8 }}>
        <p className="small muted" style={{ margin: 0 }}>
          {t("net.trd.fxHint")}
        </p>
        <button type="button" className="btn primary sm" disabled={!canEdit} title={canEdit ? undefined : needsText("trade_admin")} onClick={() => setPaste(true)} data-testid="trd-fx-paste">
          <Icon name="upload" /> {t("net.trd.btn.paste")}
        </button>
      </div>
      <MfgError error={res.error} onRetry={res.reload} />
      {!res.data ? (
        <Spinner />
      ) : !items.length ? (
        <p className="muted card">{t("net.trd.fxEmpty")}</p>
      ) : (
        <section className="card card-table">
          <div className="pl-pivot-wrap">
            <table className="pl-pivot" aria-label={t("net.trd.tab.fx")} data-testid="trd-fx-grid">
              <thead>
                <tr>
                  <th scope="col">{t("net.label.month")}</th>
                  {pairs.map((p) => (
                    <th key={p} scope="col" className="mono">
                      {p}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {months.map((m) => (
                  <tr key={m}>
                    <th scope="row">{monthLabel(m)}</th>
                    {pairs.map((p) => {
                      const r = by.get(`${p}|${m}`);
                      return (
                        <td key={p} title={r?.source}>
                          {r ? formatNumber(r.rate, 6) : <span className="muted">–</span>}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
      {paste ? (
        <PasteDialog<FxRateInput>
          title={t("net.trd.paste.fxTitle")}
          columns={t("net.trd.paste.colsFx")}
          parse={parseFx}
          preview={(r) => r.map((x) => `${x.from_ccy}/${x.to_ccy} ${monthShort(x.month)} ${x.rate}`)}
          onClose={() => setPaste(false)}
          save={async (rows, why) => {
            const r = await putFx(rows, why);
            toast(t("net.trd.toast.bulk", { i: r.inserted, u: r.updated }));
            res.reload();
          }}
        />
      ) : null}
    </div>
  );
}

// ---------------------------------------------------------------- milestones
function MilestonesTab() {
  const canEdit = useCan("trade_admin");
  const reason = useChangeReason();
  const res = useLoad((s) => getMilestones(s), []);
  const [edit, setEdit] = useState<Milestone | "new" | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const items = res.data?.items ?? [];
  const strip = (m: Milestone): MilestoneInput => ({ code: m.code, name: m.name, dest_country: m.dest_country, family: m.family, hts_prefix: m.hts_prefix, rule: m.rule, effective: m.effective, note: m.note });
  const saveAll = async (list: MilestoneInput[]) => {
    const why = await reason.ask(t("net.trd.ms.what"));
    if (why === null) return false;
    setErr(null);
    try {
      await putMilestones(list, why);
      toast(t("net.src.toast.saved"));
      res.reload();
      return true;
    } catch (e) {
      setErr(e);
      return false;
    }
  };
  const columns = useMemo<Column<Milestone>[]>(
    () => [
      { key: "code", header: t("net.chg.code"), width: "150px", sortValue: (m) => m.code, render: (m) => <span className="mono">{m.code}</span> },
      { key: "name", header: t("net.scn.label.name"), width: "minmax(180px, 1fr)", render: (m) => m.name },
      { key: "scope", header: t("net.trd.ms.scope"), width: "160px", render: (m) => t("net.trd.ms.scopeTpl", { d: m.dest_country, s: m.family ? t("net.src.familyTpl", { f: m.family }) : t("net.trd.ms.htsTpl", { p: m.hts_prefix ?? "" }) }) },
      { key: "rule", header: t("net.trd.ms.rule"), width: "minmax(220px, 1fr)", wrap: true, render: (m) => <span className="small">{t("net.trd.ms.ruleTpl", { min: formatNumber(m.rule.min_pct, 1), c: m.rule.domestic_country, b: m.rule.basis === "value" ? t("net.trd.ms.value") : t("net.trd.ms.weight"), m: m.rule.material_classes.length ? m.rule.material_classes.join(", ") : t("net.trd.ms.allMaterials") })}</span> },
      { key: "eff", header: t("net.trd.ms.effective"), width: "130px", sortValue: (m) => m.effective, render: (m) => formatDateRange(m.effective, m.effective) },
      {
        key: "act",
        header: <span className="sr-only">{t("plan.label.actions")}</span>,
        label: t("plan.label.actions"),
        width: "60px",
        render: (m) => (
          <button type="button" className="btn ghost sm icon" disabled={!canEdit} aria-label={t("net.trd.ms.edit")} onClick={() => setEdit(m)}>
            <Icon name="settings" />
          </button>
        ),
      },
    ],
    [canEdit],
  );
  return (
    <div className="col pl-gap" data-testid="trd-milestones">
      <div className="row wrap" style={{ justifyContent: "space-between" }}>
        <p className="small muted" style={{ margin: 0 }}>
          {t("net.trd.ms.hint")}
        </p>
        <button type="button" className="btn primary sm" disabled={!canEdit} title={canEdit ? undefined : needsText("trade_admin")} onClick={() => setEdit("new")} data-testid="trd-ms-new">
          <Icon name="plus" /> {t("net.trd.ms.new")}
        </button>
      </div>
      <MfgError error={err} />
      <MfgError error={res.error} onRetry={res.reload} />
      <section className="card card-table">
        <DataTable<Milestone> rows={items} columns={columns} rowKey={(m) => m.id} label={t("net.trd.tab.milestones")} testId="trd-ms-table" loading={res.loading && !res.data} exportName="milestones" empty={t("net.trd.ms.empty")} />
      </section>
      {edit ? (
        <MilestoneDialog
          m={edit === "new" ? null : edit}
          onClose={() => setEdit(null)}
          onSave={async (x) => {
            const list = edit === "new" ? [...items.map(strip), x] : items.map((y) => (y.id === edit.id ? x : strip(y)));
            if (await saveAll(list)) setEdit(null);
          }}
        />
      ) : null}
      {reason.dialog}
    </div>
  );
}

function MilestoneDialog({ m, onClose, onSave }: { m: Milestone | null; onClose(): void; onSave(x: MilestoneInput): Promise<void> }) {
  const [f, setF] = useState<MilestoneInput>(m ?? { code: "", name: "", dest_country: "US", family: "", hts_prefix: null, rule: { domestic_country: "US", basis: "value", material_classes: [], include_conversion: false, min_pct: 100 }, effective: todayIso(), note: "" });
  const [classes, setClasses] = useState(f.rule.material_classes.join(", "));
  const [busy, setBusy] = useState(false);
  const setR = (patch: Partial<MilestoneInput["rule"]>) => setF((x) => ({ ...x, rule: { ...x.rule, ...patch } }));
  const valid = /^[A-Z0-9_-]{2,32}$/.test(f.code) && f.name.trim() && /^[A-Z]{2}$/.test(f.dest_country) && (f.family || f.hts_prefix) && f.rule.min_pct >= 0 && f.rule.min_pct <= 100 && f.effective;
  return (
    <Dialog
      title={m ? t("net.trd.ms.edit") : t("net.trd.ms.new")}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose} data-dialog-close>
            {t("common.cancel")}
          </button>
          <button
            type="button"
            className="btn primary"
            disabled={!valid || busy}
            onClick={() => {
              setBusy(true);
              void onSave({ ...f, family: f.family || null, hts_prefix: f.hts_prefix || null, rule: { ...f.rule, material_classes: classes.split(",").map((s) => s.trim().toLowerCase()).filter(Boolean) } }).finally(() => setBusy(false));
            }}
            data-testid="trd-ms-save"
          >
            <Icon name="save" /> {t("net.btn.save")}
          </button>
        </>
      }
    >
      <div className="col pl-gap">
        <div className="row wrap" style={{ gap: 12 }}>
          <div className="field">
            <label htmlFor="ms-code">{t("net.chg.code")}</label>
            <input id="ms-code" className="input mono" maxLength={32} value={f.code} onChange={(e) => setF({ ...f, code: e.target.value.toUpperCase() })} />
          </div>
          <div className="field" style={{ flex: 1 }}>
            <label htmlFor="ms-name">{t("net.scn.label.name")}</label>
            <input id="ms-name" className="input" maxLength={120} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} />
          </div>
        </div>
        <div className="row wrap" style={{ gap: 12 }}>
          <div className="field">
            <label htmlFor="ms-dest">{t("net.trd.dest")}</label>
            <input id="ms-dest" className="input mono" style={{ width: 60 }} maxLength={2} value={f.dest_country} onChange={(e) => setF({ ...f, dest_country: e.target.value.toUpperCase() })} />
          </div>
          <div className="field">
            <label htmlFor="ms-fam">{t("net.label.family")}</label>
            <input id="ms-fam" className="input mono" style={{ width: 110 }} value={f.family ?? ""} onChange={(e) => setF({ ...f, family: e.target.value || null })} />
          </div>
          <div className="field">
            <label htmlFor="ms-hts">{t("net.trd.ms.orHts")}</label>
            <input id="ms-hts" className="input mono" style={{ width: 120 }} maxLength={10} value={f.hts_prefix ?? ""} onChange={(e) => setF({ ...f, hts_prefix: e.target.value.replace(/\D/g, "") || null })} />
          </div>
          <div className="field">
            <label htmlFor="ms-eff">{t("net.trd.ms.effective")}</label>
            <DateInput id="ms-eff" value={f.effective} onChange={(v) => setF({ ...f, effective: v })} />
          </div>
        </div>
        <fieldset className="pl-fieldset">
          <legend>{t("net.trd.ms.rule")}</legend>
          <div className="row wrap" style={{ gap: 12, alignItems: "flex-end" }}>
            <div className="field">
              <label htmlFor="ms-dc">{t("net.trd.ms.domestic")}</label>
              <input id="ms-dc" className="input mono" style={{ width: 60 }} maxLength={2} value={f.rule.domestic_country} onChange={(e) => setR({ domestic_country: e.target.value.toUpperCase() })} />
            </div>
            <Segmented value={f.rule.basis} onChange={(v) => setR({ basis: v as "value" | "weight" })} label={t("net.trd.ms.basis")} options={[{ value: "value", label: t("net.trd.ms.value") }, { value: "weight", label: t("net.trd.ms.weight") }]} />
            <div className="field">
              <label htmlFor="ms-min">{t("net.trd.ms.min")}</label>
              <input id="ms-min" className="input pl-w-140" type="number" min={0} max={100} value={f.rule.min_pct} onChange={(e) => setR({ min_pct: Number(e.target.value) })} />
            </div>
            <div className="field">
              <label htmlFor="ms-mc">{t("net.trd.ms.materials")}</label>
              <input id="ms-mc" className="input mono" value={classes} onChange={(e) => setClasses(e.target.value)} placeholder="steel" />
              <span className="hint">{t("net.trd.ms.materialsHint")}</span>
            </div>
          </div>
          <label className="row small" style={{ gap: 6 }}>
            <input type="checkbox" checked={f.rule.include_conversion} disabled={f.rule.basis === "weight"} onChange={(e) => setR({ include_conversion: e.target.checked })} /> {t("net.trd.ms.conversion")}
          </label>
        </fieldset>
        <div className="field">
          <label htmlFor="ms-note">{t("net.label.note")}</label>
          <input id="ms-note" className="input" maxLength={500} value={f.note} onChange={(e) => setF({ ...f, note: e.target.value })} />
        </div>
      </div>
    </Dialog>
  );
}

// ---------------------------------------------------------------- country risk
function CountryRiskTab() {
  const canEdit = useCan("trade_admin");
  const reason = useChangeReason();
  const res = useLoad((s) => getCountryRisk(s), []);
  const [rows, setRows] = useState<CountryRiskInput[] | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const list = rows ?? (res.data?.items ?? []).map((r) => ({ country: r.country, score: r.score, note: r.note }));
  const valid = list.every((r) => /^[A-Z]{2}$/.test(r.country) && r.score >= 0 && r.score <= 25);
  const upd = (i: number, p: Partial<CountryRiskInput>) => setRows(list.map((r, j) => (j === i ? { ...r, ...p } : r)));
  const save = async () => {
    const why = await reason.ask(t("net.trd.cr.what"));
    if (why === null) return;
    setErr(null);
    try {
      await putCountryRisk(list, why);
      toast(t("net.src.toast.saved"));
      setRows(null);
      res.reload();
    } catch (e) {
      setErr(e);
    }
  };
  return (
    <div className="col pl-gap" data-testid="trd-risk">
      <p className="small muted" style={{ margin: 0 }}>
        {t("net.trd.cr.hint")}
      </p>
      <MfgError error={err} />
      <MfgError error={res.error} onRetry={res.reload} />
      <section className="card" style={{ maxWidth: 720 }}>
        <table className="pl-pivot" aria-label={t("net.trd.tab.risk")}>
          <thead>
            <tr>
              <th scope="col">{t("net.chg.country")}</th>
              <th scope="col">{t("net.trd.cr.score")}</th>
              <th scope="col" style={{ textAlign: "left" }}>
                {t("net.label.note")}
              </th>
              <th scope="col">
                <span className="sr-only">{t("plan.label.actions")}</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {list.map((r, i) => (
              <tr key={i}>
                <th scope="row">
                  <input className="input sm mono" style={{ width: 60 }} maxLength={2} aria-label={t("net.chg.country")} value={r.country} disabled={!canEdit} onChange={(e) => upd(i, { country: e.target.value.toUpperCase() })} />
                </th>
                <td>
                  <input className="input sm" style={{ width: 70 }} type="number" min={0} max={25} aria-label={t("net.trd.cr.score")} value={r.score} disabled={!canEdit} onChange={(e) => upd(i, { score: Number(e.target.value) })} />
                </td>
                <td style={{ textAlign: "left" }}>
                  <input className="input sm" style={{ width: "100%" }} maxLength={200} aria-label={t("net.label.note")} value={r.note} disabled={!canEdit} onChange={(e) => upd(i, { note: e.target.value })} />
                </td>
                <td>
                  {canEdit ? (
                    <button type="button" className="btn ghost sm icon" aria-label={t("net.chg.removeRow")} onClick={() => setRows(list.filter((_, j) => j !== i))}>
                      <Icon name="x" />
                    </button>
                  ) : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {canEdit ? (
          <div className="row" style={{ gap: 8, marginTop: 8 }}>
            <button type="button" className="btn sm" onClick={() => setRows([...list, { country: "", score: 10, note: "" }])}>
              <Icon name="plus" /> {t("net.chg.addRow")}
            </button>
            <button type="button" className="btn primary sm" disabled={!rows || !valid} onClick={() => void save()}>
              <Icon name="save" /> {t("net.btn.save")}
            </button>
          </div>
        ) : null}
      </section>
      {reason.dialog}
    </div>
  );
}

// ---------------------------------------------------------------- reports
function ReportsTab() {
  const navigate = useNavigate();
  const res = useLoad((s) => listTradeReports(s), []);
  usePolling(res.reload, (res.data?.items ?? []).some((r) => isRunning(r.status)));
  const [dialog, setDialog] = useState(false);
  const columns = useMemo<Column<TradeReport>[]>(
    () => [
      { key: "number", header: t("net.trd.rep.report"), width: "140px", sortValue: (r) => r.number, render: (r) => <Link to={mfgPaths.tradeReport(r.id)} className="mono" onClick={(e) => e.stopPropagation()}>{r.number}</Link> },
      { key: "status", header: t("net.run.head.status"), width: "130px", render: (r) => <JobChip s={r.status} /> },
      { key: "range", header: t("net.trd.rep.range"), width: "200px", render: (r) => formatDateRange(r.params.from, r.params.to) },
      { key: "ms", header: t("net.trd.tab.milestones"), width: "minmax(160px, 1fr)", render: (r) => (r.result?.milestones ?? []).map((m) => m.code).join(", ") || plural(r.params.milestone_ids.length, t("net.trd.rep.milestone"), t("net.trd.rep.milestones")) },
      { key: "created", header: t("net.run.head.created"), width: "150px", sortValue: (r) => r.created_at, render: (r) => formatDateTime(r.created_at) },
    ],
    [],
  );
  return (
    <div className="col pl-gap" data-testid="trd-reports">
      <div className="row wrap" style={{ justifyContent: "space-between" }}>
        <p className="small muted" style={{ margin: 0 }}>
          {t("net.trd.rep.hint")}
        </p>
        <button type="button" className="btn primary sm" onClick={() => setDialog(true)} data-testid="trd-rep-new">
          <Icon name="play" /> {t("net.trd.rep.new")}
        </button>
      </div>
      <MfgError error={res.error} onRetry={res.reload} />
      <section className="card card-table">
        <DataTable<TradeReport> rows={res.data?.items ?? []} columns={columns} rowKey={(r) => r.id} label={t("net.trd.tab.reports")} testId="trd-rep-table" loading={res.loading && !res.data} onRowClick={(r) => navigate(mfgPaths.tradeReport(r.id))} onActivate={(r) => navigate(mfgPaths.tradeReport(r.id))} exportName="tariff-reports" empty={t("net.trd.rep.empty")} />
      </section>
      {dialog ? <NewReportDialog onClose={() => setDialog(false)} onStarted={(r) => navigate(mfgPaths.tradeReport(r.id))} /> : null}
    </div>
  );
}

function NewReportDialog({ onClose, onStarted }: { onClose(): void; onStarted(r: TradeReport): void }) {
  const ms = useLoad((s) => getMilestones(s), []);
  const scs = useLoad((s) => listScenarios({}, s).catch(() => ({ items: [] })), []);
  const [ids, setIds] = useState<string[]>([]);
  const d = new Date();
  const [from, setFrom] = useState(`${d.getFullYear() - 1}-${String(d.getMonth() + 1).padStart(2, "0")}-01`);
  const [to, setTo] = useState(`${d.getFullYear() + 1}-${String(d.getMonth() + 1).padStart(2, "0")}-01`);
  const [groupBy, setGroupBy] = useState<"family" | "item">("family");
  const [scenario, setScenario] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  useEffect(() => {
    if (ms.data && !ids.length) setIds(ms.data.items.map((m) => m.id));
  }, [ms.data]); // eslint-disable-line react-hooks/exhaustive-deps
  const go = async () => {
    setBusy(true);
    setErr(null);
    try {
      onStarted(await createTradeReport({ milestone_ids: ids, from, to, group_by: groupBy, projection: { scenario_id: scenario || null } }));
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog
      title={t("net.trd.rep.new")}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose} data-dialog-close>
            {t("common.cancel")}
          </button>
          <button type="button" className="btn primary" disabled={!ids.length || !from || !to || to < from || busy} onClick={() => void go()} data-testid="trd-rep-start">
            <Icon name="play" /> {t("net.trd.rep.start")}
          </button>
        </>
      }
    >
      <div className="col pl-gap">
        <MfgError error={err} />
        <fieldset className="pl-fieldset">
          <legend>{t("net.trd.tab.milestones")}</legend>
          {(ms.data?.items ?? []).map((m) => (
            <label key={m.id} className="row small" style={{ gap: 6 }}>
              <input type="checkbox" checked={ids.includes(m.id)} onChange={() => setIds((x) => (x.includes(m.id) ? x.filter((y) => y !== m.id) : [...x, m.id]))} />
              <span className="mono">{m.code}</span> {m.name}
            </label>
          ))}
        </fieldset>
        <div className="row wrap" style={{ gap: 12 }}>
          <div className="field">
            <label htmlFor="rep-from">{t("net.dem.from")}</label>
            <DateInput id="rep-from" value={from} onChange={setFrom} />
          </div>
          <div className="field">
            <label htmlFor="rep-to">{t("net.dem.to")}</label>
            <DateInput id="rep-to" value={to} onChange={setTo} />
          </div>
          <div className="field">
            <span className="small muted">{t("net.fin.groupBy")}</span>
            <Segmented value={groupBy} onChange={(v) => setGroupBy(v as "family" | "item")} label={t("net.fin.groupBy")} options={[{ value: "family", label: t("net.label.family") }, { value: "item", label: t("net.trd.rep.item") }]} />
          </div>
        </div>
        <div className="field">
          <label htmlFor="rep-sc">{t("net.trd.rep.projection")}</label>
          <select id="rep-sc" className="select" value={scenario} onChange={(e) => setScenario(e.target.value)}>
            <option value="">{t("net.trd.rep.approvedPlan")}</option>
            {(scs.data?.items ?? [])
              .filter((s) => s.status === "completed")
              .map((s) => (
                <option key={s.id} value={s.id}>
                  {s.number} · {s.name}
                </option>
              ))}
          </select>
          <span className="hint">{t("net.trd.rep.projectionHint")}</span>
        </div>
      </div>
    </Dialog>
  );
}
