/**
 * Organisation dashboard (M6 3.1, D3): the same tiles per plant the user can view, plus totals (sums or weighted
 * averages; the weights are stated as the server sends them). Table: one row per tile, one column per plant.
 */
import { useState } from "react";
import { Link } from "react-router";
import { Icon } from "../../../components/Icon";
import { getOrgDashboard } from "../../api/clientM6";
import type { DashboardPeriod, DashboardTile } from "../../api/typesM6";
import { MfgError, Spinner } from "../../components/Feedback";
import { useLoad } from "../../lib/useMfg";
import { DigestSettings } from "./DashboardPage";
import { fmtTileValue, PeriodSelect, TileCard, TileStatusBadge, TILE_NAMES, tileName } from "./dashboardBits";

function Cell({ t }: { t: DashboardTile | undefined }) {
  if (!t) return <td className="muted">n/a</td>;
  return (
    <td>
      <div className="col" style={{ gap: 2 }}>
        <span className="mfg-num">{fmtTileValue(t.value, t.unit)}</span>
        <TileStatusBadge status={t.status} />
      </div>
    </td>
  );
}

export function OrgDashboardTab({ orgId }: { orgId: string }) {
  const [period, setPeriod] = useState<DashboardPeriod>("13w");
  const dash = useLoad((signal) => getOrgDashboard(orgId, period, signal), [orgId, period]);
  const d = dash.data;
  const keys = d
    ? Array.from(new Set([...Object.keys(TILE_NAMES), ...Object.keys(d.totals), ...d.plants.flatMap((p) => Object.keys(p.tiles))])).filter(
        (k) => k in d.totals || d.plants.some((p) => k in p.tiles),
      )
    : [];
  return (
    <div className="col gap-lg dash-print" data-testid="org-dashboard">
      <div className="row wrap no-print" style={{ justifyContent: "space-between", gap: 8 }}>
        <span className="muted small">{d ? `As of ${new Date(d.as_of).toLocaleString()}. Only plants you can view are included.` : ""}</span>
        <div className="row" style={{ gap: 8 }}>
          <PeriodSelect value={period} onChange={setPeriod} />
          <button type="button" className="btn ghost" onClick={() => window.print()} data-testid="org-dash-print">
            <Icon name="file" /> Print
          </button>
        </div>
      </div>
      {dash.error && !d ? <MfgError error={dash.error} onRetry={dash.reload} /> : null}
      {dash.loading && !d ? <Spinner /> : null}
      {d ? (
        <>
          <div className="dash-grid" data-testid="org-dash-totals">
            {keys
              .filter((k) => d.totals[k])
              .map((k) => (
                <TileCard key={k} name={k} tile={d.totals[k]} extra={d.totals[k].weights ? `All plants: ${d.totals[k].weights}` : "All plants"} />
              ))}
          </div>
          <div className="table-wrap">
            <table className="table" data-testid="org-dash-table">
              <caption className="sr-only">Tiles per plant</caption>
              <thead>
                <tr>
                  <th scope="col">Tile</th>
                  {d.plants.map((p) => (
                    <th key={p.owner_id} scope="col" data-testid="org-dash-plant">
                      {p.plant_code ? `${p.plant_code} ` : ""}
                      {p.plant_name}
                    </th>
                  ))}
                  <th scope="col">All plants</th>
                </tr>
              </thead>
              <tbody>
                {keys.map((k) => (
                  <tr key={k}>
                    <th scope="row">{tileName(k, d.totals[k] ?? d.plants.find((p) => p.tiles[k])?.tiles[k])}</th>
                    {d.plants.map((p) => (
                      <Cell key={p.owner_id} t={p.tiles[k]} />
                    ))}
                    <Cell t={d.totals[k]} />
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="muted small no-print" style={{ margin: 0 }}>
            Open a plant's own dashboard from the plant switcher in Manufacturing (<Link to="/mfg/dashboard">Plant dashboard</Link>).
          </p>
        </>
      ) : null}
      <div className="no-print">
        <DigestSettings scope="org" scopeId={orgId} />
      </div>
    </div>
  );
}
