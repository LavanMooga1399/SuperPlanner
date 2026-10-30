/**
 * Typed wrappers for every endpoint of docs/M1-DESIGN.md 9.3 (`/api/v1/mfg/...`, 77 operations).
 * `src/api/client.ts` keeps its request helpers private, so this module has `mfgRaw`/`mfgRequest` with the same
 * A.14 envelope parsing, importing only the exported names allowed by M 2.
 */
import { API_BASE, ApiError, looksLikeProxyFailure, networkError } from "../../api/client";
import { authFetch } from "../../auth/authFetch";
import { workspaceHeaders } from "../lib/workspace";
import type {
  AssignmentQuery,
  BomCopyRequest,
  BomInput,
  BomRecord,
  BomReleaseResponse,
  BomSummary,
  CalendarExceptionInput,
  CalendarExceptionRecord,
  ExceptionQuery,
  Explosion,
  ExplosionQuery,
  FileFormat,
  GroupDetail,
  GroupInput,
  GroupRecord,
  HealthQuery,
  HealthReport,
  ImportMappingRequest,
  ImportRecord,
  ItemInput,
  ItemQuery,
  ItemRecord,
  LineInput,
  LineRecord,
  LineWindows,
  List,
  Meta,
  OperatorInput,
  OperatorQuery,
  OperatorRecord,
  Page,
  PlantInput,
  PlantRecord,
  ReleaseRequest,
  ResetResponse,
  RoutingCopyRequest,
  RoutingInput,
  RoutingRecord,
  RoutingReleaseResponse,
  RoutingSummary,
  SampleInfo,
  SampleLoadResponse,
  ShiftAssignmentInput,
  ShiftAssignmentRecord,
  ShiftPreview,
  ShiftTemplateInput,
  ShiftTemplateRecord,
  SkillInput,
  SkillRecord,
  Summary,
  ToolPoolInput,
  ToolPoolRecord,
  WhereUsed,
  WhereUsedQuery,
  AssignmentKind,
  TimePreview,
} from "./types";

export interface MfgRequestOptions {
  method?: string;
  body?: unknown;
  headers?: Record<string, string>;
  signal?: AbortSignal;
  query?: QueryParams;
}

export type QueryValue = string | number | boolean | null | undefined | readonly string[];
export type QueryParams = Record<string, QueryValue>;

export interface MfgRawResponse<T> {
  data: T;
  headers: Headers;
  status: number;
}

const M = "/mfg";
const enc = encodeURIComponent;

function envelopeOf(x: unknown): { code: string; message: string; details?: Record<string, unknown> } | null {
  if (typeof x !== "object" || x === null || !("error" in x)) return null;
  const e = (x as { error: unknown }).error;
  if (typeof e !== "object" || e === null || !("code" in e)) return null;
  return e as { code: string; message: string; details?: Record<string, unknown> };
}

/** `?a=1&b=x`; undefined, null and "" values are left out; arrays repeat the key (`status=a&status=b`). */
export function queryString(q: QueryParams | undefined): string {
  if (!q) return "";
  const parts: string[] = [];
  for (const [k, v] of Object.entries(q)) {
    if (v === undefined || v === null || v === "") continue;
    if (Array.isArray(v)) {
      for (const x of v as readonly string[]) if (x !== "") parts.push(`${enc(k)}=${enc(x)}`);
      continue;
    }
    parts.push(`${enc(k)}=${enc(String(v))}`);
  }
  return parts.length ? `?${parts.join("&")}` : "";
}

export const ifMatch = (version: number) => ({ "If-Match": `"${version}"` });

async function failure(res: Response): Promise<ApiError> {
  const text = await res.text();
  let parsed: unknown = undefined;
  if (text) {
    try {
      parsed = JSON.parse(text);
    } catch {
      parsed = text;
    }
  }
  const env = envelopeOf(parsed);
  if (env) return new ApiError(res.status, env.code, env.message, env.details ?? {});
  if (looksLikeProxyFailure(res.status, text)) return networkError(res.status);
  const detail =
    typeof parsed === "object" && parsed !== null && "detail" in parsed
      ? String((parsed as { detail: unknown }).detail)
      : res.statusText || "Request failed";
  return new ApiError(res.status, `HTTP_${res.status}`, detail);
}

async function send(path: string, init: RequestInit): Promise<Response> {
  try {
    return await authFetch(API_BASE + path, init);
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    throw networkError();
  }
}

