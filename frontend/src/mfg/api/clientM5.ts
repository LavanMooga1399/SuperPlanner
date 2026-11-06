/** M5 calls (docs/M5-DESIGN.md 9): tokens, orgs, integration, trace/recall, ECO, transfers, audit. */
import { ifMatch, mfgDownload, mfgRaw, mfgRequest, v1Download, v1Request } from "./client";
import type { Page } from "./types";
import type {
  ApiToken,
  AuditEvent,
  AuditVerify,
  Batch,
  BatchDetail,
  ChangeRequest,
  CrInput,
  CrItemInput,
  Delivery,
  EcoImpact,
  Endpoint,
  EndpointInput,
  EventPage,
  FiledropStatus,
  IntegrationSettings,
  MappingProfile,
  Org,
  OrgMember,
  OrgOverview,
  OrgPlant,
  OrgRole,
  PlantRoleGrant,
  PublishJob,
  PublishRequest,
  QuarantineResult,
  Recall,
  RecallSource,
  Reconciliation,
  TokenCreate,
  TokenCreated,
  TraceKind,
  TraceResponse,
  TransferInput,
  TransferOrder,
  ValueMap,
  WhereUsedResponse,
} from "./typesM5";

const enc = encodeURIComponent;

// ---------------------------------------------------------------- 3.3 tokens (/api/v1/tokens)
export const listTokens = (query: { kind?: "personal" | "plant" } = {}, signal?: AbortSignal) => v1Request<{ items: ApiToken[] }>("/tokens", { query: { ...query }, signal });
export const createToken = (body: TokenCreate) => v1Request<TokenCreated>("/tokens", { method: "POST", body });
export const revokeToken = (id: string) => v1Request<void>(`/tokens/${enc(id)}`, { method: "DELETE" });

// ---------------------------------------------------------------- 3.4 orgs (/api/v1/orgs)
export const listOrgs = (signal?: AbortSignal) => v1Request<{ items: Org[] }>("/orgs", { signal });
export const createOrg = (body: { name: string; slug: string }) => v1Request<Org>("/orgs", { method: "POST", body });
export const acceptOrgInvite = (org: string) => v1Request<Org>(`/orgs/${enc(org)}/accept`, { method: "POST", body: {} });
export const getOrg = (org: string, signal?: AbortSignal) => v1Request<Org>(`/orgs/${enc(org)}`, { signal });
export const updateOrg = (org: string, body: { name: string; require_2fa: boolean }, version?: number) =>
  v1Request<Org>(`/orgs/${enc(org)}`, { method: "PUT", body, headers: version !== undefined ? ifMatch(version) : undefined });
export const listOrgMembers = (org: string, signal?: AbortSignal) => v1Request<{ items: OrgMember[] }>(`/orgs/${enc(org)}/members`, { signal });
export const addOrgMember = (org: string, body: { email: string; org_role: OrgRole }) => v1Request<OrgMember>(`/orgs/${enc(org)}/members`, { method: "POST", body });
export const updateOrgMember = (org: string, id: string, body: { org_role: OrgRole }) =>
  v1Request<OrgMember>(`/orgs/${enc(org)}/members/${enc(id)}`, { method: "PUT", body });
export const removeOrgMember = (org: string, id: string) => v1Request<void>(`/orgs/${enc(org)}/members/${enc(id)}`, { method: "DELETE" });
export const listOrgPlants = (org: string, signal?: AbortSignal) => v1Request<{ items: OrgPlant[] }>(`/orgs/${enc(org)}/plants`, { signal });
export const createOrgPlant = (org: string, body: { code: string; name: string; utc_offset?: string; time_zone?: string | null }) => v1Request<OrgPlant>(`/orgs/${enc(org)}/plants`, { method: "POST", body });
export const updateOrgPlant = (org: string, plant: string, body: { name: string }) =>
  v1Request<OrgPlant>(`/orgs/${enc(org)}/plants/${enc(plant)}`, { method: "PUT", body });
export const grantPlantRoles = (org: string, plant: string, body: PlantRoleGrant) =>
  v1Request<unknown>(`/orgs/${enc(org)}/plants/${enc(plant)}/roles`, { method: "POST", body });
export const publishMaster = (org: string, body: PublishRequest) => v1Request<PublishJob>(`/orgs/${enc(org)}/publish`, { method: "POST", body });
export const getOrgOverview = (org: string, signal?: AbortSignal) => v1Request<OrgOverview>(`/orgs/${enc(org)}/overview`, { signal });

