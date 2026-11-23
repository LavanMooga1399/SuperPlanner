/**
 * Recalls (M5 6.3): `/mfg/recalls` (list; `?new=1&kind=&id=` or `?item=&supplier_lot=` opens a new one from the
 * trace) and `/mfg/recalls/:id` (the report): every affected unit and lot by status - in stock (where), in production
 * (which work order), shipped (customer, date), fitted into a parent - each marked exact or possible, with counts per
 * customer and programme; export to Excel or print; "Quarantine" moves the in-stock affected lots to a quarantine
 * location and puts them on hold (store keepers, one transfer posting per balance).
 */
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";
import { Banner } from "../../../components/Banner";
import { ConfirmDialog } from "../../../components/ConfirmDialog";
import { Icon } from "../../../components/Icon";
import { saveBlob } from "../../api/client";
import { listLocations } from "../../api/clientM2";
import { createRecall, exportRecall, getRecall, listRecalls, quarantineRecall } from "../../api/clientM5";
import type { Precision, QuarantineResult, Recall, RecallSource } from "../../api/typesM5";
import { MfgError, Spinner } from "../../components/Feedback";
import { DataTable } from "../../components/DataTable";
import { VirtualTable, type Column } from "../../components/VirtualTable";
import { fmtNum } from "../../lib/formatM2";
import { mfgPaths } from "../../lib/paths";
import { needsText, useCan } from "../../lib/permissions";
import { usePaged } from "../../lib/usePaged";
import { useLoad } from "../../lib/useMfg";
import { PrecisionTag } from "./TracePages";
import { formatDate, formatDateTime, formatDay } from "../../../lib/locale";
import { PageHeader } from "../../../components/PageHeader";
import { plural, t } from "../../../lib/i18n";

const STATUS: Record<string, { label: string; tone: string; icon: "layers" | "play" | "flag" | "circle" }> = {
  in_stock: { label: t("mfg.recallPages.str.inStock"), tone: "warn", icon: "layers" },
  wip: { label: t("mfg.recallPages.str.inProduction"), tone: "accent", icon: "play" },
  shipped: { label: t("mfg.recallPages.str.shipped"), tone: "danger", icon: "flag" },
  consumed: { label: t("mfg.recallPages.str.fittedIntoAParent"), tone: "info", icon: "circle" },
};

type UnitRow = NonNullable<Recall["report"]>["units"][number];
type LotRow = NonNullable<Recall["report"]>["lots"][number];
type CustomerRow = NonNullable<Recall["report"]>["by_customer"][number];

const RECALL_LIST_COLS: Column<Recall>[] = [
  {
    key: "recall",
    header: t("mfg.recallPages.str.recall"),
    width: "minmax(260px, 2fr)",
    exportValue: (r) => `${r.number} ${r.name}`,
    render: (r) => (
      <span className="mfg-ellipsis">
        <Link to={mfgPaths.recall(r.id)}>
          <span className="mono">{r.number}</span> {r.name}
        </Link>
        {r.quarantined_at ? <span className="small faint">{" "}{t("mfg.recallPages.text.quarantined", { quarantinedat: formatDate(r.quarantined_at) })}</span> : null}
      </span>
    ),
  },
  { key: "created", header: t("mfg.recallPages.str.created"), width: "160px", render: (r) => formatDateTime(r.created_at) },
  { key: "units", header: t("mfg.recallPages.str.units"), width: "100px", align: "right", render: (r) => fmtNum(r.report?.units.length ?? 0) },
  { key: "shipped", header: t("mfg.recallPages.str.shipped"), width: "100px", align: "right", render: (r) => fmtNum((r.report?.units ?? []).filter((u) => u.status === "shipped").length) },
  { key: "customers", header: t("mfg.recallPages.str.customers"), width: "110px", align: "right", render: (r) => fmtNum(r.report?.by_customer.length ?? 0) },
];

const QUARANTINE_COLS: Column<LotRow>[] = [
  { key: "item", header: t("mfg.recallPages.str.item"), width: "minmax(140px, 1fr)", sortValue: (l) => l.item, render: (l) => <span className="mono">{l.item}</span> },
  { key: "lot", header: t("mfg.recallPages.str.lot"), width: "minmax(120px, 1fr)", sortValue: (l) => l.lot_code, render: (l) => <span className="mono">{l.lot_code}</span> },
  { key: "on_hand", header: t("mfg.recallPages.str.onHand"), width: "100px", align: "right", sortValue: (l) => l.on_hand, render: (l) => fmtNum(l.on_hand) },
  { key: "location", header: t("mfg.recallPages.str.location"), width: "minmax(120px, 1fr)", sortValue: (l) => l.location ?? "", render: (l) => l.location ?? "" },
  {
    key: "hold",
    header: t("mfg.recallPages.str.hold"),
    width: "110px",
    sortValue: (l) => (l.on_hold ? 1 : 0),
    exportValue: (l) => (l.on_hold ? t("mfg.recallPages.str.onHold") : ""),
    render: (l) =>
      l.on_hold ? (
        <span className="badge warn">
          <Icon name="lock" /> {t("mfg.recallPages.btn.onHold")}
        </span>
      ) : null,
  },
];

