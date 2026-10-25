/**
 * Route builders for the Manufacturing area's own navigation (M 11.1). Health "Fix" links never use these:
 * they come from the server (`issue.link`, M 11.3), so the UI never derives a link for a health entity itself.
 */
import { queryString } from "../api/client";

const enc = encodeURIComponent;

export const MFG = "/mfg";

export const mfgPaths = {
  home: () => MFG,
  items: () => `${MFG}/items`,
  item: (itemId: string) => `${MFG}/items/${enc(itemId)}`,
  itemBom: (itemId: string, q?: { bom?: string; line?: string; on?: string; serial?: string; qty?: string }) =>
    `${MFG}/items/${enc(itemId)}/bom${queryString(q)}`,
  bomEdit: (itemId: string, bomId: string, line?: string) =>
    `${MFG}/items/${enc(itemId)}/bom/${enc(bomId)}/edit${queryString({ line })}`,
  whereUsed: (itemId: string) => `${MFG}/items/${enc(itemId)}/where-used`,
  routing: (itemId: string, q?: { routing?: string; op?: string | number }) =>
    `${MFG}/items/${enc(itemId)}/routing${queryString(q)}`,
  plant: () => `${MFG}/plant`,
  groups: (q?: { group?: string; line?: string }) => `${MFG}/plant/groups${queryString(q)}`,
  shifts: (q?: { template?: string; assignment?: string }) =>
    `${MFG}/plant/shifts${queryString(q)}`,
  calendar: (q?: { line?: string; exception?: string }) =>
    `${MFG}/plant/calendar${queryString(q)}`,
  settings: () => `${MFG}/plant/settings`,
  resources: () => `${MFG}/resources`,
  skills: (skill?: string) => `${MFG}/resources/skills${queryString({ skill })}`,
  operators: (operator?: string) => `${MFG}/resources/operators${queryString({ operator })}`,
  tooling: (tool?: string) => `${MFG}/resources/tooling${queryString({ tool })}`,
  health: () => `${MFG}/health`,
  importStart: (reuse?: string) => `${MFG}/import${queryString({ reuse })}`,
  importStep: (importId: string, step?: "map" | "preview" | "done") =>
    `${MFG}/import/${enc(importId)}${queryString({ step })}`,
};

/** M 11.1 `isMfgPath`. */
export function isMfgPath(pathname: string): boolean {
  return /^\/mfg(\/|$)/.test(pathname);
}
