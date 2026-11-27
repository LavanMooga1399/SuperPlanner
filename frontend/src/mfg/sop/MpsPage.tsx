/**
 * `/mfg/mps` (M9 6.6, 10): the plant's MPS targets from the published S&OP cycle (family x month quantity and load
 * hours) against what was actually received from work orders, with attainment shown as text and icon.
 */
import { useEffect, useMemo, useState } from "react";
import { FilterBar } from "../../components/FilterBar";
import { Icon } from "../../components/Icon";
import { PageHeader } from "../../components/PageHeader";
import { t } from "../../lib/i18n";
import { formatNumber } from "../../lib/locale";
import { getMpsTargets } from "../api/clientM9";
import type { MpsTarget } from "../api/typesM9";
import { MfgError, Spinner } from "../components/Feedback";
import { useLoad } from "../lib/useMfg";
import { monthShort, num, pct } from "../network/shared";

/** Attainment: at least 95 % on track, 80-95 % watch, below 80 % behind (past months only). */
export function AttainmentBadge({ a, past }: { a: number | null; past: boolean }) {
  if (a === null) return <span className="muted">–</span>;
  if (!past) return <span className="pl-num muted">{pct(a, 0)}</span>;
  const tone = a >= 0.95 ? "ok" : a >= 0.8 ? "warn" : "danger";
  return (
    <span className={`badge ${tone} pl-num-badge`} data-testid="mps-attainment" data-tone={tone}>
      <Icon name={tone === "ok" ? "check" : "alert"} />
      {pct(a, 0)}
    </span>
  );
}

export function MpsPage() {
  const [family, setFamily] = useState("");
  const res = useLoad((s) => getMpsTargets({}, s), []);
  useEffect(() => {
    document.title = t("net.mps.title");
  }, []);
  const items = res.data?.items ?? [];
  const months = useMemo(() => [...new Set(items.map((x) => x.month))].sort(), [items]);
  const fams = useMemo(() => [...new Set(items.map((x) => x.family))].sort(), [items]);
  const by = useMemo(() => new Map(items.map((x) => [`${x.family}|${x.month}`, x])), [items]);
  const thisMonth = new Date().toISOString().slice(0, 7);
  const cycle = items.find((x) => x.cycle_number)?.cycle_number ?? null;
  const shown = fams.filter((f) => !family || f === family);
  const total = (f: string, k: "qty_target" | "actual_qty") => months.reduce((a, m) => a + (by.get(`${f}|${m}`)?.[k] ?? 0), 0);
  return (
    <div className="col gap-lg" data-testid="mps-page">
      <PageHeader title={t("net.mps.title")} description={t("net.mps.desc")} facts={[[t("net.mps.fact.cycle"), cycle ?? "–"], [t("net.mps.fact.families"), formatNumber(fams.length)]]} />
      <FilterBar chips={family ? [{ key: "family", label: t("net.label.family"), value: family, onClear: () => setFamily("") }] : []}>
        <div className="field">
          <label htmlFor="mps-fam">{t("net.label.family")}</label>
          <select id="mps-fam" className="select sm" value={family} onChange={(e) => setFamily(e.target.value)}>
            <option value="">{t("net.dem.allFamilies")}</option>
            {fams.map((f) => (
              <option key={f} value={f}>
                {f}
              </option>
            ))}
          </select>
        </div>
      </FilterBar>
      <MfgError error={res.error} onRetry={res.reload} />
      {!res.data ? (
        <Spinner />
      ) : !items.length ? (
        <p className="muted card">{t("net.mps.empty")}</p>
      ) : (
        <section className="card card-table">
          <div className="pl-pivot-wrap">
            <table className="pl-pivot" aria-label={t("net.mps.aria")} data-testid="mps-grid">
              <thead>
                <tr>
                  <th scope="col">{t("net.dem.row")}</th>
                  {months.map((m) => (
                    <th key={m} scope="col">
                      {monthShort(m)}
                    </th>
                  ))}
                  <th scope="col">{t("net.dem.total")}</th>
                </tr>
              </thead>
              <tbody>
                {shown.map((f) => [
                  <tr key={`${f}-h`}>
                    <th scope="rowgroup" colSpan={months.length + 2} style={{ background: "var(--surface-2)" }}>
                      <strong>{f}</strong>
                    </th>
                  </tr>,
                  <tr key={`${f}-t`} className="net-grid-sub">
                    <th scope="row">{t("net.mps.target")}</th>
                    {months.map((m) => (
                      <td key={m} title={hoursTitle(by.get(`${f}|${m}`))}>
                        {num(by.get(`${f}|${m}`)?.qty_target)}
                      </td>
                    ))}
                    <td>{num(total(f, "qty_target"))}</td>
                  </tr>,
                  <tr key={`${f}-a`} className="net-grid-sub">
                    <th scope="row">{t("net.mps.actual")}</th>
                    {months.map((m) => (
                      <td key={m}>{m.slice(0, 7) <= thisMonth ? num(by.get(`${f}|${m}`)?.actual_qty) : ""}</td>
                    ))}
                    <td>{num(total(f, "actual_qty"))}</td>
                  </tr>,
                  <tr key={`${f}-p`} className="sop-total">
                    <th scope="row">{t("net.mps.attainment")}</th>
                    {months.map((m) => {
                      const x = by.get(`${f}|${m}`);
                      return (
                        <td key={m}>
                          <AttainmentBadge a={x?.attainment ?? null} past={m.slice(0, 7) < thisMonth} />
                        </td>
                      );
                    })}
                    <td />
                  </tr>,
                ])}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  );
}

function hoursTitle(x: MpsTarget | undefined): string | undefined {
  if (!x) return undefined;
  const h = Object.entries(x.hours);
  return h.length ? h.map(([g, v]) => t("net.mps.hoursTpl", { g, h: formatNumber(v, 1) })).join(", ") : undefined;
}