const UNIT_COLS: Column<UnitRow>[] = [
  { key: "unit", header: t("mfg.recallPages.str.unit"), width: "minmax(130px, 1fr)", sortValue: (u) => u.serial, render: (u) => <span className="mono">{u.serial}</span> },
  { key: "item", header: t("mfg.recallPages.str.item"), width: "minmax(120px, 1fr)", sortValue: (u) => u.item, render: (u) => <span className="mono">{u.item}</span> },
  {
    key: "status",
    header: t("mfg.recallPages.str.status"),
    width: "140px",
    sortValue: (u) => u.status,
    exportValue: (u) => STATUS[u.status]?.label ?? u.status,
    render: (u) => {
      const st = STATUS[u.status] ?? { label: u.status, tone: "info", icon: "circle" as const };
      return (
        <span className={`badge ${st.tone}`}>
          <Icon name={st.icon} /> {st.label}
        </span>
      );
    },
  },
  {
    key: "where",
    header: t("mfg.recallPages.str.where"),
    width: "minmax(180px, 1.4fr)",
    wrap: true,
    render: (u) =>
      u.status === "shipped" ? (
        <span>
          {u.customer ?? ""} {u.demand_order ? <span className="mono">{u.demand_order}</span> : null}
          {u.shipped_on ? <span className="faint"> · {formatDay(u.shipped_on)}</span> : null}
        </span>
      ) : u.status === "wip" ? (
        <span className="mono">{u.wo ?? ""}</span>
      ) : u.status === "consumed" ? (
        <span>{t("mfg.recallPages.text.in", { v: u.parent ?? t("mfg.recallPages.str.aParentUnit") })}</span>
      ) : (
        u.location ?? ""
      ),
  },
  { key: "link", header: t("mfg.recallPages.str.link"), width: "110px", sortValue: (u) => u.precision, exportValue: (u) => u.precision, render: (u) => <PrecisionTag p={u.precision} /> },
  { key: "path", header: t("mfg.recallPages.str.path"), width: "minmax(200px, 2fr)", wrap: true, render: (u) => <span className="small faint">{u.path.join(" › ")}</span> },
];

export function RecallsPage() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const canView = useCan("trace_view");
  const data = usePaged<Recall>((offset, limit, signal) => listRecalls({ limit, offset }, signal), []);
  const fromTrace = params.get("new") === "1" || Boolean(params.get("supplier_lot"));
  const [name, setName] = useState(() => (params.get("label") ? t("mfg.recallPages.tpl.recall", { params: params.get("label") }) : ""));
  const [possible, setPossible] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  useEffect(() => {
    document.title = t("mfg.recallPages.str.recallsSuperplanner");
  }, []);
  const source: RecallSource | null = params.get("kind") && params.get("id") ? { kind: params.get("kind") as RecallSource["kind"], id: params.get("id")! } : params.get("item") && params.get("supplier_lot") ? { item_id: params.get("item")!, supplier_lot: params.get("supplier_lot")! } : null;
  return (
    <div className="col gap-lg" data-testid="recalls-page">
      <PageHeader
        title={t("mfg.recallPages.title.recalls")}
        description={t("mfg.recallPages.desc.everythingASuspectLotOr")}
        actions={
          <>
            <Link className="btn" to={mfgPaths.trace()}>
            <Icon name="zoom-in" /> {t("mfg.recallPages.btn.traceSomethingFirst")}
            </Link>
          </>
        }
      />
      {fromTrace && source ? (
        <section className="card" data-testid="recall-new">
          <div className="card-header">
            <h2>{t("mfg.recallPages.head.newRecall")}</h2>
          </div>
          <div className="card-body col">
            <p style={{ margin: 0 }}>
              {t("mfg.recallPages.text.startingFrom")}{" "}<strong className="mono">{params.get("label") ?? source.id ?? source.supplier_lot}</strong>.
            </p>
            <div className="field" style={{ maxWidth: 480 }}>
              <label htmlFor="rc-name">{t("mfg.recallPages.label.name")}</label>
              <input id="rc-name" className="input" value={name} onChange={(e) => setName(e.target.value)} data-testid="recall-name" />
            </div>
            <label className="checkbox">
              <input type="checkbox" checked={possible} onChange={(e) => setPossible(e.target.checked)} />
              <span>
                <strong>{t("mfg.recallPages.text.includePossibleLinks")}</strong> <span className="muted small">{t("mfg.recallPages.text.unitsMadeFromWorkOrders")}</span>
              </span>
            </label>
            <MfgError error={error} />
            <div>
              <button
                type="button"
                className="btn primary"
                disabled={!canView || busy || !name.trim()}
                title={canView ? undefined : needsText("trace_view")}
                onClick={async () => {
                  setBusy(true);
                  setError(null);
                  try {
                    const r = await createRecall({ name: name.trim(), sources: [source], include_possible: possible });
                    navigate(mfgPaths.recall(r.id));
                  } catch (e) {
                    setError(e);
                    setBusy(false);
                  }
                }}
                data-testid="recall-create"
              >
                <Icon name="alert" /> {t("mfg.recallPages.btn.buildTheRecallReport")}
              </button>
            </div>
          </div>
        </section>
      ) : null}
      <MfgError error={data.error} onRetry={data.reload} />
      <VirtualTable
        rows={data.rows}
        columns={RECALL_LIST_COLS}
        rowKey={(r) => r.id}
        label={t("mfg.recallPages.label.recalls")}
        testId="recall-list"
        totalCount={data.total}
        loading={data.loading}
        onEndReached={data.onEndReached}
        exportName="recalls"
        rowExtras={() => ({ testId: "recall-row" })}
        empty={t("mfg.recallPages.empty.noRecallsStartOneFrom")}
        card={{ title: "recall", fields: ["created", "units", "shipped"] }}
      />
    </div>
  );
}

