import type { FinancePlan, GoalOverride, WhatIfChanges } from "../api/types";
import { formatMoney, formatPct } from "../lib/money";
import { addMonths, fmtDurationMonths, fmtMonth, monthsBetween } from "../lib/months";

export interface WhatIfControlsProps {
  plan: FinancePlan;
  changes: WhatIfChanges;
  onChange(c: WhatIfChanges): void;
  /** Average monthly surplus of the first year (sets the savings slider range). */
  avgSurplus: number;
}

const RISK_TEXT = ["", "Very cautious", "Cautious", "Balanced", "Growth", "High growth"];

function roundTo(v: number, step: number) {
  return Math.round(v / step) * step;
}

/** What-if sliders (FINANCE.md 20.5). Values are a view of `changes`. */
export function WhatIfControls({ plan, changes, onChange, avgSurplus }: WhatIfControlsProps) {
  const cur = plan.profile.currency;
  const loc = plan.profile.locale;
  const base = Math.max(10000, avgSurplus);
  const minSave = Math.min(-1000, roundTo(-0.5 * base, 1000));
  const maxSave = Math.max(1000, roundTo(1.0 * base, 1000));
  const extra = changes.extra_monthly_savings ?? 0;
  const risk = changes.risk_tolerance ?? plan.profile.risk_tolerance;
  const shift = changes.return_shift_pct ?? 0;
  const drop = changes.income_drop ?? null;
  const start = plan.start_month ?? plan.goals[0]?.target_month ?? "2026-01";

  const overrideOf = (gid: string) => (changes.goal_overrides ?? []).find((o) => o.goal_id === gid);
  const setOverride = (gid: string, patch: Partial<GoalOverride>) => {
    const list = [...(changes.goal_overrides ?? [])];
    const i = list.findIndex((o) => o.goal_id === gid);
    const next: GoalOverride = { ...(i >= 0 ? list[i] : { goal_id: gid }), ...patch };
    const empty = Object.entries(next).every(([k, v]) => k === "goal_id" || v === null || v === undefined);
    if (i >= 0) {
      if (empty) list.splice(i, 1);
      else list[i] = next;
    } else if (!empty) list.push(next);
    onChange({ ...changes, goal_overrides: list });
  };

  const goals = plan.goals.filter((g) => g.enabled);

  return (
    <div className="col gap-lg" data-testid="whatif-controls">
      <div className="slider-field">
        <div className="slider-head">
          <label htmlFor="wi-savings">Extra monthly savings</label>
          <span>{formatMoney(extra, cur, loc, { signed: true })} / month</span>
        </div>
        <input
          id="wi-savings"
          type="range"
          min={minSave}
          max={maxSave}
          step={1000}
          value={extra}
          data-testid="whatif-savings"
          aria-valuetext={`${formatMoney(extra, cur, loc, { signed: true })} per month`}
          onChange={(e) => onChange({ ...changes, extra_monthly_savings: Number(e.target.value) })}
        />
        <span className="small faint">Negative means saving less (for example, spending more each month).</span>
      </div>

      {goals.map((g) => {
        const o = overrideOf(g.id);
        const months = o?.target_month ? monthsBetween(g.target_month, o.target_month) : 0;
        const amount = o?.target_amount ?? g.target_amount;
        return (
          <fieldset key={g.id} className="col" style={{ border: "1px solid var(--border)", borderRadius: "var(--radius)", padding: 10, margin: 0 }}>
            <legend className="small" style={{ fontWeight: 650, padding: "0 4px" }}>{g.name}</legend>
            <div className="slider-field">
              <div className="slider-head">
                <label htmlFor={`wi-shift-${g.id}`}>Move the date</label>
                <span>
                  {months === 0 ? "as planned" : `${months > 0 ? "later by" : "earlier by"} ${fmtDurationMonths(Math.abs(months))}`} ({fmtMonth(addMonths(g.target_month, months))})
                </span>
              </div>
              <input
                id={`wi-shift-${g.id}`}
                type="range"
                min={-24}
                max={60}
                step={1}
                value={months}
                data-testid={`whatif-goal-shift-${g.id}`}
                aria-valuetext={months === 0 ? "as planned" : `${months} months, ${fmtMonth(addMonths(g.target_month, months))}`}
                onChange={(e) => {
                  const n = Number(e.target.value);
                  let tm: string | null = n === 0 ? null : addMonths(g.target_month, n);
                  if (tm && monthsBetween(start, tm) < 1) tm = addMonths(start, 1);
                  setOverride(g.id, { target_month: tm });
                }}
              />
            </div>
            <div className="field">
              <label htmlFor={`wi-amount-${g.id}`}>Target amount (today's money)</label>
              <input
                id={`wi-amount-${g.id}`}
                className="input sm"
                type="number"
                min={1}
                step={1000}
                value={amount}
                data-testid={`whatif-goal-amount-${g.id}`}
                onChange={(e) => {
                  const v = Number(e.target.value);
                  if (!Number.isFinite(v) || v <= 0) return;
                  setOverride(g.id, { target_amount: v === g.target_amount ? null : v });
                }}
              />
            </div>
          </fieldset>
        );
      })}

      <div className="slider-field">
        <div className="slider-head">
          <label htmlFor="wi-risk">Risk level</label>
          <span>{risk} - {RISK_TEXT[risk]}{changes.risk_tolerance == null ? " (your plan)" : ""}</span>
        </div>
        <input
          id="wi-risk"
          type="range"
          min={1}
          max={5}
          step={1}
          value={risk}
          data-testid="whatif-risk"
          aria-valuetext={`${risk}, ${RISK_TEXT[risk]}`}
          onChange={(e) => {
            const v = Number(e.target.value);
            onChange({ ...changes, risk_tolerance: v === plan.profile.risk_tolerance ? null : v });
          }}
        />
      </div>

      <div className="slider-field">
        <div className="slider-head">
          <label htmlFor="wi-return">Market returns compared with your assumptions</label>
          <span>{shift === 0 ? "as assumed" : `${formatPct(shift, 1, true)} a year`}</span>
        </div>
        <input
          id="wi-return"
          type="range"
          min={-3}
          max={3}
          step={0.5}
          value={shift}
          data-testid="whatif-return"
          aria-valuetext={`${formatPct(shift, 1, true)} a year`}
          onChange={(e) => onChange({ ...changes, return_shift_pct: Number(e.target.value) })}
        />
      </div>

      <fieldset className="col" style={{ border: "1px solid var(--border)", borderRadius: "var(--radius)", padding: 10, margin: 0 }}>
        <legend className="small" style={{ fontWeight: 650, padding: "0 4px" }}>Income drop</legend>
        <div className="slider-field">
          <div className="slider-head">
            <label htmlFor="wi-drop-months">How long</label>
            <span>{drop ? fmtDurationMonths(drop.months) : "no drop"}</span>
          </div>
          <input
            id="wi-drop-months"
            type="range"
            min={0}
            max={12}
            step={1}
            value={drop?.months ?? 0}
            data-testid="whatif-income-drop-months"
            onChange={(e) => {
              const n = Number(e.target.value);
              // months = 0 sends `income_drop: null` [R15]
              onChange({
                ...changes,
                income_drop: n === 0 ? null : { start_month: drop?.start_month ?? addMonths(start, 1), months: n, percent: drop?.percent ?? 50 },
              });
            }}
          />
        </div>
        {drop ? (
          <div className="fin-form">
            <div className="field">
              <label htmlFor="wi-drop-start">Starting</label>
              <input
                id="wi-drop-start"
                className="input sm"
                type="month"
                value={drop.start_month}
                min={start}
                onChange={(e) => e.target.value && onChange({ ...changes, income_drop: { ...drop, start_month: e.target.value } })}
              />
            </div>
            <div className="field">
              <label htmlFor="wi-drop-pct">Income lost (%)</label>
              <input
                id="wi-drop-pct"
                className="input sm"
                type="number"
                min={1}
                max={100}
                value={drop.percent}
                onChange={(e) => {
                  const v = Math.max(1, Math.min(100, Number(e.target.value) || 0));
                  onChange({ ...changes, income_drop: { ...drop, percent: v } });
                }}
              />
            </div>
          </div>
        ) : null}
      </fieldset>
    </div>
  );
}

export function isEmptyChanges(c: WhatIfChanges): boolean {
  return (
    !(c.extra_monthly_savings ?? 0) &&
    !(c.goal_overrides ?? []).length &&
    c.risk_tolerance == null &&
    !(c.return_shift_pct ?? 0) &&
    c.inflation_pct == null &&
    !c.income_drop &&
    c.emergency_build_share == null
  );
}
