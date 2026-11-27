/**
 * French (Canada) dictionary (M7 10): one file per English area file, same keys and placeholders
 * (`npm run i18n:check` compares them). Loaded on demand by `loadLocale()` in `lib/i18n.ts`; a key missing here
 * falls back to English. Terminology: docs/i18n/fr-CA-glossary.md.
 */
import type { StringKey } from "../../i18n";
import { accountFrCa } from "./account";
import { assistantFrCa } from "./assistant";
import { commonFrCa } from "./common";
import { financeFrCa } from "./finance";
import { floorFrCa } from "./floor";
import { gxpFrCa } from "./gxp";
import { mfgFrCa } from "./mfg";
import { mobileFrCa } from "./mobile";
import { navFrCa } from "./nav";
import { networkFrCa } from "./network";
import { planningFrCa } from "./planning";
import { qualityFrCa } from "./quality";
import { shellFrCa } from "./shell";
import { studioFrCa } from "./studio";

export const frCaStrings: Partial<Record<StringKey, string>> = {
  ...accountFrCa,
  ...assistantFrCa,
  ...commonFrCa,
  ...financeFrCa,
  ...floorFrCa,
  ...gxpFrCa,
  ...mfgFrCa,
  ...mobileFrCa,
  ...navFrCa,
  ...networkFrCa,
  ...planningFrCa,
  ...qualityFrCa,
  ...shellFrCa,
  ...studioFrCa,
} as Partial<Record<StringKey, string>>;
