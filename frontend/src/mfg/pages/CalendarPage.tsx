/**
 * `/mfg/plant/calendar` (`?line=`, `?exception=`, M 11.1/11.3): calendar exceptions (holidays, shutdowns,
 * maintenance) and the month view of a line's working windows. Saving an exception refreshes the month view,
 * so a new holiday removes that day's windows.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { Icon } from "../../components/Icon";
import {
  createCalendarException,
  deleteCalendarException,
  listCalendarExceptions,
  listGroups,
  listLines,
  updateCalendarException,
} from "../api/client";
import type {
  CalendarExceptionInput,
  CalendarExceptionRecord,
  ExceptionKind,
  ExceptionScope,
  GroupRecord,
  LineRecord,
} from "../api/types";
import { ConflictBanner, MfgError, Spinner } from "../components/Feedback";
import { CheckField, SelectField, TextField } from "../components/Field";
import { LineCalendar } from "../components/LineCalendar";
import { addDays, fmtLocalDateTime, isoToLocal, localToIso } from "../lib/format";
import { isConflict, todayInOffset, useLoad, usePlant } from "../lib/useMfg";

const KIND_LABEL: Record<ExceptionKind, string> = { holiday: "Holiday", shutdown: "Shutdown", maintenance: "Maintenance" };

export function CalendarPage() {
  const [params, setParams] = useSearchParams();
  const lineParam = params.get("line");
  const exceptionParam = params.get("exception");
  const plant = usePlant();
  const offset = plant.data?.utc_offset ?? "+00:00";
  const [tick, setTick] = useState(0);
  const exceptions = useLoad((signal) => listCalendarExceptions({}, signal), [tick]);
  const groups = useLoad((signal) => listGroups({}, signal), []);
  const lines = useLoad((signal) => listLines({}, signal), []);
  const [month, setMonth] = useState(() => todayInOffset(offset).slice(0, 7));
  const [editing, setEditing] = useState<CalendarExceptionRecord | "new" | null>(null);
  const [del, setDel] = useState<CalendarExceptionRecord | null>(null);
  const [delError, setDelError] = useState<unknown>(null);
  const opened = useRef<string | null>(null);
  const listRef = useRef<HTMLTableElement>(null);

  const allLines = lines.data?.items ?? [];
  const line = allLines.find((l) => l.id === lineParam) ?? allLines[0] ?? null;
  const list = useMemo(() => [...(exceptions.data?.items ?? [])].sort((a, b) => a.start.localeCompare(b.start)), [exceptions.data]);

  useEffect(() => {
    if (!exceptionParam || opened.current === exceptionParam) return;
    const x = list.find((e) => e.id === exceptionParam);
    if (!x) return;
    opened.current = exceptionParam;
    setEditing(x);
    setMonth(isoToLocal(x.start, offset).slice(0, 7) || month);
    listRef.current?.querySelector(`[data-exception-id="${x.id}"]`)?.scrollIntoView({ block: "center" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [exceptionParam, list]);

  const setParam = (k: string, v: string | null) =>
    setParams(
      (prev) => {
        const n = new URLSearchParams(prev);
        if (v) n.set(k, v);
        else n.delete(k);
        return n;
      },
      { replace: true },
    );

  const shiftMonth = (delta: number) => {
    const d = new Date(`${month}-01T00:00:00Z`);
    d.setUTCMonth(d.getUTCMonth() + delta);
    setMonth(d.toISOString().slice(0, 7));
  };

  return (
    <div className="col gap-lg">
      <section className="card" aria-labelledby="cal-title">
        <div className="card-header">
          <h2 id="cal-title">Working time of a line</h2>
          <div className="row wrap">
            <label className="row small">
              <span className="muted">Line</span>
              <select className="select sm" value={line?.id ?? ""} onChange={(e) => setParam("line", e.target.value)} data-testid="calendar-line" style={{ minWidth: 180 }}>
                {allLines.map((l) => (
                  <option key={l.id} value={l.id}>
                    {l.code} - {l.name} ({l.group.code})
                  </option>
                ))}
              </select>
            </label>
            <div className="btn-group" role="group" aria-label="Month">
              <button type="button" className="btn sm" onClick={() => shiftMonth(-1)} aria-label="Previous month" data-testid="calendar-prev">
                <Icon name="chevron-right" style={{ transform: "rotate(180deg)" }} />
              </button>
              <input type="month" className="input sm" style={{ width: 150, borderRadius: 0 }} value={month} onChange={(e) => e.target.value && setMonth(e.target.value)} aria-label="Month" data-testid="calendar-month" />
              <button type="button" className="btn sm" onClick={() => shiftMonth(1)} aria-label="Next month" data-testid="calendar-next">
                <Icon name="chevron-right" />
              </button>
            </div>
          </div>
        </div>
        <div className="card-body">
          <MfgError error={lines.error} onRetry={lines.reload} />
          {lines.loading && !lines.data ? <Spinner /> : null}
          {lines.data && !line ? <p className="muted" style={{ margin: 0 }}>No lines yet. Add stages and lines first.</p> : null}
          {line ? <LineCalendar line={line} month={month} utcOffset={offset} exceptions={list} refreshKey={tick} /> : null}
        </div>
      </section>

      <section className="card" aria-labelledby="exc-title">
        <div className="card-header">
          <h2 id="exc-title">Holidays, shutdowns and maintenance</h2>
          <button type="button" className="btn sm primary" onClick={() => setEditing("new")} data-testid="exception-new">
            <Icon name="plus" /> Add
          </button>
        </div>
        <div className="card-body col">
          <p className="muted small" style={{ margin: 0 }}>
            These remove working time (base and optional) from the whole plant, a stage or one line. Times are plant
            time ({offset}).
          </p>
          <MfgError error={exceptions.error} onRetry={exceptions.reload} />
          <MfgError error={delError} title="Could not delete" />
          <div className="table-wrap">
            <table className="table" ref={listRef} data-testid="exceptions-table">
              <thead>
                <tr>
                  <th>What</th>
                  <th>Applies to</th>
                  <th>From</th>
                  <th>Until</th>
                  <th>Label</th>
                  <th>
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {list.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="muted">
                      Nothing planned.
                    </td>
                  </tr>
                ) : null}
                {list.map((x) => (
                  <tr key={x.id} data-testid="exception-row" data-exception-id={x.id} className={x.id === exceptionParam ? "mfg-selected" : undefined}>
                    <td>
                      <span className="badge danger">
                        <Icon name="ban" /> {KIND_LABEL[x.kind]}
                      </span>
                    </td>
                    <td>{x.target ? `${x.target.type === "group" ? "Stage" : "Line"} ${x.target.code}` : "Whole plant"}</td>
                    <td className="nowrap">{fmtLocalDateTime(x.start)}</td>
                    <td className="nowrap">{fmtLocalDateTime(x.end)}</td>
                    <td>{x.label}</td>
                    <td className="nowrap">
                      <button
                        type="button"
                        className="btn sm"
                        onClick={() => {
                          setParam("exception", x.id);
                          opened.current = x.id;
                          setEditing(x);
                        }}
                      >
                        Edit
                      </button>
                      <button type="button" className="btn sm ghost icon" aria-label={`Delete ${x.label || x.kind}`} onClick={() => setDel(x)}>
                        <Icon name="trash" />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {editing ? (
            <ExceptionForm
              key={editing === "new" ? "new" : editing.id}
              exception={editing === "new" ? null : editing}
              offset={offset}
              groups={groups.data?.items ?? []}
              lines={allLines}
              defaultLine={line}
              onClose={() => {
                setEditing(null);
                setParam("exception", null);
              }}
              onSaved={(x) => {
                setEditing(null);
                setParam("exception", null);
                setMonth(isoToLocal(x.start, offset).slice(0, 7) || month);
                setTick((t) => t + 1);
              }}
            />
          ) : null}
        </div>
      </section>
      {del ? (
        <ConfirmDialog
          title="Delete this entry?"
          confirmLabel="Delete"
          danger
          onCancel={() => setDel(null)}
          onConfirm={() => {
            const x = del;
            setDel(null);
            setDelError(null);
            deleteCalendarException(x.id, x.row_version).then(() => setTick((t) => t + 1), setDelError);
          }}
        >
          <p style={{ margin: 0 }}>The working time comes back for that period.</p>
        </ConfirmDialog>
      ) : null}
    </div>
  );
}

function ExceptionForm({
  exception,
  offset,
  groups,
  lines,
  defaultLine,
  onClose,
  onSaved,
}: {
  exception: CalendarExceptionRecord | null;
  offset: string;
  groups: GroupRecord[];
  lines: LineRecord[];
  defaultLine: LineRecord | null;
  onClose(): void;
  onSaved(x: CalendarExceptionRecord): void;
}) {
  const startLocal = exception ? isoToLocal(exception.start, offset) : "";
  const endLocal = exception ? isoToLocal(exception.end, offset) : "";
  const wholeDays = exception ? startLocal.endsWith("T00:00") && endLocal.endsWith("T00:00") : true;
  const today = todayInOffset(offset);
  const [scope, setScope] = useState<ExceptionScope>(exception?.scope ?? "plant");
  const [groupId, setGroupId] = useState(exception?.group_id ?? groups[0]?.id ?? "");
  const [lineId, setLineId] = useState(exception?.line_id ?? defaultLine?.id ?? lines[0]?.id ?? "");
  const [kind, setKind] = useState<ExceptionKind>(exception?.kind ?? "holiday");
  const [allDay, setAllDay] = useState(wholeDays);
  const [fromDate, setFromDate] = useState(startLocal.slice(0, 10) || today);
  const [toDate, setToDate] = useState(endLocal ? addDays(endLocal.slice(0, 10), -1) : today);
  const [start, setStart] = useState(startLocal || `${today}T08:00`);
  const [end, setEnd] = useState(endLocal || `${today}T16:00`);
  const [label, setLabel] = useState(exception?.label ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [conflict, setConflict] = useState(false);

  const body = (): CalendarExceptionInput => ({
    scope,
    group_id: scope === "group" ? groupId : null,
    line_id: scope === "line" ? lineId : null,
    kind,
    start: allDay ? localToIso(`${fromDate}T00:00`, offset) : localToIso(start, offset),
    end: allDay ? localToIso(`${addDays(toDate, 1)}T00:00`, offset) : localToIso(end, offset),
    label: label.trim(),
  });
  const invalid = allDay ? !fromDate || !toDate || toDate < fromDate : !start || !end || end <= start;

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      const x = exception ? await updateCalendarException(exception.id, body(), exception.row_version) : await createCalendarException(body());
      onSaved(x);
    } catch (e) {
      if (isConflict(e)) setConflict(true);
      else setError(e);
      setBusy(false);
    }
  };

  return (
    <form
      className="card mfg-inline-form"
      onSubmit={(e) => {
        e.preventDefault();
        void save();
      }}
      data-testid="exception-form"
    >
      <div className="card-header">
        <h3>{exception ? "Edit entry" : "New holiday, shutdown or maintenance"}</h3>
      </div>
      <div className="card-body col">
        {conflict ? <ConflictBanner onReload={() => window.location.reload()} what="this entry" /> : null}
        <MfgError error={error} title="Could not save" />
        <div className="form-grid">
          <SelectField label="What" value={kind} onChange={setKind} options={(Object.keys(KIND_LABEL) as ExceptionKind[]).map((k) => ({ value: k, label: KIND_LABEL[k] }))} testId="exception-kind" />
          <SelectField
            label="Applies to"
            value={scope}
            onChange={setScope}
            options={[
              { value: "plant", label: "Whole plant" },
              { value: "group", label: "One stage" },
              { value: "line", label: "One line" },
            ]}
            testId="exception-scope"
          />
          {scope === "group" ? <SelectField label="Stage" value={groupId} onChange={setGroupId} options={groups.map((g) => ({ value: g.id, label: `${g.code} - ${g.name}` }))} /> : null}
          {scope === "line" ? <SelectField label="Line" value={lineId} onChange={setLineId} options={lines.map((l) => ({ value: l.id, label: `${l.code} - ${l.name}` }))} testId="exception-line" /> : null}
          <TextField label="Label" value={label} onChange={setLabel} maxLength={100} placeholder="e.g. Plant holiday" testId="exception-label" />
        </div>
        <CheckField label="Whole days" checked={allDay} onChange={setAllDay} />
        {allDay ? (
          <div className="form-grid">
            <TextField label="First day" type="date" value={fromDate} onChange={setFromDate} testId="exception-from" />
            <TextField label="Last day (included)" type="date" value={toDate} onChange={setToDate} testId="exception-to" />
          </div>
        ) : (
          <div className="form-grid">
            <TextField label="Starts" type="datetime-local" value={start} onChange={setStart} testId="exception-start" />
            <TextField label="Ends" type="datetime-local" value={end} onChange={setEnd} testId="exception-end" />
          </div>
        )}
        <div className="row">
          <button type="submit" className="btn primary sm" disabled={busy || invalid} data-testid="exception-save">
            {busy ? <span className="spinner" aria-hidden /> : <Icon name="save" />} Save
          </button>
          <button type="button" className="btn sm" onClick={onClose}>
            Cancel
          </button>
          {invalid ? <span className="field-error">The end must be after the start.</span> : null}
        </div>
      </div>
    </form>
  );
}
