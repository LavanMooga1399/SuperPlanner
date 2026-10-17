import { useStoredState } from "../../lib/useAsync";
import { Term } from "../../components/Term";

export type MoneyBasis = "real" | "nominal";

export function useMoneyBasis(): [MoneyBasis, (b: MoneyBasis) => void] {
  return useStoredState<MoneyBasis>("sp.fin.moneyBasis", "real");
}

/** Today's money (real) vs expected future (nominal) amounts. */
export function RealNominalToggle({ value, onChange }: { value: MoneyBasis; onChange(b: MoneyBasis): void }) {
  return (
    <span className="row" style={{ gap: 2 }}>
    <div className="btn-group" role="group" aria-label="Show amounts in">
      <button type="button" className="btn sm" aria-pressed={value === "real"} onClick={() => onChange("real")} data-testid="basis-real">
        Today's money
      </button>
      <button type="button" className="btn sm" aria-pressed={value === "nominal"} onClick={() => onChange("nominal")} data-testid="basis-nominal">
        Expected future
      </button>
    </div>
    <Term k="real_vs_nominal" bare />
    </span>
  );
}
