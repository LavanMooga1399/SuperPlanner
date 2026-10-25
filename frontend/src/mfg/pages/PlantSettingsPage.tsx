/** `/mfg/plant/settings` (M 11.1): name, time zone offset, planning horizon, currency. `If-Match: "0"` creates the row. */
import { useEffect, useState } from "react";
import { Icon } from "../../components/Icon";
import { getPlant, updatePlant } from "../api/client";
import type { PlantInput, PlantRecord } from "../api/types";
import { ConflictBanner, MfgError, SaveState, Spinner } from "../components/Feedback";
import { numOr, TextField } from "../components/Field";
import { isConflict, usePlant } from "../lib/useMfg";

const OFFSET = /^[+-](0\d|1[0-4]):[0-5]\d$/;

export function PlantSettingsPage() {
  const plant = usePlant();
  const [base, setBase] = useState<PlantRecord | null>(null);
  const [f, setF] = useState({ name: "", utc_offset: "+00:00", horizon: "90", currency: "" });
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [conflict, setConflict] = useState(false);

  const reset = (p: PlantRecord) => {
    setBase(p);
    setF({ name: p.name, utc_offset: p.utc_offset, horizon: String(p.planning_horizon_days), currency: p.currency });
    setConflict(false);
  };
  useEffect(() => {
    if (plant.data && !base) reset(plant.data);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [plant.data]);

  if (plant.error && !base) return <MfgError error={plant.error} onRetry={plant.reload} />;
  if (!base) return <Spinner />;

  const body: PlantInput = {
    name: f.name.trim() || "Plant",
    utc_offset: f.utc_offset.trim(),
    planning_horizon_days: numOr(f.horizon, 90),
    currency: f.currency.trim(),
    attributes: base.attributes,
  };
  const horizon = Number(f.horizon);
  const invalid = !OFFSET.test(f.utc_offset.trim()) || !(horizon >= 7 && horizon <= 730);

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
        <div className="row">
          <button type="submit" className="btn primary" disabled={busy || invalid} data-testid="plant-save">
            {busy ? <span className="spinner" aria-hidden /> : <Icon name="save" />} Save settings
          </button>
        </div>
      </div>
    </form>
  );
}
