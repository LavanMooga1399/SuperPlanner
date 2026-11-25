/**
 * M8 calls (docs/M8-DESIGN.md 11, `/api/v1/mfg`, `router_m8.py`): forecasting F1-F17, safety stock I1-I4, item
 * planning and packaging I5-I7, line rates and changeover matrix R1-R3, rate engine R4-R9, sterilisation S1-S7
 * (release is always signed: M7 policy `ster_load.release`), kanban K1-K6, planning settings N1-N2, validation V1-V4,
 * SAP settings X1-X2. Writes carry If-Match where the route takes it; regulated changes carry the Part 11 reason.
 */
import { mfgDownload, mfgRequest, type QueryParams } from "./client";
import { reasonHeaders, signedAction } from "./clientM7";
import type { SignatureInput } from "./typesM7";
import type {
  AccuracyGroup,
  AccuracyReport,
  Baseline,
  BaselineDiff,
  Bucket,
  ChangeoverMatrix,
  ForecastItemView,
  ForecastLine,
  ForecastLinesQuery,
  ForecastOverride,
  ForecastParams,
  ForecastRun,
  ForecastRunDetail,
  ForecastVersion,
  HistoryRecord,
  HistoryRefreshResult,
  HistoryUpdate,
  ItemPackaging,
  ItemPlanning,
  ItemPlanningInput,
  KanbanCard,
  KanbanLoop,
  KanbanLoopInput,
  KanbanScanResult,
  LineRates,
  M8Page,
  NightlyRunResult,
  OverrideInput,
  PackagingLevelInput,
  PlanningSettings,
  PlanningSettingsInput,
  RateBlock,
  RateCompare,
  RateGrid,
  RateParams,
  RatePublishResult,
  RateRun,
  SapEntity,
  SapSettings,
  SapSettingsInput,
  SapSyncResult,
  SsDecideInput,
  SsDecideResult,
  SsLine,
  SsParams,
  SsRun,
  SterAdvanceTo,
  SterLoad,
  SterPlanInput,
  SterPlanResult,
  TraceMatrix,
  VersionInput,
} from "./typesM8";

const enc = encodeURIComponent;
type Q = Record<string, string | number | boolean | null | undefined>;
const q = (x: Q) => x as QueryParams;

// ---------------------------------------------------------------- F1-F3 history
export const listHistory = (query: { item_id: string; bucket?: Bucket; limit?: number }, signal?: AbortSignal) =>
  mfgRequest<M8Page<HistoryRecord>>("/forecast/history", { query, signal });
export const updateHistory = (id: string, body: HistoryUpdate) =>
  mfgRequest<HistoryRecord>(`/forecast/history/${enc(id)}`, { method: "PUT", body, headers: reasonHeaders(body.reason) });
export const refreshHistory = () => mfgRequest<HistoryRefreshResult>("/forecast/history/refresh", { method: "POST", body: {} });

// ---------------------------------------------------------------- F4-F6 runs
export const listForecastRuns = (query: Q = {}, signal?: AbortSignal) => mfgRequest<M8Page<ForecastRun>>("/forecast/runs", { query: q(query), signal });
export const createForecastRun = (body: ForecastParams) => mfgRequest<ForecastRun>("/forecast/runs", { method: "POST", body });
export const getForecastRun = (id: string, query: Q = {}, signal?: AbortSignal) => mfgRequest<ForecastRunDetail>(`/forecast/runs/${enc(id)}`, { query: q(query), signal });

// ---------------------------------------------------------------- F7-F15 versions, lines, overrides
const V = "/forecast/versions";
export const listVersions = (query: Q = {}, signal?: AbortSignal) => mfgRequest<M8Page<ForecastVersion>>(V, { query: q(query), signal });
export const createVersion = (body: VersionInput) => mfgRequest<ForecastVersion>(V, { method: "POST", body });
export const getVersion = (id: string, signal?: AbortSignal) => mfgRequest<ForecastVersion>(`${V}/${enc(id)}`, { signal });
export const getVersionLines = (id: string, query: ForecastLinesQuery, signal?: AbortSignal) =>
  mfgRequest<M8Page<ForecastLine>>(`${V}/${enc(id)}/lines`, { query: q(query as Q), signal });
export const activateVersion = (id: string, version: number, reason?: string | null) =>
  mfgRequest<ForecastVersion>(`${V}/${enc(id)}/activate`, { method: "POST", body: {}, headers: reasonHeaders(reason, version) });
export const deleteVersion = (id: string, version: number) => mfgRequest<void>(`${V}/${enc(id)}`, { method: "DELETE", headers: reasonHeaders(null, version) });
export const listOverrides = (versionId: string, signal?: AbortSignal) => mfgRequest<{ items: ForecastOverride[] }>(`${V}/${enc(versionId)}/overrides`, { signal });
export const createOverride = (versionId: string, body: OverrideInput) =>
  mfgRequest<ForecastOverride>(`${V}/${enc(versionId)}/overrides`, { method: "POST", body, headers: reasonHeaders(body.reason) });
