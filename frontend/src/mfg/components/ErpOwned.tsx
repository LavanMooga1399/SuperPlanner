/** "Maintained in the ERP" indicator (M5 4.4): icon + text, never colour alone. */
import { Icon } from "../../components/Icon";
import type { SorEntity } from "../api/typesM5";
import { useErpOwnership } from "../lib/erpOwnership";

export function ErpOwnedBadge({ what, testId = "erp-owned" }: { what?: string; testId?: string }) {
  return (
    <span className="badge info erp-owned" title="Maintained in the ERP; change it there. It comes in with the next sync." data-testid={testId}>
      <Icon name="lock" size={12} /> {what ? `${what} from ERP` : "From ERP"}
    </span>
  );
}

export function ErpOwnedBanner({ entity }: { entity: string }) {
  return (
    <div className="banner" role="note" data-testid="erp-owned-banner">
      <Icon name="lock" />
      <div>
        <strong>{entity} are maintained in the ERP for this plant.</strong> The fields from the ERP are read-only here; planning settings stay editable. Changes come in with the next sync.
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