export async function mfgRaw<T>(path: string, opts: MfgRequestOptions = {}): Promise<MfgRawResponse<T>> {
  const headers: Record<string, string> = { Accept: "application/json", ...workspaceHeaders(), ...(opts.headers ?? {}) };
  let body: BodyInit | undefined;
  if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.body);
  }
  const res = await send(M + path + queryString(opts.query), {
    method: opts.method ?? "GET",
    headers,
    body,
    signal: opts.signal,
  });
  if (!res.ok) throw await failure(res);
  if (res.status === 204) return { data: undefined as T, headers: res.headers, status: 204 };
  const text = await res.text();
  let parsed: unknown = undefined;
  if (text) {
    try {
      parsed = JSON.parse(text);
    } catch {
      parsed = text;
    }
  }
  return { data: parsed as T, headers: res.headers, status: res.status };
}

export async function mfgRequest<T>(path: string, opts: MfgRequestOptions = {}): Promise<T> {
  return (await mfgRaw<T>(path, opts)).data;
}

/**
 * Raw-body upload (9.3 #68). Always `application/octet-stream`: a JSON content type would make the body-limit
 * middleware scan the binary body for NUL and reject it (M 8.3, R4f).
 */
export async function mfgUpload<T>(path: string, file: Blob, query?: QueryParams, signal?: AbortSignal): Promise<T> {
  const res = await send(M + path + queryString(query), {
    method: "POST",
    headers: { Accept: "application/json", "Content-Type": "application/octet-stream", ...workspaceHeaders() },
    body: file,
    signal,
  });
  if (!res.ok) throw await failure(res);
  return (await res.json()) as T;
}

/** File name from `Content-Disposition` (`filename*=UTF-8''...` preferred, then `filename="..."`). */
export function filenameFromDisposition(header: string | null, fallback: string): string {
  if (!header) return fallback;
  const star = header.match(/filename\*\s*=\s*(?:UTF-8|utf-8)''([^;]+)/);
  if (star) {
    try {
      return decodeURIComponent(star[1].trim().replace(/^"|"$/g, ""));
    } catch {
      /* fall through */
    }
  }
  const plain = header.match(/filename\s*=\s*"([^"]*)"/) ?? header.match(/filename\s*=\s*([^;]+)/);
  return plain ? plain[1].trim() : fallback;
}

export interface DownloadedFile {
  blob: Blob;
  filename: string;
}

/** GET a file (export, templates) as a blob with the server's file name. */
export async function mfgDownload(path: string, query?: QueryParams, fallbackName = "download"): Promise<DownloadedFile> {
  const res = await send(M + path + queryString(query), { method: "GET", headers: { Accept: "*/*", ...workspaceHeaders() } });
  if (!res.ok) throw await failure(res);
  const blob = await res.blob();
  return { blob, filename: filenameFromDisposition(res.headers.get("Content-Disposition"), fallbackName) };
}

