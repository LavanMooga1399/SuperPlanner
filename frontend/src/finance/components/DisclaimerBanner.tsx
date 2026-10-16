import { useState } from "react";
import { Dialog } from "../../components/Dialog";
import { Icon } from "../../components/Icon";
import { DISCLAIMER, DISCLAIMER_VERSION } from "../api/types";

export const DISCLAIMER_ACK_KEY = "sp.fin.disclaimerAck";

/** Exact F.21 disclaimer. Not dismissible; `compact` outside the results page. */
export function DisclaimerBanner({ compact = false, text = DISCLAIMER }: { compact?: boolean; text?: string }) {
  return (
    <div
      className={`banner fin-disclaimer${compact ? " compact" : " accent"}`}
      data-testid="disclaimer-banner"
      role="note"
      aria-label="Disclaimer"
    >
      <Icon name="info" />
      <div className="banner-body">{text}</div>
    </div>
  );
}

function readAck(): boolean {
  try {
    return window.localStorage.getItem(DISCLAIMER_ACK_KEY) !== null;
  } catch {
    return false;
  }
}

/** First visit to any /finance/** route: "I understand" dialog (F.21 rule 2). Does not gate the API. */
export function DisclaimerDialog() {
  const [acked, setAcked] = useState(readAck);
  if (acked) return null;
  const accept = () => {
    try {
      window.localStorage.setItem(DISCLAIMER_ACK_KEY, JSON.stringify({ version: DISCLAIMER_VERSION, at: new Date().toISOString() }));
    } catch {
      /* storage unavailable: show again next time */
    }
    setAcked(true);
  };
  return (
    <Dialog
      title="Before you start"
      onClose={accept}
      footer={
        <button className="btn primary" onClick={accept} data-testid="disclaimer-accept" data-autofocus>
          I understand
        </button>
      }
    >
      <p style={{ margin: 0 }}>{DISCLAIMER}</p>
      <p className="small muted" style={{ margin: 0 }}>
        Your plan data stays on this computer's SuperPlanner server. No market data is fetched and no products are recommended.
      </p>
    </Dialog>
  );
}
