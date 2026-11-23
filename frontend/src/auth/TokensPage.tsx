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
import { formatDateTime } from "../lib/locale";
import { PageHeader } from "../components/PageHeader";
import { DataTable } from "../mfg/components/DataTable";
import { t, t as tr } from "../lib/i18n";

const PRESETS: { key: string; label: string; help: string; scopes: TokenScope[] }[] = [
  { key: "read", label: tr("account.tokensPage.str.readOnly"), help: tr("account.tokensPage.str.reportsAndDashboardsReadEverything"), scopes: ["view", "floor_view", "trace_view"] },
  { key: "erp", label: "ERP / middleware", help: tr("account.tokensPage.str.sendMasterDataAndOrders"), scopes: ["view", "integration.read", "integration.write"] },
  { key: "events", label: tr("account.tokensPage.str.readEventsOnly"), help: tr("account.tokensPage.str.aConsumerThatPullsThe"), scopes: ["integration.read"] },
];

const SCOPE_LABEL: Partial<Record<TokenScope, string>> = {
  view: tr("account.tokensPage.str.read"),
  "integration.read": tr("account.tokensPage.str.readIntegrationEvents"),
  "integration.write": tr("account.tokensPage.str.sendIntegrationBatches"),
  master_edit: tr("account.tokensPage.str.editMasterData"),
  inventory: tr("account.tokensPage.str.stockPostings"),
  wo_edit: tr("account.tokensPage.str.workOrders"),
  mrp_run: tr("account.tokensPage.str.runMrp"),
  schedule_run: tr("account.tokensPage.str.runSchedules"),
  floor_report: tr("account.tokensPage.str.reportFloorWork"),
};