// ---------------------------------------------------------------- 4 integration (/api/v1/integration)
const I = "/integration";
export const getIntegrationSettings = (signal?: AbortSignal) => v1Request<IntegrationSettings>(`${I}/settings`, { signal });
export const updateIntegrationSettings = (body: Omit<IntegrationSettings, "row_version" | "adapters">, version: number) =>
  v1Request<IntegrationSettings>(`${I}/settings`, { method: "PUT", body, headers: ifMatch(version) });
export const listEndpoints = (signal?: AbortSignal) => v1Request<{ items: Endpoint[] }>(`${I}/endpoints`, { signal });
export const createEndpoint = (body: EndpointInput) => v1Request<Endpoint>(`${I}/endpoints`, { method: "POST", body });
export const updateEndpoint = (id: string, body: EndpointInput, version: number) => v1Request<Endpoint>(`${I}/endpoints/${enc(id)}`, { method: "PUT", body, headers: ifMatch(version) });
export const deleteEndpoint = (id: string, version: number) => v1Request<void>(`${I}/endpoints/${enc(id)}`, { method: "DELETE", headers: ifMatch(version) });
/** delivers what is waiting for this endpoint now (no synthetic test event) */
export const testEndpoint = (id: string) => v1Request<Record<string, unknown>>(`${I}/endpoints/${enc(id)}/test`, { method: "POST", body: {} });
export const getValueMaps = (signal?: AbortSignal) => v1Request<{ rows: ValueMap[] }>(`${I}/value-maps`, { signal });
export const putValueMaps = (rows: ValueMap[]) => v1Request<{ rows: ValueMap[] }>(`${I}/value-maps`, { method: "PUT", body: { rows } });
export const listBatches = (query: { status?: string; source?: string; limit?: number; offset?: number }, signal?: AbortSignal) =>
  v1Request<Page<Batch>>(`${I}/batches`, { query: { ...query }, signal });
export const getBatch = (id: string, signal?: AbortSignal) => v1Request<BatchDetail>(`${I}/batches/${enc(id)}`, { signal });
export const listEvents = (query: { after?: number; limit?: number; types?: string }, signal?: AbortSignal) => v1Request<EventPage>(`${I}/events`, { query: { ...query }, signal });
export const listDeliveries = (query: { status?: string; endpoint_id?: string; limit?: number; offset?: number }, signal?: AbortSignal) =>
  v1Request<Page<Delivery>>(`${I}/deliveries`, { query: { ...query }, signal });
export const retryDelivery = (id: string) => v1Request<Delivery>(`${I}/deliveries/${enc(id)}/retry`, { method: "POST", body: {} });
export const listMappingProfiles = (signal?: AbortSignal) => v1Request<{ items: MappingProfile[] }>(`${I}/mapping-profiles`, { signal });
export const getFiledropStatus = (signal?: AbortSignal) => v1Request<FiledropStatus>(`${I}/filedrop/status`, { signal });
export const startReconciliation = (body: { entities: string[]; snapshot: "inline" | "file" | "adapter"; records?: Record<string, unknown[]> }) =>
  v1Request<Reconciliation>(`${I}/reconciliations`, { method: "POST", body });
export const listReconciliations = (signal?: AbortSignal) => v1Request<Page<Reconciliation>>(`${I}/reconciliations`, { signal });
export const getReconciliation = (id: string, signal?: AbortSignal) => v1Request<Reconciliation>(`${I}/reconciliations/${enc(id)}`, { signal });
export const exportReconciliation = (id: string) => v1Download(`${I}/reconciliations/${enc(id)}/export`, undefined, `reconciliation-${id}.xlsx`);

// ---------------------------------------------------------------- 6 trace and recall (/api/v1/mfg)
export const getTrace = (query: { kind: TraceKind; id: string; direction: "backward" | "forward"; depth?: number; include_possible?: boolean }, signal?: AbortSignal) =>
  mfgRequest<TraceResponse>("/trace", { query: { ...query }, signal });
export const getWhereUsed = (query: { item_id: string; lot_code?: string; supplier_lot?: string }, signal?: AbortSignal) =>
  mfgRequest<WhereUsedResponse>("/trace/where-used", { query: { ...query }, signal });
