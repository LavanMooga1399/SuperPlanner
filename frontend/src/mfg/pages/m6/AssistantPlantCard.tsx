/**
 * Plant settings, "Planning assistant" (M6 1.1): the plant opt-out (`assistant_enabled`) and whether conversations
 * may switch on what-if runs (`assistant_allow_whatif`). Read from `/assistant/status` (`plant`), saved with
 * `PUT /mfg/plant/assistant` (owner / plant admin). Everyone else sees the current state read-only.
 */
import { useEffect, useState } from "react";
import { Icon } from "../../../components/Icon";
import { getAssistantStatus, putAssistantSettings } from "../../api/clientM6";
import type { AssistantPlantSettings } from "../../api/typesM6";
import { MfgError } from "../../components/Feedback";
import { useAccess } from "../../lib/permissions";
import { useLoad } from "../../lib/useMfg";
import { t } from "../../../lib/i18n";

export function AssistantPlantCard() {
  const access = useAccess();
  const mayRead = access.can("assistant_use");
  const admin = access.isOwner || access.can("owner") || Boolean(access.me?.roles?.includes("plant_admin"));
  const status = useLoad((signal) => (mayRead ? getAssistantStatus(signal) : null), [mayRead]);
  const [f, setF] = useState<AssistantPlantSettings | null>(null);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  useEffect(() => {
    if (status.data && !f) setF(status.data.plant);
  }, [status.data, f]);
  if (!mayRead) return null;
  if (status.error && !status.data) return <MfgError error={status.error} onRetry={status.reload} title={t("mfg.assistantPlantCard.attr.assistantSettingsCouldNotBe")} />;
  if (!f || !status.data) return null;
  const server = status.data;
  const save = async () => {
    setBusy(true);
    setErr(null);
    setSaved(false);
    try {
      setF(await putAssistantSettings(f));
      setSaved(true);
      status.reload();
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };
  const serverOff = !server.available && server.code && server.code !== "AI_PLANT_OPTED_OUT";
  return (
    <section className="card" style={{ maxWidth: 720 }} data-testid="plant-assistant">
      <div className="card-header">
        <h2>{t("mfg.assistantPlantCard.head.planningAssistant")}</h2>
        <span className="badge info" data-testid="plant-assistant-state">
          <Icon name={f.assistant_enabled ? "check" : "ban"} /> {f.assistant_enabled ? t("mfg.assistantPlantCard.str.onForThisPlant") : t("mfg.assistantPlantCard.str.offForThisPlant")}
        </span>
      </div>
      <div className="card-body col">
        <p className="muted small" style={{ margin: 0 }}>
          {t("mfg.assistantPlantCard.text.whenOnQuestionsAndThe")}
        </p>
        {serverOff ? (
          <p className="small" style={{ margin: 0 }}>
            <Icon name="info" size={12} />{" "}{t("mfg.assistantPlantCard.text.onThisServerTheAssistant")}{server.code}{t("mfg.assistantPlantCard.text.whateverThePlantSetting")}
          </p>
        ) : null}
        <label className="checkbox">
          <input type="checkbox" checked={f.assistant_enabled} disabled={!admin} onChange={(e) => setF({ ...f, assistant_enabled: e.target.checked })} data-testid="plant-assistant-enabled" />
          {t("mfg.assistantPlantCard.text.offerTheAiPlanningAssistant")}
        </label>
        <label className="checkbox">
          <input
            type="checkbox"
            checked={f.assistant_allow_whatif}
            disabled={!admin || !f.assistant_enabled}
            onChange={(e) => setF({ ...f, assistant_allow_whatif: e.target.checked })}
            data-testid="plant-assistant-whatif"
          />
          {t("mfg.assistantPlantCard.text.letUsersAllowItTo")}
        </label>
        {admin ? (
          <div className="row" style={{ gap: 8 }}>
            <button type="button" className="btn primary" disabled={busy} onClick={() => void save()} data-testid="plant-assistant-save">
              {busy ? <span className="spinner" aria-hidden /> : <Icon name="save" />}{" "}{t("mfg.assistantPlantCard.text.saveAssistantSettings")}
            </button>
            {saved ? <span role="status">{t("mfg.assistantPlantCard.text.saved")}</span> : null}
          </div>
        ) : (
          <span className="hint">
            <Icon name="lock" size={12} /> {t("mfg.assistantPlantCard.btn.onlyTheOwnerOrA")}
          </span>
        )}
        <MfgError error={err} title={t("mfg.assistantPlantCard.attr.couldNotSave")} />
      </div>
    </section>
  );
}
