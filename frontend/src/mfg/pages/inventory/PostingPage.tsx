/** `/mfg/inventory/postings/:postingId` (M2 14.2): posting header, its ledger lines, and Reverse (once). */
import { useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router";
import { Banner } from "../../../components/Banner";
import { Dialog } from "../../../components/Dialog";
import { Icon } from "../../../components/Icon";
import { getPosting, reversePosting } from "../../api/clientM2";
import { MfgError, NotFoundPanel, Spinner } from "../../components/Feedback";
import { PermissionGate } from "../../components/PermissionGate";
import { fmtDate, fmtTimestamp } from "../../lib/format";
import { fmtNum, POSTING_LABEL } from "../../lib/formatM2";
import { mfgPaths } from "../../lib/paths";
import { isNotFound, useLoad } from "../../lib/useMfg";
import { docRefLink } from "./TransactionsTab";

export function PostingPage() {
  const { postingId = "" } = useParams();
  const navigate = useNavigate();
  const loc = useLocation();
  const flash = (loc.state as { posted?: boolean; replay?: boolean } | null) ?? null;
  const posting = useLoad((signal) => getPosting(postingId, signal), [postingId]);
  const [reversing, setReversing] = useState(false);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const p = posting.data;

  if (posting.error && isNotFound(posting.error))
    return <NotFoundPanel what="Posting" back={<Link className="btn" to={mfgPaths.transactions()}>Back to the ledger</Link>} />;
  if (posting.error && !p) return <MfgError error={posting.error} onRetry={posting.reload} />;
  if (!p) return <Spinner label="Loading posting…" />;

  const reverse = async () => {
    setBusy(true);
    setError(null);
    try {
      const r = await reversePosting(p.id, note);
      setReversing(false);
      navigate(mfgPaths.posting(r.id), { state: { posted: true } });
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="col gap-lg" data-testid="posting-page" data-posting-number={p.number}>
      {flash?.posted ? (
        <Banner tone="ok" role="status" title={flash.replay ? "Already posted" : "Posted"} testId="posting-done">
          {flash.replay ? "This posting was already saved earlier (the same submit was sent twice); nothing was posted again." : "Stock is updated."}
        </Banner>
      ) : null}
      {p.warnings.map((w) => (
        <Banner key={w.code} tone="warn" title={w.code === "INV_RESERVATION_REDUCED" ? "Reservations reduced" : w.code}>
          {w.message}
        </Banner>
      ))}
      <section className="card">
        <div className="card-header">
          <h2 className="row">
            <span className="mono">{p.number}</span> <span className="muted">{POSTING_LABEL[p.type] ?? p.type}</span>
          </h2>
          <div className="mfg-actions">
            {p.reversed_by ? (
              <span className="badge info" data-testid="posting-reversed">
                <Icon name="refresh" /> Reversed by{" "}
                <Link to={mfgPaths.posting(p.reversed_by.id)} className="mono">
                  {p.reversed_by.number}
                </Link>
              </span>
            ) : null}
            {!p.reversed_by && !p.reversal_of ? (
              <PermissionGate perm="inventory">
                <button type="button" className="btn" onClick={() => setReversing(true)} data-testid="posting-reverse">
                  <Icon name="refresh" /> Reverse
                </button>
              </PermissionGate>
            ) : null}
          </div>
        </div>
        <div className="card-body">
          <dl className="mfg-dl">
            <dt>Date</dt>
            <dd>{fmtDate(p.txn_date)}</dd>
            {p.reason_code ? (
              <>
                <dt>Reason</dt>
                <dd className="mono">{p.reason_code}</dd>
              </>
            ) : null}
            {p.note ? (
              <>
                <dt>Note</dt>
                <dd>{p.note}</dd>
              </>
            ) : null}
            {p.reversal_of ? (
              <>
                <dt>Reverses</dt>
                <dd>
                  <Link to={mfgPaths.posting(p.reversal_of.id)} className="mono">
                    {p.reversal_of.number}
                  </Link>
                </dd>
              </>
            ) : null}
            <dt>Posted by</dt>
            <dd>
              {p.actor.name} · {fmtTimestamp(p.created_at)}
            </dd>
          </dl>
        </div>
      </section>
      <div className="table-wrap card">
        <table className="table" data-testid="posting-lines">
          <thead>
            <tr>
              <th>#</th>
              <th>Part number</th>
              <th>Location</th>
              <th>Lot</th>
              <th className="right">Change</th>
              <th className="right">Balance after</th>
              <th className="right">Unit cost</th>
              <th>Document</th>
            </tr>
          </thead>
          <tbody>
            {p.lines.map((t) => {
              const href = docRefLink(t.ref);
              return (
                <tr key={t.id} data-testid="txn-row" data-item={t.item.part_number} data-qty={t.qty}>
                  <td className="faint">{t.line_no}</td>
                  <td>
                    <Link to={mfgPaths.itemStock(t.item.id)} className="mono">
                      {t.item.part_number}
                    </Link>{" "}
                    <span className="muted small">{t.item.description}</span>
                  </td>
                  <td className="mono">{t.location.code}</td>
                  <td className="mono">{t.lot?.lot_code ?? ""}</td>
                  <td className={`right ${t.qty < 0 ? "mfg-neg" : "mfg-pos"}`}>
                    {t.qty > 0 ? "+" : t.qty < 0 ? "−" : ""}
                    {fmtNum(Math.abs(t.qty))} {t.item.uom}
                  </td>
                  <td className="right">{fmtNum(t.balance_after)}</td>
                  <td className="right">{t.unit_cost === null ? "" : fmtNum(t.unit_cost)}</td>
                  <td>{t.ref ? href ? <Link to={href}>{t.ref.label}</Link> : t.ref.label : ""}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="row">
        <Link className="btn" to={mfgPaths.transactions()}>
          <Icon name="list" /> Back to the ledger
        </Link>
      </div>

      {reversing ? (
        <Dialog
          title={`Reverse ${p.number}?`}
          onClose={() => setReversing(false)}
          footer={
            <>
              <button type="button" className="btn" onClick={() => setReversing(false)} data-dialog-close>
                Cancel
              </button>
              <button type="button" className="btn primary" onClick={() => void reverse()} disabled={busy} data-testid="posting-reverse-confirm">
                {busy ? <span className="spinner" aria-hidden /> : <Icon name="refresh" />} Post the reversal
              </button>
            </>
          }
        >
          <div className="col">
            <p style={{ margin: 0 }}>
              Posts the exact opposite movement today. Received, issued, shipped or completed quantities on the linked documents go back as well. A posting can be reversed only once; stock may not go below zero.
            </p>
            <div className="field">
              <label htmlFor="rev-note">Note</label>
              <input id="rev-note" className="input" maxLength={500} value={note} onChange={(e) => setNote(e.target.value)} placeholder="Why is this reversed?" />
            </div>
            <MfgError error={error} title="Could not reverse" />
          </div>
        </Dialog>
      ) : null}
    </div>
  );
}
