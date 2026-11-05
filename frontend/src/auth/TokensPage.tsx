/**
 * API tokens (M5 3.3). `/account/tokens` (personal, act as you in one plant) and `/mfg/settings/tokens` (plant tokens,
 * plant admins: for the ERP or middleware). Guided presets instead of a permission list first; the full list is
 * behind "Choose permissions". The token is shown once; only its first characters are kept for display.
 */
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router";
import { Banner } from "../components/Banner";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { Icon } from "../components/Icon";
import { listWorkspaces } from "../mfg/api/clientM2";
import { createToken, listTokens, revokeToken } from "../mfg/api/clientM5";
import type { ApiToken, TokenCreated, TokenScope } from "../mfg/api/typesM5";
import { MfgError } from "../mfg/components/Feedback";
import { ALL_PERMISSIONS } from "../mfg/lib/permissions";
import { useLoad } from "../mfg/lib/useMfg";
import { currentWorkspace } from "../mfg/lib/workspace";
import "./auth.css";

const PRESETS: { key: string; label: string; help: string; scopes: TokenScope[] }[] = [
  { key: "read", label: "Read only", help: "Reports and dashboards: read everything, change nothing.", scopes: ["view", "floor_view", "trace_view"] },
  { key: "erp", label: "ERP / middleware", help: "Send master data and orders in, read events out (integration).", scopes: ["view", "integration.read", "integration.write"] },
  { key: "events", label: "Read events only", help: "A consumer that pulls the event feed.", scopes: ["integration.read"] },
];

const SCOPE_LABEL: Partial<Record<TokenScope, string>> = {
  view: "Read",
  "integration.read": "Read integration events",
  "integration.write": "Send integration batches",
  master_edit: "Edit master data",
  inventory: "Stock postings",
  wo_edit: "Work orders",
  mrp_run: "Run MRP",
  schedule_run: "Run schedules",
  floor_report: "Report floor work",
};

const fmt = (iso: string | null | undefined) => (iso ? new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }) : "never");

