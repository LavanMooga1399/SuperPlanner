/**
 * `/m` home (M6 2): my plants with lines running / paused / down, late demand lines, open replanning warnings and
 * approvals waiting. The last good result is kept in IndexedDB; offline, it is shown with a "stale since" banner.
 */
import { Link } from "react-router";
import { isNetworkError } from "../../api/client";
import { Icon } from "../../components/Icon";
import type { WorkspaceInfo } from "../api/typesM2";
import { MfgError, Spinner } from "../components/Feedback";
import { useAccess } from "../lib/permissions";
import { usePolling } from "../lib/usePolling";
import { useLoad } from "../lib/useMfg";
import { currentWorkspace, switchWorkspace } from "../lib/workspace";
import { countStates, plantGlance, type PlantGlance } from "./glance";
import { useOnline } from "./MobileLayout";
import { loadSnapshot, saveSnapshot } from "./snapshot";

interface HomeRow {
  plant: { owner_id: string; plant_name: string; plant_code?: string | null };
  g: PlantGlance;
}

function Stat({ to, value, label, icon, testId }: { to?: string; value: number | null; label: string; icon: "alert" | "check" | "clock" | "flag" | "stop"; testId: string }) {
  const body = (
    <>
      <strong>{value === null ? "–" : value}</strong>
      <span>
        <Icon name={icon} size={12} /> {label}
      </span>
    </>
  );
  return to ? (
    <Link to={to} className="m-stat" data-testid={testId}>
      {body}
    </Link>
  ) : (
    <div className="m-stat" data-testid={testId}>
      {body}
    </div>
  );
}

function PlantCard({ row, current, userId }: { row: HomeRow; current: boolean; userId: string | undefined }) {
  const c = countStates(row.g.lines);
  return (
    <section className="m-card" data-testid="m-plant-card" aria-label={row.plant.plant_name}>
      <div className="row" style={{ justifyContent: "space-between", gap: 8 }}>
        <h2>
          {row.plant.plant_code ? `${row.plant.plant_code} ` : ""}
          {row.plant.plant_name}
        </h2>
        {current ? (
          <span className="chip">This plant</span>
        ) : (
          <button type="button" className="btn sm" onClick={() => switchWorkspace(row.plant.owner_id, userId, "/m")}>
            Open
          </button>
        )}
      </div>
      <div className="m-stats">
        <Stat to={current ? "/m/lines" : undefined} value={c ? c.down : null} label="lines down" icon="stop" testId="m-stat-down" />
        <Stat to={current ? "/m/lines" : undefined} value={c ? c.running : null} label={c ? `running, ${c.paused} paused` : "running"} icon="check" testId="m-stat-running" />
        <Stat value={row.g.late_demand} label="late demand lines" icon="clock" testId="m-stat-late" />
        <Stat to={current ? "/m/alerts" : undefined} value={row.g.open_triggers} label="open warnings" icon="alert" testId="m-stat-triggers" />
        <Stat to={current ? "/m/approvals" : undefined} value={row.g.approvals} label="approvals waiting" icon="flag" testId="m-stat-approvals" />
      </div>
    </section>
  );
}

export function MobileHome() {
  const access = useAccess();
  const online = useOnline();
  const uid = access.me?.user_id ?? "me";
  const ws: WorkspaceInfo[] = access.workspaces;
  const currentId = currentWorkspace() ?? access.me?.workspace_owner_id ?? null;
  const key = `home:${uid}`;
  const home = useLoad<{ rows: HomeRow[]; staleSince: string | null }>(
    (signal) => {
      if (access.loading) return null;
      return (async () => {
        const plants: HomeRow["plant"][] = ws.length
          ? [...ws].sort((a, b) => (a.owner_id === currentId ? -1 : b.owner_id === currentId ? 1 : 0))
          : [{ owner_id: currentId ?? "", plant_name: access.me?.workspace_name || "My plant" }];
        try {
          const rows = await Promise.all(plants.map(async (p) => ({ plant: p, g: await plantGlance(ws.length ? p.owner_id : null, signal) })));
          void saveSnapshot(key, rows);
          return { rows, staleSince: null };
        } catch (e) {
          if (isNetworkError(e)) {
            const s = await loadSnapshot<HomeRow[]>(key);
            if (s) return { rows: s.data, staleSince: s.at };
          }
          throw e;
        }
      })();
    },
    [access.loading, ws.map((w) => w.owner_id).join(","), online],
  );
  usePolling(home.reload, online, 60000);
  const d = home.data;
  return (
    <div className="col" style={{ gap: 12 }} data-testid="m-home">
      <h1>My plants</h1>
      {d?.staleSince ? (
        <div className="m-banner warn" role="status" data-testid="m-stale">
          <Icon name="clock" size={16} /> Offline view: these figures are from {new Date(d.staleSince).toLocaleString()} (stale since then).
        </div>
      ) : null}
      {home.error && !d ? <MfgError error={home.error} onRetry={home.reload} /> : null}
      {home.loading && !d ? <Spinner /> : null}
      {d?.rows.map((r) => (
        <PlantCard key={r.plant.owner_id || "own"} row={r} current={!ws.length || r.plant.owner_id === currentId} userId={access.me?.user_id} />
      ))}
      <div className="m-actions">
        <Link to="/m/scan" className="btn m-big">
          <Icon name="zoom-in" /> Scan
        </Link>
        <Link to="/mfg/dashboard" className="btn ghost m-big">
          <Icon name="graph" /> Dashboard
        </Link>
      </div>
    </div>
  );
}