export const createRecall = (body: { name: string; sources: RecallSource[]; include_possible: boolean }) => mfgRequest<Recall>("/recalls", { method: "POST", body });
export const listRecalls = (query: { limit?: number; offset?: number } = {}, signal?: AbortSignal) => mfgRequest<Page<Recall>>("/recalls", { query: { ...query }, signal });
export const getRecall = (id: string, signal?: AbortSignal) => mfgRequest<Recall>(`/recalls/${enc(id)}`, { signal });
export const exportRecall = (id: string) => mfgDownload(`/recalls/${enc(id)}/export`, undefined, `recall-${id}.xlsx`);
export const quarantineRecall = (id: string, body: { location_id: string; lot_ids?: string[] }) =>
  mfgRequest<QuarantineResult>(`/recalls/${enc(id)}/quarantine`, { method: "POST", body, headers: { "Idempotency-Key": `rcl-q-${id}-${Date.now()}` } });

// ---------------------------------------------------------------- 5 ECO
export const listEcos = (query: { status?: string; q?: string; limit?: number; offset?: number } = {}, signal?: AbortSignal) => mfgRequest<Page<ChangeRequest>>("/eco", { query: { ...query }, signal });
export const createEco = (body: CrInput) => mfgRequest<ChangeRequest>("/eco", { method: "POST", body });
export const getEco = (id: string, signal?: AbortSignal) => mfgRequest<ChangeRequest>(`/eco/${enc(id)}`, { signal });
export const updateEco = (id: string, body: CrInput, version: number) => mfgRequest<ChangeRequest>(`/eco/${enc(id)}`, { method: "PUT", body, headers: ifMatch(version) });
export const deleteEco = (id: string, version: number) => mfgRequest<void>(`/eco/${enc(id)}`, { method: "DELETE", headers: ifMatch(version) });
export const addEcoItem = (id: string, body: CrItemInput) => mfgRequest<ChangeRequest>(`/eco/${enc(id)}/items`, { method: "POST", body });
export const removeEcoItem = (id: string, itemId: string) => mfgRequest<ChangeRequest>(`/eco/${enc(id)}/items/${enc(itemId)}`, { method: "DELETE" });
export const getEcoImpact = (id: string, signal?: AbortSignal) => mfgRequest<EcoImpact>(`/eco/${enc(id)}/impact`, { signal });
export const ecoAction = (id: string, action: "submit" | "approve" | "reject" | "cancel" | "implement", version: number, body: { note?: string } = {}) =>
  mfgRequest<ChangeRequest>(`/eco/${enc(id)}/${action}`, { method: "POST", body, headers: ifMatch(version) });

// ---------------------------------------------------------------- 3.5 transfers
export const listTransfers = (query: { status?: string; direction?: string; limit?: number; offset?: number } = {}, signal?: AbortSignal) =>
  mfgRequest<Page<TransferOrder>>("/transfer-orders", { query: { ...query }, signal });
export const createTransfer = (body: TransferInput) => mfgRequest<TransferOrder>("/transfer-orders", { method: "POST", body });
export const getTransfer = (id: string, signal?: AbortSignal) => mfgRequest<TransferOrder>(`/transfer-orders/${enc(id)}`, { signal });
export const updateTransfer = (id: string, body: TransferInput, version: number) => mfgRequest<TransferOrder>(`/transfer-orders/${enc(id)}`, { method: "PUT", body, headers: ifMatch(version) });
export const deleteTransfer = (id: string, version: number) => mfgRequest<void>(`/transfer-orders/${enc(id)}`, { method: "DELETE", headers: ifMatch(version) });
export const transferAction = (id: string, action: "open" | "close" | "cancel", version: number) =>
  mfgRequest<TransferOrder>(`/transfer-orders/${enc(id)}/${action}`, { method: "POST", body: {}, headers: ifMatch(version) });
/** ship / receive = M2 postings with `transfer_line_id` per line (3.5) */
export const postTransferMovement = (type: "transfer_ship" | "transfer_receipt", lines: { item_id: string; location_id: string; qty: number; lot_code?: string | null; transfer_line_id: string }[], key: string) =>
  mfgRaw<unknown>("/inventory/postings", { method: "POST", body: { type, lines }, headers: { "Idempotency-Key": key } });

// ---------------------------------------------------------------- 7 audit (/api/v1/audit)
export const listAudit = (query: { from?: string; to?: string; entity_type?: string; actor?: string; limit?: number; offset?: number }, signal?: AbortSignal) =>
  v1Request<Page<AuditEvent>>("/audit/events", { query: { ...query }, signal });
export const exportAudit = (query: { format: "jsonl" | "csv"; from?: string; to?: string }) => v1Download("/audit/export", { ...query }, `audit.${query.format}`);
/** requested (15.WP-U): the chain check of `manage.py audit-verify` as an endpoint */
export const verifyAudit = (query: { from?: string; to?: string } = {}) => v1Request<AuditVerify>("/audit/verify", { query: { ...query } });
