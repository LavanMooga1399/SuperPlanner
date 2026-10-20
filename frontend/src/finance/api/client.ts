/**
 * Typed wrappers for every endpoint of FINANCE.md 18.2 (`/api/v1/finance/...`).
 * `src/api/client.ts` keeps `raw`/`request` private, so this module has its own `finRaw`/`finRequest`
 * with the same A.14 error-envelope parsing, importing only exported names [R21].
 */
import { API_BASE, ApiError, looksLikeProxyFailure, networkError } from "../../api/client";
import { authFetch } from "../../auth/authFetch";
import type {
  FinanceCancelResponse,
  FinanceComparison,
  FinanceDefaults,
  FinanceExportFile,
  FinanceInstantiateRequest,
  FinanceListResponse,
  FinancePlan,
  FinancePlanInput,
  FinancePlanRecord,
  FinancePlanSummary,
  FinancePreviewResponse,
  FinanceResultKind,
  FinanceResultRecord,
  FinanceResultSummary,
  FinanceRun,
  FinanceRunCreated,
  FinanceRunRequest,
  FinanceTemplateInfo,
  FinanceValidateResponse,
  FinRunEvent,
  SendToPlannerRequest,
  SendToPlannerResponse,
  WhatIfRequest,
} from "./types";

interface FinRequestOptions {
  method?: string;
  body?: unknown;
  headers?: Record<string, string>;
  signal?: AbortSignal;
}

export interface FinRawResponse<T> {
  data: T;
  headers: Headers;
  status: number;
}

function envelopeOf(x: unknown): { code: string; message: string; details?: Record<string, unknown> } | null {
  if (typeof x !== "object" || x === null || !("error" in x)) return null;
  const e = (x as { error: unknown }).error;
  if (typeof e !== "object" || e === null || !("code" in e)) return null;
  return e as { code: string; message: string; details?: Record<string, unknown> };
}

export async function finRaw<T>(path: string, opts: FinRequestOptions = {}): Promise<FinRawResponse<T>> {
  const headers: Record<string, string> = { Accept: "application/json", ...(opts.headers ?? {}) };
  let body: BodyInit | undefined;
  if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.body);
  }
  let res: Response;
  try {
    res = await authFetch(API_BASE + path, { method: opts.method ?? "GET", headers, body, signal: opts.signal });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    throw networkError();
  }
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
  if (!res.ok) {
    const env = envelopeOf(parsed);
    if (env) throw new ApiError(res.status, env.code, env.message, env.details ?? {});
    if (looksLikeProxyFailure(res.status, text)) throw networkError(res.status);
    const detail =
      typeof parsed === "object" && parsed !== null && "detail" in parsed
        ? String((parsed as { detail: unknown }).detail)
        : res.statusText || "Request failed";
    throw new ApiError(res.status, `HTTP_${res.status}`, detail);
  }
  return { data: parsed as T, headers: res.headers, status: res.status };
}

export async function finRequest<T>(path: string, opts: FinRequestOptions = {}): Promise<T> {
  return (await finRaw<T>(path, opts)).data;
}

const enc = encodeURIComponent;
const F = "/finance";

// ---------------------------------------------------------------- defaults and templates
export const getFinanceDefaults = (signal?: AbortSignal) => finRequest<FinanceDefaults>(`${F}/defaults`, { signal });

export const listFinanceTemplates = (signal?: AbortSignal) =>
  finRequest<FinanceListResponse<FinanceTemplateInfo>>(`${F}/templates`, { signal });

export const instantiateFinanceTemplate = (templateId: string, body: FinanceInstantiateRequest) =>
  finRequest<FinancePlanRecord>(`${F}/templates/${enc(templateId)}/instantiate`, { method: "POST", body });

// ---------------------------------------------------------------- plans
export const listFinancePlans = (signal?: AbortSignal) =>
  finRequest<FinanceListResponse<FinancePlanSummary>>(`${F}/plans`, { signal });

export const createFinancePlan = (plan: FinancePlanInput) =>
  finRequest<FinancePlanRecord>(`${F}/plans`, { method: "POST", body: plan });

