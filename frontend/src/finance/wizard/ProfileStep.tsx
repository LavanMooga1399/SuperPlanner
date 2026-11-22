import { Banner } from "../../components/Banner";
import { compareMonths, currentUtcMonth, fmtMonth } from "../lib/months";
import type { StepProps } from "./common";
import { Field, FinOptionalNumber, FinNumber, FinText, MonthInput, Select } from "./fields";
import { HelpText } from "./HelpText";
import { t } from "../../lib/i18n";

const CURRENCIES = ["INR", "USD", "EUR", "GBP", "AUD", "CAD", "SGD", "AED", "JPY", "CHF"];
const LOCALES: Record<string, string> = { INR: "en-IN", USD: "en-US", EUR: "de-DE", GBP: "en-GB", AUD: "en-AU", CAD: "en-CA", SGD: "en-SG", AED: "en-AE", JPY: "ja-JP", CHF: "de-CH" };

export function ProfileStep({ plan, update, expert }: StepProps) {
  const now = currentUtcMonth();
  const stale = plan.start_month !== null && compareMonths(plan.start_month, now) < 0;
  const cur = plan.profile.currency;
  const currencyOptions = (CURRENCIES.includes(cur) ? CURRENCIES : [cur, ...CURRENCIES]).map((c) => ({ value: c, label: c }));
  return (
    <div className="col gap-lg">
      <HelpText>
        Tell us a little about yourself. Use take-home amounts everywhere; taxes are not calculated. Everything here is optional
        except the plan name.
      </HelpText>
      {stale ? (
        <Banner
          tone="warn"
          title={`This plan starts in ${fmtMonth(plan.start_month)}, which has already passed.`}
          actions={
            <button className="btn sm" onClick={() => update((p) => ({ ...p, start_month: now }))} data-testid="fin-move-start">
              {t("finance.profileStep.btn.moveToThisMonth")}
            </button>
          }
        >
          Amounts you enter are treated as values at the plan start. Move the start to {fmtMonth(now)} if your numbers are current.
        </Banner>
      ) : null}
      <div className="fin-form">
        <Field label={t("finance.profileStep.label.planName")} wide>
          {(id) => <FinText id={id} value={plan.name} onChange={(v) => update((p) => ({ ...p, name: v }))} testId="fin-plan-name" />}
        </Field>
        <Field label={t("finance.profileStep.label.currency")} hint={t("finance.profileStep.hint.singleCurrencyForTheWhole")}>
          {(id) => (
            <Select
              id={id}
              value={cur}
              options={currencyOptions}
              onChange={(v) => update((p) => ({ ...p, profile: { ...p.profile, currency: v, locale: LOCALES[v] ?? p.profile.locale } }))}
            />
          )}
        </Field>
        <Field label={t("finance.profileStep.label.yourAge")} hint={t("finance.profileStep.hint.optionalHelpsWithRetirementDates")}>
          {(id) => (
            <FinOptionalNumber id={id} value={plan.profile.age} min={16} max={100} onChange={(v) => update((p) => ({ ...p, profile: { ...p.profile, age: v === null ? null : Math.round(v) } }))} />
          )}
        </Field>
        <Field label={t("finance.profileStep.label.retirementAge")}>
          {(id) => (
            <FinNumber id={id} value={plan.profile.retirement_age} min={40} max={80} onChange={(v) => update((p) => ({ ...p, profile: { ...p.profile, retirement_age: Math.round(v) } }))} />
          )}
        </Field>
        <Field label={t("finance.profileStep.label.planStarts")} hint={t("finance.profileStep.hint.amountsAreInMoneyOf")}>
          {(id) => <MonthInput id={id} value={plan.start_month} onChange={(v) => v && update((p) => ({ ...p, start_month: v }))} testId="fin-start-month" />}
        </Field>
        <Field label={t("finance.profileStep.label.planUntilOptional")} hint={t("finance.profileStep.hint.leaveEmptyToPlanUntil")}>
          {(id) => (
            <MonthInput id={id} value={plan.horizon_end_month} optional min={plan.start_month ?? undefined} onChange={(v) => update((p) => ({ ...p, horizon_end_month: v }))} testId="fin-horizon-end" />
          )}
        </Field>
      </div>
      <div className="field">
        <label htmlFor="fin-tax-note">{t("finance.profileStep.label.taxNoteOptionalNotCalculated")}</label>
        <textarea
          id="fin-tax-note"
          className="textarea"
          maxLength={1000}
          value={plan.profile.tax_note}
          placeholder={t("finance.profileStep.ph.forExampleSalaryIsAfter")}
          onChange={(e) => {
            const v = e.target.value;
            update((p) => ({ ...p, profile: { ...p.profile, tax_note: v } }));
          }}
        />
        <span className="hint">Shown back with your results. No tax is computed.</span>
      </div>
      {expert ? (
        <div className="fin-form">
          <Field label={t("finance.profileStep.label.numberFormatLocale")}>
            {(id) => (
              <FinText id={id} value={plan.profile.locale} maxLength={16} onChange={(v) => update((p) => ({ ...p, profile: { ...p.profile, locale: v } }))} />
            )}
          </Field>
        </div>
      ) : null}
    </div>
  );
}
