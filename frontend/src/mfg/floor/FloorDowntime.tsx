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
import { t } from "../../lib/i18n";

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
        ? await submitDowntimeUpdate(editing.id, editing.row_version, { expected_end_at: expectedEnd(), ...(reason ? { reason } : {}) }, t("floor.floorDowntime.str.downtimeExpectedEndChanged"))
        : await submitDowntimeOpen(
            { line_id: lineId, kind: kind as DowntimeKind, planned, start_at: new Date().toISOString(), expected_end_at: expectedEnd(), reason },
            t("floor.floorDowntime.tpl.lineDown", { v: DOWNTIME[kind as DowntimeKind]?.label ?? kind }),
          );
      floor.flash(out.status === "queued" ? t("floor.floorDowntime.str.savedOnThisTabletIt") : editing ? t("floor.floorDowntime.str.expectedEndChanged") : t("floor.floorDowntime.str.lineReportedDownPlannersAre"));
      navigate(mfgPaths.floorLine(lineId));
    } catch (e) {
      setError(floorErrorText(e));
    } finally {
      setBusy(false);
    }
  };

  if (!can) return <div className="floor-card muted">{t("floor.floorDowntime.text.yourRoleCannotReportDowntime")}</div>;
  return (
    <section className="floor-card" aria-label={t("floor.floorDowntime.aria.reportDowntime")} data-testid="floor-downtime">
      <h1>{editing ? t("floor.floorDowntime.str.changeWhenTheLineIs") : t("floor.floorDowntime.str.reportTheLineDown")}</h1>
      {!editing ? (
        <>
          <h2 style={{ fontSize: 18 }}>{t("floor.floorDowntime.head.whatHappened")}</h2>
          <div className="floor-grid" role="radiogroup" aria-label={t("floor.floorDowntime.aria.kind")}>
            {DOWNTIME_KINDS.map((k) => (
              <button key={k} type="button" role="radio" aria-checked={kind === k} className={`floor-tile${kind === k ? " active" : ""}`} onClick={() => setKind(k)} data-testid={`downtime-kind-${k}`}>
                <Icon name={DOWNTIME[k].icon} size={22} />
                <strong style={{ fontSize: 18 }}>{DOWNTIME[k].label}</strong>
              </button>
            ))}
          </div>
          <label className="checkbox">
            <input type="checkbox" checked={planned} onChange={(e) => setPlanned(e.target.checked)} />{" "}{t("floor.floorDowntime.text.plannedStopEGScheduled")}
          </label>
        </>
      ) : null}
      <div className="field">
        <label htmlFor="dt-reason">{t("floor.floorDowntime.label.reason")}</label>
        <input id="dt-reason" className="input" value={reason} onChange={(e) => setReason(e.target.value)} maxLength={200} placeholder={editing?.reason || t("floor.floorDowntime.str.eGConveyorJamNozzle")} data-testid="downtime-reason" />
      </div>
      <h2 style={{ fontSize: 18 }}>{t("floor.floorDowntime.head.expectedBack")}</h2>
      <div className="floor-grid" role="radiogroup" aria-label={t("floor.floorDowntime.aria.expectedBack")}>
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
            <strong style={{ fontSize: 18 }}>{t("floor.floorDowntime.text.in", { v: m < 60 ? `${m} min` : `${m / 60} h` })}</strong>
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
          <strong style={{ fontSize: 18 }}>{t("floor.floorDowntime.head.notKnown")}</strong>
          <span className="small muted">{t("floor.floorDowntime.text.thePlanAssumes4H")}</span>
        </button>
      </div>
      <div className="field" style={{ maxWidth: 320 }}>
        <label htmlFor="dt-custom">{t("floor.floorDowntime.label.orATime")}</label>
        <input id="dt-custom" className="input" type="datetime-local" value={custom} onChange={(e) => setCustom(e.target.value)} />
      </div>
      {error ? (
        <div className="floor-flash danger" role="alert">
          <Icon name="alert" /> {error}
        </div>
      ) : null}
      <div className="row wrap">
        <button type="button" className="btn danger floor-action" disabled={busy || (!editing && !kind)} onClick={() => void submit()} data-testid="downtime-submit">
          <Icon name={editing ? "save" : "alert"} /> {editing ? t("floor.floorDowntime.str.save") : t("floor.floorDowntime.str.lineIsDown")}
        </button>
        <button type="button" className="btn floor-btn" onClick={() => navigate(mfgPaths.floorLine(lineId))}>
          {t("floor.floorDowntime.btn.cancel")}
        </button>
      </div>
    </section>
  );
}
