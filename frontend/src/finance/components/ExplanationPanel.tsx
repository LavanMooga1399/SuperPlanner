import type { FinanceResult } from "../api/types";
import { formatPct } from "../lib/money";
import { realReturnPct } from "../lib/resultView";
import { DataTable } from "../../mfg/components/DataTable";
import { t } from "../../lib/i18n";

const REASON_LABEL: Record<string, string> = {
  ALLOCATION_SPLIT: t("finance.explanationPanel.str.whereTheMoneyGoes"),
  RISK_CAP: t("finance.explanationPanel.str.growthLimit"),
  GLIDE_DOWN: t("finance.explanationPanel.str.gettingSaferNearTheDate"),
  LOCKIN_EXCLUDED: t("finance.explanationPanel.str.lockInNotUsed"),
  EF_GATED: t("finance.explanationPanel.str.afterTheEmergencyFund"),
  CASH_LIMITED: t("finance.explanationPanel.str.savingsFullyUsed"),
  HOLDINGS_USED: t("finance.explanationPanel.str.existingSavings"),
  CAUTIOUS_RETURNS: t("finance.explanationPanel.str.cautiousPlanning"),
  SHORTFALL: t("finance.explanationPanel.str.shortfall"),
  LOW_PROBABILITY: t("finance.explanationPanel.str.lowerChance"),
  ON_TRACK: t("finance.explanationPanel.str.onTrack"),
};

/** Computed explanations (FINANCE.md 12): every sentence comes from the engine's message catalog. */
export function ExplanationPanel({ result, taxNote }: { result: FinanceResult; taxNote?: string }) {
  const ex = result.explanation;
  const used = result.assumptions_used;
  return (
    <section className="card" data-testid="fin-explanations" aria-labelledby="fin-expl-title">
      <div className="card-header">
        <h2 id="fin-expl-title">{t("finance.explanationPanel.head.whyThePlanLooksLike")}</h2>
      </div>
      <div className="card-body">
        <details className="explain-section" open>
          <summary>{t("finance.explanationPanel.head.summary")}</summary>
          <ul className="explain-list">
            {ex.summary.map((s, i) => (
              <li key={i}>{s}</li>
            ))}
          </ul>
        </details>
        {result.goals.map((g) => {
          const ge = ex.goals[g.goal_id];
          if (!ge || !ge.reasons.length) return null;
          return (
            <details className="explain-section" key={g.goal_id} open={g.status !== "on_track"}>
              <summary>{g.name}</summary>
              <ul className="explain-list">
                {ge.reasons.map((r, i) => (
                  <li key={i}>
                    <span className="label-tag">{REASON_LABEL[r.code] ?? r.code.replace(/_/g, " ").toLowerCase()}</span> {r.message}
                  </li>
                ))}
              </ul>
            </details>
          );
        })}
        {ex.binding_constraints.length ? (
          <details className="explain-section">
            <summary>{t("finance.explanationPanel.head.whatLimitsThePlan")}</summary>
            <ul className="explain-list">
              {ex.binding_constraints.map((b, i) => (
                <li key={i}>{b.message}</li>
              ))}
            </ul>
          </details>
        ) : null}
        <details className="explain-section">
          <summary>{t("finance.explanationPanel.head.assumptions")}</summary>
          <ul className="explain-list">
            {ex.assumptions.map((s, i) => (
              <li key={i}>{s}</li>
            ))}
          </ul>
          <div className="mt">
            <DataTable
              rows={used.asset_classes}
              columns={[
                { key: "name", header: "Asset class", width: "minmax(150px, 1.4fr)", sortValue: (c) => c.name, render: (c) => c.name },
                { key: "ret", header: "Expected return", label: "Expected return (your assumption)", width: "140px", align: "right", sortValue: (c) => c.expected_return_pct, render: (c) => formatPct(c.expected_return_pct, 1) },
                { key: "vol", header: "Ups and downs", label: "Ups and downs (your assumption)", width: "130px", align: "right", sortValue: (c) => c.volatility_pct, render: (c) => formatPct(c.volatility_pct, 1) },
                { key: "real", header: "After costs and inflation", label: "After costs and inflation (calculated)", width: "190px", align: "right", sortValue: (c) => realReturnPct(c, used.inflation_pct), render: (c) => formatPct(realReturnPct(c, used.inflation_pct), 1) },
              ]}
              rowKey={(c) => c.id}
              label={t("finance.explanationPanel.label.assumptionsUsedForThisResult")}
              tableId="finance-explain-assumptions"
              exportName="assumptions-used"
            />
          </div>
          <p className="small muted">{t("finance.explanationPanel.text.inflationAYearYourAssumption", { inflationpct: formatPct(used.inflation_pct, 1) })}</p>
          {taxNote ? (
            <p className="small muted">
              {t("finance.explanationPanel.text.yourTaxNoteNotCalculated", { taxNote: taxNote })}
            </p>
          ) : null}
        </details>
        <details className="explain-section">
          <summary>{t("finance.explanationPanel.head.limitations")}</summary>
          <ul className="explain-list">
            {ex.limitations.map((s, i) => (
              <li key={i}>{s}</li>
            ))}
          </ul>
        </details>
        <details className="explain-section">
          <summary>{t("finance.explanationPanel.head.whenToReplan")}</summary>
          <ul className="explain-list">
            {ex.replanning_triggers.map((s, i) => (
              <li key={i}>{s}</li>
            ))}
          </ul>
        </details>
        {result.violations.length ? (
          <details className="explain-section" open={result.violations.some((v) => v.severity === "hard")}>
            <summary>{t("finance.explanationPanel.text.independentCheckFindings", { length: result.violations.length })}</summary>
            <ul className="explain-list">
              {result.violations.map((v, i) => (
                <li key={i}>
                  <span className="label-tag">{v.severity === "hard" ? t("finance.explanationPanel.str.ruleBroken") : t("finance.explanationPanel.str.note")}</span> {v.message}
                </li>
              ))}
            </ul>
          </details>
        ) : null}
      </div>
    </section>
  );
}
