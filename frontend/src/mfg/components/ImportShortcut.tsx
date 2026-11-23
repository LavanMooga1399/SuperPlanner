/**
 * "Import from Excel" shortcut for the M2 list pages: opens the M1 import wizard (same upload -> map -> preview
 * -> commit flow; M2 sheets such as stock, purchase documents, demand and work orders are mapped there) and
 * offers the blank template with the transactional sheets.
 */
import { useState } from "react";
import { Link } from "react-router";
import { Icon } from "../../components/Icon";
import { downloadImportTemplate, saveBlob } from "../api/client";
import { mfgPaths } from "../lib/paths";
import { useCan } from "../lib/permissions";
import { MfgError } from "./Feedback";
import { t } from "../../lib/i18n";

export function ImportShortcut({ what, testId }: { what: string; testId?: string }) {
  const canImport = useCan("import");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  if (!canImport) return null;
  const template = async () => {
    setBusy(true);
    setError(null);
    try {
      saveBlob(await downloadImportTemplate("xlsx", "transactions"));
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="col" style={{ gap: 4 }}>
      <div className="row" style={{ gap: 4 }}>
        <Link className="btn" to={mfgPaths.importStart()} data-testid={testId} title={t("mfg.importShortcut.tpl.importFromAnExcelOr", { what: what })}>
          <Icon name="upload" />{" "}{t("mfg.importShortcut.text.import", { what: what })}
        </Link>
        <button type="button" className="btn ghost" onClick={() => void template()} disabled={busy} aria-label={t("mfg.importShortcut.tpl.downloadABlankExcelTemplate", { what: what })} title={t("mfg.importShortcut.tpl.downloadABlankExcelTemplate", { what: what })}>
          {busy ? <span className="spinner" aria-hidden /> : <Icon name="file" />}{" "}{t("mfg.importShortcut.text.template")}
        </button>
      </div>
      <MfgError error={error} title={t("mfg.importShortcut.attr.downloadFailed")} />
    </div>
  );
}
