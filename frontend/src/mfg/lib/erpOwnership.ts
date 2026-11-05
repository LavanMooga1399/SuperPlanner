/**
 * M5 4.4 system of record, for the read-only indicators: which entities (and fields) of this plant the ERP owns, and
 * who books goods receipts (14 Q2). Read once per page load from `GET /integration/settings`; when that is not
 * readable (role without `integration_admin`, server without M5) nothing is marked and the server's 409
 * `INT_ERP_OWNED` still explains a refused save (16 requests a read for every role, 15.WP-U).
 */
import { useEffect, useState } from "react";
import { getIntegrationSettings } from "../api/clientM5";
import type { IntegrationSettings, SorEntity } from "../api/typesM5";
import { currentWorkspace } from "./workspace";

/** 4.4 table: ERP-owned fields when the entity's SoR is `erp` (used when the server sends no list) */
export const DEFAULT_ERP_FIELDS: Partial<Record<SorEntity, string[]>> = {
  items: ["part_number", "revision", "description", "uom", "make_buy", "active", "external_ref", "standard_cost"],
  suppliers: ["*", "!preferred"],
  item_suppliers: ["*", "!preferred"],
  boms: ["*"],
  routings: ["*"],
  purchase_orders: ["*"],
  demand_orders: ["*", "!priority"],
};

let cache: { ws: string | null; p: Promise<IntegrationSettings | null> } | null = null;

export function invalidateErpOwnership() {
  cache = null;
}

export interface ErpOwnership {
  ready: boolean;
  settings: IntegrationSettings | null;
  /** the ERP owns this entity (SoR erp) */
  owns(entity: SorEntity): boolean;
  /** the ERP owns this field of the entity */
  ownsField(entity: SorEntity, field: string): boolean;
  goodsReceiptsByErp: boolean;
}

export function useErpOwnership(): ErpOwnership {
  const [s, setS] = useState<IntegrationSettings | null>(null);
  const [ready, setReady] = useState(false);
  useEffect(() => {
    const ws = currentWorkspace();
    if (!cache || cache.ws !== ws) cache = { ws, p: getIntegrationSettings().catch(() => null) };
    let alive = true;
    void cache.p.then((x) => {
      if (!alive) return;
      setS(x);
      setReady(true);
    });
    return () => {
      alive = false;
    };
  }, []);
  const owns = (e: SorEntity) => Boolean(s?.enabled && s.sor[e] === "erp");
  return {
    ready,
    settings: s,
    owns,
    ownsField: (e, f) => {
      if (!owns(e)) return false;
      const list = s?.erp_owned_fields?.[e] ?? DEFAULT_ERP_FIELDS[e] ?? [];
      if (list.includes(`!${f}`)) return false;
      return list.includes("*") || list.includes(f);
    },
    goodsReceiptsByErp: Boolean(s?.enabled && (s.goods_receipts_owner === "erp" || s.sor.po_receipts === "erp")),
  };
}
