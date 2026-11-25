/**
 * Safety stock proposals `/mfg/invopt` (M8 5, 12): the latest (or chosen) proposal run, the ABC x XYZ matrix
 * (items, value at standard cost and the service level each cell targets; a cell filters the list), and the
 * proposal table - class, service level, current -> proposed safety stock, change in value, cover days - with bulk
 * approve / reject (always with a reason; approval writes the item's safety stock, audited). Statistics propose,
 * planners decide (V2): nothing is applied without an approval.
 */
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router";
import { Banner } from "../../components/Banner";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { FilterBar, type FilterChip } from "../../components/FilterBar";
import { Icon } from "../../components/Icon";
import { PageHeader } from "../../components/PageHeader";
import { toast } from "../../components/Toast";
import { plural, t } from "../../lib/i18n";
import { formatDateTime, formatNumber } from "../../lib/locale";
import { createSsRun, decideSs, getPlanningSettings, listSsLines, listSsRuns } from "../api/clientM8";
import type { M8Page, SsLine, SsRun } from "../api/typesM8";
import { MfgError, Spinner } from "../components/Feedback";
import { VirtualTable, type Column } from "../components/VirtualTable";
import { fmtMoney } from "../lib/formatM2";
import { needsText, useCan } from "../lib/permissions";
import { setSearchParam, usePaged } from "../lib/usePaged";
import { usePolling } from "../lib/usePolling";
import { useDebounced, useLoad, usePlant } from "../lib/useMfg";
import { Chip, ClassTag, codeText, isRunning, JobChip, num, pct } from "../forecast/shared";

const ABC = ["A", "B", "C"] as const;
const XYZ = ["X", "Y", "Z"] as const;
const DECISION = {
  pending: { label: "plan.ss.decision.pending", tone: "warn", icon: "clock" },
  approved: { label: "plan.ss.decision.approved", tone: "ok", icon: "check" },
  rejected: { label: "plan.ss.decision.rejected", tone: "info", icon: "x" },
} as const;

