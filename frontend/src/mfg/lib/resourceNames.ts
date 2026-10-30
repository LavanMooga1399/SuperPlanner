/** Group (stage) and line codes by id, for views that carry only ids (M3 load, overtime, bottlenecks). Cached per page load. */
import { useEffect, useState } from "react";
import { listGroups, listLines } from "../api/client";

interface Names {
  group(id: string | null | undefined): { code: string; name: string };
  line(id: string | null | undefined): { code: string; name: string; group_id: string | null };
  ready: boolean;
}

let cache: Promise<{ g: Map<string, { code: string; name: string }>; l: Map<string, { code: string; name: string; group_id: string }> }> | null = null;

export function invalidateResourceNames(): void {
  cache = null;
}

export function useResourceNames(): Names {
  const [maps, setMaps] = useState<Awaited<NonNullable<typeof cache>> | null>(null);
  useEffect(() => {
    let alive = true;
    if (!cache)
      cache = Promise.all([listGroups({}), listLines({})]).then(
        ([g, l]) => ({ g: new Map(g.items.map((x) => [x.id, { code: x.code, name: x.name }])), l: new Map(l.items.map((x) => [x.id, { code: x.code, name: x.name, group_id: x.group_id }])) }),
        (e: unknown) => {
          cache = null;
          throw e;
        },
      );
    cache.then(
      (m) => alive && setMaps(m),
      () => undefined,
    );
    return () => {
      alive = false;
    };
  }, []);
  return {
    ready: maps !== null,
    group: (id) => (id && maps?.g.get(id)) || { code: id ? "…" : "", name: "" },
    line: (id) => (id && maps?.l.get(id)) || { code: id ? "…" : "", name: "", group_id: null },
  };
}
