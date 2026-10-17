/**
 * Plain-language explanations shown by `components/Term.tsx` (PHASE2.md 3.6).
 * One entry per term; keep each to one or two short sentences without jargon.
 */
export const GLOSSARY = {
  critical_chain: {
    term: "Critical chain",
    text: "The sequence of work that decides the finish date. If anything on it takes longer, the whole plan finishes later.",
  },
  makespan: {
    term: "Finish time",
    text: "How long the whole plan takes, from the plan start until the last piece of work is done (also called makespan).",
  },
  hard_deadline: {
    term: "Hard deadline",
    text: "A date that must be met. The planner never accepts a schedule that misses it; if it cannot be met, it says so.",
  },
  soft_deadline: {
    term: "Soft deadline",
    text: "A date you would like to meet. The planner tries to, but may finish later if there is no other way, and shows how late.",
  },
  dependency: {
    term: "Dependency",
    text: "A rule that one piece of work has to wait for another, for example \"Testing starts after Build\".",
  },
  resource: {
    term: "Resource",
    text: "Who or what does the work: a person, a machine or your own study time. Each can do a limited amount at once.",
  },
  calendar_window: {
    term: "Working time",
    text: "The hours in which a resource can work, such as 09:00-17:00 on weekdays. Nothing is planned outside these windows.",
  },
  expected_duration: {
    term: "Expected duration",
    text: "A single planning figure from a range: (shortest + 4 x most likely + longest) / 6. This is the PERT estimate.",
  },
  duration_range: {
    term: "Duration range",
    text: "How long the work might take: shortest, most likely and longest. The plan uses the expected duration and notes the risk.",
  },
  real_vs_nominal: {
    term: "Today's money vs future amounts",
    text: "Today's money (real) removes inflation so amounts are comparable with prices now. Future amounts (nominal) are what the numbers will actually read then.",
  },
  todays_money: {
    term: "Today's money",
    text: "An amount at today's prices. The plan adds inflation for you, so enter costs as they would be today.",
  },
  cautious_return: {
    term: "Cautious return",
    text: "The return the plan counts on: below the average, so that most outcomes are at least this good.",
  },
  glide_path: {
    term: "Glide path",
    text: "As a goal gets close, the plan moves its money step by step from growth assets to safer ones.",
  },
  risk_level: {
    term: "Risk level",
    text: "From 1 (very careful) to 5 (comfortable with big ups and downs). It limits how much may go into growth assets.",
  },
  growth_assets: {
    term: "Growth assets",
    text: "Investments such as shares that tend to grow faster over many years but can fall in value along the way.",
  },
  emergency_fund: {
    term: "Emergency fund",
    text: "Money kept safe and easy to reach for surprises, usually a few months of expenses. It is built first.",
  },
  shortfall: {
    term: "Shortfall",
    text: "How much a goal is likely to miss its target by, as an amount or a share of the target.",
  },
  chance_of_success: {
    term: "Chance of success",
    text: "In how many of many simulated futures the goal is fully reached. 70% means 7 out of 10.",
  },
  lock_in: {
    term: "Lock-in",
    text: "Money in this kind of saving cannot be taken out for a number of years without a penalty.",
  },
} as const;

export type GlossaryKey = keyof typeof GLOSSARY;