export function InvoptPage() {
  const [params, setParams] = useSearchParams();
  const set = (k: string, v: string) => setSearchParam(setParams, k, v);
  const canRun = useCan("inventory_policy_edit");
  const canDecide = useCan("inventory_policy_approve");
  const plant = usePlant();
  const currency = plant.data?.currency;
  const settings = useLoad((s) => getPlanningSettings(s).catch(() => null), []);
  useEffect(() => {
    document.title = t("plan.ss.title");
  }, []);
  const runs = useLoad((s) => listSsRuns({ limit: 20 }, s), []);
  const runParam = params.get("run") ?? "";
  const list = runs.data?.items ?? [];
  const run: SsRun | null = list.find((r) => r.id === runParam) ?? list[0] ?? null;
  const running = isRunning(run?.status);
  usePolling(runs.reload, running);
  const [q, setQ] = useState(params.get("q") ?? "");
  const dq = useDebounced(q.trim(), 250);
  useEffect(() => set("q", dq), [dq]); // eslint-disable-line react-hooks/exhaustive-deps
  const decision = params.get("decision") ?? "pending";
  const abc = params.get("abc") ?? "";
  const xyz = params.get("xyz") ?? "";
  const key = JSON.stringify([run?.id, run?.status, dq, decision, abc, xyz]);
  const lines = usePaged<SsLine, M8Page<SsLine>>(
    run && run.status === "completed" ? (offset, limit, signal) => listSsLines(run.id, { q: dq || undefined, decision: decision === "all" ? undefined : decision, abc: abc || undefined, xyz: xyz || undefined, limit, offset }, signal) : null,
    [key],
    200,
  );
  const [selected, setSelected] = useState<Set<string>>(new Set());
  useEffect(() => setSelected(new Set()), [key]);
  const [deciding, setDeciding] = useState<null | "approved" | "rejected">(null);
  const [starting, setStarting] = useState(false);
  const [err, setErr] = useState<unknown>(null);

  const start = async () => {
    setStarting(true);
    setErr(null);
    try {
      const r = await createSsRun({});
      toast(t("plan.ss.toast.started", { n: r.number }));
      setParams({}, { replace: true });
      runs.reload();
    } catch (e) {
      setErr(e);
    } finally {
      setStarting(false);
    }
  };

  const columns = useMemo<Column<SsLine>[]>(
    () => [
      { key: "item", header: t("plan.fc.head.item"), width: "minmax(130px, 1fr)", sortValue: (l) => l.part_number, exportValue: (l) => l.part_number, render: (l) => <span className="mono mfg-ellipsis">{l.part_number ?? l.item_id}</span> },
      { key: "class", header: t("plan.fc.head.class"), width: "60px", sortValue: (l) => `${l.abc}${l.xyz}`, exportValue: (l) => `${l.abc}${l.xyz}`, render: (l) => <ClassTag abc={l.abc} xyz={l.xyz} /> },
      { key: "sl", header: t("plan.ss.head.sl"), width: "84px", align: "right", sortValue: (l) => l.service_level, exportValue: (l) => l.service_level, render: (l) => <span className="pl-num">{pct(l.service_level, 1)}</span> },
      { key: "d", header: t("plan.ss.head.dDay"), width: "96px", align: "right", drop: 3, sortValue: (l) => l.d_day, exportValue: (l) => l.d_day, render: (l) => <span className="pl-num">{num(l.d_day, 1)}</span> },
      { key: "lt", header: t("plan.ss.head.lt"), width: "84px", align: "right", drop: 2, sortValue: (l) => l.lt_days, exportValue: (l) => l.lt_days, render: (l) => <span className="pl-num">{num(l.lt_days, 1)}</span> },
      { key: "current", header: t("plan.ss.head.current"), width: "96px", align: "right", sortValue: (l) => l.current_ss, exportValue: (l) => l.current_ss, render: (l) => <span className="pl-num">{num(l.current_ss)}</span> },
      {
        key: "proposed",
        header: t("plan.ss.head.proposed"),
        width: "120px",
        align: "right",
        sortValue: (l) => l.proposed_ss,
        exportValue: (l) => l.proposed_ss,
        render: (l) => (
          <span className="pl-num pl-strong" title={t("plan.ss.tpl.formula", { z: num(l.z, 3), lt: num(l.lt_days, 1), sd: num(l.sigma_d_day, 1), d: num(l.d_day, 1), slt: num(l.sigma_lt_days, 1) })}>
            {num(l.proposed_ss)}
          </span>
        ),
      },
      {
        key: "change",
        header: t("plan.ss.head.change"),
        width: "104px",
        align: "right",
        sortValue: (l) => l.proposed_ss - l.current_ss,
        exportValue: (l) => l.proposed_ss - l.current_ss,
        render: (l) => <Delta v={l.proposed_ss - l.current_ss} />,
      },
      { key: "value", header: t("plan.ss.head.value"), width: "120px", align: "right", drop: 1, sortValue: (l) => l.delta_value, exportValue: (l) => l.delta_value, render: (l) => <span className="pl-num">{fmtMoney(l.delta_value, currency)}</span> },
      { key: "cover", header: t("plan.ss.head.cover"), width: "84px", align: "right", drop: 4, sortValue: (l) => l.cover_days ?? -1, exportValue: (l) => l.cover_days, render: (l) => <span className="pl-num">{num(l.cover_days, 1)}</span> },
      {
        key: "flags",
        header: t("plan.fc.head.flags"),
        width: "120px",
        drop: 5,
        exportValue: (l) => l.flags.join(" "),
        render: (l) => (l.flags.length ? <span className="mfg-ellipsis small" title={l.flags.map(codeText).join(", ")}>{l.flags.map(codeText).join(", ")}</span> : null),
      },
      { key: "status", header: t("plan.ss.head.decision"), width: "116px", exportValue: (l) => l.decision, render: (l) => <Chip def={DECISION[l.decision]} value={l.decision} testId="ss-decision" /> },
    ],
    [currency],
  );

  const chips: FilterChip[] = [];
  if (dq) chips.push({ key: "q", label: t("plan.label.search"), value: dq, onClear: () => setQ("") });
  if (abc) chips.push({ key: "abc", label: t("plan.fc.label.abc"), value: abc, onClear: () => set("abc", "") });
  if (xyz) chips.push({ key: "xyz", label: t("plan.fc.label.xyz"), value: xyz, onClear: () => set("xyz", "") });
  const s = run?.summary;
  const selPending = lines.rows.filter((l) => selected.has(l.id) && l.decision === "pending");

  return (
    <div className="col gap-lg" data-testid="ss-page">
      <PageHeader
        title={t("plan.ss.title")}
        meta={run ? <JobChip s={run.status} testId="ss-run-status" /> : null}
        description={t("plan.ss.desc")}
        facts={
          run
            ? [
                [t("plan.ss.fact.run"), run.number],
                [t("plan.ss.fact.calculated"), formatDateTime(run.finished_at ?? run.created_at)],
                [t("plan.ss.fact.pending"), formatNumber(s?.pending ?? 0)],
                [t("plan.ss.fact.delta"), fmtMoney(s?.delta_value ?? 0, currency)],
                ...(s?.capped ? ([[t("plan.ss.fact.capped"), formatNumber(s.capped)]] as [string, string][]) : []),
              ]
            : []
        }
        actions={
          <>
            {list.length > 1 ? (
              <select className="select" aria-label={t("plan.ss.label.run")} value={run?.id ?? ""} onChange={(e) => setParams({ run: e.target.value }, { replace: true })} data-testid="ss-run-select">
                {list.map((r) => (
                  <option key={r.id} value={r.id}>
                    {`${r.number} · ${formatDateTime(r.created_at)}`}
                  </option>
                ))}
              </select>
            ) : null}
            <button type="button" className="btn primary" disabled={!canRun || running || starting} title={canRun ? undefined : needsText("inventory_policy_edit")} onClick={() => void start()} data-testid="ss-run">
              {starting ? <span className="spinner" aria-hidden /> : <Icon name="play" />} {t("plan.ss.btn.run")}
            </button>
          </>
        }
      />
      <MfgError error={err} />
      <MfgError error={runs.error} onRetry={runs.reload} />
      {runs.loading && !runs.data ? <Spinner /> : null}
      {running ? (
        <Banner tone="accent" icon="loader" role="status" testId="ss-running">
          {t("plan.ss.text.running", { n: run?.number ?? "" })}
        </Banner>
      ) : run?.status === "failed" ? (
        <Banner tone="danger" role="alert" title={t("plan.ss.text.failed", { n: run.number })}>
          {run.error ?? ""}
        </Banner>
      ) : null}
      {runs.data && !run ? (
        <div className="card card-body pl-empty" data-testid="ss-empty">
          <Icon name="shield" size={20} />
          <div>
            <strong>{t("plan.ss.empty.title")}</strong>
            <p className="muted">{t("plan.ss.empty.body")}</p>
          </div>
        </div>
      ) : null}
      {run && run.status === "completed" ? (
        <>
          <Matrix run={run} slMatrix={settings.data?.sl_matrix ?? null} currency={currency} abc={abc} xyz={xyz} onPick={(a, x) => setParams((p) => {
            const n = new URLSearchParams(p);
            const same = n.get("abc") === a && n.get("xyz") === x;
            if (same) {
              n.delete("abc");
              n.delete("xyz");
            } else {
              n.set("abc", a);
              n.set("xyz", x);
            }
            return n;
          }, { replace: true })} />
          <FilterBar
            search={{ id: "ss-q", value: q, onChange: setQ, placeholder: t("plan.fc.ph.search"), testId: "ss-search" }}
            chips={chips}
            onClearAll={() => {
              setQ("");
              setParams(run ? { run: run.id } : {}, { replace: true });
            }}
            pageKey="invopt"
          >
            <div className="field">
              <span className="field-label">{t("plan.ss.head.decision")}</span>
              <div className="btn-group" role="group" aria-label={t("plan.ss.head.decision")} data-testid="ss-decision-filter">
                {(["pending", "approved", "rejected", "all"] as const).map((d) => (
                  <button key={d} type="button" className="btn" aria-pressed={decision === d} onClick={() => set("decision", d === "pending" ? "" : d)}>
                    {d === "all" ? t("plan.label.all") : t(DECISION[d].label)}
                  </button>
                ))}
              </div>
            </div>
          </FilterBar>
          {canDecide && selected.size ? (
            <div className="pl-bulk" role="region" aria-label={t("plan.ss.aria.bulk")} data-testid="ss-bulk">
              <span>{t("plan.ss.tpl.selected", { n: plural(selected.size, t("plan.noun.proposal"), t("plan.noun.proposals")) })}</span>
              <button type="button" className="btn primary sm" disabled={!selPending.length} onClick={() => setDeciding("approved")} data-testid="ss-approve">
                <Icon name="check" /> {t("plan.ss.btn.approve")}
              </button>
              <button type="button" className="btn sm" disabled={!selPending.length} onClick={() => setDeciding("rejected")} data-testid="ss-reject">
                <Icon name="x" /> {t("plan.ss.btn.reject")}
              </button>
              <button type="button" className="btn ghost sm" onClick={() => setSelected(new Set())}>
                {t("plan.ss.btn.clear")}
              </button>
            </div>
          ) : null}
          <MfgError error={lines.error} onRetry={lines.reload} />
          <VirtualTable
            rows={lines.rows}
            columns={columns}
            rowKey={(l) => l.id}
            label={t("plan.ss.aria.table")}
            testId="ss-lines"
            loading={lines.loading && !lines.rows.length}
            totalCount={lines.total}
            onEndReached={lines.onEndReached}
            selection={canDecide ? { selected, onChange: setSelected, rowId: (l) => l.id, rowLabel: (l) => l.part_number ?? l.item_id } : undefined}
            rowExtras={(l) => ({ testId: "ss-line", data: { decision: l.decision, item: l.part_number } })}
            exportName="safety-stock-proposals"
            empty={decision === "pending" ? t("plan.ss.empty.pending") : t("plan.ss.empty.lines")}
            card={{ title: "item", status: "status", fields: ["class", "current", "proposed"] }}
            footer={<span>{t("plan.tpl.showing", { n: t("common.nOfM", { n: formatNumber(lines.rows.length), m: formatNumber(lines.total) }), noun: t("plan.noun.proposals") })}</span>}
          />
        </>
      ) : null}
      {deciding && run ? (
        <DecideDialog
          decision={deciding}
          count={selPending.length}
          onClose={() => setDeciding(null)}
          run={async (reason) => {
            const r = await decideSs(run.id, { line_ids: selPending.map((l) => l.id), decision: deciding, reason });
            toast(deciding === "approved" ? t("plan.ss.toast.approved", { n: plural(r.decided, t("plan.noun.proposal"), t("plan.noun.proposals")), m: formatNumber(r.items_updated) }) : t("plan.ss.toast.rejected", { n: plural(r.decided, t("plan.noun.proposal"), t("plan.noun.proposals")) }));
            setDeciding(null);
            setSelected(new Set());
            lines.reload();
            runs.reload();
          }}
        />
      ) : null}
    </div>
  );
}