const fmt = (iso: string | null | undefined) => (iso ? formatDateTime(iso) : "never");

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
        <Banner tone="ok" title={tr("account.tokensPage.tpl.tokenCreated", { name: created.name })} testId="token-created">
          <div className="col" style={{ gap: 8 }}>
            <span>{tr("account.tokensPage.text.copyItNowItIs")}</span>
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
                <Icon name="copy" /> {copied ? tr("account.tokensPage.str.copied") : tr("account.tokensPage.str.copy")}
              </button>
              <button type="button" className="btn sm ghost" onClick={() => setCreated(null)}>
                {t("account.tokensPage.btn.iHaveStoredIt")}
              </button>
            </div>
            <span className="faint small">
              {tr("account.tokensPage.text.useItAs")}{" "}<span className="mono">{tr("account.tokensPage.text.authorizationBearer", { prefix: created.prefix })}</span>
            </span>
          </div>
        </Banner>
      ) : null}
      <section className="card">
        <div className="card-header">
          <h2>{tr("account.tokensPage.text.newToken", { v: kind === "plant" ? "plant" : "personal" })}</h2>
        </div>
        <div className="card-body col">
          <div className="form-grid">
            <div className="field">
              <label htmlFor="tk-name">{t("account.tokensPage.label.name")}</label>
              <input id="tk-name" className="input" value={name} onChange={(e) => setName(e.target.value)} maxLength={100} placeholder={kind === "plant" ? tr("account.tokensPage.str.eGErpMiddleware") : tr("account.tokensPage.str.eGPowerBiReport")} data-testid="token-name" />
            </div>
            {kind === "personal" && workspaces.length > 1 ? (
              <div className="field">
                <label htmlFor="tk-ws">{t("account.tokensPage.label.plant")}</label>
                <select id="tk-ws" className="select" value={workspace} onChange={(e) => setWorkspace(e.target.value)}>
                  {workspaces.map((w) => (
                    <option key={w.owner_id} value={w.is_owner ? "" : w.owner_id}>
                      {w.plant_name || tr("account.tokensPage.str.plant")}
                      {w.is_owner ? " (mine)" : ""}
                    </option>
                  ))}
                </select>
              </div>
            ) : null}
            <div className="field">
              <label htmlFor="tk-days">{t("account.tokensPage.label.validFor")}</label>
              <select id="tk-days" className="select" value={days} onChange={(e) => setDays(Number(e.target.value))} data-testid="token-days">
                <option value={30}>30 days</option>
                <option value={90}>{tr("account.tokensPage.text.90DaysRecommended")}</option>
                <option value={180}>180 days</option>
                <option value={365}>{tr("account.tokensPage.text.1YearMaximum")}</option>
              </select>
            </div>
          </div>
          <fieldset className="mfg-fieldset">
            <legend>{t("account.tokensPage.head.whatItMayDo")}</legend>
            {!custom ? (
              <div className="col" style={{ gap: 6 }} role="radiogroup" aria-label={t("account.tokensPage.aria.tokenPurpose")}>
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
              <Icon name="settings" /> {custom ? tr("account.tokensPage.str.useAPreset") : tr("account.tokensPage.str.choosePermissions")}
            </button>
            <span className="faint small">
              {kind === "personal" ? tr("account.tokensPage.str.theTokenCanNeverDo") : tr("account.tokensPage.str.aPlantTokenActsFor")}
            </span>
          </fieldset>
          <MfgError error={error} />
          <div>
            <button type="button" className="btn primary" disabled={busy || !name.trim() || scopes.size === 0} onClick={() => void create()} data-testid="token-create">
              <Icon name="plus" /> {t("account.tokensPage.btn.createToken")}
            </button>
          </div>
        </div>
      </section>
      <section className="card card-table">
        <div className="card-header">
          <h2>{t("account.tokensPage.head.tokens")}</h2>
        </div>
        <MfgError error={tokens.error} onRetry={tokens.reload} />
        <DataTable
          rows={items}
          columns={[
            {
              key: "name",
              header: "Name",
              width: "minmax(180px, 1.4fr)",
              sortValue: (x) => x.name,
              exportValue: (x) => x.name,
              render: (x) => (
                <span>
                  <strong>{x.name}</strong> <span className="mono small faint">{x.prefix}…</span>
                  {x.plant_name ? <span className="vt-sub">{x.plant_name}</span> : null}
                </span>
              ),
            },
            { key: "scopes", header: "Permissions", width: "minmax(200px, 2fr)", wrap: true, render: (x) => <span className="small">{x.scopes.map((sc) => SCOPE_LABEL[sc] ?? sc).join(", ")}</span> },
            {
              key: "expires",
              header: "Expires",
              width: "150px",
              sortValue: (x) => x.expires_at,
              exportValue: (x) => (x.revoked_at ? "revoked" : x.expires_at),
              render: (x) =>
                x.revoked_at ? (
                  <span className="badge info">
                    <Icon name="ban" /> {t("account.tokensPage.btn.revoked")}
                  </span>
                ) : Date.parse(x.expires_at) < Date.now() ? (
                  <span className="badge warn">
                    <Icon name="clock" /> {t("account.tokensPage.btn.expired")}
                  </span>
                ) : (
                  fmt(x.expires_at)
                ),
            },
            {
              key: "used",
              header: "Last used",
              width: "170px",
              sortValue: (x) => x.last_used_at ?? null,
              exportValue: (x) => x.last_used_at ?? "",
              render: (x) => (
                <span>
                  {fmt(x.last_used_at)}
                  {x.last_used_ip ? <span className="vt-sub">{x.last_used_ip}</span> : null}
                </span>
              ),
            },
            {
              key: "actions",
              header: <span className="sr-only">{tr("account.tokensPage.text.actions")}</span>,
              label: "Actions",
              width: "96px",
              align: "right",
              exportValue: () => "",
              render: (x) =>
                !x.revoked_at ? (
                  <button type="button" className="btn sm ghost" onClick={() => setRevoking(x)} data-testid="token-revoke">
                    {t("account.tokensPage.btn.revoke")}
                  </button>
                ) : null,
            },
          ]}
          rowKey={(x) => x.id}
          label={t("account.tokensPage.label.tokens")}
          testId="token-table"
          loading={tokens.loading && !items.length}
          rowExtras={(x) => ({ testId: "token-row", data: { revoked: Boolean(x.revoked_at) }, className: x.revoked_at || Date.parse(x.expires_at) < Date.now() ? "faint" : undefined })}
          empty={t("account.tokensPage.empty.noTokensYet")}
          card={{ title: "name", status: "expires", actions: "actions", fields: ["scopes", "used"] }}
        />
      </section>
      {revoking ? (
        <ConfirmDialog
          title={tr("account.tokensPage.tpl.revoke", { name: revoking.name })}
          confirmLabel={t("account.tokensPage.btn.revoke")}
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
          <p style={{ margin: 0 }}>{t("account.tokensPage.text.anythingStillUsingItStops")}</p>
        </ConfirmDialog>
      ) : null}
    </div>
  );
}

export function TokensPage() {
  useEffect(() => {
    document.title = tr("account.tokensPage.str.apiTokensSuperplanner");
  }, []);
  return (
    <div className="col gap-lg" style={{ maxWidth: 960, margin: "0 auto", width: "100%" }}>
      <PageHeader
        title={t("account.tokensPage.title.personalApiTokens")}
        actions={
          <>
            <Link to="/account">{tr("account.tokensPage.text.account")}</Link>
            <span className="faint">·</span>
            <Link to="/account/security">{tr("account.tokensPage.text.twoStepVerification")}</Link>
          </>
        }
      />
      <p className="muted" style={{ margin: 0 }}>
        {tr("account.tokensPage.text.forScriptsAndReportsThat")}
      </p>
      <TokenManager kind="personal" />
    </div>
  );
}
