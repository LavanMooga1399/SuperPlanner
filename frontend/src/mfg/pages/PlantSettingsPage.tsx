/** `/mfg/plant/settings` (M 11.1): name, time zone offset, planning horizon, currency. `If-Match: "0"` creates the row. */
import { useEffect, useState } from "react";
import { Icon } from "../../components/Icon";
import { getPlant, updatePlant } from "../api/client";
import { WEEKDAYS, type PlantInput, type PlantRecord, type Weekday } from "../api/types";
import type { PlantM2Fields } from "../api/typesM2";
import { OVERTIME_POLICIES, type OvertimePolicy, type PlantM3Fields } from "../api/typesM3";
import type { PlantM4Fields, ReplanPolicy } from "../api/typesM4";
import { listLocations } from "../api/clientM2";
import { POLICY_TEXT } from "./schedule/ApsRunForm";
import { WEEKDAY_LABEL } from "../lib/format";
import { ConflictBanner, MfgError, SaveState, Spinner } from "../components/Feedback";
import { Field, numOr, SelectField, TextField } from "../components/Field";
import { PermissionGate } from "../components/PermissionGate";
import { isConflict, useLoad, useMeta, usePlant } from "../lib/useMfg";

const OFFSET = /^[+-](0\d|1[0-4]):[0-5]\d$/;

const REPLAN_HELP: Record<ReplanPolicy, string> = {
  notify: "Changes are listed under Replanning; you decide when to make a new schedule.",
  auto_whatif: "A new schedule is prepared after a line stops, a delivery is late, and so on. You compare and publish it.",
  auto_publish: "As above, and published only when it breaks no rules, keeps the frozen work and is not later than the current plan.",
};

