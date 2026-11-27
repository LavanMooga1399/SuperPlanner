/**
 * M9 calls (docs/M9-DESIGN.md 9, `/api/v1/mfg`, `router_m9.py`): network N1-N16 and S&OP S1-S23 and trade T1-T8
 * answer only in the network workspace; P1-P5 are plant routes. S&OP approval is always signed (M7 policy
 * `sop_cycle.approve`, two steps). Regulated writes carry the Part 11 change reason.
 */
import { ifMatch, mfgDownload, mfgRequest, v1Request, type QueryParams } from "./client";
import { reasonHeaders, signedAction } from "./clientM7";
import type { SignatureInput } from "./typesM7";
import type {
  BulkResult,
  CountryRiskInput,
  FxRate,
  FxRateInput,
  ItemTrade,
  ItemTradeInput,
  LandedRow,
  LotContent,
  M9List,
  M9Page,
  Milestone,
  MilestoneInput,
  MpsTarget,
  NetGrid,
  NetLane,
  NetLaneInput,
  NetNodeInfo,
  NetParams,
  NetPegging,
  NetPublishResult,
  NetRun,
  NetShortage,
  NetTransfer,
  NetUtilisation,
  NetworkCreated,
  RampCurve,
  RiskRow,
  SopAspInput,
  SopCompare,
  SopCycle,
  SopDemand,
  SopFinancial,
  SopMakeBuyRow,
  SopOverride,
  SopOverrideInput,
  SopPlan,
  SopRoughCut,
  SopScenario,
  SopScenarioInput,
  SourcingResolve,
  SourcingRule,
  SourcingRuleInput,
  TariffRate,
  TariffRateInput,
  TradeReport,
  TradeReportParams,
} from "./typesM9";

const enc = encodeURIComponent;
type Q = Record<string, string | number | boolean | null | undefined>;
const q = (x: Q) => x as QueryParams;

// ---------------------------------------------------------------- O1
export const createNetwork = (org: string) => v1Request<NetworkCreated>(`/orgs/${enc(org)}/network`, { method: "POST", body: {} });

// ---------------------------------------------------------------- N1-N7, N16 topology
export const listNodes = (signal?: AbortSignal) => mfgRequest<M9List<NetNodeInfo>>("/net/nodes", { signal });
export const listLanes = (signal?: AbortSignal) => mfgRequest<M9List<NetLane>>("/net/lanes", { signal });
export const createLane = (body: NetLaneInput) => mfgRequest<NetLane>("/net/lanes", { method: "POST", body });
export const updateLane = (l: NetLane, body: NetLaneInput, reason?: string | null) =>
  mfgRequest<NetLane>(`/net/lanes/${enc(l.id)}`, { method: "PUT", body, headers: reasonHeaders(reason, l.row_version) });
export const deleteLane = (l: NetLane, reason?: string | null) =>
  mfgRequest<void>(`/net/lanes/${enc(l.id)}`, { method: "DELETE", headers: reasonHeaders(reason, l.row_version) });
export const listSourcing = (query: { dest?: string; key?: string; family?: string } = {}, signal?: AbortSignal) =>
  mfgRequest<M9List<SourcingRule>>("/net/sourcing", { query: q(query), signal });
export const createSourcing = (body: SourcingRuleInput) => mfgRequest<SourcingRule>("/net/sourcing", { method: "POST", body });
export const updateSourcing = (r: SourcingRule, body: SourcingRuleInput, reason?: string | null) =>
  mfgRequest<SourcingRule>(`/net/sourcing/${enc(r.id)}`, { method: "PUT", body, headers: reasonHeaders(reason, r.row_version) });
export const deleteSourcing = (r: SourcingRule, reason?: string | null) =>
  mfgRequest<void>(`/net/sourcing/${enc(r.id)}`, { method: "DELETE", headers: reasonHeaders(reason, r.row_version) });
export const resolveSourcing = (query: { dest: string; key: string; date: string }, signal?: AbortSignal) =>
  mfgRequest<SourcingResolve>("/net/sourcing/resolve", { query: q(query), signal });
