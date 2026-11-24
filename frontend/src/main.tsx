/**
 * Entry point: the stored language's dictionary is loaded first (M7 10, `lib/i18n.ts`), then the app modules, so
 * labels created when a module loads are already in that language.
 */
import { loadLocale } from "./lib/i18n";

void loadLocale().then(() => import("./boot"));
