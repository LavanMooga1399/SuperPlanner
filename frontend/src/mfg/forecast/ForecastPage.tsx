/**
 * Forecast workbench `/mfg/forecast` (M8 4, 12): version picker and filters, the item list with accuracy badges, and
 * the item panel - chart (history, cleaned, fitted, statistical, final, orders consumed), period grid whose final
 * cells open an override (always with a reason; drafts only), family override, outlier reset, and the version
 * actions: run forecast (guided, expert settings folded), activate (MRP then uses it), delete draft.
 */
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { Banner } from "../../components/Banner";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { Dialog } from "../../components/Dialog";
import { FilterBar, type FilterChip } from "../../components/FilterBar";
import { Icon } from "../../components/Icon";
import { PageHeader } from "../../components/PageHeader";
import { toast } from "../../components/Toast";
import { plural, t } from "../../lib/i18n";
import { formatDateTime, formatNumber } from "../../lib/locale";
import { activateVersion, createForecastRun, createOverride, deleteVersion, getForecastItem, getVersionLines, listForecastRuns, listVersions, removeOverride, updateHistory } from "../api/clientM8";
import type { Bucket, ForecastGrid, ForecastGridRow, ForecastItemDetail, ForecastOverride, ForecastVersion, OverrideMode } from "../api/typesM8";
import { DataTable } from "../components/DataTable";
import { MfgError, Spinner } from "../components/Feedback";
import { VirtualTable, type Column } from "../components/VirtualTable";
import { mfgPaths } from "../lib/paths";
import { needsText, useCan } from "../lib/permissions";
import { setSearchParam, usePaged } from "../lib/usePaged";
import { usePolling } from "../lib/usePolling";
import { useDebounced, useLoad } from "../lib/useMfg";
import { useChangeReason } from "../qa/ChangeReason";
import { ForecastChart } from "./ForecastChart";
import { BiasBadge, ClassTag, codeText, Facts, FLAG_CODES, isRunning, ItemLink, itemLabel, methodText, METHODS, classText, num, pct, periodLabel, periodShort, VersionChip, WapeBadge, signedPct } from "./shared";

const ABC = ["A", "B", "C"];
const XYZ = ["X", "Y", "Z"];