export const getRampCurves = (signal?: AbortSignal) => mfgRequest<M9List<RampCurve>>("/net/ramp-curves", { signal });
export const putRampCurves = (items: RampCurve[], reason?: string | null) =>
  mfgRequest<M9List<RampCurve>>("/net/ramp-curves", { method: "PUT", body: { items }, headers: reasonHeaders(reason) });

// ---------------------------------------------------------------- N8-N15 runs
export const listNetRuns = (query: Q = {}, signal?: AbortSignal) => mfgRequest<M9Page<NetRun>>("/net/runs", { query: q(query), signal });
export const createNetRun = (body: NetParams) => mfgRequest<NetRun>("/net/runs", { method: "POST", body });
export const getNetRun = (id: string, signal?: AbortSignal) => mfgRequest<NetRun>(`/net/runs/${enc(id)}`, { signal });
export const getNetGrid = (id: string, query: { node?: string; key?: string; family?: string; page?: number }, signal?: AbortSignal) =>
  mfgRequest<NetGrid>(`/net/runs/${enc(id)}/grid`, { query: q(query), signal });
export const getNetTransfers = (id: string, query: { src?: string; dst?: string } = {}, signal?: AbortSignal) =>
  mfgRequest<M9List<NetTransfer>>(`/net/runs/${enc(id)}/transfers`, { query: q(query), signal });
export const getNetShortages = (id: string, signal?: AbortSignal) => mfgRequest<M9List<NetShortage>>(`/net/runs/${enc(id)}/shortages`, { signal });
export const getNetUtilisation = (id: string, signal?: AbortSignal) => mfgRequest<M9List<NetUtilisation>>(`/net/runs/${enc(id)}/utilisation`, { signal });
export const getNetPegging = (id: string, query: { node?: string; key?: string; week?: string; supply_id?: string }, signal?: AbortSignal) =>
  mfgRequest<NetPegging>(`/net/runs/${enc(id)}/pegging`, { query: q(query), signal });
export const publishNetRun = (id: string, reason?: string | null) =>
  mfgRequest<NetPublishResult>(`/net/runs/${enc(id)}/publish`, { method: "POST", body: {}, headers: reasonHeaders(reason) });

// ---------------------------------------------------------------- S1-S10 cycle and demand review
export const listCycles = (query: Q = {}, signal?: AbortSignal) => mfgRequest<M9Page<SopCycle>>("/sop/cycles", { query: q(query), signal });
export const createCycle = (period: string) => mfgRequest<SopCycle>("/sop/cycles", { method: "POST", body: { period } });
export const getCycle = (id: string, signal?: AbortSignal) => mfgRequest<SopCycle>(`/sop/cycles/${enc(id)}`, { signal });
export const advanceCycle = (c: SopCycle, note: string) =>
  mfgRequest<SopCycle>(`/sop/cycles/${enc(c.id)}/advance`, { method: "POST", body: { note }, headers: reasonHeaders(note || null, c.row_version) });
export const reopenCycle = (c: SopCycle, to_step: string, reason: string) =>
  mfgRequest<SopCycle>(`/sop/cycles/${enc(c.id)}/reopen`, { method: "POST", body: { to_step, reason }, headers: reasonHeaders(reason, c.row_version) });
export const cancelCycle = (c: SopCycle, reason: string) =>
  mfgRequest<SopCycle>(`/sop/cycles/${enc(c.id)}/cancel`, { method: "POST", body: { reason }, headers: reasonHeaders(reason, c.row_version) });
export const getDemand = (id: string, query: { node?: string; family?: string } = {}, signal?: AbortSignal) =>
  mfgRequest<SopDemand>(`/sop/cycles/${enc(id)}/demand`, { query: q(query), signal });