export const removeOverride = (id: string, reason: string) => mfgRequest<ForecastOverride>(`/forecast/overrides/${enc(id)}`, { method: "DELETE", headers: reasonHeaders(reason) });

// ---------------------------------------------------------------- F16-F17
export const getForecastItem = (itemId: string, query: { version_id?: string } = {}, signal?: AbortSignal) =>
  mfgRequest<ForecastItemView>(`/forecast/items/${enc(itemId)}`, { query, signal });
export const getAccuracy = (query: { lag: 1 | 3; group_by: AccuracyGroup; periods?: number }, signal?: AbortSignal) =>
  mfgRequest<AccuracyReport>("/forecast/accuracy", { query, signal });

// ---------------------------------------------------------------- I1-I4 safety stock
export const listSsRuns = (query: Q = {}, signal?: AbortSignal) => mfgRequest<M8Page<SsRun>>("/invopt/runs", { query: q(query), signal });
export const createSsRun = (body: SsParams = {}) => mfgRequest<SsRun>("/invopt/runs", { method: "POST", body });
export const getSsRun = (id: string, signal?: AbortSignal) => mfgRequest<SsRun>(`/invopt/runs/${enc(id)}`, { signal });
export const listSsLines = (runId: string, query: Q = {}, signal?: AbortSignal) => mfgRequest<M8Page<SsLine>>(`/invopt/runs/${enc(runId)}/lines`, { query: q(query), signal });
export const decideSs = (runId: string, body: SsDecideInput) =>
  mfgRequest<SsDecideResult>(`/invopt/runs/${enc(runId)}/decide`, { method: "POST", body, headers: reasonHeaders(body.reason) });

// ---------------------------------------------------------------- I5-I7 item planning and packaging, R1-R3
export const getItemPlanning = (itemId: string, signal?: AbortSignal) => mfgRequest<ItemPlanning>(`/items/${enc(itemId)}/planning`, { signal });
export const updateItemPlanning = (itemId: string, body: ItemPlanningInput, version: number, reason?: string | null) =>
  mfgRequest<ItemPlanning>(`/items/${enc(itemId)}/planning`, { method: "PUT", body, headers: reasonHeaders(reason, version) });
export const getItemPackaging = (itemId: string, signal?: AbortSignal) => mfgRequest<ItemPackaging>(`/items/${enc(itemId)}/packaging`, { signal });
export const updateItemPackaging = (itemId: string, levels: PackagingLevelInput[], version: number, reason?: string | null) =>
  mfgRequest<ItemPackaging>(`/items/${enc(itemId)}/packaging`, { method: "PUT", body: { levels }, headers: reasonHeaders(reason, version) });
export const getLineRates = (lineId: string, signal?: AbortSignal) => mfgRequest<LineRates>(`/lines/${enc(lineId)}/rates`, { signal });
export const getChangeoverMatrix = (query: { line_setup_family?: string } = {}, signal?: AbortSignal) => mfgRequest<ChangeoverMatrix>("/changeover-matrix", { query, signal });

// ---------------------------------------------------------------- R4-R9 rate engine
const R = "/rate/runs";
export const listRateRuns = (query: Q = {}, signal?: AbortSignal) => mfgRequest<M8Page<RateRun>>(R, { query: q(query), signal });
export const createRateRun = (body: RateParams) => mfgRequest<RateRun>(R, { method: "POST", body });
export const getRateRun = (id: string, signal?: AbortSignal) => mfgRequest<RateRun>(`${R}/${enc(id)}`, { signal });
export const getRateBlocks = (id: string, query: { line_id?: string; from?: string; to?: string; limit?: number } = {}, signal?: AbortSignal) =>
  mfgRequest<M8Page<RateBlock>>(`${R}/${enc(id)}/blocks`, { query, signal });
export const getRateGrid = (id: string, bucket: "shift" | "day", signal?: AbortSignal) => mfgRequest<RateGrid>(`${R}/${enc(id)}/grid`, { query: { bucket }, signal });
export const publishRateRun = (id: string, reason?: string | null) => mfgRequest<RatePublishResult>(`${R}/${enc(id)}/publish`, { method: "POST", body: {}, headers: reasonHeaders(reason) });
export const compareRateRuns = (a: string, b: string, signal?: AbortSignal) => mfgRequest<RateCompare>("/rate/compare", { query: { a, b }, signal });

