/**
 * `/mfg/sop` (M9 6.1, 10): S&OP cycles with a calendar strip per cycle (steps, due dates, owners, overdue in
 * text + icon) and "New cycle" for a period (one non-cancelled cycle per month).
 */
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router";
import { Dialog } from "../../components/Dialog";
import { Icon } from "../../components/Icon";
import { PageHeader } from "../../components/PageHeader";
import { toast } from "../../components/Toast";
import { t } from "../../lib/i18n";
import { formatDay } from "../../lib/locale";
import { createCycle, listCycles } from "../api/clientM9";
import { SOP_STEPS, type SopCycle } from "../api/typesM9";
import { DataTable } from "../components/DataTable";
import { MfgError } from "../components/Feedback";
import type { Column } from "../components/VirtualTable";
import { mfgPaths } from "../lib/paths";
import { needsText, useCan } from "../lib/permissions";
import { useLoad } from "../lib/useMfg";
import { CycleChip, monthLabel, nextMonthIso, stepText } from "../network/shared";

/** Seven steps of a cycle as a compact strip: done (check), current (accent), overdue (alert), later (plain). */
export function StepStrip({ cycle }: { cycle: SopCycle }) {
  const cur = SOP_STEPS.indexOf(cycle.status as (typeof SOP_STEPS)[number]);
  return (
    <div className="sop-strip" role="list" aria-label={t("net.sop.aria.strip")} data-testid="sop-strip">
      {SOP_STEPS.map((s, i) => {
        const info = cycle.steps.find((x) => x.step === s);
        const done = cur > i || Boolean(info?.done_at);
        const isCur = cur === i;
        const late = !done && Boolean(info?.overdue);
        return (
          <span
            key={s}
            role="listitem"
            className={done ? "done" : late ? "late" : isCur ? "cur" : undefined}
            title={[stepText(s), info?.due ? t("net.sop.tpl.due", { d: formatDay(info.due) }) : "", info?.owner_name ?? "", late ? t("net.sop.overdue") : ""].filter(Boolean).join(" · ")}
          >
            {done ? <Icon name="check" size={11} /> : late ? <Icon name="alert" size={11} /> : isCur ? <Icon name="circle" size={11} /> : null}
            {stepText(s)}
            {late ? <span className="sr-only"> {t("net.sop.overdue")}</span> : null}
          </span>
        );
      })}
    </div>
  );
}

export function SopCyclesPage() {
  const canEdit = useCan("sop_edit");
  const navigate = useNavigate();
  const cycles = useLoad((s) => listCycles({ limit: 36 }, s), []);
  const [dialog, setDialog] = useState(false);
  useEffect(() => {
    document.title = t("net.sop.title");
  }, []);
  const columns = useMemo<Column<SopCycle>[]>(
    () => [
      {
        key: "number",
        header: t("net.sop.head.cycle"),
        width: "140px",
        sortValue: (c) => c.period,
        exportValue: (c) => c.number,
        render: (c) => (
          <Link to={mfgPaths.sopCycle(c.id)} className="mono" onClick={(e) => e.stopPropagation()} tabIndex={-1}>
            {c.number}
          </Link>
        ),
      },
      { key: "period", header: t("net.sop.head.period"), width: "120px", sortValue: (c) => c.period, render: (c) => monthLabel(c.period) },
      { key: "status", header: t("net.sop.head.status"), width: "150px", exportValue: (c) => c.status, render: (c) => <CycleChip s={c.status} /> },
      { key: "steps", header: t("net.sop.head.calendar"), width: "minmax(520px, 1fr)", drop: 1, render: (c) => <StepStrip cycle={c} /> },
      {
        key: "next",
        header: t("net.sop.head.nextDue"),
        width: "150px",
        drop: 2,
        render: (c) => {
          const n = c.steps.find((s) => !s.done_at && s.due);
          if (!n || c.status === "cancelled" || c.status === "published") return <span className="muted">–</span>;
          return n.overdue ? (
            <span className="badge danger">
              <Icon name="alert" /> {formatDay(n.due)}
            </span>
          ) : (
            formatDay(n.due)
          );
        },
      },
    ],
    [],
  );
  return (
    <div className="col gap-lg" data-testid="sop-cycles">
      <PageHeader
        title={t("net.sop.title")}
        description={t("net.sop.desc")}
        actions={
          <button type="button" className="btn primary" disabled={!canEdit} title={canEdit ? undefined : needsText("sop_edit")} onClick={() => setDialog(true)} data-testid="sop-new">
            <Icon name="plus" /> {t("net.sop.btn.new")}
          </button>
        }
      />
      <MfgError error={cycles.error} onRetry={cycles.reload} />
      <section className="card card-table">
        <DataTable<SopCycle>
          rows={cycles.data?.items ?? []}
          columns={columns}
          rowKey={(c) => c.id}
          label={t("net.sop.title")}
          testId="sop-cycle-list"
          loading={cycles.loading && !cycles.data}
          onRowClick={(c) => navigate(mfgPaths.sopCycle(c.id))}
          onActivate={(c) => navigate(mfgPaths.sopCycle(c.id))}
          rowExtras={(c) => ({ testId: "sop-cycle-row", data: { status: c.status } })}
          exportName="sop-cycles"
          empty={t("net.sop.empty")}
        />
      </section>
      {dialog ? <NewCycleDialog onClose={() => setDialog(false)} onCreated={(c) => navigate(mfgPaths.sopCycle(c.id))} /> : null}
    </div>
  );
}

function NewCycleDialog({ onClose, onCreated }: { onClose(): void; onCreated(c: SopCycle): void }) {
  const [month, setMonth] = useState(nextMonthIso().slice(0, 7));
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const create = async () => {
    setBusy(true);
    setErr(null);
    try {
      const c = await createCycle(`${month}-01`);
      toast(t("net.sop.toast.created", { n: c.number }));
      onCreated(c);
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog
      title={t("net.sop.dlg.newTitle")}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose} data-dialog-close>
            {t("common.cancel")}
          </button>
          <button type="button" className="btn primary" disabled={!/^\d{4}-\d{2}$/.test(month) || busy} onClick={() => void create()} data-testid="sop-create">
            <Icon name="plus" /> {t("net.sop.btn.create")}
          </button>
        </>
      }
    >
      <div className="col pl-gap">
        <MfgError error={err} />
        <p style={{ margin: 0 }}>{t("net.sop.dlg.newBody")}</p>
        <div className="field">
          <label htmlFor="sop-month">{t("net.sop.label.period")}</label>
          <input id="sop-month" className="input pl-w-140" type="month" value={month} onChange={(e) => setMonth(e.target.value)} />
          <span className="hint">{/^\d{4}-\d{2}$/.test(month) ? monthLabel(`${month}-01`) : ""}</span>
        </div>
      </div>
    </Dialog>
  );
}