export function TokenManager({ kind }: { kind: "personal" | "plant" }) {
  const tokens = useLoad((signal) => listTokens({ kind }, signal), [kind]);
  const ws = useLoad((signal) => (kind === "personal" ? listWorkspaces(signal).catch(() => null) : null), [kind]);
  const [name, setName] = useState("");
  const [preset, setPreset] = useState("read");
  const [custom, setCustom] = useState(false);
  const [scopes, setScopes] = useState<Set<TokenScope>>(new Set(PRESETS[0].scopes));
  const [days, setDays] = useState(90);
  const [workspace, setWorkspace] = useState<string>(() => currentWorkspace() ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [created, setCreated] = useState<TokenCreated | null>(null);
  const [copied, setCopied] = useState(false);
  const [revoking, setRevoking] = useState<ApiToken | null>(null);
  const allScopes = useMemo<TokenScope[]>(() => [...ALL_PERMISSIONS.filter((p) => p !== "owner"), "integration.read", "integration.write"], []);
  useEffect(() => {
    if (!custom) setScopes(new Set(PRESETS.find((p) => p.key === preset)?.scopes ?? []));
  }, [preset, custom]);
  const items = (tokens.data?.items ?? []).slice().sort((a, b) => Number(Boolean(a.revoked_at)) - Number(Boolean(b.revoked_at)));
  const workspaces = ws.data?.items ?? [];

  const create = async () => {
    setBusy(true);
    setError(null);
    try {
      const t = await createToken({ kind, name: name.trim(), scopes: [...scopes], expires_days: days, ...(kind === "personal" ? { workspace_owner_id: workspace || null } : {}) });
      setCreated(t);
      setCopied(false);
      setName("");
      tokens.reload();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="col gap-lg" data-testid={`tokens-${kind}`}>
      {created ? (
        <Banner tone="ok" title={`Token "${created.name}" created`} testId="token-created">
          <div className="col" style={{ gap: 8 }}>
            <span>Copy it now. It is not shown again; if it is lost, revoke it and make a new one.</span>
            <code className="totp-secret" data-testid="token-value">
              {created.token}
            </code>
            <div className="row">
              <button
                type="button"
                className="btn sm"
                onClick={() => {
                  void navigator.clipboard?.writeText(created.token);
                  setCopied(true);
                }}
              >
                <Icon name="copy" /> {copied ? "Copied" : "Copy"}
              </button>
              <button type="button" className="btn sm ghost" onClick={() => setCreated(null)}>
                I have stored it
              </button>
            </div>
            <span className="faint small">
              Use it as <span className="mono">Authorization: Bearer {created.prefix}…</span>
            </span>
          </div>
        </Banner>
      ) : null}
      <section className="card">
        <div className="card-header">
          <h2>New {kind === "plant" ? "plant" : "personal"} token</h2>
        </div>
        <div className="card-body col">
          <div className="form-grid">
            <div className="field">
              <label htmlFor="tk-name">Name</label>
              <input id="tk-name" className="input" value={name} onChange={(e) => setName(e.target.value)} maxLength={100} placeholder={kind === "plant" ? "e.g. ERP middleware" : "e.g. Power BI report"} data-testid="token-name" />
            </div>
            {kind === "personal" && workspaces.length > 1 ? (
              <div className="field">
                <label htmlFor="tk-ws">Plant</label>
                <select id="tk-ws" className="select" value={workspace} onChange={(e) => setWorkspace(e.target.value)}>
                  {workspaces.map((w) => (
                    <option key={w.owner_id} value={w.is_owner ? "" : w.owner_id}>
                      {w.plant_name || "Plant"}
                      {w.is_owner ? " (mine)" : ""}
                    </option>
                  ))}
                </select>
              </div>
            ) : null}
            <div className="field">
              <label htmlFor="tk-days">Valid for</label>
              <select id="tk-days" className="select" value={days} onChange={(e) => setDays(Number(e.target.value))} data-testid="token-days">
                <option value={30}>30 days</option>
                <option value={90}>90 days (recommended)</option>
                <option value={180}>180 days</option>
                <option value={365}>1 year (maximum)</option>
              </select>
            </div>
          </div>
          <fieldset className="mfg-fieldset">
            <legend>What it may do</legend>
            {!custom ? (
              <div className="col" style={{ gap: 6 }} role="radiogroup" aria-label="Token purpose">
                {PRESETS.map((p) => (
                  <label key={p.key} className="checkbox">
                    <input type="radio" name="tk-preset" checked={preset === p.key} onChange={() => setPreset(p.key)} data-testid={`token-preset-${p.key}`} />
                    <span>
                      <strong>{p.label}</strong> <span className="muted small">{p.help}</span>
                    </span>
                  </label>
                ))}
              </div>
            ) : (
              <div className="token-scopes">
                {allScopes.map((s) => (
                  <label key={s} className="checkbox">
                    <input
                      type="checkbox"
                      checked={scopes.has(s)}
                      onChange={() =>
                        setScopes((x) => {
                          const n = new Set(x);
                          if (n.has(s)) n.delete(s);
                          else n.add(s);
                          return n;
                        })
                      }
                    />
                    <span>{SCOPE_LABEL[s] ?? s.replace(/_/g, " ")}</span>
                  </label>
                ))}
              </div>
            )}
            <button type="button" className="btn ghost sm" style={{ alignSelf: "flex-start" }} aria-expanded={custom} onClick={() => setCustom((v) => !v)} data-testid="token-custom">
              <Icon name="settings" /> {custom ? "Use a preset" : "Choose permissions"}
            </button>
            <span className="faint small">
              {kind === "personal" ? "The token can never do more than you can in that plant." : "A plant token acts for the plant, not for a person: keep it in the ERP's secret store."}
            </span>
          </fieldset>
          <MfgError error={error} />
          <div>
            <button type="button" className="btn primary" disabled={busy || !name.trim() || scopes.size === 0} onClick={() => void create()} data-testid="token-create">
              <Icon name="plus" /> Create token
            </button>
          </div>
        </div>
      </section>
      <section className="card">
        <div className="card-header">
          <h2>Tokens</h2>
        </div>
        <MfgError error={tokens.error} onRetry={tokens.reload} />
        <div className="table-wrap">
          <table className="table" data-testid="token-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Permissions</th>
                <th>Expires</th>
                <th>Last used</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {items.length === 0 ? (
                <tr>
                  <td colSpan={5} className="muted">
                    {tokens.loading ? "Loading…" : "No tokens yet."}
                  </td>
                </tr>
              ) : null}
              {items.map((t) => {
                const expired = Date.parse(t.expires_at) < Date.now();
                return (
                  <tr key={t.id} data-testid="token-row" data-revoked={Boolean(t.revoked_at)} className={t.revoked_at || expired ? "faint" : undefined}>
                    <td>
                      <strong>{t.name}</strong>
                      <div className="mono small faint">{t.prefix}…</div>
                      {t.plant_name ? <div className="small muted">{t.plant_name}</div> : null}
                    </td>
                    <td className="small">{t.scopes.map((s) => SCOPE_LABEL[s] ?? s).join(", ")}</td>
                    <td className="small">
                      {t.revoked_at ? (
                        <span className="badge info">
                          <Icon name="ban" /> revoked
                        </span>
                      ) : expired ? (
                        <span className="badge warn">
                          <Icon name="clock" /> expired
                        </span>
                      ) : (
                        fmt(t.expires_at)
                      )}
                    </td>
                    <td className="small">
                      {fmt(t.last_used_at)}
                      {t.last_used_ip ? <div className="faint">{t.last_used_ip}</div> : null}
                    </td>
                    <td>
                      {!t.revoked_at ? (
                        <button type="button" className="btn sm ghost" onClick={() => setRevoking(t)} data-testid="token-revoke">
                          Revoke
                        </button>
                      ) : null}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>
      {revoking ? (
        <ConfirmDialog
          title={`Revoke "${revoking.name}"?`}
          confirmLabel="Revoke"
          danger
          onCancel={() => setRevoking(null)}
          onConfirm={async () => {
            try {
              await revokeToken(revoking.id);
            } catch (e) {
              setError(e);
            }
            setRevoking(null);
            tokens.reload();
          }}
        >
          <p style={{ margin: 0 }}>Anything still using it stops working at once.</p>
        </ConfirmDialog>
      ) : null}
    </div>
  );
}

export function TokensPage() {
  useEffect(() => {
    document.title = "API tokens - SuperPlanner";
  }, []);
  return (
    <div className="col gap-lg" style={{ maxWidth: 960, margin: "0 auto", width: "100%" }}>
      <div className="row wrap" style={{ justifyContent: "space-between" }}>
        <h1 style={{ margin: 0 }}>Personal API tokens</h1>
        <span className="row">
          <Link to="/account">Account</Link>
          <span className="faint">·</span>
          <Link to="/account/security">Two-step verification</Link>
        </span>
      </div>
      <p className="muted" style={{ margin: 0 }}>
        For scripts and reports that call SuperPlanner as you. For an ERP connection, a plant admin creates a plant token under Manufacturing, Integration.
      </p>
      <TokenManager kind="personal" />
    </div>
  );
}
