/**
 * WP-D (M1-DESIGN 15.4 mfg-contract, PLAN-M1 D-3): with Kavach loaded, visit every page of M 11.1 and every health
 * link; fail on any unexpected 4xx/5xx. Every JSON response the screens receive is checked against the TypeScript
 * type the UI declares for that endpoint (`src/mfg/api/client.ts` -> `src/mfg/api/types.ts`, parsed here), so a
 * field the screens rely on that the API does not send (or sends with another type) fails the run.
 */
import { test, expect, type APIRequestContext, type Page } from "@playwright/test";
import * as fs from "node:fs";
import * as path from "node:path";
import { fileURLToPath } from "node:url";
import { expectClean, watch } from "./helpers";
import { findByCode, findItem, loadSample, mfgCall, mfgJson, resetMfg, MFG_DIRECT } from "./mfg-helpers";

const here = path.dirname(fileURLToPath(import.meta.url));
const TYPES = fs.readFileSync(path.join(here, "../src/mfg/api/types.ts"), "utf-8");
const CLIENT = fs.readFileSync(path.join(here, "../src/mfg/api/client.ts"), "utf-8");

// ---------------------------------------------------------------- a small TypeScript type reader
type T =
  | { k: "any" }
  | { k: "prim"; p: "string" | "number" | "boolean" | "null" }
  | { k: "lit"; v: string | number | boolean }
  | { k: "arr"; of: T }
  | { k: "tuple"; of: T[] }
  | { k: "union"; of: T[] }
  | { k: "obj"; fields: Field[] }
  | { k: "record"; v: T }
  | { k: "ref"; name: string; args: T[] };
interface Field { name: string; opt: boolean; t: T }
interface Decl { params: string[]; ext: string[]; body: T }

function stripComments(s: string): string {
  return s.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:"])\/\/.*$/gm, "$1");
}

function splitTop(s: string, sep: string): string[] {
  const out: string[] = [];
  let depth = 0;
  let cur = "";
  let q: string | null = null;
  for (const ch of s) {
    if (q) {
      cur += ch;
      if (ch === q) q = null;
      continue;
    }
    if (ch === '"' || ch === "'") q = ch;
    if ("{[(<".includes(ch)) depth++;
    if ("}])>".includes(ch)) depth--;
    if (ch === sep && depth === 0) {
      out.push(cur);
      cur = "";
    } else cur += ch;
  }
  if (cur.trim()) out.push(cur);
  return out.map((x) => x.trim()).filter(Boolean);
}

