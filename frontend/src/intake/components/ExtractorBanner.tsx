import { Banner } from "../../components/Banner";
import type { ExtractorInfo } from "../api/types";

/** Which reader made the draft, or why AI assist was not used (PHASE2.md 3.3, 2.10). */
export function ExtractorBanner({ info, fromTable }: { info: ExtractorInfo; fromTable?: boolean }) {
  if (info.used === "ai+rule") {
    return (
      <Banner tone="accent" icon="star" testId="intake-extractor" title="Read with AI assist">
        AI assist and the built-in reader made this draft together. Numbers you typed were kept as you wrote them. Please
        check the draft before you create the plan.
      </Banner>
    );
  }
  if (info.requested === "ai") {
    return (
      <Banner tone="warn" testId="intake-extractor" title="Read with the built-in reader">
        {info.fallback_message || "AI assist could not be used this time, so the built-in reader made the draft."}
      </Banner>
    );
  }
  return (
    <Banner tone="info" testId="intake-extractor" title="Read with the built-in reader">
      {fromTable ? "Every row of your table became one item. " : ""}Check the draft; values marked Low or Medium are guesses.
    </Banner>
  );
}