export const listOverrides = (id: string, signal?: AbortSignal) => mfgRequest<M9List<SopOverride>>(`/sop/cycles/${enc(id)}/demand/overrides`, { signal });
export const addOverride = (id: string, body: SopOverrideInput) =>
  mfgRequest<SopOverride>(`/sop/cycles/${enc(id)}/demand/overrides`, { method: "POST", body, headers: reasonHeaders(body.reason) });
export const removeOverride = (id: string, reason: string) =>
  mfgRequest<void>(`/sop/demand-overrides/${enc(id)}`, { method: "DELETE", headers: reasonHeaders(reason) });
export const putAsp = (id: string, body: SopAspInput) =>
  mfgRequest<SopDemand>(`/sop/cycles/${enc(id)}/demand/asp`, { method: "PUT", body, headers: reasonHeaders(body.reason) });

// ---------------------------------------------------------------- S11-S21 scenarios
export const listScenarios = (query: { cycle_id?: string } = {}, signal?: AbortSignal) => mfgRequest<M9List<SopScenario>>("/sop/scenarios", { query: q(query), signal });
export const createScenario = (body: SopScenarioInput & { cycle_id: string | null }) => mfgRequest<SopScenario>("/sop/scenarios", { method: "POST", body });
export const getScenario = (id: string, signal?: AbortSignal) => mfgRequest<SopScenario>(`/sop/scenarios/${enc(id)}`, { signal });
export const updateScenario = (s: SopScenario, body: SopScenarioInput) =>
  mfgRequest<SopScenario>(`/sop/scenarios/${enc(s.id)}`, { method: "PUT", body, headers: ifMatch(s.row_version) });
export const deleteScenario = (s: SopScenario) => mfgRequest<void>(`/sop/scenarios/${enc(s.id)}`, { method: "DELETE", headers: ifMatch(s.row_version) });
export const runScenario = (id: string) => mfgRequest<SopScenario>(`/sop/scenarios/${enc(id)}/run`, { method: "POST", body: {} });
export const copyScenario = (id: string, cycle_id: string | null) => mfgRequest<SopScenario>(`/sop/scenarios/${enc(id)}/copy`, { method: "POST", body: { cycle_id } });
export const recommendScenario = (c: SopCycle, scenario_id: string, note: string) =>
  mfgRequest<SopCycle>(`/sop/cycles/${enc(c.id)}/recommend`, { method: "POST", body: { scenario_id, note }, headers: reasonHeaders(note || null, c.row_version) });
export const getScenarioPlan = (id: string, query: { node?: string; family?: string } = {}, signal?: AbortSignal) =>
  mfgRequest<SopPlan>(`/sop/scenarios/${enc(id)}/plan`, { query: q(query), signal });
export const getRoughCut = (id: string, signal?: AbortSignal) => mfgRequest<SopRoughCut>(`/sop/scenarios/${enc(id)}/rough-cut`, { signal });
export const getFinancial = (id: string, group_by: "total" | "node" | "family", signal?: AbortSignal) =>
  mfgRequest<SopFinancial>(`/sop/scenarios/${enc(id)}/financial`, { query: { group_by }, signal });
export const getMakeBuy = (id: string, signal?: AbortSignal) => mfgRequest<M9List<SopMakeBuyRow>>(`/sop/scenarios/${enc(id)}/make-buy`, { signal });
export const compareScenarios = (ids: string[], signal?: AbortSignal) => mfgRequest<SopCompare>("/sop/compare", { query: { ids: ids.join(",") }, signal });

// ---------------------------------------------------------------- S22-S23 approval and publish
export const approveCycle = (c: SopCycle, scenario_id: string, signature: SignatureInput | null, comment: string) =>
  signedAction<SopCycle>(`/sop/cycles/${enc(c.id)}/approve`, { scenario_id }, { version: c.row_version, signature, reason: comment || null });
export const publishCycle = (c: SopCycle, reason?: string | null) =>
  mfgRequest<SopCycle>(`/sop/cycles/${enc(c.id)}/publish`, { method: "POST", body: {}, headers: reasonHeaders(reason, c.row_version) });

