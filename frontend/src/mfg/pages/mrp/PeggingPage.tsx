/**
 * `/mfg/mrp/runs/:runId/pegging?item=&node=&kind=&direction=` (M2 14.2 `PeggingPage`, #160): who needs this
 * supply (up, to the demand) or what covers this requirement (down the BOM), as a collapsible tree.
 */
import { Link, useNavigate, useSearchParams } from "react-router";
import { Banner } from "../../../components/Banner";
import { Icon } from "../../../components/Icon";
import { getPegging } from "../../api/clientM2";
import { MfgError, Spinner } from "../../components/Feedback";
import { PeggingTree } from "../../components/PeggingTree";
import { mfgPaths } from "../../lib/paths";
import { useLoad } from "../../lib/useMfg";
import { useRun } from "./RunShell";

export function PeggingPage() {
  const { run } = useRun();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const item = params.get("item") ?? "";
  const node = Number(params.get("node") ?? "");
  const kind = params.get("kind") === "requirement" ? "requirement" : "supply";
  const direction = params.get("direction") === "down" ? "down" : "up";
  const valid = Boolean(item) && Number.isInteger(node);
  const peg = useLoad((signal) => (valid ? getPegging(run.id, { item_id: item, node, kind, direction, max_depth: 20 }, signal) : null), [run.id, item, node, kind, direction]);
  const go = (d: "up" | "down") => navigate(mfgPaths.runPegging(run.id, { item, node, kind, direction: d }), { replace: true });
  if (!valid) return <Banner tone="info" title="Choose a requirement or supply">Open an item plan and use "Peg up" or "Peg down" on a row.</Banner>;
  const root = peg.data?.rows[0];
  return (
    <div className="col gap-lg" data-testid="pegging-page" data-direction={direction}>
      <div className="row between wrap">
        <div className="row wrap">
          <Link to={mfgPaths.runItem(run.id, item)} className="small">
            <Icon name="chevron-right" size={12} style={{ transform: "rotate(180deg)" }} /> Item plan
          </Link>
          <h3 style={{ margin: 0 }}>
            {direction === "up" ? "Who needs" : "What covers"} {root ? <span className="mono">{root.item.part_number}</span> : null} {root?.label}
          </h3>
        </div>
        <div className="row" role="group" aria-label="Direction">
          <button type="button" className={`btn sm${direction === "up" ? " primary" : ""}`} aria-pressed={direction === "up"} onClick={() => go("up")} data-testid="peg-up">
            Up to demand
          </button>
          <button type="button" className={`btn sm${direction === "down" ? " primary" : ""}`} aria-pressed={direction === "down"} onClick={() => go("down")} data-testid="peg-down">
            Down to supply
          </button>
        </div>
      </div>
      <MfgError error={peg.error} onRetry={peg.reload} />
      {peg.loading && !peg.data ? <Spinner label="Following the pegs…" /> : null}
      {peg.data?.truncated ? <Banner tone="warn" title="Only the first 2,000 rows are shown">Peg from a lower row to see the rest.</Banner> : null}
      {peg.data ? (
        <PeggingTree
          rows={peg.data.rows}
          onPeg={(r) => navigate(mfgPaths.runPegging(run.id, { item: r.item.id, node: r.node, kind: r.kind === "demand" || r.kind.endsWith("component") || r.kind === "safety_stock" || r.kind === "extra_demand" ? "requirement" : "supply", direction }))}
        />
      ) : null}
    </div>
  );
}
