/** Schedule exceptions (M3 12, 10 `APS_*`): filter chips by severity and code, messages with server links. */
import { useSearchParams } from "react-router";
import { listApsExceptions } from "../../api/clientM3";
import { MRP_SEVERITIES, type MrpExceptionRow, type MrpSeverity } from "../../api/typesM2";
import { ExceptionList } from "../../components/ExceptionList";
import { MfgError } from "../../components/Feedback";
import { MrpSeverityBadge } from "../../components/StatusM2";
import { exceptionLabel } from "../../lib/mrpText";
import { setSearchParam, usePaged } from "../../lib/usePaged";
import { useApsRun } from "./ApsRunShell";

const csv = (v: string | null) => (v ?? "").split(",").filter(Boolean);

export function ApsExceptionsTab() {
  const { run } = useApsRun();
  const [params, setParams] = useSearchParams();
  const codes = csv(params.get("code"));
  const sevs = csv(params.get("severity"));
  const data = usePaged<MrpExceptionRow>(
    (offset, limit, signal) => listApsExceptions(run.id, { code: codes.length ? codes : undefined, severity: sevs.length ? sevs : undefined, limit, offset }, signal),
    [run.id, codes.join(","), sevs.join(",")],
  );
  const counts = (data.last as unknown as { counts?: { by_severity: Record<MrpSeverity, number>; by_code: Record<string, number> } } | null)?.counts;
  const toggle = (k: "code" | "severity", list: string[], v: string) => setSearchParam(setParams, k, (list.includes(v) ? list.filter((x) => x !== v) : [...list, v]).join(","));
  return (
    <div className="col gap-lg" data-testid="aps-exceptions">
      <div className="row wrap" role="group" aria-label="Filter by severity">
        {MRP_SEVERITIES.map((s) => (
          <button key={s} type="button" className="btn sm" aria-pressed={sevs.includes(s)} onClick={() => toggle("severity", sevs, s)}>
            <MrpSeverityBadge severity={s} label={`${s === "critical" ? "Critical" : s === "warning" ? "Warnings" : "Info"}: ${counts?.by_severity[s] ?? 0}`} />
          </button>
        ))}
      </div>
      {counts ? (
        <div className="row wrap" role="group" aria-label="Filter by message">
          {Object.entries(counts.by_code).map(([c, n]) => (
            <button key={c} type="button" className="btn sm mfg-code-chip" aria-pressed={codes.includes(c)} onClick={() => toggle("code", codes, c)} title={c} data-code={c}>
              {exceptionLabel(c)} {n}
            </button>
          ))}
        </div>
      ) : null}
      <MfgError error={data.error} onRetry={data.reload} />
      {data.rows.length === 0 && !data.loading ? <p className="muted">No messages.</p> : null}
      <section className="card">
        <ExceptionList items={data.rows} />
        {data.rows.length < data.total ? (
          <div className="card-footer">
            <button type="button" className="btn sm" onClick={data.onEndReached} disabled={data.loading}>
              Show more ({data.rows.length} of {data.total})
            </button>
          </div>
        ) : null}
      </section>
    </div>
  );
}
