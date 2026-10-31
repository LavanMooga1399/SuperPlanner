/**
 * `/mfg/floor/lines/:lineId/downtime` (M4 12, #209/#210): report the line down (kind, reason, expected end) in three
 * taps, or change the expected end of the open downtime (`?edit=<id>`). Works offline (queued, synced later).
 */
import { useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router";
import { Icon } from "../../components/Icon";
import { listDowntime } from "../api/clientM4";
import { DOWNTIME_KINDS, type DowntimeKind } from "../api/typesM4";
import { usePlantClock } from "../lib/plantTime";
import { mfgPaths } from "../lib/paths";
import { useCan } from "../lib/permissions";
import { useLoad } from "../lib/useMfg";
import { useFloor } from "./FloorLayout";
import { DOWNTIME, floorErrorText } from "./floorText";
import { submitDowntimeOpen, submitDowntimeUpdate } from "./offlineQueue";

const QUICK = [30, 60, 120, 240];

export function FloorDowntime() {
  const { lineId = "" } = useParams();
  const [params] = useSearchParams();
  const editId = params.get("edit");
  const navigate = useNavigate();
  const floor = useFloor();
  const clock = usePlantClock();
  const can = useCan("downtime_report");
  const open = useLoad((signal) => (editId ? listDowntime({ line_id: lineId, open: true }, signal) : null), [lineId, editId]);
  const editing = editId ? (open.data?.items ?? []).find((x) => x.id === editId) ?? null : null;
  const [kind, setKind] = useState<DowntimeKind | "">("");
  const [reason, setReason] = useState("");
  const [planned, setPlanned] = useState(false);
  const [quick, setQuick] = useState<number | null>(60);
  const [custom, setCustom] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const expectedEnd = (): string | null => {
    if (custom) return clock.fromLocal(custom);
    if (quick === null) return null;
    return new Date(Date.now() + quick * 60000).toISOString();
  };

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const out = editing
        ? await submitDowntimeUpdate(editing.id, editing.row_version, { expected_end_at: expectedEnd(), ...(reason ? { reason } : {}) }, "Downtime expected end changed")
        : await submitDowntimeOpen(
            { line_id: lineId, kind: kind as DowntimeKind, planned, start_at: new Date().toISOString(), expected_end_at: expectedEnd(), reason },
            `Line down (${DOWNTIME[kind as DowntimeKind]?.label ?? kind})`,
          );
      floor.flash(out.status === "queued" ? "Saved on this tablet; it will sync when the network is back" : editing ? "Expected end changed" : "Line reported down; planners are notified");
      navigate(mfgPaths.floorLine(lineId));
    } catch (e) {
      setError(floorErrorText(e));
    } finally {
      setBusy(false);
    }
  };

  if (!can) return <div className="floor-card muted">Your role cannot report downtime.</div>;
  return (
    <section className="floor-card" aria-label="Report downtime" data-testid="floor-downtime">
      <h1>{editing ? "Change when the line is expected back" : "Report the line down"}</h1>
      {!editing ? (
        <>
          <h2 style={{ fontSize: 18 }}>What happened?</h2>
          <div className="floor-grid" role="radiogroup" aria-label="Kind">
            {DOWNTIME_KINDS.map((k) => (
              <button key={k} type="button" role="radio" aria-checked={kind === k} className={`floor-tile${kind === k ? " active" : ""}`} onClick={() => setKind(k)} data-testid={`downtime-kind-${k}`}>
                <Icon name={DOWNTIME[k].icon} size={22} />
                <strong style={{ fontSize: 18 }}>{DOWNTIME[k].label}</strong>
              </button>
            ))}
          </div>
          <label className="checkbox">
            <input type="checkbox" checked={planned} onChange={(e) => setPlanned(e.target.checked)} /> Planned stop (e.g. scheduled maintenance)
          </label>
        </>
      ) : null}
      <div className="field">
        <label htmlFor="dt-reason">Reason</label>
        <input id="dt-reason" className="input" value={reason} onChange={(e) => setReason(e.target.value)} maxLength={200} placeholder={editing?.reason || "e.g. conveyor jam, nozzle broken"} data-testid="downtime-reason" />
      </div>
      <h2 style={{ fontSize: 18 }}>Expected back</h2>
      <div className="floor-grid" role="radiogroup" aria-label="Expected back">
        {QUICK.map((m) => (
          <button
            key={m}
            type="button"
            role="radio"
            aria-checked={quick === m && !custom}
            className={`floor-tile${quick === m && !custom ? " active" : ""}`}
            onClick={() => {
              setQuick(m);
              setCustom("");
            }}
          >
            <strong style={{ fontSize: 18 }}>in {m < 60 ? `${m} min` : `${m / 60} h`}</strong>
          </button>
        ))}
        <button
          type="button"
          role="radio"
          aria-checked={quick === null && !custom}
          className={`floor-tile${quick === null && !custom ? " active" : ""}`}
          onClick={() => {
            setQuick(null);
            setCustom("");
          }}
        >
          <strong style={{ fontSize: 18 }}>Not known</strong>
          <span className="small muted">the plan assumes 4 h</span>
        </button>
      </div>
      <div className="field" style={{ maxWidth: 320 }}>
        <label htmlFor="dt-custom">Or a time</label>
        <input id="dt-custom" className="input" type="datetime-local" value={custom} onChange={(e) => setCustom(e.target.value)} />
      </div>
      {error ? (
        <div className="floor-flash danger" role="alert">
          <Icon name="alert" /> {error}
        </div>
      ) : null}
      <div className="row wrap">
        <button type="button" className="btn danger floor-action" disabled={busy || (!editing && !kind)} onClick={() => void submit()} data-testid="downtime-submit">
          <Icon name={editing ? "save" : "alert"} /> {editing ? "Save" : "Line is down"}
        </button>
        <button type="button" className="btn floor-btn" onClick={() => navigate(mfgPaths.floorLine(lineId))}>
          Cancel
        </button>
      </div>
    </section>
  );
}
