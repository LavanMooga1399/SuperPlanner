/**
 * `/mfg/serials` and `/mfg/serials/:serialId` (M4 10, #214/#215): find a unit by serial, item or work order; the
 * detail shows its work order, the parent it went into and the units fitted into it (one level; multi-level
 * genealogy is M5). Labels print from the browser.
 */
import { useState } from "react";
import { Link, useParams, useSearchParams } from "react-router";
import { Icon } from "../../../components/Icon";
import { getSerial, listSerials } from "../../api/clientM4";
import type { SerialStatus, UnitSerial } from "../../api/typesM4";
import { MfgError, Spinner } from "../../components/Feedback";
import { VirtualTable, type Column } from "../../components/VirtualTable";
import { usePlantClock } from "../../lib/plantTime";
import { mfgPaths } from "../../lib/paths";
import { setSearchParam, usePaged } from "../../lib/usePaged";
import { useDebounced, useLoad } from "../../lib/useMfg";
import { PageHeader } from "../../../components/PageHeader";
import { FilterBar, type FilterChip } from "../../../components/FilterBar";
import { t } from "../../../lib/i18n";
import { LOCALE } from "../../../lib/locale";

const STATUS: Record<SerialStatus, { label: string; tone: string; icon: "check" | "clock" | "layers" | "arrow-right" | "trash" }> = {
  wip: { label: t("mfg.serialsPage.str.inProduction"), tone: "accent", icon: "clock" },
  in_stock: { label: t("mfg.serialsPage.str.inStock"), tone: "ok", icon: "check" },
  consumed: { label: t("mfg.serialsPage.str.fittedIntoAParent"), tone: "info", icon: "layers" },
  shipped: { label: t("mfg.serialsPage.str.shipped"), tone: "info", icon: "arrow-right" },
  scrapped: { label: t("mfg.serialsPage.str.scrapped"), tone: "danger", icon: "trash" },
};

export function SerialStatusChip({ s }: { s: SerialStatus }) {
  const m = STATUS[s] ?? { label: s, tone: "info", icon: "clock" as const };
  return (
    <span className={`badge ${m.tone}`} data-status={s}>
      <Icon name={m.icon} /> {m.label}
    </span>
  );
}

export function SerialsPage() {
  const clock = usePlantClock();
  const [params, setParams] = useSearchParams();
  const [q, setQ] = useState(params.get("q") ?? "");
  const dq = useDebounced(q.trim(), 250);
  const status = (params.get("status") ?? "") as SerialStatus | "";
  const wo = params.get("wo") ?? "";
  const data = usePaged<UnitSerial>((offset, limit, signal) => listSerials({ q: dq || undefined, status: status || undefined, wo_id: wo || undefined, limit, offset }, signal), [dq, status, wo]);
  const chips: FilterChip[] = [];
  if (q.trim()) chips.push({ key: "q", label: t("mfg.serialsPage.str.search"), value: q.trim(), onClear: () => setQ("") });
  if (status) chips.push({ key: "st", label: t("mfg.serialsPage.str.status"), value: status.replace(/_/g, " "), onClear: () => setSearchParam(setParams, "status", "") });
  if (wo) chips.push({ key: "wo", label: t("mfg.serialsPage.str.workOrder"), value: "One work order", onClear: () => setSearchParam(setParams, "wo", "") });

  const columns: Column<UnitSerial>[] = [
    { key: "serial", header: t("mfg.serialsPage.str.serial"), width: "minmax(160px, 1fr)", exportValue: (s) => s.serial, render: (s) => <Link to={mfgPaths.serial(s.id)} className="mono">{s.serial}</Link> },
    { key: "item", header: t("mfg.serialsPage.str.item"), width: "minmax(140px, 1fr)", render: (s) => <span className="mono">{s.item?.part_number ?? ""}</span> },
    { key: "wo", header: t("mfg.serialsPage.str.workOrder"), width: "140px", exportValue: (s) => s.wo?.number ?? "", render: (s) => (s.wo ? <Link to={mfgPaths.workOrder(s.wo.id)} className="mono">{s.wo.number}</Link> : "") },
    { key: "status", header: t("mfg.serialsPage.str.status"), width: "130px", exportValue: (s) => STATUS[s.status]?.label ?? s.status, render: (s) => <SerialStatusChip s={s.status} /> },
    { key: "captured", header: t("mfg.serialsPage.str.captured"), width: "minmax(180px, 1fr)", render: (s) => `${clock.dateTime(s.captured_at)}${s.captured_op_seq ? t("mfg.serialsPage.tpl.atOp", { capturedopseq: s.captured_op_seq }) : ""}` },
  ];
  return (
    <div className="col gap-lg" data-testid="serials-page">
      <PageHeader title={t("mfg.serialsPage.title.unitSerials")} />
      <FilterBar chips={chips} onClearAll={() => (setQ(""), setParams({}, { replace: true }))} search={{ id: "sr-q", value: q, onChange: setQ, placeholder: "e.g. TPU-000123", label: "Serial, part or work order", testId: "serial-search" }} pageKey="SerialsPage">
        <div className="field">
          <label htmlFor="sr-status">{t("mfg.serialsPage.label.status")}</label>
          <select id="sr-status" className="select" value={status} onChange={(e) => setSearchParam(setParams, "status", e.target.value)}>
            <option value="">{t("mfg.serialsPage.text.any")}</option>
            {(Object.keys(STATUS) as SerialStatus[]).map((s) => (
              <option key={s} value={s}>
                {STATUS[s].label}
              </option>
            ))}
          </select>
        </div>
      </FilterBar>
      <MfgError error={data.error} onRetry={data.reload} />
      <VirtualTable
        rows={data.rows}
        columns={columns}
        rowKey={(s) => s.id}
        label={t("mfg.serialsPage.label.unitSerials")}
        testId="serials-table"
        totalCount={data.total}
        loading={data.loading}
        onEndReached={data.onEndReached}
        exportName="serials"
        rowExtras={() => ({ testId: "serial-row" })}
        empty={chips.length ? t("mfg.serialsPage.str.noSerialsMatchTheseFilters") : t("mfg.serialsPage.str.noSerialsYetSerialsAre")}
        footer={<span className="muted small">{t("mfg.serialsPage.text.showingSerials", { t: t("common.nOfM", { n: data.rows.length.toLocaleString(LOCALE), m: data.total.toLocaleString(LOCALE) }) })}</span>}
        card={{ title: "serial", status: "status", fields: ["item", "wo", "captured"] }}
      />
    </div>
  );
}

