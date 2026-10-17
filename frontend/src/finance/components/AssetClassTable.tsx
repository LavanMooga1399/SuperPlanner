import type { AssetClass } from "../api/types";
import { Term } from "../../components/Term";
import { formatPct } from "../lib/money";
import { realReturnPct } from "../lib/resultView";
import { FinNumber } from "../wizard/fields";

const CATEGORY_LABEL: Record<AssetClass["category"], string> = {
  cash: "Cash",
  debt: "Debt (lower risk)",
  equity: "Equity (growth)",
  gold: "Gold (growth)",
  other: "Other (growth)",
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
        <caption className="sr-only">Asset class assumptions</caption>
        <thead>
          <tr>
            <th scope="col">Asset class</th>
            <th scope="col">Type</th>
            <th scope="col" className="num">Expected return % a year<br /><span className="label-tag">Your assumption</span></th>
            <th scope="col" className="num">Ups and downs %<br /><span className="label-tag">Your assumption</span></th>
            {expert ? (
              <>
                <th scope="col" className="num">Yearly costs %<br /><span className="label-tag">Your assumption</span></th>
                <th scope="col" className="num">
                  <Term k="lock_in">Lock-in</Term> months<br /><span className="label-tag">Your assumption</span>
                </th>
              </>
            ) : null}
            <th scope="col" className="num">After costs and inflation<br /><span className="label-tag">Calculated</span></th>
          </tr>
        </thead>
        <tbody>
          {classes.map((c, i) => (
            <tr key={c.id}>
              <td>{c.name}</td>
              <td className="small muted">{CATEGORY_LABEL[c.category]}</td>
              <td className="num">
                <FinNumber label={`${c.name} expected return`} value={c.expected_return_pct} min={-20} max={40} step={0.1} onChange={(v) => patch(i, { expected_return_pct: v })} width={80} />
              </td>
              <td className="num">
                <FinNumber label={`${c.name} ups and downs (volatility)`} value={c.volatility_pct} min={0} max={80} step={0.5} onChange={(v) => patch(i, { volatility_pct: v })} width={80} />
              </td>
              {expert ? (
                <>
                  <td className="num">
                    <FinNumber label={`${c.name} yearly costs`} value={c.expense_ratio_pct} min={0} max={5} step={0.05} onChange={(v) => patch(i, { expense_ratio_pct: v })} width={80} />
                  </td>
                  <td className="num">
                    <FinNumber label={`${c.name} lock-in months`} value={c.lock_in_months} min={0} max={360} step={1} onChange={(v) => patch(i, { lock_in_months: Math.round(v) })} width={80} />
                  </td>
                </>
              ) : null}
              <td className="num" aria-label={`${c.name}: ${formatPct(realReturnPct(c, inflationPct), 1)} a year after costs and inflation`}>
                {formatPct(realReturnPct(c, inflationPct), 1)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
