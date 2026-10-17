import { useState } from "react";
import { useNavigate } from "react-router";
import { errorMessage } from "../../api/client";
import { Banner } from "../../components/Banner";
import { Dialog } from "../../components/Dialog";
import { browserUtcOffset } from "../../lib/time";
import { sendToPlanner } from "../api/client";

/** Creates a scheduling plan ("money calendar") for the next 1-12 months (FINANCE.md 16.1). */
export function SendToPlannerDialog({ resultId, planName, onClose }: { resultId: string; planName: string; onClose(): void }) {
  const navigate = useNavigate();
  const [name, setName] = useState(`${planName} - money calendar`.slice(0, 200));
  const [months, setMonths] = useState(12);
  const [review, setReview] = useState(3);
  const [rebalances, setRebalances] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const valid = name.trim().length > 0 && months >= 1 && months <= 12 && review >= 1 && review <= 12;

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await sendToPlanner(resultId, {
        name: name.trim(),
        months,
        utc_offset: browserUtcOffset(),
        review_every_months: review,
        include_rebalances: rebalances,
      });
      navigate(res.url || `/plans/${res.problem_id}/tasks`);
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  };

  return (
    <Dialog
      title="Send to planner"
      onClose={onClose}
      footer={
        <>
          <button className="btn" onClick={onClose} disabled={busy}>Cancel</button>
          <button className="btn primary" onClick={() => void submit()} disabled={!valid || busy} data-testid="send-to-planner-confirm">
            {busy ? <span className="spinner" aria-hidden /> : null} Create money calendar
          </button>
        </>
      }
    >
      <p className="muted" style={{ margin: 0 }}>
        Creates a regular scheduling plan with one action per contribution start, change, stop and review, between the 1st and the 5th
        of each month. You can then schedule and adjust it like any other plan.
      </p>
      <div className="fin-form">
        <div className="field wide">
          <label htmlFor="stp-name">Calendar name</label>
          <input id="stp-name" className="input" value={name} maxLength={200} onChange={(e) => setName(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="stp-months">Months to include</label>
          <input id="stp-months" className="input" type="number" min={1} max={12} value={months} onChange={(e) => setMonths(Math.round(Number(e.target.value)))} />
          <span className="hint">1 to 12</span>
        </div>
        <div className="field">
          <label htmlFor="stp-review">Review every (months)</label>
          <input id="stp-review" className="input" type="number" min={1} max={12} value={review} onChange={(e) => setReview(Math.round(Number(e.target.value)))} />
        </div>
      </div>
      <label className="checkbox">
        <input type="checkbox" checked={rebalances} onChange={(e) => setRebalances(e.target.checked)} />
        Include rebalancing actions
      </label>
      {error ? <Banner tone="danger" role="alert">{error}</Banner> : null}
    </Dialog>
  );
}