function UnitLine({ u }: { u: UnitSerial }) {
  return (
    <span className="row wrap" style={{ gap: 6 }}>
      <Link to={mfgPaths.serial(u.id)} className="mono">
        {u.serial}
      </Link>
      <span className="mono faint">{u.item?.part_number ?? ""}</span>
      <SerialStatusChip s={u.status} />
    </span>
  );
}

export function SerialPage() {
  const { serialId = "" } = useParams();
  const clock = usePlantClock();
  const s = useLoad((signal) => getSerial(serialId, signal), [serialId]);
  const u = s.data;
  if (s.loading && !u) return <Spinner />;
  if (!u) return <MfgError error={s.error} onRetry={s.reload} />;
  return (
    <div className="col gap-lg" data-testid="serial-page">
      <nav className="breadcrumb" aria-label={t("mfg.serialsPage.aria.breadcrumb")}>
        <Link to={mfgPaths.serials()}>{t("mfg.serialsPage.text.serials")}</Link> <Icon name="chevron-right" size={12} /> <span>{u.serial}</span>
      </nav>
      <div className="row wrap" style={{ justifyContent: "space-between" }}>
        <h1 style={{ margin: 0 }}>
          <span className="mono">{u.serial}</span> <SerialStatusChip s={u.status} />
        </h1>
        <Link className="btn" to={mfgPaths.printLabels({ type: "serial", ids: u.id })}>
          <Icon name="file" /> {t("mfg.serialsPage.btn.printLabel")}
        </Link>
      </div>
      <section className="card card-body">
        <dl className="floor-kv">
          <dt>{t("mfg.serialsPage.head.item")}</dt>
          <dd>
            {u.item ? (
              <Link to={mfgPaths.item(u.item.id)} className="mono">
                {u.item.part_number}
              </Link>
            ) : null}{" "}
            {u.item?.description ?? ""}
          </dd>
          <dt>{t("mfg.serialsPage.head.madeIn")}</dt>
          <dd>{u.wo ? <Link to={mfgPaths.workOrder(u.wo.id)} className="mono">{u.wo.number}</Link> : "-"}</dd>
          <dt>{t("mfg.serialsPage.head.captured")}</dt>
          <dd>
            {clock.dateTime(u.captured_at)}
            {u.captured_op_seq ? t("mfg.serialsPage.tpl.atOperation", { capturedopseq: u.captured_op_seq }) : ""}
          </dd>
          {u.consumed_at ? (
            <>
              <dt>{t("mfg.serialsPage.head.fitted")}</dt>
              <dd>{clock.dateTime(u.consumed_at)}</dd>
            </>
          ) : null}
        </dl>
      </section>
      <div className="grid-2" style={{ alignItems: "start" }}>
        <section className="card" data-testid="serial-parent">
          <div className="card-header">
            <h2>{t("mfg.serialsPage.head.fittedInto")}</h2>
          </div>
          <div className="card-body">{u.parent ? <UnitLine u={u.parent} /> : <span className="muted">{t("mfg.serialsPage.text.notFittedIntoAnotherUnit")}</span>}</div>
        </section>
        <section className="card" data-testid="serial-children">
          <div className="card-header">
            <h2>{t("mfg.serialsPage.text.unitsFittedIntoIt", { length: u.children.length })}</h2>
          </div>
          <div className="card-body col" style={{ gap: 6 }}>
            {u.children.length ? u.children.map((c) => <UnitLine key={c.id} u={c} />) : <span className="muted">{t("mfg.serialsPage.text.noneRecorded")}</span>}
          </div>
        </section>
      </div>
      {u.consumed_by_wo ? (
        <p style={{ margin: 0 }}>
          {t("mfg.serialsPage.text.fittedInWorkOrder", { v: " " })}
          <Link to={mfgPaths.workOrder(u.consumed_by_wo.id)} className="mono">
            {u.consumed_by_wo.number}
          </Link>{" "}
          {t("mfg.serialsPage.text.theParentItemHasNo")}
        </p>
      ) : null}
      {u.wo ? (
        <Link className="btn ghost sm" style={{ alignSelf: "flex-start" }} to={mfgPaths.floorEvents({ wo: u.wo.id })}>
          <Icon name="list" />{" "}{t("mfg.serialsPage.text.floorEventsOf", { number: u.wo.number })}
        </Link>
      ) : null}
      <p className="faint small" style={{ margin: 0 }}>
        {t("mfg.serialsPage.text.oneLevelShownFullGenealogy")}
      </p>
    </div>
  );
}