function Delta({ v }: { v: number }) {
  if (Math.abs(v) < 0.5) return <span className="muted pl-num">0</span>;
  return (
    <span className="pl-num" aria-label={v > 0 ? t("plan.ss.aria.up", { v: num(v) }) : t("plan.ss.aria.down", { v: num(-v) })}>
      {v > 0 ? "▲ +" : "▼ −"}
      {num(Math.abs(v))}
    </span>
  );
}

/** ABC x XYZ matrix: items and value per cell, the service level it targets; a cell filters the proposals. */
function Matrix({ run, slMatrix, currency, abc, xyz, onPick }: { run: SsRun; slMatrix: Record<string, number> | null; currency?: string; abc: string; xyz: string; onPick(a: string, x: string): void }) {
  const m = run.summary.matrix ?? {};
  let maxV = 0;
  for (const c of Object.values(m)) maxV = Math.max(maxV, c.value);
  return (
    <section className="card" aria-labelledby="ss-matrix-h" data-testid="ss-matrix">
      <div className="card-header pl-card-header">
        <h2 className="pl-h2" id="ss-matrix-h">{t("plan.ss.matrix.title")}</h2>
        <span className="muted small">{t("plan.ss.matrix.hint")}</span>
      </div>
      <div className="card-body pl-matrix-wrap">
        <table className="pl-matrix">
          <thead>
            <tr>
              <th scope="col"><span className="sr-only">{t("plan.fc.label.abc")}</span></th>
              {XYZ.map((x) => (
                <th key={x} scope="col">
                  <span className="pl-class">{x}</span> <span className="muted small">{t(`plan.ss.xyz.${x}` as const)}</span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {ABC.map((a) => (
              <tr key={a}>
                <th scope="row">
                  <span className="pl-class">{a}</span> <span className="muted small">{t(`plan.ss.abc.${a}` as const)}</span>
                </th>
                {XYZ.map((x) => {
                  const c = m[`${a}${x}`];
                  const on = abc === a && xyz === x;
                  const sl = slMatrix?.[`${a}${x}`];
                  const share = maxV > 0 && c ? c.value / maxV : 0;
                  return (
                    <td key={x}>
                      <button
                        type="button"
                        className={`pl-matrix-cell${on ? " on" : ""}`}
                        aria-pressed={on}
                        onClick={() => onPick(a, x)}
                        data-testid="ss-matrix-cell"
                        data-cell={`${a}${x}`}
                        style={{ ["--pl-share" as string]: `${Math.round(share * 100)}%` }}
                        aria-label={t("plan.ss.matrix.cellAria", { cell: `${a}${x}`, n: num(c?.count ?? 0), v: fmtMoney(c?.value ?? 0, currency), sl: sl ? pct(sl, 1) : "–" })}
                      >
                        <span className="pl-matrix-n">{plural(c?.count ?? 0, t("plan.noun.item"), t("plan.noun.items"))}</span>
                        <span className="pl-matrix-v">{fmtMoney(c?.value ?? 0, currency)}</span>
                        <span className="pl-matrix-sl">{sl ? t("plan.ss.matrix.sl", { v: pct(sl, 0) }) : ""}</span>
                        <span className="pl-matrix-bar" aria-hidden />
                      </button>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function DecideDialog({ decision, count, onClose, run }: { decision: "approved" | "rejected"; count: number; onClose(): void; run(reason: string): Promise<void> }) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const n = plural(count, t("plan.noun.proposal"), t("plan.noun.proposals"));
  return (
    <ConfirmDialog
      title={decision === "approved" ? t("plan.ss.dlg.approveTitle", { n }) : t("plan.ss.dlg.rejectTitle", { n })}
      confirmLabel={decision === "approved" ? t("plan.ss.btn.approve") : t("plan.ss.btn.reject")}
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
        <p style={{ margin: 0 }}>{decision === "approved" ? t("plan.ss.dlg.approveBody") : t("plan.ss.dlg.rejectBody")}</p>
        <MfgError error={err} />
        <div className="field">
          <label htmlFor="ss-reason">
            {t("plan.label.reason")} <span className="req" aria-hidden>*</span>
          </label>
          <textarea id="ss-reason" className="textarea" rows={2} maxLength={500} value={text} onChange={(e) => setText(e.target.value)} placeholder={t("plan.ss.ph.reason")} data-testid="ss-reason" data-autofocus />
        </div>
      </div>
    </ConfirmDialog>
  );
}
