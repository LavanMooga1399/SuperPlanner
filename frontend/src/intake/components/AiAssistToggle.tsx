import { Icon } from "../../components/Icon";
import type { Capabilities } from "../api/types";
import { t } from "../../lib/i18n";

/**
 * Per-request opt-in for AI assist (PHASE2.md 3.3, 2.12). Shown only when the server offers it; off by
 * default on every visit; the privacy notice is shown inline as soon as it is switched on.
 */
export function AiAssistToggle({
  capabilities,
  on,
  onChange,
  disabled,
}: {
  capabilities: Capabilities | null;
  on: boolean;
  onChange(v: boolean): void;
  disabled?: boolean;
}) {
  if (!capabilities?.ai_available) {
    return (
      <p className="small muted row" data-testid="intake-ai-unavailable" style={{ margin: 0 }}>
        <Icon name="info" size={14} /> {t("studio.aiAssistToggle.btn.aiAssistIsNotAvailable")}
      </p>
    );
  }
  return (
    <div className="col" style={{ gap: 6 }}>
      <label className="switch">
        <input
          type="checkbox"
          role="switch"
          checked={on}
          disabled={disabled}
          aria-describedby={on ? "intake-ai-notice" : "intake-ai-help"}
          data-testid="intake-ai-toggle"
          onChange={(e) => onChange(e.target.checked)}
        />
        <span>{t("studio.aiAssistToggle.text.useAiAssistForThis")}</span>
      </label>
      {on ? (
        <div className="banner warn ai-notice" id="intake-ai-notice" data-testid="intake-ai-notice">
          <Icon name="lock" />
          <div className="banner-body">
            <strong>{t("studio.aiAssistToggle.head.beforeYouSend")}</strong>
            <div>{capabilities.privacy_notice}</div>
          </div>
        </div>
      ) : (
        <span id="intake-ai-help" className="small muted">
          {t("studio.aiAssistToggle.text.offYourTextIsRead")}
        </span>
      )}
    </div>
  );
}
