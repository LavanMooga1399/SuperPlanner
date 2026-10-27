/** `/mfg/plant/settings` (M 11.1): name, time zone offset, planning horizon, currency. `If-Match: "0"` creates the row. */
import { useEffect, useState } from "react";
import { Icon } from "../../components/Icon";
import { getPlant, updatePlant } from "../api/client";
import { WEEKDAYS, type PlantInput, type PlantRecord, type Weekday } from "../api/types";
import type { PlantM2Fields } from "../api/typesM2";
import { WEEKDAY_LABEL } from "../lib/format";
import { ConflictBanner, MfgError, SaveState, Spinner } from "../components/Feedback";
import { Field, numOr, TextField } from "../components/Field";
import { PermissionGate } from "../components/PermissionGate";
import { isConflict, usePlant } from "../lib/useMfg";

const OFFSET = /^[+-](0\d|1[0-4]):[0-5]\d$/;

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
  });
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [conflict, setConflict] = useState(false);

  const reset = (p: PlantRecord) => {
    setBase(p);
    const x = p as PlantRecord & PlantM2Fields;
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
  const body: PlantInput & PlantM2Fields = {
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
  const invalid = !OFFSET.test(f.utc_offset.trim()) || !(horizon >= 7 && horizon <= 730) || m2Invalid;

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
            value={f.utc_offset}
            onChange={(v) => setF({ ...f, utc_offset: v })}
            placeholder="+05:30"
            hint={OFFSET.test(f.utc_offset.trim()) ? "Shift times, holidays and dates use this offset (no daylight saving)." : "Use the form +05:30 or -04:00."}
            testId="plant-offset"
          />
          <TextField label="Planning horizon (days)" type="number" value={f.horizon} onChange={(v) => setF({ ...f, horizon: v })} hint="7 to 730; used by the data-health check." testId="plant-horizon" />
          <TextField label="Currency" value={f.currency} onChange={(v) => setF({ ...f, currency: v })} maxLength={8} hint="Shown with costs, e.g. INR" />
        </div>
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
