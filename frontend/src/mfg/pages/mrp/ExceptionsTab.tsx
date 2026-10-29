/**
 * Exceptions (M2 14.2 `ExceptionsTab`, #158): severity and code filter chips (counts from the server), the
 * messages in a virtual table (up to 50,000 per run) and the full text of the focused message with its action
 * link (server-built, 14.3).
 */
import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router";
import { Icon } from "../../../components/Icon";
import { listRunExceptions } from "../../api/clientM2";
import { MRP_SEVERITIES, type ExceptionPage, type MrpExceptionRow, type MrpSeverity } from "../../api/typesM2";
import { ExceptionDetail } from "../../components/ExceptionList";
import { MfgError } from "../../components/Feedback";
import { MrpSeverityBadge } from "../../components/StatusM2";
import { VirtualTable, type Column } from "../../components/VirtualTable";
import { fmtDate } from "../../lib/format";
import { fmtNum } from "../../lib/formatM2";
import { exceptionLabel } from "../../lib/mrpText";
import { setSearchParam, usePaged } from "../../lib/usePaged";
import { useDebounced } from "../../lib/useMfg";
import { useRun } from "./RunShell";
import { severityOfCode } from "./RunSummaryTab";

const csv = (v: string | null) => new Set((v ?? "").split(",").filter(Boolean));

export function ExceptionsTab() {
  const { run } = useRun();
  const [params, setParams] = useSearchParams();
  const codes = csv(params.get("code"));
  const sevs = csv(params.get("severity")) as Set<MrpSeverity>;
  const [q, setQ] = useState(params.get("q") ?? "");
  const dq = useDebounced(q.trim(), 250);
  const set = (k: string, v: string) => setSearchParam(setParams, k, v);
  useEffect(() => set("q", dq), [dq]); // eslint-disable-line react-hooks/exhaustive-deps
  const codeKey = [...codes].sort().join(",");
  const sevKey = [...sevs].sort().join(",");
  const data = usePaged<MrpExceptionRow, ExceptionPage>(
    (offset, limit, signal) => listRunExceptions(run.id, { code: codeKey || undefined, severity: sevKey || undefined, q: dq || undefined, limit, offset }, signal),
    [run.id, codeKey, sevKey, dq],
  );
  const [active, setActive] = useState(0);
  useEffect(() => setActive(0), [codeKey, sevKey, dq]);
  // chip counts are of the whole run (summary), so they do not shrink while filtering
  const all = run.summary?.exceptions;
  const toggle = (key: "code" | "severity", s: Set<string>, v: string) => {
    const n = new Set(s);
    if (n.has(v)) n.delete(v);
    else n.add(v);
    set(key, [...n].join(","));
  };
  const columns: Column<MrpExceptionRow>[] = [
    { key: "sev", header: "Severity", width: "104px", render: (e) => <MrpSeverityBadge severity={e.severity} /> },
    { key: "what", header: "Message", width: "minmax(150px, 1fr)", render: (e) => <span className="mfg-ellipsis">{exceptionLabel(e.code)}</span> },
    { key: "subj", header: "About", width: "minmax(150px, 1fr)", render: (e) => <span className="mono mfg-ellipsis">{e.subject.label}</span> },
    { key: "item", header: "Part", width: "minmax(120px, 0.9fr)", render: (e) => <span className="mono mfg-ellipsis">{e.item?.part_number ?? ""}</span> },
    { key: "date", header: "Date", width: "100px", render: (e) => fmtDate(e.date) },
    { key: "qty", header: "Qty", width: "80px", align: "right", render: (e) => (e.qty === null ? "" : fmtNum(e.qty)) },
    { key: "days", header: "Days", width: "60px", align: "right", render: (e) => e.days ?? "" },
    { key: "text", header: "Details", width: "minmax(220px, 2.5fr)", render: (e) => <span className="mfg-ellipsis small" title={e.message}>{e.message}</span> },
    {
      key: "go",
      header: <span className="sr-only">Open</span>,
      label: "Open",
      width: "76px",
      render: (e) =>
        e.link ? (
          <Link to={e.link} className="btn sm" tabIndex={-1} data-testid="exception-link" onClick={(ev) => ev.stopPropagation()}>
            Open
          </Link>
        ) : null,
    },
  ];
  const cur = data.rows[Math.min(active, data.rows.length - 1)];
  return (
    <div className="col gap-lg">
      <div className="row wrap" role="group" aria-label="Filter by severity">
        {MRP_SEVERITIES.map((s) => (
          <button key={s} type="button" className="btn sm" aria-pressed={sevs.has(s)} onClick={() => toggle("severity", sevs, s)} data-testid={`exception-filter-${s}`}>
            <MrpSeverityBadge severity={s} label={`${s === "critical" ? "Critical" : s === "warning" ? "Warnings" : "Info"}: ${all?.by_severity[s] ?? 0}`} />
          </button>
        ))}
        <div className="field" style={{ marginLeft: "auto", width: 260 }}>
          <input className="input sm" type="search" aria-label="Search messages" placeholder="Search part or document" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
      </div>
      {all ? (
        <div className="row wrap" role="group" aria-label="Filter by message">
          {Object.entries(all.by_code)
            .filter(([, n]) => n > 0)
            .map(([code, n]) => (
              <button key={code} type="button" className="btn sm mfg-code-chip" aria-pressed={codes.has(code)} onClick={() => toggle("code", codes, code)} data-testid="exception-code-chip" data-code={code} title={code}>
                <Icon name={severityOfCode(code) === "critical" ? "x" : severityOfCode(code) === "warning" ? "alert" : "info"} size={12} /> {exceptionLabel(code)} {n.toLocaleString()}
              </button>
            ))}
          {codes.size || sevs.size ? (
            <button
              type="button"
              className="btn sm ghost"
              onClick={() =>
                setParams(
                  (p) => {
                    const n = new URLSearchParams(p);
                    n.delete("code");
                    n.delete("severity");
                    return n;
                  },
                  { replace: true },
                )
              }
            >
              <Icon name="x" /> Clear filters
            </button>
          ) : null}
        </div>
      ) : null}
      <MfgError error={data.error} onRetry={data.reload} />
      <VirtualTable
        rows={data.rows}
        columns={columns}
        rowKey={(e) => e.id}
        label="Exception messages"
        testId="exceptions-table"
        totalCount={data.total}
        height="min(50vh, 560px)"
        activeIndex={active}
        onActiveChange={setActive}
        rowExtras={(e) => ({ testId: "exception-row", data: { code: e.code, severity: e.severity, subject: e.subject.label } })}
        onEndReached={data.onEndReached}
        empty={data.loading ? "Loading messages…" : "No messages match these filters."}
        footer={<span className="muted small">Showing {data.rows.length.toLocaleString()} of {data.total.toLocaleString()} messages · the focused message is shown in full below</span>}
      />
      {cur ? (
        <section className="card card-body" aria-live="polite" data-testid="exception-focus">
          <ExceptionDetail ex={cur} testId="exception-detail" />
        </section>
      ) : null}
    </div>
  );
}
