/**
 * Small per-page-load cache of full item records (lot tracking, unit, standard cost) for forms whose pickers
 * only return an `ItemRef`. One request per item id; failures are not cached.
 */
import { useEffect, useState } from "react";
import { getItem } from "../api/client";
import type { ItemRecord } from "../api/types";
import type { ItemM2Fields } from "../api/typesM2";

export type ItemInfo = ItemRecord & ItemM2Fields;

const cache = new Map<string, Promise<ItemInfo>>();

export function loadItemInfo(id: string): Promise<ItemInfo> {
  let p = cache.get(id);
  if (!p) {
    p = getItem(id).catch((e: unknown) => {
      cache.delete(id);
      throw e;
    });
    cache.set(id, p);
  }
  return p;
}

export function useItemInfo(id: string | null | undefined): ItemInfo | null {
  const [info, setInfo] = useState<ItemInfo | null>(null);
  useEffect(() => {
    if (!id) {
      setInfo(null);
      return;
    }
    let alive = true;
    loadItemInfo(id).then(
      (r) => alive && setInfo(r),
      () => alive && setInfo(null),
    );
    return () => {
      alive = false;
    };
  }, [id]);
  return info && info.id === id ? info : null;
}

/** Count units (`EA`): quantities must be whole numbers (M2 3 `INV_FRACTIONAL_QTY`). */
export function isCountUom(uom: string | undefined): boolean {
  return (uom ?? "").toUpperCase() === "EA";
}
