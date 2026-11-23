import { Banner } from "../../components/Banner";
import type { ExtractorInfo } from "../api/types";
import { t } from "../../lib/i18n";

/** Which reader made the draft, or why AI assist was not used (PHASE2.md 3.3, 2.10). */
export function ExtractorBanner({ info, fromTable }: { info: ExtractorInfo; fromTable?: boolean }) {
  if (info.used === "ai+rule") {
    return (
      <Banner tone="accent" icon="star" testId="intake-extractor" title={t("studio.extractorBanner.title.readWithAiAssist")}>
        {t("studio.extractorBanner.text.aiAssistAndTheBuilt")}
      </Banner>
    );
  }
  if (info.requested === "ai") {
    return (
      <Banner tone="warn" testId="intake-extractor" title={t("studio.extractorBanner.title.readWithTheBuiltinReader")}>
        {info.fallback_message || t("studio.extractorBanner.str.aiAssistCouldNotBe")}
      </Banner>
    );
  }
  return (
    <Banner tone="info" testId="intake-extractor" title={t("studio.extractorBanner.title.readWithTheBuiltinReader")}>
      {t("studio.extractorBanner.text.checkTheDraftValuesMarked", { v: fromTable ? t("studio.extractorBanner.str.everyRowOfYourTable") : "" })}
    </Banner>
  );
}