function parseFields(body: string): Field[] {
  const parts = splitTop(body.replace(/\n/g, ";"), ";").flatMap((p) => splitTop(p, ","));
  const out: Field[] = [];
  for (const p of parts) {
    const m = p.match(/^(readonly\s+)?("?[\w$-]+"?|\[[^\]]+\])(\?)?\s*:\s*([\s\S]+)$/);
    if (!m) continue;
    if (m[2].startsWith("[")) out.push({ name: "*", opt: true, t: parseType(m[4]) });
    else out.push({ name: m[2].replace(/"/g, ""), opt: Boolean(m[3]), t: parseType(m[4]) });
  }
  return out;
}

function parseType(src: string): T {
  const s = src.trim().replace(/;$/, "").trim();
  const u = splitTop(s, "|");
  if (u.length > 1) return { k: "union", of: u.map(parseType) };
  if (s.endsWith("[]")) return { k: "arr", of: parseType(s.slice(0, -2)) };
  if (s.startsWith("(") && s.endsWith(")")) return parseType(s.slice(1, -1));
  if (s.startsWith("{") && s.endsWith("}")) return { k: "obj", fields: parseFields(s.slice(1, -1)) };
  if (s.startsWith("[") && s.endsWith("]")) return { k: "tuple", of: splitTop(s.slice(1, -1), ",").map(parseType) };
  if (/^"[^"]*"$/.test(s)) return { k: "lit", v: s.slice(1, -1) };
  if (/^-?\d+(\.\d+)?$/.test(s)) return { k: "lit", v: Number(s) };
  if (s === "true" || s === "false") return { k: "lit", v: s === "true" };
  if (s === "string" || s === "number" || s === "boolean" || s === "null") return { k: "prim", p: s };
  if (s === "unknown" || s === "any" || s === "undefined" || s === "void" || s.includes("[\"")) return { k: "any" };
  const g = s.match(/^(\w+)\s*<([\s\S]+)>$/);
  if (g) {
    const args = splitTop(g[2], ",").map(parseType);
    if (g[1] === "Record") return { k: "record", v: args[1] };
    if (g[1] === "Partial" || g[1] === "Readonly") return args[0];
    if (g[1] === "Array") return { k: "arr", of: args[0] };
    return { k: "ref", name: g[1], args };
  }
  if (/^\w+$/.test(s)) return { k: "ref", name: s, args: [] };
  return { k: "any" };
}

function readDecls(src: string): Map<string, Decl> {
  const s = stripComments(src);
  const decls = new Map<string, Decl>();
  const re = /(?:^|\n)\s*(?:export\s+)?(interface|type)\s+(\w+)(\s*<[^>]*>)?/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(s))) {
    const params = m[3] ? m[3].replace(/[<>\s]/g, "").split(",").map((p) => p.split("=")[0]) : [];
    let i = re.lastIndex;
    if (m[1] === "interface") {
      const open = s.indexOf("{", i);
      const head = s.slice(i, open);
      const ext = (head.match(/extends\s+([\s\S]+)/)?.[1] ?? "").split(",").map((x) => x.trim()).filter(Boolean);
      let depth = 0;
      let j = open;
      for (; j < s.length; j++) {
        if (s[j] === "{") depth++;
        if (s[j] === "}" && --depth === 0) break;
      }
      decls.set(m[2], { params, ext, body: { k: "obj", fields: parseFields(s.slice(open + 1, j)) } });
      re.lastIndex = j;
    } else {
      const eq = s.indexOf("=", i);
      let depth = 0;
      let j = eq + 1;
      for (; j < s.length; j++) {
        const ch = s[j];
        if ("{[(<".includes(ch)) depth++;
        if ("}])>".includes(ch)) depth--;
        if (ch === ";" && depth === 0) break;
      }
      decls.set(m[2], { params, ext: [], body: parseType(s.slice(eq + 1, j)) });
      re.lastIndex = j;
    }
  }
  return decls;
}

const DECLS = readDecls(TYPES);

function fieldsOf(name: string, env: Map<string, T>): Field[] {
  const d = DECLS.get(name);
  if (!d || d.body.k !== "obj") return [];
  const own = d.body.fields.map((f) => ({ ...f, t: subst(f.t, env) }));
  const inherited = d.ext.flatMap((e) => {
    const t = parseType(e);
    return t.k === "ref" ? fieldsOf(t.name, envFor(t.name, t.args.map((a) => subst(a, env)))) : [];
  });
  const names = new Set(own.map((f) => f.name));
  return [...inherited.filter((f) => !names.has(f.name)), ...own];
}

function envFor(name: string, args: T[]): Map<string, T> {
  const d = DECLS.get(name);
  const env = new Map<string, T>();
  d?.params.forEach((p, i) => env.set(p, args[i] ?? { k: "any" }));
  return env;
}

function subst(t: T, env: Map<string, T>): T {
  switch (t.k) {
    case "ref":
      if (env.has(t.name) && t.args.length === 0) return env.get(t.name)!;
      return { ...t, args: t.args.map((a) => subst(a, env)) };
    case "arr":
      return { k: "arr", of: subst(t.of, env) };
    case "union":
      return { k: "union", of: t.of.map((x) => subst(x, env)) };
    case "tuple":
      return { k: "tuple", of: t.of.map((x) => subst(x, env)) };
    case "record":
      return { k: "record", v: subst(t.v, env) };
    case "obj":
      return { k: "obj", fields: t.fields.map((f) => ({ ...f, t: subst(f.t, env) })) };
    default:
      return t;
  }
}