/** Hand a blob to the browser as a download. */
export function saveBlob(file: DownloadedFile): void {
  const url = URL.createObjectURL(file.blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = file.filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

// ---------------------------------------------------------------- #1-4 meta, summary, plant
export const getMeta = (signal?: AbortSignal) => mfgRequest<Meta>("/meta", { signal });
export const getSummary = (signal?: AbortSignal) => mfgRequest<Summary>("/summary", { signal });
export const getPlant = (signal?: AbortSignal) => mfgRequest<PlantRecord>("/plant", { signal });
/** `version` 0 creates the plant row (3.3). */
export const updatePlant = (body: PlantInput, version: number) =>
  mfgRequest<PlantRecord>("/plant", { method: "PUT", body, headers: ifMatch(version) });

// ---------------------------------------------------------------- #5-13 items
export const listItems = (query: ItemQuery, signal?: AbortSignal) =>
  mfgRequest<Page<ItemRecord>>("/items", { query: { ...query }, signal });
export const createItem = (body: ItemInput) => mfgRequest<ItemRecord>("/items", { method: "POST", body });
export const getItem = (id: string, signal?: AbortSignal) => mfgRequest<ItemRecord>(`/items/${enc(id)}`, { signal });
export const updateItem = (id: string, body: ItemInput, version: number) =>
  mfgRequest<ItemRecord>(`/items/${enc(id)}`, { method: "PUT", body, headers: ifMatch(version) });
export const deleteItem = (id: string, version: number) =>
  mfgRequest<void>(`/items/${enc(id)}`, { method: "DELETE", headers: ifMatch(version) });
export const getExplosion = (id: string, query: ExplosionQuery, signal?: AbortSignal) =>
  mfgRequest<Explosion>(`/items/${enc(id)}/explosion`, { query: { ...query }, signal });
export const getWhereUsed = (id: string, query: WhereUsedQuery, signal?: AbortSignal) =>
  mfgRequest<WhereUsed>(`/items/${enc(id)}/where-used`, { query: { ...query }, signal });
export const listItemBoms = (id: string, signal?: AbortSignal) =>
  mfgRequest<List<BomSummary>>(`/items/${enc(id)}/boms`, { signal });
export const listItemRoutings = (id: string, signal?: AbortSignal) =>
  mfgRequest<List<RoutingSummary>>(`/items/${enc(id)}/routings`, { signal });

// ---------------------------------------------------------------- #14-20 BOMs
export const createBom = (body: BomInput) => mfgRequest<BomRecord>("/boms", { method: "POST", body });
export const getBom = (id: string, signal?: AbortSignal) => mfgRequest<BomRecord>(`/boms/${enc(id)}`, { signal });
export const updateBom = (id: string, body: BomInput, version: number) =>
  mfgRequest<BomRecord>(`/boms/${enc(id)}`, { method: "PUT", body, headers: ifMatch(version) });
export const deleteBom = (id: string, version: number) =>
  mfgRequest<void>(`/boms/${enc(id)}`, { method: "DELETE", headers: ifMatch(version) });
export const releaseBom = (id: string, body: ReleaseRequest, version: number) =>
  mfgRequest<BomReleaseResponse>(`/boms/${enc(id)}/release`, { method: "POST", body, headers: ifMatch(version) });
export const obsoleteBom = (id: string, version: number) =>
  mfgRequest<BomRecord>(`/boms/${enc(id)}/obsolete`, { method: "POST", body: {}, headers: ifMatch(version) });
export const copyBom = (id: string, body: BomCopyRequest, version: number) =>
  mfgRequest<BomRecord>(`/boms/${enc(id)}/copy`, { method: "POST", body, headers: ifMatch(version) });

// ---------------------------------------------------------------- #21-28 routings
export const createRouting = (body: RoutingInput) => mfgRequest<RoutingRecord>("/routings", { method: "POST", body });
export const getRouting = (id: string, signal?: AbortSignal) =>
  mfgRequest<RoutingRecord>(`/routings/${enc(id)}`, { signal });
export const updateRouting = (id: string, body: RoutingInput, version: number) =>
  mfgRequest<RoutingRecord>(`/routings/${enc(id)}`, { method: "PUT", body, headers: ifMatch(version) });
export const deleteRouting = (id: string, version: number) =>
  mfgRequest<void>(`/routings/${enc(id)}`, { method: "DELETE", headers: ifMatch(version) });
export const releaseRouting = (id: string, body: ReleaseRequest, version: number) =>
  mfgRequest<RoutingReleaseResponse>(`/routings/${enc(id)}/release`, {
    method: "POST",
    body,
    headers: ifMatch(version),
  });
export const obsoleteRouting = (id: string, version: number) =>
  mfgRequest<RoutingRecord>(`/routings/${enc(id)}/obsolete`, { method: "POST", body: {}, headers: ifMatch(version) });
export const copyRouting = (id: string, body: RoutingCopyRequest, version: number) =>
  mfgRequest<RoutingRecord>(`/routings/${enc(id)}/copy`, { method: "POST", body, headers: ifMatch(version) });
export const getTimePreview = (id: string, qty: number, signal?: AbortSignal) =>
  mfgRequest<TimePreview>(`/routings/${enc(id)}/time-preview`, { query: { qty }, signal });

// ---------------------------------------------------------------- #29-39 groups and lines
export const listGroups = (query: { q?: string; active?: boolean } = {}, signal?: AbortSignal) =>
  mfgRequest<List<GroupRecord>>("/groups", { query: { ...query }, signal });
export const createGroup = (body: GroupInput) => mfgRequest<GroupRecord>("/groups", { method: "POST", body });
export const getGroup = (id: string, signal?: AbortSignal) => mfgRequest<GroupDetail>(`/groups/${enc(id)}`, { signal });
export const updateGroup = (id: string, body: GroupInput, version: number) =>
  mfgRequest<GroupRecord>(`/groups/${enc(id)}`, { method: "PUT", body, headers: ifMatch(version) });
export const deleteGroup = (id: string, version: number) =>
  mfgRequest<void>(`/groups/${enc(id)}`, { method: "DELETE", headers: ifMatch(version) });

export const listLines = (query: { group_id?: string; q?: string; active?: boolean } = {}, signal?: AbortSignal) =>
  mfgRequest<List<LineRecord>>("/lines", { query: { ...query }, signal });
export const createLine = (body: LineInput) => mfgRequest<LineRecord>("/lines", { method: "POST", body });
export const getLine = (id: string, signal?: AbortSignal) => mfgRequest<LineRecord>(`/lines/${enc(id)}`, { signal });
export const updateLine = (id: string, body: LineInput, version: number) =>
  mfgRequest<LineRecord>(`/lines/${enc(id)}`, { method: "PUT", body, headers: ifMatch(version) });
export const deleteLine = (id: string, version: number) =>
  mfgRequest<void>(`/lines/${enc(id)}`, { method: "DELETE", headers: ifMatch(version) });
/** `to` is exclusive; at most 62 days (`MAX_WINDOW_RANGE_DAYS`). */
export const getLineWindows = (
  id: string,
  from: string,
  to: string,
  kinds: AssignmentKind[] = ["base", "optional"],
  signal?: AbortSignal,
) => mfgRequest<LineWindows>(`/lines/${enc(id)}/windows`, { query: { from, to, kinds: kinds.join(",") }, signal });

// ---------------------------------------------------------------- #40-49 shift templates and assignments
export const listShiftTemplates = (signal?: AbortSignal) =>
  mfgRequest<List<ShiftTemplateRecord>>("/shift-templates", { signal });
export const createShiftTemplate = (body: ShiftTemplateInput) =>
  mfgRequest<ShiftTemplateRecord>("/shift-templates", { method: "POST", body });
export const previewShiftTemplate = (body: ShiftTemplateInput, signal?: AbortSignal) =>
  mfgRequest<ShiftPreview>("/shift-templates/preview", { method: "POST", body, signal });
export const getShiftTemplate = (id: string, signal?: AbortSignal) =>
  mfgRequest<ShiftTemplateRecord>(`/shift-templates/${enc(id)}`, { signal });
export const updateShiftTemplate = (id: string, body: ShiftTemplateInput, version: number) =>
  mfgRequest<ShiftTemplateRecord>(`/shift-templates/${enc(id)}`, { method: "PUT", body, headers: ifMatch(version) });
export const deleteShiftTemplate = (id: string, version: number) =>
  mfgRequest<void>(`/shift-templates/${enc(id)}`, { method: "DELETE", headers: ifMatch(version) });

export const listShiftAssignments = (query: AssignmentQuery = {}, signal?: AbortSignal) =>
  mfgRequest<List<ShiftAssignmentRecord>>("/shift-assignments", { query: { ...query }, signal });
export const createShiftAssignment = (body: ShiftAssignmentInput) =>
  mfgRequest<ShiftAssignmentRecord>("/shift-assignments", { method: "POST", body });
export const updateShiftAssignment = (id: string, body: ShiftAssignmentInput, version: number) =>
  mfgRequest<ShiftAssignmentRecord>(`/shift-assignments/${enc(id)}`, {
    method: "PUT",
    body,
    headers: ifMatch(version),
  });
export const deleteShiftAssignment = (id: string, version: number) =>
  mfgRequest<void>(`/shift-assignments/${enc(id)}`, { method: "DELETE", headers: ifMatch(version) });

// ---------------------------------------------------------------- #50-53 calendar exceptions
export const listCalendarExceptions = (query: ExceptionQuery = {}, signal?: AbortSignal) =>
  mfgRequest<List<CalendarExceptionRecord>>("/calendar-exceptions", { query: { ...query }, signal });
export const createCalendarException = (body: CalendarExceptionInput) =>
  mfgRequest<CalendarExceptionRecord>("/calendar-exceptions", { method: "POST", body });
export const updateCalendarException = (id: string, body: CalendarExceptionInput, version: number) =>
  mfgRequest<CalendarExceptionRecord>(`/calendar-exceptions/${enc(id)}`, {
    method: "PUT",
    body,
    headers: ifMatch(version),
  });
export const deleteCalendarException = (id: string, version: number) =>
  mfgRequest<void>(`/calendar-exceptions/${enc(id)}`, { method: "DELETE", headers: ifMatch(version) });

// ---------------------------------------------------------------- #54-66 skills, operators, tool pools
export const listSkills = (signal?: AbortSignal) => mfgRequest<List<SkillRecord>>("/skills", { signal });
export const createSkill = (body: SkillInput) => mfgRequest<SkillRecord>("/skills", { method: "POST", body });
export const updateSkill = (id: string, body: SkillInput, version: number) =>
  mfgRequest<SkillRecord>(`/skills/${enc(id)}`, { method: "PUT", body, headers: ifMatch(version) });
export const deleteSkill = (id: string, version: number) =>
  mfgRequest<void>(`/skills/${enc(id)}`, { method: "DELETE", headers: ifMatch(version) });

export const listOperators = (query: OperatorQuery = {}, signal?: AbortSignal) =>
  mfgRequest<List<OperatorRecord>>("/operators", { query: { ...query }, signal });
export const createOperator = (body: OperatorInput) =>
  mfgRequest<OperatorRecord>("/operators", { method: "POST", body });
export const getOperator = (id: string, signal?: AbortSignal) =>
  mfgRequest<OperatorRecord>(`/operators/${enc(id)}`, { signal });
export const updateOperator = (id: string, body: OperatorInput, version: number) =>
  mfgRequest<OperatorRecord>(`/operators/${enc(id)}`, { method: "PUT", body, headers: ifMatch(version) });
export const deleteOperator = (id: string, version: number) =>
  mfgRequest<void>(`/operators/${enc(id)}`, { method: "DELETE", headers: ifMatch(version) });

export const listToolPools = (signal?: AbortSignal) => mfgRequest<List<ToolPoolRecord>>("/tool-pools", { signal });
export const createToolPool = (body: ToolPoolInput) =>
  mfgRequest<ToolPoolRecord>("/tool-pools", { method: "POST", body });
export const updateToolPool = (id: string, body: ToolPoolInput, version: number) =>
  mfgRequest<ToolPoolRecord>(`/tool-pools/${enc(id)}`, { method: "PUT", body, headers: ifMatch(version) });
export const deleteToolPool = (id: string, version: number) =>
  mfgRequest<void>(`/tool-pools/${enc(id)}`, { method: "DELETE", headers: ifMatch(version) });

// ---------------------------------------------------------------- #67 health
export const getHealthReport = (query: HealthQuery = {}, signal?: AbortSignal) =>
  mfgRequest<HealthReport>("/health", { query: { ...query }, signal });

// ---------------------------------------------------------------- #68-74 import / export
export const uploadImport = (file: Blob, filename: string, sheet?: string) =>
  mfgUpload<ImportRecord>("/imports", file, { filename, sheet });
export const getImport = (id: string, signal?: AbortSignal) =>
  mfgRequest<ImportRecord>(`/imports/${enc(id)}`, { signal });
export const putImportMapping = (id: string, body: ImportMappingRequest, version: number) =>
  mfgRequest<ImportRecord>(`/imports/${enc(id)}/mapping`, { method: "PUT", body, headers: ifMatch(version) });
export const commitImport = (id: string, version: number) =>
  mfgRequest<ImportRecord>(`/imports/${enc(id)}/commit`, { method: "POST", body: {}, headers: ifMatch(version) });
export const deleteImport = (id: string) => mfgRequest<void>(`/imports/${enc(id)}`, { method: "DELETE" });
/** `scope` (M2 11): `master` (default, M1 behaviour + M2 master sheets) | `transactions` | `all`. */
export type ExportScope = "master" | "transactions" | "all";
export const downloadExport = (format: FileFormat, scope?: ExportScope) =>
  mfgDownload("/export", { format, scope }, `superplanner-mfg.${format}`);
export const downloadImportTemplate = (format: FileFormat, scope?: ExportScope) =>
  mfgDownload("/import-templates", { format, scope }, `superplanner-mfg-template.${format}`);

// ---------------------------------------------------------------- #75-77 samples and reset
export const listSamples = (signal?: AbortSignal) => mfgRequest<List<SampleInfo>>("/samples", { signal });
export const loadSample = (id: string, replace: boolean) =>
  mfgRequest<SampleLoadResponse>(`/samples/${enc(id)}/load`, { method: "POST", body: { replace } });
export const resetMfg = (confirm: string) => mfgRequest<ResetResponse>("/reset", { method: "POST", body: { confirm } });
