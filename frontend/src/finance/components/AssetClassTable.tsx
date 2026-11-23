import type { AssetClass } from "../api/types";
import { Term } from "../../components/Term";
import { formatPct } from "../lib/money";
import { realReturnPct } from "../lib/resultView";
import { FinNumber } from "../wizard/fields";
import { t } from "../../lib/i18n";

const CATEGORY_LABEL: Record<AssetClass["category"], string> = {
  cash: t("finance.assetClassTable.str.cash"),
  debt: t("finance.assetClassTable.str.debtLowerRisk"),
  equity: t("finance.assetClassTable.str.equityGrowth"),
  gold: t("finance.assetClassTable.str.goldGrowth"),
  other: t("finance.assetClassTable.str.otherGrowth"),
};

/** Editable asset-class assumptions with a calculated real-return column (FINANCE.md 20.3). */
export function AssetClassTable({
  classes,
  inflationPct,
  onChange,
  expert,
}: {
  classes: AssetClass[];
  inflationPct: number;
  onChange(next: AssetClass[]): void;
  expert: boolean;
}) {
  const patch = (i: number, p: Partial<AssetClass>) => onChange(classes.map((c, j) => (j === i ? { ...c, ...p } : c)));
  return (
    <div className="table-wrap">
      <table className="table" data-testid="asset-class-table">
        <caption className="sr-only">{t("finance.assetClassTable.text.assetClassAssumptions")}</caption>
        <thead>
          <tr>
            <th scope="col">{t("finance.assetClassTable.head.assetClass")}</th>
            <th scope="col">{t("finance.assetClassTable.head.type")}</th>
            <th scope="col" className="num">{t("finance.assetClassTable.text.expectedReturnAYear")}<br /><span className="label-tag">{t("finance.assetClassTable.text.yourAssumption")}</span></th>
            <th scope="col" className="num">{t("finance.assetClassTable.text.upsAndDowns")}<br /><span className="label-tag">{t("finance.assetClassTable.text.yourAssumption")}</span></th>
            {expert ? (
              <>
                <th scope="col" className="num">{t("finance.assetClassTable.text.yearlyCosts")}<br /><span className="label-tag">{t("finance.assetClassTable.text.yourAssumption")}</span></th>
                <th scope="col" className="num">
                  <Term k="lock_in">Lock-in</Term> months<br /><span className="label-tag">{t("finance.assetClassTable.text.yourAssumption")}</span>
                </th>
              </>
            ) : null}
            <th scope="col" className="num">{t("finance.assetClassTable.text.afterCostsAndInflation")}<br /><span className="label-tag">{t("finance.assetClassTable.text.calculated")}</span></th>
          </tr>
        </thead>
        <tbody>
          {classes.map((c, i) => (
            <tr key={c.id}>
              <td>{c.name}</td>
              <td className="small muted">{CATEGORY_LABEL[c.category]}</td>
              <td className="num">
                <FinNumber label={t("finance.assetClassTable.tpl.expectedReturn", { name: c.name })} value={c.expected_return_pct} min={-20} max={40} step={0.1} onChange={(v) => patch(i, { expected_return_pct: v })} width={80} />
              </td>
              <td className="num">
                <FinNumber label={t("finance.assetClassTable.tpl.upsAndDownsVolatility", { name: c.name })} value={c.volatility_pct} min={0} max={80} step={0.5} onChange={(v) => patch(i, { volatility_pct: v })} width={80} />
              </td>
              {expert ? (
                <>
                  <td className="num">
                    <FinNumber label={t("finance.assetClassTable.tpl.yearlyCosts", { name: c.name })} value={c.expense_ratio_pct} min={0} max={5} step={0.05} onChange={(v) => patch(i, { expense_ratio_pct: v })} width={80} />
                  </td>
                  <td className="num">
                    <FinNumber label={t("finance.assetClassTable.tpl.lockInMonths", { name: c.name })} value={c.lock_in_months} min={0} max={360} step={1} onChange={(v) => patch(i, { lock_in_months: Math.round(v) })} width={80} />
                  </td>
                </>
              ) : null}
              <td className="num" aria-label={t("finance.assetClassTable.tpl.aYearAfterCostsAnd", { name: c.name, formatPct: formatPct(realReturnPct(c, inflationPct), 1) })}>
                {formatPct(realReturnPct(c, inflationPct), 1)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