export function RecallPage() {
  const { recallId = "" } = useParams();
  const canQuarantine = useCan("inventory");
  const rc = useLoad((signal) => getRecall(recallId, signal), [recallId]);
  const locs = useLoad((signal) => listLocations({ active: true }, signal).catch(() => null), []);
  const [status, setStatus] = useState("");
  const [prec, setPrec] = useState<"" | Precision>("");
  const [loc, setLoc] = useState("");
  const [confirm, setConfirm] = useState(false);
  const [qResult, setQResult] = useState<QuarantineResult | null>(null);
  const [qError, setQError] = useState<unknown>(null);
  const r = rc.data;
  const rep = r?.report ?? null;
  const units = useMemo(() => (rep?.units ?? []).filter((u) => (!status || u.status === status) && (!prec || u.precision === prec)), [rep, status, prec]);
  const quarantineLocs = (locs.data?.items ?? []).filter((l) => l.kind === "quarantine");
  useEffect(() => {
    if (!loc && quarantineLocs[0]) setLoc(quarantineLocs[0].id);
  }, [quarantineLocs, loc]);
  if (rc.loading && !r) return <Spinner label={t("mfg.recallPages.label.buildingTheRecallReport")} />;
  if (!r) return <MfgError error={rc.error} onRetry={rc.reload} />;
  const all = rep?.units ?? [];
  const by = (st: string) => all.filter((u) => u.status === st).length;
  const exact = all.filter((u) => u.precision === "exact").length;
  const lotsToMove = (rep?.lots ?? []).filter((l) => l.on_hand > 0 && !l.on_hold);
  return (
    <div className="col gap-lg print-page" data-testid="recall-page">
      <nav className="breadcrumb no-print" aria-label={t("mfg.recallPages.aria.breadcrumb")}>
        <Link to={mfgPaths.recalls()}>{t("mfg.recallPages.text.recalls")}</Link> <Icon name="chevron-right" size={12} /> <span className="mono">{r.number}</span>
      </nav>
      <div className="row wrap" style={{ justifyContent: "space-between" }}>
        <h1 style={{ margin: 0 }}>
          <span className="mono">{r.number}</span> {r.name}
        </h1>
        <span className="row no-print">
          <button type="button" className="btn" onClick={async () => saveBlob(await exportRecall(r.id))} data-testid="recall-export">
            <Icon name="download" /> {t("mfg.recallPages.btn.excel")}
          </button>
          <button type="button" className="btn" onClick={() => window.print()}>
            <Icon name="file" /> {t("mfg.recallPages.btn.print")}
          </button>
        </span>
      </div>
      <p className="muted small" style={{ margin: 0 }}>
        {t("mfg.recallPages.text.created", { v: r.include_possible ? t("mfg.recallPages.str.includesPossibleLinksLotLevel") : t("mfg.recallPages.str.exactLinksOnly"), createdat: formatDateTime(r.created_at) })}
      </p>
      <div className="kpis" data-testid="recall-summary" data-units={all.length}>
        <div className="card kpi">
          <div className="kpi-label">{t("mfg.recallPages.text.affectedUnits")}</div>
          <div className="kpi-value">{fmtNum(all.length)}</div>
          <div className="kpi-sub">
            {fmtNum(exact)} exact · {fmtNum(all.length - exact)} possible
          </div>
        </div>
        <div className="card kpi">
          <div className="kpi-label">{t("mfg.recallPages.text.shipped")}</div>
          <div className="kpi-value" style={{ color: by("shipped") ? "var(--danger)" : undefined }}>
            {fmtNum(by("shipped"))}
          </div>
          <div className="kpi-sub">{t("mfg.recallPages.text.toCustomers", { fmtNum: fmtNum(rep?.by_customer.length ?? 0) })}</div>
        </div>
        <div className="card kpi">
          <div className="kpi-label">{t("mfg.recallPages.text.inStock")}</div>
          <div className="kpi-value">{fmtNum(by("in_stock"))}</div>
          <div className="kpi-sub">{fmtNum(rep?.lots.length ?? 0)} lots</div>
        </div>
        <div className="card kpi">
          <div className="kpi-label">{t("mfg.recallPages.text.inProduction")}</div>
          <div className="kpi-value">{fmtNum(by("wip"))}</div>
          <div className="kpi-sub">{t("mfg.recallPages.text.workOrders", { fmtNum: fmtNum(rep?.wos.length ?? 0) })}</div>
        </div>
        <div className="card kpi">
          <div className="kpi-label">{t("mfg.recallPages.text.fittedIntoParents")}</div>
          <div className="kpi-value">{fmtNum(by("consumed"))}</div>
        </div>
      </div>

      <section className="card no-print" data-testid="recall-quarantine">
        <div className="card-header">
          <h2>{t("mfg.recallPages.head.stopItMoving")}</h2>
        </div>
        <div className="card-body col">
          {r.quarantined_at ? (
            <Banner tone="ok" title={t("mfg.recallPages.title.quarantined")}>
              {t("mfg.recallPages.text.affectedStockWasMovedAnd", { quarantinedat: formatDateTime(r.quarantined_at) })}
            </Banner>
          ) : null}
          {qResult ? (
            <Banner tone="ok" title={t("mfg.recallPages.title.quarantineDone")} testId="quarantine-done">
              {qResult.moved !== undefined ? t("mfg.recallPages.tpl.balancesMoved", { moved: qResult.moved }) : t("mfg.recallPages.str.stockMoved")}
              {qResult.lots_on_hold !== undefined ? t("mfg.recallPages.tpl.lotsOnHold", { lotsonhold: qResult.lots_on_hold }) : ""}.
            </Banner>
          ) : null}
          <DataTable
            rows={rep?.lots ?? []}
            columns={QUARANTINE_COLS}
            rowKey={(_, i) => i}
            label={t("mfg.recallPages.label.affectedStock")}
            tableId="recall-lots"
            rowExtras={() => ({ testId: "quarantine-lot" })}
            empty={t("mfg.recallPages.empty.noAffectedStockOnHand")}
            card={{ title: "item", status: "hold", fields: ["lot", "on_hand", "location"] }}
          />
          {rep?.open_pos.length ? (
            <p className="small" style={{ margin: 0 }}>
              {t("mfg.recallPages.text.openPurchaseOrdersOfThe", { join: rep.open_pos.map((p) => `${p.number}${p.qty ? ` (${fmtNum(p.qty)})` : ""}`).join(", ") })}
            </p>
          ) : null}
          {lotsToMove.length && !r.quarantined_at ? (
            <div className="row wrap" style={{ alignItems: "flex-end" }}>
              <div className="field">
                <label htmlFor="rc-loc">{t("mfg.recallPages.label.moveTo")}</label>
                <select id="rc-loc" className="select" value={loc} onChange={(e) => setLoc(e.target.value)} data-testid="quarantine-location">
                  {quarantineLocs.length === 0 ? <option value="">{t("mfg.recallPages.text.noQuarantineLocationAddOne")}</option> : null}
                  {quarantineLocs.map((l) => (
                    <option key={l.id} value={l.id}>
                      {l.code} · {l.name}
                    </option>
                  ))}
                </select>
              </div>
              <button type="button" className="btn danger" disabled={!canQuarantine || !loc} title={canQuarantine ? undefined : needsText("inventory")} onClick={() => setConfirm(true)} data-testid="quarantine-run">
                <Icon name="lock" />{" "}{t("mfg.recallPages.text.quarantine", { length: plural(lotsToMove.length, "lot") })}
              </button>
            </div>
          ) : null}
          <MfgError error={qError} />
        </div>
      </section>

      {rep?.by_customer.length || rep?.by_program.length ? (
        <div className="grid-2" style={{ alignItems: "start" }}>
          <section className="card card-table">
            <div className="card-header">
              <h2>{t("mfg.recallPages.head.perCustomer")}</h2>
            </div>
            <DataTable
              rows={rep?.by_customer ?? []}
              columns={[
                { key: "customer", header: "Customer", width: "minmax(160px, 1fr)", sortValue: (c) => c.customer, render: (c) => c.customer },
                { key: "units", header: "Units", width: "110px", align: "right", sortValue: (c) => c.units, render: (c) => fmtNum(c.units) },
                ...(rep?.by_customer.some((c) => c.exact !== undefined)
                  ? [{ key: "exact", header: "Exact", width: "100px", align: "right" as const, sortValue: (c: CustomerRow) => c.exact ?? null, render: (c: CustomerRow) => (c.exact === undefined ? "" : fmtNum(c.exact)) }]
                  : []),
              ]}
              rowKey={(_, i) => i}
              label={t("mfg.recallPages.label.affectedUnitsPerCustomer")}
              testId="recall-customers"
              exportName="recall-customers"
            />
          </section>
          {rep?.by_program.length ? (
            <section className="card card-table">
              <div className="card-header">
                <h2>{t("mfg.recallPages.head.perProgramme")}</h2>
              </div>
              <DataTable
                rows={rep.by_program}
                columns={[
                  { key: "program", header: "Programme", width: "minmax(160px, 1fr)", sortValue: (c) => c.program, render: (c) => c.program },
                  { key: "units", header: "Units", width: "110px", align: "right", sortValue: (c) => c.units, render: (c) => fmtNum(c.units) },
                ]}
                rowKey={(_, i) => i}
                label={t("mfg.recallPages.label.affectedUnitsPerProgramme")}
                tableId="recall-programmes"
                exportName="recall-programmes"
              />
            </section>
          ) : null}
        </div>
      ) : null}

      <section className="card card-table">
        <div className="card-header row wrap" style={{ justifyContent: "space-between" }}>
          <h2>{t("mfg.recallPages.text.affectedUnits2", { length: units.length })}</h2>
          <span className="row no-print">
            <select className="select sm" style={{ width: "auto" }} aria-label={t("mfg.recallPages.aria.status")} value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="">{t("mfg.recallPages.text.anyStatus")}</option>
              {Object.entries(STATUS).map(([k, v]) => (
                <option key={k} value={k}>
                  {v.label}
                </option>
              ))}
            </select>
            <select className="select sm" style={{ width: "auto" }} aria-label={t("mfg.recallPages.aria.precision")} value={prec} onChange={(e) => setPrec(e.target.value as "" | Precision)}>
              <option value="">{t("mfg.recallPages.text.exactAndPossible")}</option>
              <option value="exact">{t("mfg.recallPages.text.exactOnly")}</option>
              <option value="possible">{t("mfg.recallPages.text.possibleOnly")}</option>
            </select>
          </span>
        </div>
        <DataTable
          rows={units}
          columns={UNIT_COLS}
          rowKey={(u, i) => `${u.serial}-${i}`}
          label={t("mfg.recallPages.label.affectedUnits")}
          testId="recall-units"
          exportName="recall-units"
          rowExtras={(u) => ({ testId: "recall-unit", data: { status: u.status, precision: u.precision } })}
          empty={t("mfg.recallPages.empty.noAffectedUnitsMatchThese")}
          card={{ title: "unit", status: "status", fields: ["item", "where", "link"] }}
        />
      </section>
      {confirm ? (
        <ConfirmDialog
          title={t("mfg.recallPages.tpl.quarantine", { length: plural(lotsToMove.length, "lot") })}
          confirmLabel={t("mfg.recallPages.btn.moveAndHold")}
          danger
          onCancel={() => setConfirm(false)}
          onConfirm={async () => {
            setConfirm(false);
            setQError(null);
            try {
              setQResult(await quarantineRecall(r.id, { location_id: loc }));
              rc.reload();
            } catch (e) {
              setQError(e);
            }
          }}
        >
          <p style={{ margin: 0 }}>{t("mfg.recallPages.text.theInstockQuantitiesAreMoved")}</p>
        </ConfirmDialog>
      ) : null}
    </div>
  );
}
