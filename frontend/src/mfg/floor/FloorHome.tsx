/** `/mfg/floor`: line picker (remembered on this device). With a remembered line it opens that line's queue. */
import { useEffect } from "react";
import { Navigate, useNavigate, useSearchParams } from "react-router";
import { Icon } from "../../components/Icon";
import { listGroups, listLines } from "../api/client";
import { MfgError, Spinner } from "../components/Feedback";
import { mfgPaths } from "../lib/paths";
import { useLoad } from "../lib/useMfg";
import { useFloor } from "./FloorLayout";

export function FloorHome() {
  const { lineId, setLineId } = useFloor();
  const [params] = useSearchParams();
  const pick = params.get("pick") === "1";
  if (lineId && !pick) return <Navigate to={mfgPaths.floorLine(lineId)} replace />;
  return <LinePicker current={lineId} onPick={setLineId} />;
}

function LinePicker({ current, onPick }: { current: string | null; onPick(id: string): void }) {
  const navigate = useNavigate();
  const lines = useLoad((signal) => listLines({ active: true }, signal), []);
  const groups = useLoad((signal) => listGroups({}, signal), []);
  useEffect(() => {
    document.title = "Choose a line - Floor";
  }, []);
  const byGroup = new Map<string, { code: string; name: string; lines: { id: string; code: string; name: string }[] }>();
  for (const g of groups.data?.items ?? []) byGroup.set(g.id, { code: g.code, name: g.name, lines: [] });
  for (const l of lines.data?.items ?? []) {
    const g = byGroup.get(l.group_id) ?? { code: "", name: "Other", lines: [] };
    g.lines.push({ id: l.id, code: l.code, name: l.name });
    byGroup.set(l.group_id, g);
  }
  return (
    <section className="floor-card">
      <h1>Which line is this tablet at?</h1>
      <p className="muted" style={{ margin: 0 }}>
        The choice is remembered on this device. You can also scan the line's barcode (LIN:code).
      </p>
      <MfgError error={lines.error ?? groups.error} onRetry={lines.reload} />
      {lines.loading && !lines.data ? <Spinner /> : null}
      {[...byGroup.values()]
        .filter((g) => g.lines.length)
        .map((g) => (
          <div key={g.code + g.name} className="col" style={{ gap: 6 }}>
            <h2 style={{ fontSize: 18 }}>
              {g.code} · {g.name}
            </h2>
            <div className="floor-grid">
              {g.lines.map((l) => (
                <button
                  key={l.id}
                  type="button"
                  className={`floor-tile${current === l.id ? " active" : ""}`}
                  onClick={() => {
                    onPick(l.id);
                    navigate(mfgPaths.floorLine(l.id));
                  }}
                  data-testid="floor-line-pick"
                  data-line-id={l.id}
                  data-code={l.code}
                  aria-pressed={current === l.id}
                >
                  <strong>{l.code}</strong>
                  <span className="muted">{l.name}</span>
                  {current === l.id ? (
                    <span className="badge ok">
                      <Icon name="check" /> This tablet
                    </span>
                  ) : null}
                </button>
              ))}
            </div>
          </div>
        ))}
    </section>
  );
}