export const getFinancePlan = (id: string, signal?: AbortSignal) =>
  finRequest<FinancePlanRecord>(`${F}/plans/${enc(id)}`, { signal });

/** Full replacement with optimistic concurrency (`If-Match: "<version>"`). */
export const updateFinancePlan = (id: string, plan: FinancePlan, version: number) =>
  finRequest<FinancePlanRecord>(`${F}/plans/${enc(id)}`, {
    method: "PUT",
    body: plan,
    headers: { "If-Match": `"${version}"` },
  });

export const deleteFinancePlan = (id: string) => finRequest<void>(`${F}/plans/${enc(id)}`, { method: "DELETE" });

export const exportFinancePlan = (id: string) => finRequest<FinanceExportFile>(`${F}/plans/${enc(id)}/export`);

export const importFinancePlan = (file: FinanceExportFile) =>
  finRequest<FinancePlanRecord>(`${F}/plans/import`, { method: "POST", body: file });

export const previewFinancePlan = (plan: FinancePlan | FinancePlanInput, signal?: AbortSignal) =>
  finRequest<FinancePreviewResponse>(`${F}/preview`, { method: "POST", body: plan, signal });

export const validateFinancePlan = (id: string, signal?: AbortSignal) =>
  finRequest<FinanceValidateResponse>(`${F}/plans/${enc(id)}/validate`, { method: "POST", signal });

// ---------------------------------------------------------------- runs
export const createFinanceRun = (planId: string, body: FinanceRunRequest = {}) =>
  finRequest<FinanceRunCreated>(`${F}/plans/${enc(planId)}/runs`, { method: "POST", body });

export const createWhatIfRun = (planId: string, body: WhatIfRequest) =>
  finRequest<FinanceRunCreated>(`${F}/plans/${enc(planId)}/what-if`, { method: "POST", body });

export const listFinanceRuns = (planId: string, signal?: AbortSignal) =>
  finRequest<FinanceListResponse<FinanceRun>>(`${F}/plans/${enc(planId)}/runs`, { signal });

export const getFinanceRun = (runId: string, signal?: AbortSignal) =>
  finRequest<FinanceRun>(`${F}/runs/${enc(runId)}`, { signal });

export const cancelFinanceRun = (runId: string) =>
  finRequest<FinanceCancelResponse>(`${F}/runs/${enc(runId)}/cancel`, { method: "POST" });

/** Non-streaming event list; resolves `{items: []}` for a 204 (finished run, nothing new). */
export async function listFinanceRunEvents(runId: string, after = 0): Promise<FinanceListResponse<FinRunEvent>> {
  const data = await finRequest<FinanceListResponse<FinRunEvent> | undefined>(
    `${F}/runs/${enc(runId)}/events?stream=false&after=${after}`,
  );
  return data ?? { items: [] };
}

export const financeRunEventsUrl = (runId: string) => `${API_BASE}${F}/runs/${enc(runId)}/events`;

// ---------------------------------------------------------------- results
export const listFinanceResults = (planId: string, kind?: FinanceResultKind, signal?: AbortSignal) =>
  finRequest<FinanceListResponse<FinanceResultSummary>>(
    `${F}/plans/${enc(planId)}/results${kind ? `?kind=${kind}` : ""}`,
    { signal },
  );

export const compareFinanceResults = (a: string, b: string, signal?: AbortSignal) =>
  finRequest<FinanceComparison>(`${F}/results/compare?a=${enc(a)}&b=${enc(b)}`, { signal });

export const getFinanceResult = (rid: string, signal?: AbortSignal) =>
  finRequest<FinanceResultRecord>(`${F}/results/${enc(rid)}`, { signal });

export const contributionsCsvUrl = (rid: string) => `${API_BASE}${F}/results/${enc(rid)}/contributions.csv`;

export const sendToPlanner = (rid: string, body: SendToPlannerRequest) =>
  finRequest<SendToPlannerResponse>(`${F}/results/${enc(rid)}/send-to-planner`, { method: "POST", body });