// ---------------------------------------------------------------- T1-T8 trade (network)
export const getTariffs = (signal?: AbortSignal) => mfgRequest<M9List<TariffRate>>("/trade/tariffs", { signal });
export const putTariffs = (items: TariffRateInput[], reason?: string | null) =>
  mfgRequest<BulkResult>("/trade/tariffs", { method: "PUT", body: { items }, headers: reasonHeaders(reason) });
export const getFx = (signal?: AbortSignal) => mfgRequest<M9List<FxRate>>("/trade/fx", { signal });
export const putFx = (items: FxRateInput[], reason?: string | null) => mfgRequest<BulkResult>("/trade/fx", { method: "PUT", body: { items }, headers: reasonHeaders(reason) });
export const getMilestones = (signal?: AbortSignal) => mfgRequest<M9List<Milestone>>("/trade/milestones", { signal });
export const putMilestones = (items: MilestoneInput[], reason?: string | null) =>
  mfgRequest<BulkResult>("/trade/milestones", { method: "PUT", body: { items }, headers: reasonHeaders(reason) });
export const getCountryRisk = (signal?: AbortSignal) => mfgRequest<M9List<CountryRiskInput>>("/trade/country-risk", { signal });
export const putCountryRisk = (items: CountryRiskInput[], reason?: string | null) =>
  mfgRequest<BulkResult>("/trade/country-risk", { method: "PUT", body: { items }, headers: reasonHeaders(reason) });
export const listTradeReports = (signal?: AbortSignal) => mfgRequest<M9Page<TradeReport>>("/trade/reports", { signal });
export const createTradeReport = (body: TradeReportParams) => mfgRequest<TradeReport>("/trade/reports", { method: "POST", body });
export const getTradeReport = (id: string, signal?: AbortSignal) => mfgRequest<TradeReport>(`/trade/reports/${enc(id)}`, { signal });
export const downloadTradeReport = (id: string) => mfgDownload(`/trade/reports/${enc(id)}`, { format: "xlsx" }, "tariff-report.xlsx");
export const getNetLotContent = (plant: string, lotId: string, milestone_id?: string, signal?: AbortSignal) =>
  mfgRequest<LotContent>(`/trade/lots/${enc(plant)}/${enc(lotId)}/content`, { query: q({ milestone_id }), signal });
/** T8 (network) and P3 (plant) share the path; the workspace decides the scope. */
export const getRisk = (query: { node?: string; min_score?: number } = {}, signal?: AbortSignal) => mfgRequest<M9List<RiskRow>>("/trade/risk", { query: q(query), signal });

// ---------------------------------------------------------------- P1-P5 plant
export const getItemTrade = (itemId: string, signal?: AbortSignal) => mfgRequest<ItemTrade>(`/items/${enc(itemId)}/trade`, { signal });
export const putItemTrade = (itemId: string, body: ItemTradeInput, version: number, reason?: string | null) =>
  mfgRequest<ItemTrade>(`/items/${enc(itemId)}/trade`, { method: "PUT", body, headers: reasonHeaders(reason, version) });
export const getLanded = (itemId: string, signal?: AbortSignal) => mfgRequest<M9List<LandedRow>>("/trade/landed", { query: { item_id: itemId }, signal });
export const getLotContent = (lotId: string, signal?: AbortSignal) => mfgRequest<LotContent>(`/lots/${enc(lotId)}/content`, { signal });
/** P4b (8.1): regulated correction of a lot's country of origin; the reason is required (body and Part 11 header). */
export const putLotCoo = (lotId: string, coo: string | null, reason: string, version?: number) =>
  mfgRequest<unknown>(`/lots/${enc(lotId)}/coo`, { method: "PUT", body: { coo, reason }, headers: reasonHeaders(reason, version) });
export const getMpsTargets = (query: { family?: string; from?: string; to?: string } = {}, signal?: AbortSignal) =>
  mfgRequest<M9List<MpsTarget>>("/mps/targets", { query: q(query), signal });