function check(v: unknown, t: T, at: string, errs: string[], depth = 0): void {
  if (depth > 40) return;
  switch (t.k) {
    case "any":
      return;
    case "prim":
      if (t.p === "null" ? v !== null : typeof v !== t.p) errs.push(`${at}: expected ${t.p}, got ${JSON.stringify(v)?.slice(0, 60)}`);
      return;
    case "lit":
      if (v !== t.v) errs.push(`${at}: expected ${JSON.stringify(t.v)}, got ${JSON.stringify(v)?.slice(0, 60)}`);
      return;
    case "arr":
      if (!Array.isArray(v)) errs.push(`${at}: expected array`);
      else v.forEach((x, i) => (i < 300 || i % 97 === 0 ? check(x, t.of, `${at}[${i}]`, errs, depth + 1) : undefined));
      return;
    case "tuple":
      if (!Array.isArray(v) || v.length !== t.of.length) errs.push(`${at}: expected tuple of ${t.of.length}`);
      else v.forEach((x, i) => check(x, t.of[i], `${at}[${i}]`, errs, depth + 1));
      return;
    case "record":
      if (typeof v !== "object" || v === null || Array.isArray(v)) errs.push(`${at}: expected object`);
      else for (const [k, x] of Object.entries(v)) check(x, t.v, `${at}.${k}`, errs, depth + 1);
      return;
    case "union": {
      for (const o of t.of) {
        const e: string[] = [];
        check(v, o, at, e, depth + 1);
        if (e.length === 0) return;
      }
      errs.push(`${at}: ${JSON.stringify(v)?.slice(0, 80)} matches none of the union members`);
      return;
    }
    case "obj":
      if (typeof v !== "object" || v === null || Array.isArray(v)) {
        errs.push(`${at}: expected object, got ${JSON.stringify(v)?.slice(0, 60)}`);
        return;
      }
      for (const f of t.fields) {
        if (f.name === "*") continue;
        const x = (v as Record<string, unknown>)[f.name];
        if (x === undefined) {
          if (!f.opt) errs.push(`${at}.${f.name}: missing`);
          continue;
        }
        check(x, f.t, `${at}.${f.name}`, errs, depth + 1);
      }
      return;
    case "ref": {
      const d = DECLS.get(t.name);
      if (!d) return; // external / unknown name: not checked
      if (d.body.k === "obj") check(v, { k: "obj", fields: fieldsOf(t.name, envFor(t.name, t.args)) }, at, errs, depth + 1);
      else check(v, subst(d.body, envFor(t.name, t.args)), at, errs, depth + 1);
      return;
    }
  }
}