export function PlantSettingsPage() {
  const plant = usePlant();
  const [base, setBase] = useState<PlantRecord | null>(null);
  const [f, setF] = useState({
    name: "",
    utc_offset: "+00:00",
    horizon: "90",
    currency: "",
    workdays: ["mon", "tue", "wed", "thu", "fri", "sat"] as Weekday[],
    dayMinutes: "480",
    deferTol: "7",
    releaseWindow: "7",
    overReceipt: "0",
    timeZone: "",
    freeze: "48",
    apsHorizon: "42",
    policy: "suggest" as OvertimePolicy,
    replanPolicy: "notify" as ReplanPolicy,
    debounce: "15",
    overrun: "20",
    adherence: "120",
    receiptLoc: "",
    backflushLoc: "",
  });
  const locs = useLoad((signal) => listLocations({ active: true }, signal).catch(() => null), []);
  const meta = useMeta() as (ReturnType<typeof useMeta> & { time_zones?: string[] }) | null;
  const zones = (() => {
    if (meta?.time_zones?.length) return meta.time_zones;
    try {
      return (Intl as unknown as { supportedValuesOf?: (k: string) => string[] }).supportedValuesOf?.("timeZone") ?? [];
    } catch {
      return [];
    }
  })();
  const [floorExpert, setFloorExpert] = useState(false);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [conflict, setConflict] = useState(false);

  const reset = (p: PlantRecord) => {
    setBase(p);
    const x = p as PlantRecord & PlantM2Fields & PlantM3Fields;
    setF({
      name: p.name,
      utc_offset: p.utc_offset,
      horizon: String(p.planning_horizon_days),
      currency: p.currency,
      workdays: x.mrp_workdays ?? ["mon", "tue", "wed", "thu", "fri", "sat"],
      dayMinutes: String(x.mrp_day_minutes ?? 480),
      deferTol: String(x.mrp_defer_tolerance_days ?? 7),
      releaseWindow: String(x.mrp_release_window_days ?? 7),
      overReceipt: String(x.over_receipt_pct ?? 0),
      timeZone: x.time_zone ?? "",
      freeze: String(x.aps_freeze_hours ?? 48),
      apsHorizon: String(x.aps_horizon_days ?? 42),
      policy: x.aps_overtime_policy ?? "suggest",
      replanPolicy: (p as PlantRecord & PlantM4Fields).replan_policy ?? "notify",
      debounce: String((p as PlantRecord & PlantM4Fields).replan_debounce_minutes ?? 15),
      overrun: String((p as PlantRecord & PlantM4Fields).overrun_tolerance_pct ?? 20),
      adherence: String((p as PlantRecord & PlantM4Fields).adherence_tolerance_minutes ?? 120),
      receiptLoc: (p as PlantRecord & PlantM4Fields).wo_receipt_location_id ?? "",
      backflushLoc: (p as PlantRecord & PlantM4Fields).backflush_location_id ?? "",
    });
    setConflict(false);
  };
  useEffect(() => {
    if (plant.data && !base) reset(plant.data);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [plant.data]);

  if (plant.error && !base) return <MfgError error={plant.error} onRetry={plant.reload} />;
  if (!base) return <Spinner />;

  // M2 3.1: the MRP fields are sent (full replacement) only when the server knows them
  const m2 = "mrp_workdays" in base;
  const m2Body: PlantM2Fields = m2
    ? {
        mrp_workdays: WEEKDAYS.filter((d) => f.workdays.includes(d)),
        mrp_day_minutes: numOr(f.dayMinutes, 480),
        mrp_defer_tolerance_days: numOr(f.deferTol, 7),
        mrp_release_window_days: numOr(f.releaseWindow, 7),
        over_receipt_pct: numOr(f.overReceipt, 0),
      }
    : {};
  // M3 3.1: time zone and schedule defaults, only when the server knows them
  const m3 = "aps_overtime_policy" in base;
  const m3Body: PlantM3Fields = m3
    ? { time_zone: f.timeZone.trim() || null, aps_freeze_hours: numOr(f.freeze, 48), aps_horizon_days: numOr(f.apsHorizon, 42), aps_overtime_policy: f.policy }
    : {};
  // M4 3.1: floor and replanning settings, only when the server knows them
  const m4 = "replan_policy" in base;
  const m4Body: PlantM4Fields = m4
    ? {
        replan_policy: f.replanPolicy,
        replan_debounce_minutes: numOr(f.debounce, 15),
        overrun_tolerance_pct: numOr(f.overrun, 20),
        adherence_tolerance_minutes: numOr(f.adherence, 120),
        wo_receipt_location_id: f.receiptLoc || null,
        backflush_location_id: f.backflushLoc || null,
      }
    : {};
  const body: PlantInput & PlantM2Fields & PlantM3Fields & PlantM4Fields = {
    ...m3Body,
    ...m4Body,
    name: f.name.trim() || "Plant",
    utc_offset: f.utc_offset.trim(),
    planning_horizon_days: numOr(f.horizon, 90),
    currency: f.currency.trim(),
    attributes: base.attributes,
    ...m2Body,
  };
  const horizon = Number(f.horizon);
  const inRange = (t: string, lo: number, hi: number, int = true) => {
    const v = Number(t);
    return t.trim() !== "" && Number.isFinite(v) && v >= lo && v <= hi && (!int || Number.isInteger(v));
  };
  const m2Invalid =
    m2 &&
    (f.workdays.length === 0 ||
      !inRange(f.dayMinutes, 60, 1440, false) ||
      !inRange(f.deferTol, 0, 90) ||
      !inRange(f.releaseWindow, 0, 90) ||
      !inRange(f.overReceipt, 0, 100, false));
  const tzBad = m3 && f.timeZone.trim() !== "" && zones.length > 0 && !zones.includes(f.timeZone.trim());
  const m3Invalid = m3 && (tzBad || !inRange(f.freeze, 0, 336) || !inRange(f.apsHorizon, 7, 120));
  const m4Invalid = m4 && (!inRange(f.debounce, 0, 1440) || !inRange(f.overrun, 0, 500, false) || !inRange(f.adherence, 0, 1440));
  const invalid = m4Invalid || (!m3 || !f.timeZone.trim() ? !OFFSET.test(f.utc_offset.trim()) : false) || !(horizon >= 7 && horizon <= 730) || m2Invalid || m3Invalid;

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      reset(await updatePlant(body, base.row_version));
      setSaved(true);
    } catch (e) {
      if (isConflict(e)) setConflict(true);
      else setError(e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <form
      className="card"
      style={{ maxWidth: 720 }}
      onSubmit={(e) => {
        e.preventDefault();
        void save();
      }}
      data-testid="plant-settings"
    >
      <div className="card-header">
        <h2>Plant settings</h2>
        <SaveState busy={false} saved={saved} />
      </div>
      <div className="card-body col">
        {conflict ? <ConflictBanner onReload={() => void getPlant().then(reset, setError)} what="the plant settings" /> : null}
        <MfgError error={error} title="Could not save" />
        {base.id === null ? <p className="muted small" style={{ margin: 0 }}>Default settings; nothing is stored until you save.</p> : null}
        <TextField label="Plant name" value={f.name} onChange={(v) => setF({ ...f, name: v })} testId="plant-name" />
        <div className="form-grid">
          <TextField
            label="Time zone offset"
            disabled={m3 && Boolean(f.timeZone.trim())}
            value={f.utc_offset}
            onChange={(v) => setF({ ...f, utc_offset: v })}
            placeholder="+05:30"
            hint={OFFSET.test(f.utc_offset.trim()) ? "Shift times, holidays and dates use this offset (no daylight saving)." : "Use the form +05:30 or -04:00."}
            testId="plant-offset"
          />
          <TextField label="Planning horizon (days)" type="number" value={f.horizon} onChange={(v) => setF({ ...f, horizon: v })} hint="7 to 730; used by the data-health check." testId="plant-horizon" />
          <TextField label="Currency" value={f.currency} onChange={(v) => setF({ ...f, currency: v })} maxLength={8} hint="Shown with costs, e.g. INR" />
        </div>
        {m3 ? (
          <fieldset className="mfg-fieldset" data-testid="plant-aps">
            <legend>Time zone and production schedule</legend>
            <div className="form-grid">
              <div className="field">
                <label htmlFor="plant-tz">Time zone</label>
                <input
                  id="plant-tz"
                  className="input"
                  list="plant-tz-list"
                  value={f.timeZone}
                  onChange={(e) => setF({ ...f, timeZone: e.target.value })}
                  placeholder="e.g. Asia/Kolkata"
                  aria-invalid={tzBad}
                  data-testid="tz-select"
                />
                <datalist id="plant-tz-list">
                  {zones.map((z) => (
                    <option key={z} value={z} />
                  ))}
                </datalist>
                <span className="hint">{tzBad ? "Choose a zone from the list." : "With a zone, daylight saving is handled and the offset above is only shown. Empty = use the fixed offset."}</span>
              </div>
              <TextField label="Freeze window (hours)" type="number" value={f.freeze} onChange={(v) => setF({ ...f, freeze: v })} hint="0 to 336. Published operations starting this soon stay where they are." testId="plant-aps-freeze" />
              <TextField label="Schedule horizon (days)" type="number" value={f.apsHorizon} onChange={(v) => setF({ ...f, apsHorizon: v })} hint="7 to 120; default of new schedule runs." testId="plant-aps-horizon" />
              <div className="field">
                <label htmlFor="plant-aps-policy">Overtime in new schedules</label>
                <select id="plant-aps-policy" className="select" value={f.policy} onChange={(e) => setF({ ...f, policy: e.target.value as OvertimePolicy })} data-testid="plant-aps-policy">
                  {OVERTIME_POLICIES.map((p) => (
                    <option key={p} value={p}>
                      {POLICY_TEXT[p].label}
                    </option>
                  ))}
                </select>
                <span className="hint">{POLICY_TEXT[f.policy].help}</span>
              </div>
            </div>
          </fieldset>
        ) : null}
        {m4 ? (
          <fieldset className="mfg-fieldset" data-testid="plant-floor">
            <legend>Shop floor and replanning</legend>
            <div className="form-grid">
              <div className="field">
                <label htmlFor="plant-replan">When the floor or supply changes</label>
                <select id="plant-replan" className="select" value={f.replanPolicy} onChange={(e) => setF({ ...f, replanPolicy: e.target.value as ReplanPolicy })} data-testid="plant-replan-policy">
                  <option value="notify">Notify the planner (recommended)</option>
                  <option value="auto_whatif">Prepare a new schedule automatically</option>
                  <option value="auto_publish">Prepare and publish automatically when safe</option>
                </select>
                <span className="hint">{REPLAN_HELP[f.replanPolicy]}</span>
              </div>
              <SelectField label="Finished goods go to" value={f.receiptLoc} onChange={(v) => setF({ ...f, receiptLoc: v })} options={[{ value: "", label: "Not set (each work order needs one)" }, ...(locs.data?.items ?? []).map((l) => ({ value: l.id, label: `${l.code} - ${l.name}` }))]} hint="Receipt of the last operation's good output." />
              <SelectField label="Backflush from" value={f.backflushLoc} onChange={(v) => setF({ ...f, backflushLoc: v })} options={[{ value: "", label: "Not set" }, ...(locs.data?.items ?? []).map((l) => ({ value: l.id, label: `${l.code} - ${l.name}` }))]} hint="Default line-side stock for backflushed items (a line can override)." />
            </div>
            <button type="button" className="btn ghost sm" style={{ alignSelf: "flex-start" }} aria-expanded={floorExpert} onClick={() => setFloorExpert((v) => !v)}>
              <Icon name={floorExpert ? "chevron-down" : "chevron-right"} /> Expert settings (tolerances, waiting time)
            </button>
            {floorExpert ? (
              <div className="form-grid">
                <TextField label="Collect changes for (min)" type="number" value={f.debounce} onChange={(v) => setF({ ...f, debounce: v })} hint="0 to 1440. Automatic proposals wait this long so several changes go into one run." />
                <TextField label="Overrun warning after (%)" type="number" value={f.overrun} onChange={(v) => setF({ ...f, overrun: v })} hint="A running operation projected this much over its planned time (at least 30 min) raises a warning." />
                <TextField label="On time if within (min)" type="number" value={f.adherence} onChange={(v) => setF({ ...f, adherence: v })} hint="Schedule adherence: started and finished within this many minutes of the plan." />
              </div>
            ) : null}
          </fieldset>
        ) : null}
        {m2 ? (
          <fieldset className="mfg-fieldset" data-testid="plant-mrp">
            <legend>Material planning (MRP)</legend>
            <Field label="Working days" hint="Manufacturing lead times count these days (holidays of the plant calendar are skipped).">
              {(id) => (
                <div className="row wrap" id={id} role="group" aria-label="Working days">
                  {WEEKDAYS.map((d) => (
                    <label key={d} className="checkbox">
                      <input
                        type="checkbox"
                        checked={f.workdays.includes(d)}
                        data-testid={`plant-workday-${d}`}
                        onChange={(e) => setF({ ...f, workdays: e.target.checked ? [...f.workdays, d] : f.workdays.filter((x) => x !== d) })}
                      />
                      {WEEKDAY_LABEL[d]}
                    </label>
                  ))}
                </div>
              )}
            </Field>
            {f.workdays.length === 0 ? <span className="field-error">Choose at least one working day.</span> : null}
            <div className="form-grid">
              <TextField
                label="Routing minutes per working day"
                type="number"
                value={f.dayMinutes}
                onChange={(v) => setF({ ...f, dayMinutes: v })}
                hint="60 to 1440. 480 = one 8-hour shift; turns routing times into lead-time days."
                testId="plant-mrp-day-minutes"
              />
              <TextField
                label="Release window (days)"
                type="number"
                value={f.releaseWindow}
                onChange={(v) => setF({ ...f, releaseWindow: v })}
                hint="Planned orders starting within this many days are marked 'Release now'."
                testId="plant-mrp-release-window"
              />
              <TextField
                label="Defer tolerance (days)"
                type="number"
                value={f.deferTol}
                onChange={(v) => setF({ ...f, deferTol: v })}
                hint="Suggest pushing out a delivery only when it is this much earlier than needed."
                testId="plant-mrp-defer"
              />
              <TextField
                label="Over-receipt allowed (%)"
                type="number"
                value={f.overReceipt}
                onChange={(v) => setF({ ...f, overReceipt: v })}
                hint="How much more than ordered the stores may receive on one delivery."
                testId="plant-over-receipt"
              />
            </div>
          </fieldset>
        ) : null}
        <div className="row">
          <PermissionGate perm="master_edit" mode="disable">
            <button type="submit" className="btn primary" disabled={busy || invalid} data-testid="plant-save">
              {busy ? <span className="spinner" aria-hidden /> : <Icon name="save" />} Save settings
            </button>
          </PermissionGate>
        </div>
      </div>
    </form>
  );
}