// ---------------------------------------------------------------- S1-S7 sterilisation
const SL = "/ster/loads";
export const planSterLoads = (body: SterPlanInput = {}) => mfgRequest<SterPlanResult>("/ster/plan", { method: "POST", body });
export const listSterLoads = (query: { status?: string; from?: string; to?: string; chamber_line_id?: string; limit?: number; offset?: number } = {}, signal?: AbortSignal) =>
  mfgRequest<M8Page<SterLoad>>(SL, { query, signal });
export const getSterLoad = (id: string, signal?: AbortSignal) => mfgRequest<SterLoad>(`${SL}/${enc(id)}`, { signal });
export const loadSterLoad = (l: SterLoad) => mfgRequest<SterLoad>(`${SL}/${enc(l.id)}/load`, { method: "POST", body: {}, headers: reasonHeaders(null, l.row_version) });
export const advanceSterLoad = (l: SterLoad, to: SterAdvanceTo) => mfgRequest<SterLoad>(`${SL}/${enc(l.id)}/advance`, { method: "POST", body: { to }, headers: reasonHeaders(null, l.row_version) });
/** S6: signed QA release (M7 policy `ster_load.release`, always signed); 202 = a step signed, the next one pending. */
export const releaseSterLoad = (l: SterLoad, signature: SignatureInput | null, note: string) =>
  signedAction<SterLoad>(`${SL}/${enc(l.id)}/release`, { note }, { version: l.row_version, signature, reason: note });
export const failSterLoad = (l: SterLoad, reason: string) =>
  mfgRequest<SterLoad>(`${SL}/${enc(l.id)}/fail`, { method: "POST", body: { reason }, headers: reasonHeaders(reason, l.row_version) });

// ---------------------------------------------------------------- K1-K6 kanban
const K = "/kanban/loops";
export const listKanbanLoops = (query: Q = {}, signal?: AbortSignal) => mfgRequest<M8Page<KanbanLoop>>(K, { query: q(query), signal });
export const createKanbanLoop = (body: KanbanLoopInput) => mfgRequest<KanbanLoop>(K, { method: "POST", body });
export const getKanbanLoop = (id: string, signal?: AbortSignal) => mfgRequest<KanbanLoop>(`${K}/${enc(id)}`, { signal });
export const updateKanbanLoop = (id: string, body: KanbanLoopInput, version: number, reason?: string | null) =>
  mfgRequest<KanbanLoop>(`${K}/${enc(id)}`, { method: "PUT", body, headers: reasonHeaders(reason, version) });
export const listKanbanCards = (id: string, signal?: AbortSignal) => mfgRequest<{ items: KanbanCard[] }>(`${K}/${enc(id)}/cards`, { signal });
export const scanKanban = (code: string) => mfgRequest<KanbanScanResult>("/kanban/scan", { method: "POST", body: { code } });

// ---------------------------------------------------------------- N1-N2 planning settings
export const getPlanningSettings = (signal?: AbortSignal) => mfgRequest<PlanningSettings>("/plant/planning-settings", { signal });
export const updatePlanningSettings = (body: PlanningSettingsInput, version: number, reason?: string | null) =>
  mfgRequest<PlanningSettings>("/plant/planning-settings", { method: "PUT", body, headers: reasonHeaders(reason, version) });
export const runNightlyNow = () => mfgRequest<NightlyRunResult>("/planning/nightly/run-now", { method: "POST", body: {} });

// ---------------------------------------------------------------- V1-V4 validation kit
export const getTraceMatrix = (signal?: AbortSignal) => mfgRequest<TraceMatrix>("/validation/trace-matrix", { signal });
export const downloadTraceMatrix = (format: "csv" | "html") => mfgDownload("/validation/trace-matrix", { format }, `trace-matrix.${format}`);
export const listBaselines = (signal?: AbortSignal) => mfgRequest<M8Page<Baseline>>("/validation/baselines", { query: { limit: 200 }, signal });
export const createBaseline = (label: string) => mfgRequest<Baseline>("/validation/baselines", { method: "POST", body: { label } });
export const diffBaselines = (a: string, b: string, signal?: AbortSignal) => mfgRequest<BaselineDiff>(`/validation/baselines/${enc(a)}/diff/${enc(b)}`, { signal });

// ---------------------------------------------------------------- X1-X2 SAP S/4HANA
export const getSapSettings = (signal?: AbortSignal) => mfgRequest<SapSettings>("/integration/sap-settings", { signal });
export const updateSapSettings = (body: SapSettingsInput, version: number, reason?: string | null) =>
  mfgRequest<SapSettings>("/integration/sap-settings", { method: "PUT", body, headers: reasonHeaders(reason, version) });
export const syncSap = (entities: SapEntity[], full = false) => mfgRequest<SapSyncResult>("/integration/sap/sync", { method: "POST", body: { entities, full } });
