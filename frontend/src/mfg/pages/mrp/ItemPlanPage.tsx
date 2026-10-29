/**
 * Item plan (M2 14.2 `ItemPlanPage`, #155): projected stock chart, bucket table, requirements with their pegs and
 * supplies with what they serve; "Peg up / down" opens the pegging tree from any row.
 */
import { useState } from "react";
import { Link, useParams } from "react-router";
import { Icon } from "../../../components/Icon";
import { getRunItemPlan } from "../../api/clientM2";
import { MfgError, NotFoundPanel, Spinner } from "../../components/Feedback";
import { ProjectedStockChart } from "../../components/ProjectedStockChart";
import { MakeBuyBadge } from "../../components/StatusChip";
import { LateBadge } from "../../components/StatusM2";
import { fmtDate } from "../../lib/format";
import { fmtNum, segmentText } from "../../lib/formatM2";
import { exceptionLabel, leadTimeText, REQUIREMENT_KIND, SUPPLY_KIND } from "../../lib/mrpText";
import { mfgPaths } from "../../lib/paths";
import { isNotFound, useLoad } from "../../lib/useMfg";
import { useRun } from "./RunShell";

type BucketSize = "day" | "week" | "month";

export function ItemPlanPage() {
  const { run } = useRun();
  const { itemId = "" } = useParams();
  const [bucket, setBucket] = useState<BucketSize>("week");
  const plan = useLoad((signal) => getRunItemPlan(run.id, itemId, { bucket }, signal), [run.id, itemId, bucket]);
  const p = plan.data;
  if (plan.error && isNotFound(plan.error)) return <NotFoundPanel what="Item in this plan" back={<Link className="btn" to={mfgPaths.runItems(run.id)}>Back to the material plan</Link>} />;
  if (plan.error && !p) return <MfgError error={plan.error} onRetry={plan.reload} />;
  if (!p) return <Spinner label="Loading the item plan…" />;
  const r = p.row;
  const uom = r.uom;
  const lotBits = [
    p.lot.rule === "lot_for_lot" ? "order what is needed" : p.lot.rule === "fixed" ? `fixed lots of ${fmtNum(p.lot.fixed_qty)}` : `combine ${p.lot.period_days} days`,
    p.lot.moq ? `min. ${fmtNum(p.lot.moq)}` : "",
    p.lot.multiple ? `multiple ${fmtNum(p.lot.multiple)}` : "",
    p.lot.pack > 1 ? `pack ${fmtNum(p.lot.pack)}` : "",
  ].filter(Boolean);

  return (
    <div className="col gap-lg" data-testid="item-plan" data-item={r.item.part_number}>
      <nav aria-label="Breadcrumb" className="small muted mfg-breadcrumb">
        <Link to={mfgPaths.runItems(run.id)}>Material plan</Link> <Icon name="chevron-right" size={12} /> <span className="mono">{r.item.part_number}</span>
      </nav>
      <div className="ws-header">
        <div className="ws-title">
          <h2 className="mono" style={{ margin: 0 }}>
            {r.item.part_number}
          </h2>
          <MakeBuyBadge value={r.make_buy} />
          <span className="muted">{r.item.description}</span>
        </div>
        <div className="row" style={{ gap: 4 }}>
          <Link className="btn sm" to={mfgPaths.itemStock(r.item.id)}>
            Stock
          </Link>
          <Link className="btn sm" to={mfgPaths.item(r.item.id)}>
            Item
          </Link>
        </div>
      </div>
      <div className="card card-body">
        <dl className="mfg-dl">
          <dt>Lead time</dt>
          <dd>{leadTimeText(r.lead_time)}</dd>
          <dt>Ordering</dt>
          <dd>{lotBits.join(" · ")}</dd>
          {p.supplier ? (
            <>
              <dt>Supplier</dt>
              <dd>
                <Link to={mfgPaths.supplier(p.supplier.id)}>
                  {p.supplier.code} · {p.supplier.name}
                </Link>
              </dd>
            </>
          ) : null}
          <dt>Totals</dt>
          <dd>
            on hand {fmtNum(r.on_hand)} · needed {fmtNum(r.gross_qty)} · open supply {fmtNum(r.existing_supply_qty)} · planned {fmtNum(r.planned_qty)} {uom}
            {r.short_qty > 0 ? (
              <span className="badge danger" style={{ marginLeft: 6 }}>
                <Icon name="alert" /> short {fmtNum(r.short_qty)} from {fmtDate(r.first_short_date)}
              </span>
            ) : null}
          </dd>
        </dl>
      </div>

      <section className="card card-body col">
        <div className="row between">
          <h3 style={{ margin: 0 }}>Projected stock</h3>
          <div className="row" role="group" aria-label="Period">
            {(["day", "week", "month"] as BucketSize[]).map((b) => (
              <button key={b} type="button" className={`btn sm${b === bucket ? " primary" : ""}`} aria-pressed={b === bucket} onClick={() => setBucket(b)}>
                {b === "day" ? "Days" : b === "week" ? "Weeks" : "Months"}
              </button>
            ))}
          </div>
        </div>
        <ProjectedStockChart timeline={p.timeline} buckets={p.buckets} asOf={p.run.as_of} uom={uom} />
      </section>

      <div className="table-wrap card" style={{ maxHeight: 360, overflow: "auto" }}>
        <table className="table" data-testid="item-plan-buckets">
          <thead>
            <tr>
              <th>Period</th>
              <th className="right">Needed</th>
              <th className="right">Existing supply</th>
              <th className="right">Planned</th>
              <th className="right">End balance (existing)</th>
              <th className="right">End balance (with planned)</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {p.buckets.map((b) => (
              <tr key={b.start} data-testid="item-plan-bucket" data-short={b.short ? "true" : "false"} data-start={b.start}>
                <td>
                  {fmtDate(b.start)}
                  {b.end !== b.start ? ` – ${fmtDate(b.end)}` : ""}
                </td>
                <td className="right">{b.gross ? fmtNum(b.gross) : ""}</td>
                <td className="right">{b.existing_supply ? fmtNum(b.existing_supply) : ""}</td>
                <td className="right">{b.planned ? fmtNum(b.planned) : ""}</td>
                <td className={`right${b.balance_existing_end < 0 ? " mfg-neg" : ""}`}>{fmtNum(b.balance_existing_end)}</td>
                <td className={`right${b.balance_planned_end < 0 ? " mfg-neg" : ""}`}>{fmtNum(b.balance_planned_end)}</td>
                <td>
                  {b.short ? (
                    <span className="badge danger">
                      <Icon name="alert" /> Short
                    </span>
                  ) : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <section className="card" data-testid="item-plan-requirements">
        <div className="card-header">
          <h3>Requirements ({p.requirements.length})</h3>
          <span className="muted small">What needs this part, and what covers it</span>
        </div>
        <div className="table-wrap" style={{ maxHeight: 420, overflow: "auto" }}>
          <table className="table">
            <thead>
              <tr>
                <th>Needed</th>
                <th>For</th>
                <th className="right">Qty</th>
                <th>Covered by</th>
                <th>Covered on</th>
                <th>
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {p.requirements.map((q) => (
                <tr key={q.node} data-testid="plan-requirement" data-late-days={q.late_days}>
                  <td>{fmtDate(q.need_date)}</td>
                  <td>
                    <div className="small muted">{REQUIREMENT_KIND[q.kind] ?? q.kind}</div>
                    {q.source.link ? <Link to={q.source.link}>{q.source.label}</Link> : q.source.label}
                    <div className="faint small">
                      {q.rank_label}
                      {q.segment ? ` · ${segmentText(q.segment)}` : ""}
                    </div>
                  </td>
                  <td className="right">{fmtNum(q.qty)}</td>
                  <td className="small">
                    {q.pegs.map((g, i) => (
                      <div key={i}>
                        {fmtNum(g.qty)} from {g.supply_label} {g.late_days > 0 ? <LateBadge days={g.late_days} /> : null}
                      </div>
                    ))}
                  </td>
                  <td>
                    {fmtDate(q.satisfied_date)} <LateBadge days={q.late_days} />
                  </td>
                  <td>
                    <Link className="btn sm ghost" to={mfgPaths.runPegging(run.id, { item: r.item.id, node: q.node, kind: "requirement", direction: "up" })} title="Which demand does this serve?">
                      Peg up
                    </Link>
                    <Link className="btn sm ghost" to={mfgPaths.runPegging(run.id, { item: r.item.id, node: q.node, kind: "requirement", direction: "down" })} title="What covers this, down the BOM?">
                      Peg down
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="card" data-testid="item-plan-supplies">
        <div className="card-header">
          <h3>Supplies ({p.supplies.length})</h3>
          <span className="muted small">Stock, deliveries, work orders and planned orders</span>
        </div>
        <div className="table-wrap" style={{ maxHeight: 420, overflow: "auto" }}>
          <table className="table">
            <thead>
              <tr>
                <th>Supply</th>
                <th>Available</th>
                <th>Projected</th>
                <th className="right">Qty</th>
                <th className="right">Used</th>
                <th>Messages</th>
                <th>
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {p.supplies.map((s) => (
                <tr key={s.node} data-testid="plan-supply" data-kind={s.kind}>
                  <td>
                    <div className="small muted">{SUPPLY_KIND[s.kind] ?? s.kind}</div>
                    {s.ref.link ? <Link to={s.ref.link}>{s.label}</Link> : s.label}
                    {s.expires_on ? <div className="faint small">expires {fmtDate(s.expires_on)}</div> : null}
                  </td>
                  <td>{fmtDate(s.avail_date)}</td>
                  <td>{fmtDate(s.projected_date)}</td>
                  <td className="right">{fmtNum(s.qty)}</td>
                  <td className="right">{s.pegged_qty < s.qty - 1e-6 ? <span title="Part of this supply is not needed">{fmtNum(s.pegged_qty)}</span> : fmtNum(s.pegged_qty)}</td>
                  <td className="small">
                    {s.exception_codes.map((c) => (
                      <Link key={c} to={mfgPaths.runExceptions(run.id, { code: c })} className="badge warn" style={{ marginRight: 4 }}>
                        {exceptionLabel(c)}
                      </Link>
                    ))}
                  </td>
                  <td>
                    <Link className="btn sm ghost" to={mfgPaths.runPegging(run.id, { item: r.item.id, node: s.node, kind: "supply", direction: "up" })}>
                      Peg up
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
