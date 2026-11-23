/** "Maintained in the ERP" indicator (M5 4.4): icon + text, never colour alone. */
import { Icon } from "../../components/Icon";
import type { SorEntity } from "../api/typesM5";
import { useErpOwnership } from "../lib/erpOwnership";
import { t } from "../../lib/i18n";

export function ErpOwnedBadge({ what, testId = "erp-owned" }: { what?: string; testId?: string }) {
  return (
    <span className="badge info erp-owned" title={t("mfg.erpOwned.attr.maintainedInTheErpChange")} data-testid={testId}>
      <Icon name="lock" size={12} /> {what ? t("mfg.erpOwned.tpl.fromErp", { what: what }) : t("mfg.erpOwned.str.fromErp")}
    </span>
  );
}

export function ErpOwnedBanner({ entity }: { entity: string }) {
  return (
    <div className="banner" role="note" data-testid="erp-owned-banner">
      <Icon name="lock" />
      <div>
        <strong>{t("mfg.erpOwned.text.areMaintainedInTheErp", { entity: entity })}</strong>{" "}{t("mfg.erpOwned.text.theFieldsFromTheErp")}
      </div>
    </div>
  );
}

/** Shown only when the ERP owns `entity` in this plant (self-loading; nothing on servers without M5). */
export function ErpOwnedNotice({ entity, label }: { entity: SorEntity; label: string }) {
  const erp = useErpOwnership();
  if (!erp.owns(entity)) return null;
  return <ErpOwnedBanner entity={label} />;
}
