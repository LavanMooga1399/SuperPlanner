
import { t } from "./i18n";/**
 * Plain-language explanations shown by `components/Term.tsx` (PHASE2.md 3.6).
 * One entry per term; keep each to one or two short sentences without jargon.
 */
export const GLOSSARY = {
  critical_chain: {
    term: t("shell.glossary.str.criticalChain"),
    text: t("shell.glossary.str.theSequenceOfWorkThat"),
  },
  makespan: {
    term: t("shell.glossary.str.finishTime"),
    text: t("shell.glossary.str.howLongTheWholePlan"),
  },
  hard_deadline: {
    term: t("shell.glossary.str.hardDeadline"),
    text: t("shell.glossary.str.aDateThatMustBe"),
  },
  soft_deadline: {
    term: t("shell.glossary.str.softDeadline"),
    text: t("shell.glossary.str.aDateYouWouldLike"),
  },
  dependency: {
    term: t("shell.glossary.str.dependency"),
    text: t("shell.glossary.str.aRuleThatOnePiece"),
  },
  resource: {
    term: t("shell.glossary.str.resource"),
    text: t("shell.glossary.str.whoOrWhatDoesThe"),
  },
  calendar_window: {
    term: t("shell.glossary.str.workingTime"),
    text: t("shell.glossary.str.theHoursInWhichA"),
  },
  expected_duration: {
    term: t("shell.glossary.str.expectedDuration"),
    text: t("shell.glossary.str.aSinglePlanningFigureFrom"),
  },
  duration_range: {
    term: t("shell.glossary.str.durationRange"),
    text: t("shell.glossary.str.howLongTheWorkMight"),
  },
  real_vs_nominal: {
    term: t("shell.glossary.str.todaySMoneyVsFuture"),
    text: t("shell.glossary.str.todaySMoneyRealRemoves"),
  },
  todays_money: {
    term: "Today's money",
    text: t("shell.glossary.str.anAmountAtTodayS"),
  },
  cautious_return: {
    term: t("shell.glossary.str.cautiousReturn"),
    text: t("shell.glossary.str.theReturnThePlanCounts"),
  },
  glide_path: {
    term: t("shell.glossary.str.glidePath"),
    text: t("shell.glossary.str.asAGoalGetsClose"),
  },
  risk_level: {
    term: t("shell.glossary.str.riskLevel"),
    text: t("shell.glossary.str.from1VeryCarefulTo"),
  },
  growth_assets: {
    term: t("shell.glossary.str.growthAssets"),
    text: t("shell.glossary.str.investmentsSuchAsSharesThat"),
  },
  emergency_fund: {
    term: t("shell.glossary.str.emergencyFund"),
    text: t("shell.glossary.str.moneyKeptSafeAndEasy"),
  },
  shortfall: {
    term: t("shell.glossary.str.shortfall"),
    text: t("shell.glossary.str.howMuchAGoalIs"),
  },
  chance_of_success: {
    term: t("shell.glossary.str.chanceOfSuccess"),
    text: t("shell.glossary.str.inHowManyOfMany"),
  },
  lock_in: {
    term: "Lock-in",
    text: t("shell.glossary.str.moneyInThisKindOf"),
  },
} as const;

export type GlossaryKey = keyof typeof GLOSSARY;