export function ForecastPage() {
  const [params, setParams] = useSearchParams();
  const set = (k: string, v: string) => setSearchParam(setParams, k, v);
  const canEdit = useCan("forecast_edit");
  const canApprove = useCan("forecast_approve");
  const reason = useChangeReason();
  const [q, setQ] = useState(params.get("q") ?? "");
  const dq = useDebounced(q.trim(), 250);
  useEffect(() => set("q", dq), [dq]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    document.title = t("plan.fc.title");
  }, []);
  const versions = useLoad((s) => listVersions({ limit: 50 }, s), []);
  const runs = useLoad((s) => listForecastRuns({ limit: 1 }, s), []);
  const lastRun = runs.data?.items[0] ?? null;
  const running = isRunning(lastRun?.status);
  usePolling(runs.reload, running);
  const [wasRunning, setWasRunning] = useState(false);
  useEffect(() => {
    if (running) setWasRunning(true);
    else if (wasRunning && lastRun) {
      setWasRunning(false);
      versions.reload();
      if (lastRun.status === "done") {
        toast(t("plan.fc.toast.runDone", { n: lastRun.number }));
        if (lastRun.version_id) set("v", lastRun.version_id);
      }
    }
  }, [running]); // eslint-disable-line react-hooks/exhaustive-deps

  const list = versions.data?.items ?? [];
  const vParam = params.get("v") ?? "";
  const version: ForecastVersion | null = list.find((v) => v.id === vParam) ?? list.find((v) => v.status === "active") ?? list[0] ?? null;
  const filters = { abc: params.get("abc") ?? "", xyz: params.get("xyz") ?? "", method: params.get("method") ?? "", flag: params.get("flag") ?? "", family: params.get("family") ?? "" };
  const key = JSON.stringify([version?.id, dq, filters]);
  const grid = usePaged<ForecastGridRow, ForecastGrid>(
    version ? (offset, limit, signal) => getVersionLines(version.id, { q: dq || undefined, ...Object.fromEntries(Object.entries(filters).filter(([, v]) => v)), limit, offset }, signal) : null,
    [key],
    100,
  );
  const itemId = params.get("item") ?? "";
  const selected = grid.rows.find((r) => r.item.id === itemId) ?? null;
  useEffect(() => {
    if (!itemId && grid.rows.length) set("item", grid.rows[0].item.id);
  }, [grid.rows.length, itemId]); // eslint-disable-line react-hooks/exhaustive-deps

  const [dialog, setDialog] = useState<null | "run" | "activate" | "delete">(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const draft = version?.status === "draft";
  const active = list.find((v) => v.status === "active") ?? null;

  const activate = async () => {
    if (!version) return;
    const r = await reason.ask(t("plan.fc.str.versionWhat", { n: version.number }));
    if (r === null) return;
    setBusy(true);
    setErr(null);
    try {
      await activateVersion(version.id, version.row_version, r);
      toast(t("plan.fc.toast.activated", { n: version.number }));
      setDialog(null);
      versions.reload();
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };
  const remove = async () => {
    if (!version) return;
    setBusy(true);
    setErr(null);
    try {
      await deleteVersion(version.id, version.row_version);
      toast(t("plan.fc.toast.deleted", { n: version.number }));
      setDialog(null);
      set("v", "");
      versions.reload();
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };

  const columns = useMemo<Column<ForecastGridRow>[]>(
    () => [
      { key: "item", header: t("plan.fc.head.item"), width: "minmax(170px, 1fr)", exportValue: (r) => itemLabel(r.item), sortValue: (r) => r.item.part_number, render: (r) => <ItemLink item={r.item} /> },
      { key: "class", header: t("plan.fc.head.class"), width: "56px", exportValue: (r) => `${r.abc ?? ""}${r.xyz ?? ""}`, sortValue: (r) => `${r.abc ?? "Z"}${r.xyz ?? "Z"}`, render: (r) => <ClassTag abc={r.abc} xyz={r.xyz} /> },
      { key: "method", header: t("plan.fc.head.method"), width: "120px", drop: 1, sortValue: (r) => methodText(r.method), render: (r) => <span className="mfg-ellipsis">{methodText(r.method)}</span> },
      { key: "wape", header: t("plan.fc.head.wape"), width: "84px", align: "right", sortValue: (r) => r.wape ?? -1, exportValue: (r) => r.wape, render: (r) => <WapeBadge v={r.wape} /> },
      { key: "bias", header: t("plan.fc.head.bias"), width: "84px", align: "right", sortValue: (r) => r.bias ?? 0, exportValue: (r) => r.bias, render: (r) => <BiasBadge v={r.bias} /> },
      {
        key: "flags",
        header: t("plan.fc.head.flags"),
        label: t("plan.fc.head.flags"),
        width: "56px",
        align: "center",
        exportValue: (r) => r.flags.join(" "),
        render: (r) =>
          r.flags.length ? (
            <span className="badge warn" title={r.flags.map(codeText).join(", ")} aria-label={r.flags.map(codeText).join(", ")}>
              <Icon name="flag" />
              {r.flags.length}
            </span>
          ) : null,
      },
    ],
    [],
  );

  const chips: FilterChip[] = [];
  if (dq) chips.push({ key: "q", label: t("plan.label.search"), value: dq, onClear: () => setQ("") });
  const fLabels: Record<string, string> = { abc: t("plan.fc.label.abc"), xyz: t("plan.fc.label.xyz"), method: t("plan.fc.head.method"), flag: t("plan.fc.head.flags"), family: t("plan.fc.label.family") };
  for (const [k, v] of Object.entries(filters)) if (v) chips.push({ key: k, label: fLabels[k], value: k === "method" ? methodText(v) : k === "flag" ? codeText(v) : v, onClear: () => set(k, "") });

  const facts: [string, ReactNode][] = version
    ? [
        [t("plan.fc.fact.bucket"), version.bucket === "m" ? t("plan.fc.bucket.m") : t("plan.fc.bucket.w")],
        [t("plan.fc.fact.horizon"), `${periodLabel(version.start, version.bucket)} · ${plural(version.periods, version.bucket === "m" ? t("plan.noun.month") : t("plan.noun.week"), version.bucket === "m" ? t("plan.noun.months") : t("plan.noun.weeks"))}`],
        [t("plan.fc.fact.items"), formatNumber(version.item_count)],
        [t("plan.fc.fact.overrides"), formatNumber(version.override_count)],
        ...(version.activated_at ? ([[t("plan.fc.fact.activated"), formatDateTime(version.activated_at)]] as [string, string][]) : []),
      ]
    : [];

  return (
    <div className="col gap-lg" data-testid="fc-page">
      <PageHeader
        title={t("plan.fc.title")}
        meta={version ? <VersionChip s={version.status} /> : null}
        description={version ? t("plan.fc.tpl.versionLine", { n: version.number, name: version.name || version.number }) : t("plan.fc.desc")}
        facts={facts}
        actions={
          <>
            <Link className="btn" to={mfgPaths.forecastAccuracy()} data-testid="fc-accuracy-link">
              <Icon name="chart" /> {t("plan.fc.btn.accuracy")}
            </Link>
            {draft && canEdit ? (
              <button type="button" className="btn ghost" onClick={() => setDialog("delete")} data-testid="fc-delete">
                <Icon name="trash" /> {t("plan.fc.btn.deleteDraft")}
              </button>
            ) : null}
            {draft ? (
              <button type="button" className="btn" disabled={!canApprove} title={canApprove ? undefined : needsText("forecast_approve")} onClick={() => setDialog("activate")} data-testid="fc-activate">
                <Icon name="check" /> {t("plan.fc.btn.activate")}
              </button>
            ) : null}
            <button type="button" className="btn primary" disabled={!canEdit || running} title={canEdit ? undefined : needsText("forecast_edit")} onClick={() => setDialog("run")} data-testid="fc-run">
              <Icon name="play" /> {t("plan.fc.btn.run")}
            </button>
          </>
        }
      />
      {running && lastRun ? (
        <Banner tone="accent" icon="loader" role="status" testId="fc-running">
          {t("plan.fc.text.running", { n: lastRun.number })}
        </Banner>
      ) : lastRun?.status === "failed" ? (
        <Banner tone="danger" role="alert" title={t("plan.fc.text.runFailed", { n: lastRun.number })}>
          {lastRun.error ?? ""}
        </Banner>
      ) : null}
      <MfgError error={versions.error} onRetry={versions.reload} />
      <MfgError error={err} />
      {versions.loading && !versions.data ? <Spinner /> : null}
      {versions.data && !list.length ? (
        <div className="card card-body pl-empty" data-testid="fc-empty">
          <Icon name="chart" size={20} />
          <div>
            <strong>{t("plan.fc.empty.title")}</strong>
            <p className="muted">{t("plan.fc.empty.body")}</p>
          </div>
        </div>
      ) : null}
      {version ? (
        <>
          <FilterBar
            search={{ id: "fc-q", value: q, onChange: setQ, placeholder: t("plan.fc.ph.search"), testId: "fc-search" }}
            chips={chips}
            onClearAll={() => {
              setQ("");
              setParams(version ? { v: version.id } : {}, { replace: true });
            }}
            pageKey="forecast"
          >
            <div className="field">
              <label htmlFor="fc-version">{t("plan.fc.label.version")}</label>
              <select id="fc-version" className="select" value={version.id} onChange={(e) => setParams({ v: e.target.value }, { replace: true })} data-testid="fc-version">
                {list.map((v) => (
                  <option key={v.id} value={v.id}>
                    {t("plan.fc.tpl.versionOption", { n: v.number, status: v.status === "active" ? t("plan.version.active") : v.status === "draft" ? t("plan.version.draft") : t("plan.version.archived") })}
                  </option>
                ))}
              </select>
            </div>
            <FilterSelect id="fc-abc" label={fLabels.abc} value={filters.abc} onChange={(v) => set("abc", v)} options={ABC.map((x) => ({ value: x, label: x }))} />
            <FilterSelect id="fc-xyz" label={fLabels.xyz} value={filters.xyz} onChange={(v) => set("xyz", v)} options={XYZ.map((x) => ({ value: x, label: x }))} />
            <FilterSelect id="fc-method" label={fLabels.method} value={filters.method} onChange={(v) => set("method", v)} options={METHODS.map((m) => ({ value: m, label: methodText(m) }))} />
            <FilterSelect id="fc-flag" label={fLabels.flag} value={filters.flag} onChange={(v) => set("flag", v)} options={FLAG_CODES.map((c) => ({ value: c, label: codeText(c) }))} />
            <FamilyFilter value={filters.family} onChange={(v) => set("family", v)} label={fLabels.family} />
          </FilterBar>
          <div className="pl-split">
            <section className="card card-table pl-split-list" aria-label={t("plan.fc.aria.items")}>
              <MfgError error={grid.error} onRetry={grid.reload} />
              <VirtualTable
                rows={grid.rows}
                columns={columns}
                rowKey={(r) => r.item.id}
                label={t("plan.fc.aria.items")}
                testId="fc-items"
                height="min(64vh, 620px)"
                loading={grid.loading && !grid.rows.length}
                totalCount={grid.total}
                onEndReached={grid.onEndReached}
                onRowClick={(r) => set("item", r.item.id)}
                onActivate={(r) => set("item", r.item.id)}
                rowExtras={(r) => ({ testId: "fc-item-row", ariaSelected: r.item.id === itemId, className: r.item.id === itemId ? "mfg-selected" : undefined, data: { item: r.item.part_number } })}
                exportName="forecast-items"
                empty={t("plan.fc.empty.items")}
                card={{ title: "item", status: "wape", fields: ["class", "method", "bias"] }}
                footer={<span>{t("plan.tpl.showing", { n: t("common.nOfM", { n: formatNumber(grid.rows.length), m: formatNumber(grid.total) }), noun: t("plan.noun.items") })}</span>}
              />
            </section>
            <section className="pl-split-panel" aria-label={t("plan.fc.aria.panel")}>
              {itemId ? (
                <ItemPanel key={`${version.id}:${itemId}`} itemId={itemId} version={version} row={selected} periods={grid.last?.periods ?? []} canEdit={canEdit && draft} onChanged={() => {
                  grid.reload();
                  versions.reload();
                }} />
              ) : (
                <div className="card card-body muted">{t("plan.fc.text.pickItem")}</div>
              )}
            </section>
          </div>
        </>
      ) : null}
      {dialog === "run" ? (
        <RunDialog
          bucket={version?.bucket ?? "m"}
          onClose={() => setDialog(null)}
          onStarted={() => {
            setDialog(null);
            runs.reload();
          }}
        />
      ) : null}
      {dialog === "activate" && version ? (
        <ConfirmDialog title={t("plan.fc.dlg.activateTitle", { n: version.number })} confirmLabel={t("plan.fc.btn.activate")} busy={busy} onConfirm={() => void activate()} onCancel={() => setDialog(null)}>
          <p>{t("plan.fc.dlg.activateBody")}</p>
          {active ? <p className="muted">{t("plan.fc.dlg.activateArchives", { n: active.number })}</p> : null}
        </ConfirmDialog>
      ) : null}
      {dialog === "delete" && version ? (
        <ConfirmDialog title={t("plan.fc.dlg.deleteTitle", { n: version.number })} confirmLabel={t("plan.fc.btn.deleteDraft")} danger busy={busy} onConfirm={() => void remove()} onCancel={() => setDialog(null)}>
          <p>{t("plan.fc.dlg.deleteBody")}</p>
        </ConfirmDialog>
      ) : null}
      {reason.dialog}
    </div>
  );
}

function FilterSelect({ id, label, value, onChange, options }: { id: string; label: string; value: string; onChange(v: string): void; options: { value: string; label: string }[] }) {
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <select id={id} className="select" value={value} onChange={(e) => onChange(e.target.value)} data-testid={id}>
        <option value="">{t("plan.label.any")}</option>
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </div>
  );
}

function FamilyFilter({ value, onChange, label }: { value: string; onChange(v: string): void; label: string }) {
  const [text, setText] = useState(value);
  const d = useDebounced(text.trim(), 300);
  useEffect(() => setText(value), [value]);
  useEffect(() => {
    if (d !== value) onChange(d);
  }, [d]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <div className="field">
      <label htmlFor="fc-family">{label}</label>
      <input id="fc-family" className="input pl-w-140" value={text} onChange={(e) => setText(e.target.value)} placeholder={t("plan.fc.ph.family")} />
    </div>
  );
}

// ---------------------------------------------------------------- item panel
interface OverrideDraft {
  scope: "item" | "family";
  from: string;
  to: string;
  mode: OverrideMode;
  value: string;
}

function ItemPanel({ itemId, version, row, periods, canEdit, onChanged }: { itemId: string; version: ForecastVersion; row: ForecastGridRow | null; periods: string[]; canEdit: boolean; onChanged(): void }) {
  const detail = useLoad((s) => getForecastItem(itemId, { version_id: version.id }, s), [itemId, version.id]);
  const [ov, setOv] = useState<OverrideDraft | null>(null);
  const [removing, setRemoving] = useState<ForecastOverride | null>(null);
  const [resetting, setResetting] = useState<ForecastItemDetail["history"][number] | null>(null);
  const d = detail.data;
  if (detail.error && !d) return <MfgError error={detail.error} onRetry={detail.reload} />;
  if (!d) return <div className="card card-body"><Spinner /></div>;
  const ps = periods.length ? periods : d.forecast.map((f) => f.period_start);
  const changed = () => {
    detail.reload();
    onChanged();
  };
  const m = d.method;
  const outliers = d.history.filter((h) => h.outlier || (h.cleaned_qty !== null && h.cleaned_qty !== h.qty));
  return (
    <div className="col pl-gap" data-testid="fc-panel" data-item={d.item.part_number}>
      <div className="card">
        <div className="card-header pl-card-header">
          <h2 className="pl-h2">
            <ItemLink item={d.item} />
          </h2>
          {canEdit ? (
            <button type="button" className="btn sm" onClick={() => setOv({ scope: "item", from: ps[0] ?? "", to: ps[ps.length - 1] ?? "", mode: "pct", value: "" })} data-testid="fc-override">
              <Icon name="plus" /> {t("plan.fc.btn.override")}
            </button>
          ) : null}
        </div>
        <div className="card-body col pl-gap">
          <Facts
            testId="fc-facts"
            rows={[
              [t("plan.fc.head.class"), <span key="c"><ClassTag abc={d.abc} xyz={d.xyz} /> {m ? <span className="muted">{classText(m.class)}</span> : null}</span>],
              [t("plan.fc.head.method"), m ? <span key="m" title={Object.entries(m.params).map(([k, v]) => `${k} ${v}`).join(", ")}>{methodText(m.name)}</span> : "–"],
              [t("plan.fc.fact.holdout"), <WapeBadge key="w" v={m?.holdout_wape} />],
              [t("plan.fc.head.bias"), <BiasBadge key="b" v={m?.bias} />],
              [t("plan.fc.fact.lag1"), `${pct(d.accuracy.lag1_wape, 0)} · ${signedPct(d.accuracy.lag1_bias)}`],
              [t("plan.fc.fact.lag3"), `${pct(d.accuracy.lag3_wape, 0)} · ${signedPct(d.accuracy.lag3_bias)}`],
            ]}
          />
          {m?.flags.length ? (
            <div className="row wrap" style={{ gap: 6 }}>
              {m.flags.map((f) => (
                <span key={f} className="badge warn" data-testid="fc-flag" data-code={f}>
                  <Icon name="flag" /> {codeText(f)}
                </span>
              ))}
            </div>
          ) : null}
          <ForecastChart d={d} uom={d.item.uom} />
          {outliers.length ? (
            <div className="pl-note" data-testid="fc-outliers">
              <Icon name="alert" size={14} />
              <span>{t("plan.fc.text.outliers", { n: plural(outliers.length, t("plan.noun.period"), t("plan.noun.periods")) })}</span>
              {outliers.map((h) => (
                <span key={h.id} className="pl-outlier">
                  {periodLabel(h.period_start, d.bucket)}: <s>{num(h.qty)}</s> → {num(h.cleaned_qty)}
                  {canEdit ? (
                    <button type="button" className="btn ghost sm" onClick={() => setResetting(h)} data-testid="fc-outlier-reset">
                      {t("plan.fc.btn.useActual")}
                    </button>
                  ) : null}
                </span>
              ))}
            </div>
          ) : null}
        </div>
      </div>
      <PeriodGrid d={d} periods={ps} row={row} canEdit={canEdit} onEdit={(p, v) => setOv({ scope: "item", from: p, to: p, mode: "abs", value: String(Math.round(v)) })} />
      <section className="card card-table" aria-label={t("plan.fc.ov.title")}>
        <div className="card-header pl-card-header">
          <h3>{t("plan.fc.ov.title")}</h3>
        </div>
        <DataTable<ForecastOverride>
          rows={d.overrides.filter((o) => !o.removed_at)}
          rowKey={(o) => o.id}
          label={t("plan.fc.ov.title")}
          testId="fc-overrides"
          columnSettings={false}
          empty={canEdit ? t("plan.fc.ov.emptyDraft") : t("plan.fc.ov.empty")}
          columns={[
            { key: "scope", header: t("plan.fc.ov.head.scope"), width: "minmax(140px, 1fr)", render: (o) => (o.item_family ? t("plan.fc.ov.family", { f: o.item_family }) : t("plan.fc.ov.thisItem")) },
            { key: "periods", header: t("plan.fc.ov.head.periods"), width: "170px", render: (o) => (o.period_from === o.period_to ? periodLabel(o.period_from, d.bucket) : `${periodLabel(o.period_from, d.bucket)} – ${periodLabel(o.period_to, d.bucket)}`) },
            { key: "change", header: t("plan.fc.ov.head.change"), width: "110px", align: "right", render: (o) => (o.mode === "pct" ? signedPct(o.value / 100) : t("plan.fc.ov.setTo", { v: num(o.value) })) },
            { key: "reason", header: t("plan.fc.ov.head.reason"), width: "minmax(160px, 2fr)", wrap: true, render: (o) => o.reason },
            { key: "by", header: t("plan.fc.ov.head.by"), width: "150px", drop: 1, render: (o) => <span className="pl-by">{o.created_by ?? ""}<span className="muted small"> {formatDateTime(o.created_at)}</span></span> },
            ...(canEdit
              ? [
                  {
                    key: "actions",
                    header: "",
                    label: t("plan.label.actions"),
                    width: "48px",
                    render: (o: ForecastOverride) => (
                      <button type="button" className="btn ghost sm icon" aria-label={t("plan.fc.ov.remove")} title={t("plan.fc.ov.remove")} onClick={() => setRemoving(o)} data-testid="fc-override-remove">
                        <Icon name="trash" />
                      </button>
                    ),
                  } as Column<ForecastOverride>,
                ]
              : []),
          ]}
        />
      </section>
      {ov ? <OverrideDialog versionId={version.id} bucket={d.bucket} periods={ps} itemId={d.item.id} itemText={itemLabel(d.item)} family={d.item.family ?? ""} draft={ov} onClose={() => setOv(null)} onDone={() => {
        setOv(null);
        changed();
      }} /> : null}
      {removing ? <ReasonConfirm title={t("plan.fc.ov.removeTitle")} body={t("plan.fc.ov.removeBody")} confirm={t("plan.fc.ov.remove")} danger onClose={() => setRemoving(null)} run={async (r) => {
        await removeOverride(removing.id, r);
        toast(t("plan.fc.toast.overrideRemoved"));
        setRemoving(null);
        changed();
      }} /> : null}
      {resetting ? <ReasonConfirm title={t("plan.fc.dlg.resetTitle", { p: periodLabel(resetting.period_start, d.bucket) })} body={t("plan.fc.dlg.resetBody", { qty: num(resetting.qty), cleaned: num(resetting.cleaned_qty) })} confirm={t("plan.fc.btn.useActual")} onClose={() => setResetting(null)} run={async (r) => {
        await updateHistory(resetting.id, { cleaned_qty: null, reason: r }, resetting.row_version);
        toast(t("plan.fc.toast.historyReset"));
        setResetting(null);
        changed();
      }} /> : null}
    </div>
  );
}

/** Period grid (pivot: periods are columns): statistical, final (editable on drafts), orders consumed, open forecast, last year. */
function PeriodGrid({ d, periods, row, canEdit, onEdit }: { d: ForecastItemDetail; periods: string[]; row: ForecastGridRow | null; canEdit: boolean; onEdit(p: string, v: number): void }) {
  const fc = new Map(d.forecast.map((f) => [f.period_start, f]));
  const cons = new Map(d.consumption.map((c) => [c.period_start, c]));
  const hist = new Map(d.history.map((h) => [h.period_start, h.cleaned_qty ?? h.qty]));
  const lastYear = (p: string) => {
    if (d.bucket === "m") return hist.get(`${Number(p.slice(0, 4)) - 1}${p.slice(4)}`);
    const dt = new Date(`${p}T00:00:00Z`);
    dt.setUTCDate(dt.getUTCDate() - 364);
    return hist.get(dt.toISOString().slice(0, 10));
  };
  const overridden = (i: number, p: string) => (row ? Boolean(row.overridden[i]) : d.overrides.some((o) => !o.removed_at && o.period_from <= p && o.period_to >= p));
  const totals = { stat: 0, final: 0 };
  for (const p of periods) {
    totals.stat += fc.get(p)?.stat_qty ?? 0;
    totals.final += fc.get(p)?.final_qty ?? 0;
  }
  return (
    <section className="card" aria-label={t("plan.fc.grid.title")}>
      <div className="card-header pl-card-header">
        <h3>{t("plan.fc.grid.title")}</h3>
        <span className="muted small">{canEdit ? t("plan.fc.grid.hintEdit") : t("plan.fc.grid.hintLocked")}</span>
      </div>
      <div className="pl-pivot-wrap">
        <table className="pl-pivot" data-testid="fc-grid">
          <thead>
            <tr>
              <th scope="col" className="pl-pivot-head">{t("plan.fc.head.row")}</th>
              {periods.map((p) => (
                <th key={p} scope="col" title={periodLabel(p, d.bucket)}>
                  {periodShort(p, d.bucket)}
                </th>
              ))}
              <th scope="col">{t("plan.fc.head.total")}</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <th scope="row">{t("plan.fc.series.lastYear")}</th>
              {periods.map((p) => (
                <td key={p} className="muted">{num(lastYear(p) ?? null)}</td>
              ))}
              <td />
            </tr>
            <tr>
              <th scope="row">{t("plan.fc.series.stat")}</th>
              {periods.map((p) => (
                <td key={p}>{num(fc.get(p)?.stat_qty ?? null)}</td>
              ))}
              <td className="pl-strong">{num(totals.stat)}</td>
            </tr>
            <tr className="pl-final-row">
              <th scope="row">{t("plan.fc.series.final")}</th>
              {periods.map((p, i) => {
                const v = fc.get(p)?.final_qty ?? 0;
                const o = overridden(i, p);
                const label = t("plan.fc.grid.cellAria", { p: periodLabel(p, d.bucket), v: num(v), o: o ? t("plan.fc.grid.overridden") : "" });
                return (
                  <td key={p} className={o ? "pl-overridden" : undefined} data-overridden={o ? "true" : "false"}>
                    {canEdit ? (
                      <button type="button" className="pl-cell-btn" aria-label={label} onClick={() => onEdit(p, v)} data-testid="fc-final-cell" data-period={p}>
                        {num(v)}
                        {o ? <span className="pl-ov-mark" aria-hidden>•</span> : null}
                      </button>
                    ) : (
                      <span aria-label={label} data-testid="fc-final-cell" data-period={p}>
                        {num(v)}
                        {o ? <span className="pl-ov-mark" aria-hidden>•</span> : null}
                      </span>
                    )}
                  </td>
                );
              })}
              <td className="pl-strong" data-testid="fc-final-total">{num(totals.final)}</td>
            </tr>
            <tr>
              <th scope="row">{t("plan.fc.series.consumed")}</th>
              {periods.map((p) => (
                <td key={p}>{num(cons.get(p)?.consumed ?? null)}</td>
              ))}
              <td />
            </tr>
            <tr>
              <th scope="row">{t("plan.fc.series.open")}</th>
              {periods.map((p) => (
                <td key={p}>{num(cons.get(p)?.open ?? null)}</td>
              ))}
              <td />
            </tr>
          </tbody>
        </table>
      </div>
      <div className="card-footer muted small pl-legend-line">
        <span className="pl-ov-mark" aria-hidden>•</span> {t("plan.fc.grid.legend")}
      </div>
    </section>
  );
}

function OverrideDialog({ versionId, bucket, periods, itemId, itemText, family, draft, onClose, onDone }: { versionId: string; bucket: Bucket; periods: string[]; itemId: string; itemText: string; family: string; draft: OverrideDraft; onClose(): void; onDone(): void }) {
  const [f, setF] = useState<OverrideDraft & { family: string; reason: string }>({ ...draft, family, reason: "" });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const value = Number(f.value);
  const valid = f.value.trim() !== "" && Number.isFinite(value) && (f.mode === "pct" || value >= 0) && f.reason.trim().length > 0 && f.from <= f.to && (f.scope === "item" || f.family.trim());
  const save = async () => {
    setBusy(true);
    setErr(null);
    try {
      await createOverride(versionId, {
        item_id: f.scope === "item" ? itemId : null,
        item_family: f.scope === "family" ? f.family.trim() : null,
        period_from: f.from,
        period_to: f.to,
        mode: f.mode,
        value,
        reason: f.reason.trim(),
      });
      toast(t("plan.fc.toast.overrideSaved"));
      onDone();
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog
      title={t("plan.fc.ov.dlgTitle")}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose} data-dialog-close>
            {t("common.cancel")}
          </button>
          <button type="button" className="btn primary" disabled={!valid || busy} onClick={() => void save()} data-testid="fc-override-save">
            {busy ? <span className="spinner" aria-hidden /> : null} {t("plan.fc.ov.save")}
          </button>
        </>
      }
    >
      <form
        className="col pl-gap"
        onSubmit={(e) => {
          e.preventDefault();
          if (valid) void save();
        }}
      >
        <MfgError error={err} />
        <fieldset className="pl-fieldset">
          <legend>{t("plan.fc.ov.head.scope")}</legend>
          <label className="row" style={{ gap: 6 }}>
            <input type="radio" name="ov-scope" checked={f.scope === "item"} onChange={() => setF({ ...f, scope: "item" })} /> {t("plan.fc.ov.scopeItem", { item: itemText })}
          </label>
          <label className="row" style={{ gap: 6 }}>
            <input type="radio" name="ov-scope" checked={f.scope === "family"} onChange={() => setF({ ...f, scope: "family" })} data-testid="fc-ov-scope-family" /> {t("plan.fc.ov.scopeFamily")}
          </label>
          {f.scope === "family" ? (
            <div className="field">
              <label htmlFor="ov-family">{t("plan.fc.label.family")}</label>
              <input id="ov-family" className="input" value={f.family} onChange={(e) => setF({ ...f, family: e.target.value })} data-testid="fc-ov-family" />
              <span className="hint">{t("plan.fc.ov.familyHint")}</span>
            </div>
          ) : null}
        </fieldset>
        <div className="row wrap" style={{ gap: 12 }}>
          <div className="field">
            <label htmlFor="ov-from">{t("plan.fc.ov.from")}</label>
            <select id="ov-from" className="select" value={f.from} onChange={(e) => setF({ ...f, from: e.target.value, to: f.to < e.target.value ? e.target.value : f.to })} data-testid="fc-ov-from">
              {periods.map((p) => (
                <option key={p} value={p}>
                  {periodLabel(p, bucket)}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="ov-to">{t("plan.fc.ov.to")}</label>
            <select id="ov-to" className="select" value={f.to} onChange={(e) => setF({ ...f, to: e.target.value })} data-testid="fc-ov-to">
              {periods.filter((p) => p >= f.from).map((p) => (
                <option key={p} value={p}>
                  {periodLabel(p, bucket)}
                </option>
              ))}
            </select>
          </div>
        </div>
        <div className="row wrap" style={{ gap: 12, alignItems: "flex-end" }}>
          <div className="field">
            <span className="field-label" id="ov-mode-l">{t("plan.fc.ov.mode")}</span>
            <div className="btn-group" role="group" aria-labelledby="ov-mode-l">
              <button type="button" className="btn" aria-pressed={f.mode === "pct"} onClick={() => setF({ ...f, mode: "pct" })} data-testid="fc-ov-mode-pct">
                {t("plan.fc.ov.modePct")}
              </button>
              <button type="button" className="btn" aria-pressed={f.mode === "abs"} onClick={() => setF({ ...f, mode: "abs" })} data-testid="fc-ov-mode-abs">
                {t("plan.fc.ov.modeAbs")}
              </button>
            </div>
          </div>
          <div className="field">
            <label htmlFor="ov-value">{f.mode === "pct" ? t("plan.fc.ov.valuePct") : t("plan.fc.ov.valueAbs")}</label>
            <input id="ov-value" className="input pl-w-140" type="number" step="any" min={f.mode === "abs" ? 0 : undefined} value={f.value} onChange={(e) => setF({ ...f, value: e.target.value })} data-testid="fc-ov-value" data-autofocus />
          </div>
        </div>
        <p className="muted small" style={{ margin: 0 }}>{f.mode === "pct" ? t("plan.fc.ov.pctHint") : t("plan.fc.ov.absHint")}</p>
        <div className="field">
          <label htmlFor="ov-reason">
            {t("plan.fc.ov.head.reason")} <span className="req" aria-hidden>*</span>
          </label>
          <textarea id="ov-reason" className="textarea" rows={2} maxLength={500} required aria-required value={f.reason} onChange={(e) => setF({ ...f, reason: e.target.value })} data-testid="fc-ov-reason" />
          <span className="hint">{t("plan.fc.ov.reasonHint")}</span>
        </div>
      </form>
    </Dialog>
  );
}

/** A confirmation that needs a reason (always, not only in Part 11 mode): removing an override, resetting history. */
export function ReasonConfirm({ title, body, confirm, danger, onClose, run }: { title: string; body: string; confirm: string; danger?: boolean; onClose(): void; run(reason: string): Promise<void> }) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  return (
    <ConfirmDialog
      title={title}
      confirmLabel={confirm}
      danger={danger}
      busy={busy}
      confirmDisabled={!text.trim()}
      onCancel={onClose}
      onConfirm={() => {
        setBusy(true);
        setErr(null);
        run(text.trim())
          .catch((e: unknown) => setErr(e))
          .finally(() => setBusy(false));
      }}
    >
      <div className="col pl-gap">
        <p style={{ margin: 0 }}>{body}</p>
        <MfgError error={err} />
        <div className="field">
          <label htmlFor="pl-reason">
            {t("plan.label.reason")} <span className="req" aria-hidden>*</span>
          </label>
          <textarea id="pl-reason" className="textarea" rows={2} maxLength={500} value={text} onChange={(e) => setText(e.target.value)} data-testid="pl-reason" data-autofocus />
        </div>
      </div>
    </ConfirmDialog>
  );
}

function RunDialog({ bucket, onClose, onStarted }: { bucket: Bucket; onClose(): void; onStarted(): void }) {
  const [expert, setExpert] = useState(false);
  const [b, setB] = useState<Bucket>(bucket);
  const [horizon, setHorizon] = useState("");
  const [clean, setClean] = useState(true);
  const [label, setLabel] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const navigate = useNavigate();
  const start = async () => {
    setBusy(true);
    setErr(null);
    try {
      const run = await createForecastRun(expert ? { label, bucket: b, horizon_periods: horizon ? Number(horizon) : null, outlier_clean: clean } : { label });
      toast(t("plan.fc.toast.runStarted", { n: run.number }));
      onStarted();
      navigate(mfgPaths.forecast(), { replace: true });
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog
      title={t("plan.fc.dlg.runTitle")}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose} data-dialog-close>
            {t("common.cancel")}
          </button>
          <button type="button" className="btn primary" disabled={busy} onClick={() => void start()} data-testid="fc-run-start">
            {busy ? <span className="spinner" aria-hidden /> : <Icon name="play" />} {t("plan.fc.btn.run")}
          </button>
        </>
      }
    >
      <div className="col pl-gap">
        <MfgError error={err} />
        <p style={{ margin: 0 }}>{t("plan.fc.dlg.runBody")}</p>
        <ul className="pl-bullets">
          <li>{t("plan.fc.dlg.runStep1")}</li>
          <li>{t("plan.fc.dlg.runStep2")}</li>
          <li>{t("plan.fc.dlg.runStep3")}</li>
        </ul>
        <div className="field">
          <label htmlFor="fc-run-label">{t("plan.fc.label.runLabel")}</label>
          <input id="fc-run-label" className="input" maxLength={80} value={label} onChange={(e) => setLabel(e.target.value)} placeholder={t("plan.fc.ph.runLabel")} />
        </div>
        <button type="button" className="btn ghost sm pl-expert-toggle" aria-expanded={expert} onClick={() => setExpert((v) => !v)} data-testid="fc-expert">
          <Icon name={expert ? "chevron-down" : "chevron-right"} /> {t("plan.label.expert")}
        </button>
        {expert ? (
          <div className="pl-expert col pl-gap">
            <div className="row wrap" style={{ gap: 12 }}>
              <div className="field">
                <label htmlFor="fc-run-bucket">{t("plan.fc.fact.bucket")}</label>
                <select id="fc-run-bucket" className="select" value={b} onChange={(e) => setB(e.target.value as Bucket)}>
                  <option value="m">{t("plan.fc.bucket.m")}</option>
                  <option value="w">{t("plan.fc.bucket.w")}</option>
                </select>
              </div>
              <div className="field">
                <label htmlFor="fc-run-horizon">{t("plan.fc.label.horizonPeriods")}</label>
                <input id="fc-run-horizon" className="input pl-w-140" type="number" min={1} max={104} placeholder={b === "m" ? "18" : "78"} value={horizon} onChange={(e) => setHorizon(e.target.value)} />
              </div>
            </div>
            <label className="row" style={{ gap: 6 }}>
              <input type="checkbox" checked={clean} onChange={(e) => setClean(e.target.checked)} /> {t("plan.fc.label.clean")}
            </label>
            <p className="muted small" style={{ margin: 0 }}>{t("plan.fc.dlg.expertHint")}</p>
          </div>
        ) : null}
      </div>
    </Dialog>
  );
}