// ---------------------------------------------------------------- endpoint -> declared response type, from client.ts
interface Endpoint { method: string; re: RegExp; type: T; src: string }
const ENDPOINTS: Endpoint[] = (() => {
  const out: Endpoint[] = [];
  const re = /mfg(?:Request|Upload)<([^>]+(?:<[^>]+>)?)>\(\s*([`"])([^`"]+)\2([^;]*)/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(CLIENT))) {
    const method = m[0].startsWith("mfgUpload") ? "POST" : m[4].match(/method:\s*"(\w+)"/)?.[1] ?? "GET";
    const pat = m[3].replace(/\$\{[^}]+\}/g, "[^/?]+").replace(/[.]/g, "\\.");
    out.push({ method, re: new RegExp(`^${pat}$`), type: parseType(m[1]), src: m[1] });
  }
  return out;
})();

function endpointFor(method: string, p: string): Endpoint | undefined {
  // fixed paths win over parameterised ones (e.g. /shift-templates/preview)
  const hits = ENDPOINTS.filter((e) => e.method === method && e.re.test(p));
  return hits.sort((a, b) => b.re.source.replace(/\[\^\/\?\]\+/g, "").length - a.re.source.replace(/\[\^\/\?\]\+/g, "").length)[0];
}

interface Seen { method: string; path: string; body: unknown }

function capture(page: Page): Seen[] {
  const seen: Seen[] = [];
  page.on("response", async (r) => {
    const u = new URL(r.url());
    if (!u.pathname.startsWith("/api/v1/mfg/") || r.status() >= 300 || r.status() === 204) return;
    if (!(r.headers()["content-type"] ?? "").includes("application/json")) return;
    try {
      seen.push({ method: r.request().method(), path: u.pathname.slice("/api/v1/mfg".length), body: await r.json() });
    } catch {
      /* navigation aborted the body */
    }
  });
  return seen;
}

function validate(seen: Seen[]): { errors: string[]; covered: Set<string> } {
  const errors: string[] = [];
  const covered = new Set<string>();
  for (const s of seen) {
    const ep = endpointFor(s.method, s.path);
    if (!ep) {
      errors.push(`${s.method} ${s.path}: no client function declares this call`);
      continue;
    }
    covered.add(`${ep.method} ${ep.re.source}`);
    const e: string[] = [];
    check(s.body, ep.type, `${s.method} ${s.path} <${ep.src}>`, e);
    errors.push(...e.slice(0, 10));
  }
  return { errors, covered };
}

async function visit(page: Page, url: string, notFound = false): Promise<void> {
  await page.goto(url);
  await expect(page.getByTestId("mfg-subnav-overview")).toBeVisible();
  await page.waitForLoadState("networkidle");
  if (notFound) await expect(page.getByTestId("mfg-not-found")).toBeVisible();
  else await expect(page.getByTestId("mfg-not-found"), url).toHaveCount(0);
  await expect(page.getByTestId("mfg-error"), url).toHaveCount(0);
}

async function world(request: APIRequestContext) {
  await resetMfg(request);
  await loadSample(request, "kavach");
  const top = await findItem(request, "KV-TPU-1000");
  const cpu = await findItem(request, "KV-PCB-CPU");
  const boms = await mfgJson<{ items: { id: string; status: string; row_version: number }[] }>(request, `/items/${cpu.id}/boms`);
  const rel = boms.items.find((b) => b.status === "released")!;
  const draft = (await mfgCall(request, "POST", `/boms/${rel.id}/copy`, { data: { revision: null }, headers: { "If-Match": `"${rel.row_version}"` } })) as { id: string };
  const relRec = await mfgJson<{ lines: { id: string }[] }>(request, `/boms/${rel.id}`);
  const routings = await mfgJson<{ items: { id: string; status: string; priority: number }[] }>(request, `/items/${cpu.id}/routings`);
  const rtg = routings.items.find((r) => r.status === "released" && r.priority === 1)!;
  const grp = await findByCode(request, "/groups", "SMT");
  const line = await findByCode(request, "/lines", "SMT-2");
  const tpl = await findByCode(request, "/shift-templates", "3SHIFT");
  const asg = (await mfgJson<{ items: { id: string }[] }>(request, "/shift-assignments")).items[0];
  const exc = (await mfgJson<{ items: { id: string }[] }>(request, "/calendar-exceptions")).items[0];
  const skill = await findByCode(request, "/skills", "COATING");
  const op = await findByCode(request, "/operators", "OP-001");
  const tool = (await mfgJson<{ items: { id: string }[] }>(request, "/tool-pools")).items[0];
  const up = await request.post(`${MFG_DIRECT}/imports?filename=items.csv&sheet=items`, {
    data: Buffer.from("part_number,make_buy,lead_time_days\nKV-NEW-1,buy,5\n"),
    headers: { "content-type": "application/octet-stream" },
  });
  const imp = (await up.json()) as { id: string; sheets: { suggested: unknown }[] };
  await mfgCall(request, "PUT", `/imports/${imp.id}/mapping`, { data: { sheets: { items: imp.sheets[0].suggested }, options: {} }, headers: { "If-Match": '"1"' } });
  return { top, cpu, rel, relLine: relRec.lines[0].id, draft, rtg, grp, line, tpl, asg, exc, skill, op, tool, imp };
}

test("every Manufacturing page and every Kavach health link: no unexpected 4xx/5xx, responses match the UI types", async ({ page, request }) => {
  test.setTimeout(300_000);
  expect(DECLS.size).toBeGreaterThan(80);
  expect(ENDPOINTS.length).toBeGreaterThanOrEqual(70);
  const w = await world(request);
  const problems = watch(page);
  const seen = capture(page);
  const pages = [
    "/mfg",
    "/mfg/items",
    `/mfg/items/${w.top.id}`,
    `/mfg/items/${w.top.id}/bom`,
    `/mfg/items/${w.cpu.id}/bom?bom=${w.rel.id}&line=${w.relLine}`,
    `/mfg/items/${w.cpu.id}/bom/${w.draft.id}/edit`,
    `/mfg/items/${w.cpu.id}/bom/${w.draft.id}/edit?line=${w.relLine}`,
    `/mfg/items/${w.cpu.id}/bom/${w.rel.id}/edit`,
    `/mfg/items/${w.cpu.id}/where-used`,
    `/mfg/items/${w.top.id}/routing`,
    `/mfg/items/${w.cpu.id}/routing?routing=${w.rtg.id}&op=80`,
    "/mfg/plant",
    "/mfg/plant/groups",
    `/mfg/plant/groups?group=${w.grp.id}`,
    `/mfg/plant/groups?line=${w.line.id}`,
    "/mfg/plant/shifts",
    `/mfg/plant/shifts?template=${w.tpl.id}`,
    `/mfg/plant/shifts?assignment=${w.asg.id}`,
    "/mfg/plant/calendar",
    `/mfg/plant/calendar?line=${w.line.id}`,
    `/mfg/plant/calendar?exception=${w.exc.id}`,
    "/mfg/plant/settings",
    "/mfg/resources",
    `/mfg/resources/skills?skill=${w.skill.id}`,
    `/mfg/resources/operators?operator=${w.op.id}`,
    `/mfg/resources/tooling?tool=${w.tool.id}`,
    "/mfg/health",
    "/mfg/import",
    `/mfg/import/${w.imp.id}`,
    `/mfg/import/${w.imp.id}?step=map`,
    `/mfg/import/${w.imp.id}?step=preview`,
  ];
  for (const url of pages) await visit(page, url);
  // interactions that call further endpoints
  await visit(page, `/mfg/items/${w.top.id}/bom`);
  await page.getByTestId("bom-mode-summarized").click();
  await expect(page.getByTestId("bom-summary-row").first()).toBeVisible();
  await visit(page, `/mfg/items/${w.cpu.id}/where-used`);
  await page.getByTestId("whereused-mode-indented").click();
  await page.getByTestId("whereused-include-all").click();
  await page.waitForLoadState("networkidle");
  await visit(page, `/mfg/items/${w.cpu.id}/routing?routing=${w.rtg.id}`);
  await page.getByTestId("time-preview-qty").fill("37");
  await expect(page.getByTestId("time-preview-op").first()).toBeVisible();
  await page.waitForLoadState("networkidle");
  await visit(page, `/mfg/plant/shifts?template=${w.tpl.id}`);
  await expect(page.getByTestId("week-segment").first()).toBeVisible();
  // unknown routes / ids are the not-found page, not an API error
  await visit(page, "/mfg/does-not-exist", true);
  // every health link of Kavach
  const report = await mfgJson<{ issues: { link: string }[] }>(request, "/health");
  for (const i of report.issues) await visit(page, i.link);

  const { errors, covered } = validate(seen);
  console.log(`[mfg-contract] ${seen.length} JSON responses checked against ${covered.size} declared endpoint types`);
  expect(errors, errors.slice(0, 30).join("\n")).toEqual([]);
  expect(covered.size).toBeGreaterThanOrEqual(25);
  expectClean(problems);
});

test("every GET endpoint the UI declares answers in the declared shape (direct sweep with Kavach ids)", async ({ request }) => {
  test.setTimeout(180_000);
  const w = await world(request);
  const ids: Record<string, string> = {};
  const gets: [string, string][] = [
    ["/meta", ""], ["/summary", ""], ["/plant", ""], ["/items?limit=200&q=KV-PCB", ""], [`/items/${w.cpu.id}`, ""],
    [`/items/${w.top.id}/explosion?on=2026-11-02`, ""], [`/items/${w.top.id}/explosion?mode=summarized`, ""],
    [`/items/${w.cpu.id}/where-used?mode=indented&include=all`, ""], [`/items/${w.cpu.id}/boms`, ""],
    [`/items/${w.cpu.id}/routings`, ""], [`/boms/${w.rel.id}`, ""], [`/boms/${w.draft.id}`, ""], [`/routings/${w.rtg.id}`, ""],
    [`/routings/${w.rtg.id}/time-preview?qty=250`, ""], ["/groups", ""], [`/groups/${w.grp.id}`, ""], ["/lines", ""],
    [`/lines/${w.line.id}`, ""], [`/lines/${w.line.id}/windows?from=2026-11-01&to=2027-01-02&kinds=base,optional`, ""],
    ["/shift-templates", ""], [`/shift-templates/${w.tpl.id}`, ""], ["/shift-assignments", ""], ["/calendar-exceptions", ""],
    ["/skills", ""], ["/operators", ""], [`/operators?skill_id=${w.skill.id}`, ""], [`/operators/${w.op.id}`, ""], ["/tool-pools", ""],
    ["/health?as_of=2026-11-02", ""], [`/imports/${w.imp.id}`, ""], ["/samples", ""],
  ];
  void ids;
  const errors: string[] = [];
  for (const [p] of gets) {
    const body = await mfgJson(request, p);
    const ep = endpointFor("GET", p.split("?")[0]);
    if (!ep) {
      errors.push(`GET ${p}: not declared in client.ts`);
      continue;
    }
    check(body, ep.type, `GET ${p} <${ep.src}>`, errors);
  }
  // the stateless shift preview (POST) as the template editor sends it
  const tpl = await mfgJson<{ code: string; name: string; description: string; shifts: unknown[] }>(request, `/shift-templates/${w.tpl.id}`);
  const prev = await mfgCall(request, "POST", "/shift-templates/preview", { data: { code: tpl.code, name: tpl.name, description: tpl.description, shifts: tpl.shifts } });
  check(prev, endpointFor("POST", "/shift-templates/preview")!.type, "POST /shift-templates/preview", errors);
  expect(errors, errors.slice(0, 40).join("\n")).toEqual([]);
});

test("the shape checker itself rejects missing and mistyped fields (self-check)", async ({ request }) => {
  await resetMfg(request);
  await loadSample(request, "small");
  const it = await findItem(request, "SM-100");
  const rec = await mfgJson<Record<string, unknown>>(request, `/items/${it.id}`);
  const ep = endpointFor("GET", `/items/${it.id}`)!;
  expect(ep.src).toBe("ItemRecord");
  const ok: string[] = [];
  check(rec, ep.type, "item", ok);
  expect(ok).toEqual([]);
  for (const [mut, field] of [
    [{ ...rec, part_number: 5 }, "part_number"],
    [{ ...rec, make_buy: "rent" }, "make_buy"],
    [{ ...rec, row_version: "1" }, "row_version"],
    [Object.fromEntries(Object.entries(rec).filter(([k]) => k !== "has_bom")), "has_bom"],
    [{ ...rec, attributes: [] }, "attributes"],
  ] as [unknown, string][]) {
    const e: string[] = [];
    check(mut, ep.type, "item", e);
    expect(e.join("\n"), field).toContain(field);
  }
  const ex = await mfgJson<{ rows: Record<string, unknown>[] }>(request, `/items/${it.id}/explosion`);
  const e2: string[] = [];
  check({ ...ex, rows: [{ ...ex.rows[0], subtree_end: null }] }, endpointFor("GET", `/items/${it.id}/explosion`)!.type, "explosion", e2);
  expect(e2.length).toBeGreaterThan(0);
});
