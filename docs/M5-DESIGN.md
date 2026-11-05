# SuperPlanner M5 - Integration and traceability (design + plan + acceptance)

Status: design for build. Phase M5 of `docs/MANUFACTURING-GAP-ANALYSIS.md`. Builds on M1-M4 as built
(`docs/M1-DESIGN.md` .. `docs/M4-DESIGN.md`, cited "M1 n" .. "M4 n", incl. their implementation notes) and the
platform (`docs/ARCHITECTURE.md` 25, `docs/DEPLOY.md`). Their conventions apply unchanged and are not restated.
Interpretations go to section 15 only.

Scope (roadmap): ERP integration in and out; multi-level serial and lot genealogy with recall; engineering change
handling; multi-plant organisations; enterprise sign-in (OIDC SSO, TOTP), API tokens; data retention, archival,
audit export; HA deployment notes.

## 0. Decisions

1. **Vendor-neutral integration first, ERP adapters later.** One versioned contract `superplanner.v1` (JSON records
   keyed by `external_ref` / natural keys) over three transports: **REST batch upsert** (inbound), **file drop**
   (CSV/xlsx/JSON into a per-plant inbox directory, processed through the existing M1 import pipeline with saved
   mappings), and a **transactional outbox** (outbound) readable by **cursor pull** and delivered by **signed
   webhooks** with retries, plus optional periodic **file export**. A Python `ErpAdapter` protocol maps a specific
   ERP's formats to and from `superplanner.v1`; M5 ships `generic_v1` only. No SFTP code: SFTP is provided by the
   infrastructure writing into the mounted inbox/outbox volume.
2. **System of record per entity, field-level.** Per plant, each entity is owned by `erp` or `superplanner`
   (defaults in 4.4). For ERP-owned entities the ERP fields are read-only in SuperPlanner (409 `INT_ERP_OWNED`),
   while planning fields (lot rules, families, setup families, safety stock...) stay SuperPlanner-owned. Inbound
   writes to SuperPlanner-owned data are rejected per record (`INT_SOR_CONFLICT`). Stock: the SuperPlanner ledger is
   the record of movements and sends them out; ERP stock snapshots feed a **reconciliation report**, never a silent
   overwrite (unless stock SoR is set to `erp`, then snapshots post `count` corrections, reason `ERP_SYNC`).
3. **Genealogy from a maintained trace-edge table** (`mfg_trace_edges`), written in the same transaction as every
   relevant posting/floor event (and backfilled once from M2-M4 history): lot/serial -> WO (consumed), WO ->
   lot/serial (produced), serial -> parent serial (M4 exact links), shipment -> demand line, inter-plant transfer.
   Traces are recursive SQL queries with depth and row limits; each edge is marked `exact` (serial captured) or
   `possible` (lot-level: any unit of the WO may contain it). Recall reports list every affected unit, lot, WO,
   location and customer shipment, with precision shown.
4. **ECO workflow on top of M1 versioning**: change requests (`ECR/ECO`) bundle draft BOM/routing versions with a
   target effectivity (date, unit serial, or "use-up" date suggested from MRP projected stock), an impact analysis
   (open WOs, POs, stock to be obsoleted, MRP delta), approval (`eco_approve`), and atomic implementation (M1
   release with supersede). ERP-sourced document changes create an ECO record automatically (`source erp`).
5. **Multi-plant without a new tenant column.** The tenant key stays `owner_id` (M2 0 decision 10 invariant: one
   owner = one plant). M5 adds **organisations** with **plant principals**: a plant of an organisation is owned by a
   non-login user row (`users.kind = plant`); people reach it through the existing M2 workspace mechanism with a new
   `plant_admin` role (owner-equivalent). An existing personal plant joins an organisation by `manage.py
   convert-plant` (reassigns its data to a new plant principal; the person becomes `plant_admin`). This replaces the
   earlier "add `plant_id` to every table" plan: the same isolation with no change to ~90 tables. In scope: orgs,
   plants, users across plants, org admins, master-data publish between plants (bundle export -> import), **inter-plant
   transfer orders** (demand in the source plant's MRP, supply in the destination's, ledger postings both sides,
   lots carried over), an org overview. Out: cross-plant MRP optimisation (DRP), consolidated cross-plant scheduling.
6. **Enterprise sign-in**: one OIDC provider per deployment (env config; authorization code + PKCE; JIT provisioning
   for allowed email domains; optional "SSO required" for those domains), **TOTP 2FA** for local accounts (RFC 6238,
   stdlib HMAC; recovery codes), **personal and plant API tokens** with scopes (bearer, hashed, expiring, CSRF-exempt).
   SCIM is deferred: SSO sessions are capped at `SSO_SESSION_HOURS` (default 12) so IdP deprovisioning takes effect
   within a working day, and org admins can disable users.
7. **Retention**: ledger, floor events, genealogy and audit are kept indefinitely (railway traceability for the
   product life); only derived/ephemeral classes (planning runs, notifications, delivered outbox rows, inbox payloads,
   KPI cache) are purged after archiving. Audit gets a per-owner **hash chain** (tamper evidence) and export.
8. **Lean delivery**: WP-S (one backend developer), WP-U (one UI developer), S0 contract freeze, targeted tests,
   one full backend suite at the end. New pins: `PyJWT` and `cryptography` (OIDC token validation, encryption of
   TOTP/webhook secrets); nothing else.

## 1. Scope and principles

**Principles** (in addition to M1-M4): I1 integration never bypasses domain rules - every inbound record goes
through the same validation, locks and audit as a UI write (M1 8 pipeline / services); I2 exactly-once effects via
idempotency keys inbound and an outbox written in the business transaction outbound; I3 traceability data is
append-only and never purged by the application; I4 every external identity, token and webhook secret is stored
hashed or encrypted, never in clear text or logs.

**Out of M5:** specific ERP adapters (SAP/Oracle/Tally: plug-ins after the customer's ERP is known), SCIM,
multiple OIDC providers, SAML, cross-plant planning, e-signatures (21 CFR Part 11 style), BI warehouse.

## 2. Package layout (ownership in 12)

```
backend/superplanner/
  identity/            oidc.py totp.py tokens.py crypto.py (Fernet with SECRETS_KEY) router.py   (auth area, not mfg)
  orgs/                model.py service.py router.py                                           (organisations, plants)
  integration/
    contract.py        superplanner.v1 record models per entity (4.2)          [frozen at S0]
    adapters/base.py   ErpAdapter protocol; adapters/generic_v1.py
    inbound.py         batch upsert -> mfg services / import plan (4.3)
    filedrop.py        inbox scan, mapping profiles, archive (4.5)
    outbox.py          event writers (called from mfg services), cursor, delivery job (4.6)
    sor.py             system-of-record rules (4.4); reconcile.py (4.8)
    router.py          /api/v1/integration/...
  mfg/trace/           edges.py (writers), query.py (traces, where-used), recall.py (pure assembly)
  mfg/eco/             model.py rules.py impact.py
  mfg/transfers.py     inter-plant transfer rules
  api/mfg/...          db_models_m5.py repo_m5.py services/{trace,eco,transfers}.py router_m5.py
frontend/src/mfg/...   trace, recall, ECO, transfers pages; frontend/src/settings/... security, tokens, org, integration
```

## 3. Identity, tokens, organisations

### 3.1 OIDC SSO

Env: `OIDC_ISSUER`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`, `OIDC_SCOPES` (`openid email profile`),
`OIDC_ALLOWED_DOMAINS` (comma list; empty = only already linked or pre-created users), `OIDC_REQUIRED_DOMAINS`
(passwords disabled for these), `OIDC_ORG_SLUG` (JIT users join this organisation as `org_member`),
`SSO_SESSION_HOURS` (12). Flow: `GET /auth/oidc/login?next=` -> redirect with `state`, `nonce`, PKCE S256 (state
stored server-side 10 min) -> `GET /auth/oidc/callback` -> code exchange (stdlib HTTPS client, TLS verified, 10 s
timeout) -> id_token validated with `PyJWT` against the issuer's JWKS (cached 1 h, `iss`, `aud`, `exp`, `nonce`,
RS256/ES256 only) -> identity row `(issuer, sub) -> user`; first login links to an existing user by verified email,
else JIT-creates one (allowed domains only, 403 `AUTH_SSO_NOT_ALLOWED` otherwise) -> normal session cookie (M2
sessions) with `max_age = SSO_SESSION_HOURS`. Disabled users are refused. Config errors fail at startup (M2-platform
config checks); `/auth/config` tells the UI whether SSO is enabled.

### 3.2 TOTP 2FA (local accounts)

`POST /auth/totp/setup` -> secret (shown once as otpauth URI + QR rendered client-side) ; `POST /auth/totp/enable
{code}` -> 10 recovery codes (argon2-hashed, shown once); login with a password then requires `POST
/auth/login/totp {code | recovery_code}` within 5 minutes (pending-login token). TOTP: SHA-1, 30 s, 6 digits,
+-1 step, replay of the same step refused. Secrets encrypted with `SECRETS_KEY` (Fernet; required if TOTP or
webhooks are used; key rotation by a list `SECRETS_KEYS`, first encrypts). Org admins can **require 2FA** for their
organisation's local accounts (login without it -> setup forced). Rate limits as existing auth.

### 3.3 API tokens

`api_tokens`: `id, kind (personal|plant), user_id (personal: the person; plant: the plant principal), name,
token_hash (sha256), prefix (first 8 chars for display), scopes JSON, workspace_owner_id, expires_at (max 1 year,
default 90 days), last_used_at, last_used_ip, created_by, revoked_at`. Token format `spt_<43 url-safe chars>`, shown
once. Use: `Authorization: Bearer spt_...`; CSRF not required; the request runs as the token's user in its workspace
with permissions = `scopes ∩ the user's permissions there` (plant tokens: scopes only, created by `plant_admin`).
Scopes: every M2-M4 permission name plus `integration.read`, `integration.write`. Rate limit per token (600
req/min). `GET/POST /tokens`, `DELETE /tokens/{id}` (revoke). Audit actor `tok_<id>` with the user.

### 3.4 Organisations and plants

Tables: `orgs (id, name, slug, require_2fa)`, `org_members (org_id, user_id, org_role: org_admin|org_member)`,
`org_plants (org_id, plant_owner_id -> users, code, name)`; `users.kind` (`person` default, `plant`, `service`).
Org admins: create plants (creates the plant principal user + `mfg_plant` row), add org members, grant plant roles
(writes M2 `mfg_plant_members` of that plant; new role `plant_admin` = all permissions incl. owner-only), view the
org overview (per-plant KPIs M4 9, late demand, open triggers, integration health). Workspace switcher (M2) lists
plants of the user's organisations they are members of. `manage.py convert-plant --from-user E --org SLUG --code C`
moves a personal plant into an organisation (M2 reassign-owner machinery; members kept; the person becomes
`plant_admin`). **Master-data publish**: `POST /orgs/{org}/publish {source_plant, target_plants, scope: items|
master, part_number_prefix?}` exports the source bundle and runs the import plan into each target as a job;
per-plant results; ERP-owned fields follow 4.4.

### 3.5 Inter-plant transfer orders (`mfg/transfers.py`)

A transfer order (`TO-000001`) is one document in the **source** plant (lines: item, qty, ship date, receive date)
mirrored as an inbound document in the **destination** plant (same number, `mirror_of`). Items are matched by
`external_ref`, else part number (422 `TRF_ITEM_UNMATCHED` per line). MRP: source lines are demand (type
`transfer`, priority 5), destination lines are supply at their receive date (like PO schedules). Ship: posting
`transfer_ship` in the source (stock out, lots recorded); the destination expects the shipped lots in transit;
receive: posting `transfer_receipt` in the destination (lots/serials carried over; trace edge across plants).
The service writes both plants in one transaction under `system_scope` with explicit owner stamps; the caller
needs `transfer_edit` (create) / `inventory` (ship in the source, receive in the destination) in the respective
plant. Statuses: `draft, open, shipped (partly), received, closed, cancelled`.

## 4. Integration

### 4.1 Model

Per plant: `int_settings` (SoR per entity, file-drop profile, export schedule), `int_endpoints` (webhook targets),
`int_value_maps` (domain, external_value, internal_value: UoM codes, location codes, reason codes, statuses),
`int_inbox` (inbound batches: source, idempotency_key, status, counts, results JSON, payload hash, received_at),
`int_outbox` (events), `int_deliveries` (per endpoint and event: attempts, status, next_attempt_at, last_error),
`int_reconciliations` (runs and results). All owned by the plant (`owner_id`).

### 4.2 Contract `superplanner.v1` (`integration/contract.py`, frozen at S0)

Records per entity, fields = the M1-M4 Input fields with references by external keys: `item` (`external_ref`,
`part_number`, ...), `bom` (`parent_ref`, revision, version, effectivity, status, `lines: [{child_ref, ...}]`),
`routing` (with operations, group/line codes), `supplier`, `item_supplier`, `stock_snapshot` (item, location, lot,
qty, as_at), `purchase_order` (with lines and schedules; `received_qty` read-only), `po_receipt` (when receipts SoR is
`erp`), `demand_order`, `work_order` (when created in the ERP). Every record carries `ref` (stable external key), and
the batch `{schema: "superplanner.v1", entity, mode: upsert|replace_children|delete, records: [...]}`.
Outbound events: `{schema, id (seq), type, occurred_at, plant {code, owner_id}, actor, data}` with types
`work_order.created|released|completed|closed|cancelled`, `purchase_request.submitted|approved`,
`inventory.posting` (receipts, issues, adjustments, transfers, WO issue/receipt, ship - with lines and lots),
`floor.operation_completed` (good/scrap/labour), `schedule.published`, `eco.implemented`,
`transfer_order.shipped|received`. `data` = the record shape of the corresponding API GET.

### 4.3 Inbound REST

`POST /api/v1/integration/batches` (scope `integration.write`, header `Idempotency-Key` required) -> 202 with a
batch id when > 500 records (job kind `integration_import`), else 200 with per-record results `[{ref, status:
created|updated|unchanged|rejected, id, errors[]}]`. Processing maps records to the M1 bundle sheets / M2-M4 inputs
and calls the same plan/apply code as the import wizard (I1), in chunks of 2,000 records per transaction (a batch is
not all-or-nothing across chunks; each chunk is). Value maps translate codes; unmapped codes -> record error
`INT_UNMAPPED_VALUE`. Replays of a key return the stored results. `GET /integration/batches/{id}`.

### 4.4 System of record

Defaults (changeable per plant by `integration_admin`, audited):

| Entity | Default SoR | ERP-owned fields when SoR = erp | Always SuperPlanner-owned |
|---|---|---|---|
| items | erp | part_number, revision, description, uom, make_buy, active, external_ref, standard_cost | family, setup_family, lead/receiving days\*, lot rule/period/fixed, MOQ\*, multiple\*, safety stock, issue_method, handling, attributes prefixed `sp:` |
| BOMs, routings | erp | whole document; inbound releases go through an auto-approved ECO (5) | line rates, setup matrix (M3) |
| suppliers, item-suppliers | erp | all except `preferred` | `preferred` |
| purchase orders | erp | header, lines, schedules (dates, qty) | none (receipts per row below) |
| PO receipts | superplanner | - | postings sent out as `inventory.posting` |
| demand orders | erp | all except priority | priority |
| PRs, WOs, floor, transfers | superplanner | - | everything; sent out |
| stock | superplanner | - | ledger; ERP snapshots reconcile (4.8) |

(\* item values are used only where no item-supplier row overrides them, M2 3.3.) A local write to an ERP-owned
field -> 409 `INT_ERP_OWNED` (`details.fields`); an inbound write to a SuperPlanner-owned entity or field -> record
`rejected` with `INT_SOR_CONFLICT`. SoR `shared` (allowed for items and suppliers only): last writer wins, and a
change from both sides since the last sync of that record is logged as a conflict in the reconciliation report.

### 4.5 File drop

Volume `INTEGRATION_ROOT/<plant code>/{inbox,processing,archive,error,outbox}`. A worker (job kind
`integration_filedrop`, scheduled every `FILEDROP_POLL_SECONDS`, default 60, one run per plant via the job queue)
moves complete files (size stable for 2 polls, or a `.done` marker) to `processing`, reads them with the M1 readers
(xlsx/csv/zip, M1 8.3 limits) or as `superplanner.v1` JSON, applies the plant's saved **mapping profile** (M1
mapping JSON per file-name pattern), plans and commits (zero row errors required per file, as M1), then archives
the file with a `<name>.result.json` (counts, row errors). Errors go to `error/` with the report and a notification.

### 4.6 Outbox, pull, webhooks, file export

- Services write `int_outbox` rows in the business transaction (`seq` BigInt identity, `type`, `entity_ref`, `data`
  JSON) when integration is enabled for the plant (I2).
- **Pull**: `GET /api/v1/integration/events?after=<seq>&limit=1000&types=` (scope `integration.read`) returns
  ordered events and `next_after`; consumers commit their own cursor.
- **Webhooks** (`int_endpoints`: url https only, event types, secret encrypted, active): job kind
  `integration_delivery` posts each event (in seq order per endpoint) with headers `SP-Event-Id`, `SP-Signature:
  t=<unix>,v1=<hex hmac-sha256(secret, t + "." + body)>`; 2xx = delivered; else retry with backoff 30 s .. 1 h up to
  24 h, then `dead` (notification; `POST /integration/deliveries/{id}/retry`). Order per endpoint is preserved: a
  failing event blocks later ones for that endpoint (FIFO), visible in the console. URLs to private address ranges
  are refused unless `INTEGRATION_ALLOW_PRIVATE_TARGETS=true` (SSRF guard; ERP middleware on the LAN needs it).
- **File export** (optional per plant): every `export_interval_minutes` (default 15) new events are written as CSV
  per type (and JSONL) into `outbox/`.

### 4.7 Adapter interface (`integration/adapters/base.py`)

```python
class ErpAdapter(Protocol):
    name: str                                         # "generic_v1", later "sap_s4", "tally_prime", ...
    def inbound(self, raw: bytes | dict, filename: str | None) -> list[V1Batch]   # ERP format -> superplanner.v1
    def outbound(self, event: V1Event) -> list[Delivery]                         # v1 event -> ERP calls/files
    def snapshot(self, entity: str) -> Iterable[V1Record] | None                  # optional pull for reconciliation
```
Adapters are selected per plant (`int_settings.adapter`) from a registry; a new ERP is one module plus tests, no
change elsewhere.

### 4.8 Reconciliation

`POST /integration/reconciliations {entities: [stock, purchase_orders, items], snapshot: inline|file|adapter}` (job)
compares an ERP snapshot with SuperPlanner: per record `missing_in_sp`, `missing_in_erp`, `different` (fields and
quantities; stock by item x location x lot with tolerance 1e-6), `sor_conflicts` (4.4). Result downloadable
(xlsx); stock differences can be turned into a reviewed `count` posting by a store keeper (never automatic unless
stock SoR = erp).

## 5. Engineering changes (`mfg/eco`)

`mfg_change_requests`: `number (ECO-000001), title, reason, kind (eco|ecn), source (manual|erp), status (draft,
submitted, approved, rejected, implemented, cancelled), priority, requested_by, approved_by/at, implemented_at,
effectivity {mode: date|serial|use_up, date, serial_from}, note`. Items `mfg_change_request_items`: `(cr_id, doc_type
bom|routing, doc_id (a draft), supersedes_doc_id, disposition {open_wos: keep|refresh_planned|flag,
open_pos: keep|flag_cancel, stock: use_up|scrap|rework}`.

- **Prepare**: drafts are made with M1 copy/edit; adding a draft to a CR locks it (edits only while the CR is
  draft).
- **Impact** (`GET /eco/{id}/impact`, pure `eco/impact.py`): explosion delta per affected parent (added/removed/
  changed components and quantities), open WOs and planned orders of affected items with component differences, open
  POs/PRs of components no longer needed (after the effectivity), on-hand and on-order of phased-out components with
  value, an MRP what-if delta (M2 run with the drafts treated as released at the effectivity: demand lines whose
  projected dates change), and for `use_up` a **suggested date** = first date the phased-out component's projected
  balance (latest live MRP run, M2 8.13) reaches zero.
- **Approve** (`eco_approve`; approver != submitter unless owner/plant_admin, as M2 PR rule), **implement**
  (`eco_edit`): releases all drafts atomically with `supersede_previous` at the effectivity date, or with the serial
  range from `serial_from` (M1 4.1-4.2); applies dispositions (refresh components of `planned` WOs; flag released
  WOs with exception `ECO_WO_DIFFERS`; flag POs `ECO_PO_NOT_NEEDED`); outbox `eco.implemented`. Failure of any
  release rule -> 422 with the M1 release issues, nothing released.
- ERP-sourced BOM/routing changes (4.4) create a CR with `source erp`, auto-approved and implemented by the inbound
  batch, so every structure change is traceable.

## 6. Genealogy (`mfg/trace`)

### 6.1 Edges

`mfg_trace_edges`: `id, from_kind (lot|serial|wo|item_stock|transfer|demand_line), from_id, from_item_id, to_kind,
to_id, to_item_id, qty, precision (exact|possible), event_at, posting_id N, floor_event_id N, plant_owner_id
(for cross-plant edges), owner_id`. Written by:

| Source | Edge |
|---|---|
| `wo_issue` / backflush (lot-controlled or serialized component) | lot/serial -> WO (`exact` at WO level) |
| `wo_issue` of non-lot items | item_stock(item, location) -> WO (`possible`; quantity only) |
| `wo_receipt` | WO -> output lot / serials (`exact`) |
| M4 serial consumed into parent | child serial -> parent serial (`exact`) |
| WO consumed lot, WO produced serials | lot -> each serial (`possible`, derived at query time, not stored) |
| `ship` (with lots/serials) | lot/serial -> demand line (`exact`) |
| transfer ship/receive | lot/serial (source plant) -> lot/serial (destination plant) (`exact`) |

Backfill: `manage.py trace-backfill` (and on migration as a job) rebuilds edges from existing postings and M4
events, idempotently (`uq (posting_id, from_id, to_id)` / floor event).

### 6.2 Queries (`GET /mfg/trace`)

`GET /mfg/trace?kind=lot|serial|wo&id=&direction=backward|forward&depth=1..30&include_possible=true` -> tree
(depth-first) of nodes `{kind, id, item: ItemRef, label (lot code / serial / WO number), qty, precision, at,
location/status, link}`, limits 20,000 rows (`truncated`). Backward from a finished serial: its WO, consumed child
serials (exact), lots issued to that WO (exact for the WO, possible for the unit), recursively. Forward from a
supplier lot: WOs that consumed it, their outputs, their consumers..., shipments and customers. **Where-used of a lot
/ supplier lot**: `GET /mfg/trace/where-used?item_id=&lot_code=|supplier_lot=`. Implemented as recursive CTEs over
`mfg_trace_edges` with `(from_kind, from_id)` / `(to_kind, to_id)` indexes, plant-scoped (cross-plant edges followed
only into plants the user can view; others shown as "in plant X, not visible").

### 6.3 Recall report

`POST /mfg/recalls {name, sources: [{kind, id} | {item_id, supplier_lot}], include_possible: true}` (perm
`trace_view`; saved, `RCL-000001`) -> report: affected finished units (serials) and lots by status (`in_stock`
location, `wip` WO/operation, `shipped` demand order/customer/date, `consumed` parent), each with precision and the
path; counts per customer and programme; open POs/stock of the source lots for quarantine; export xlsx/PDF-print.
Action `POST /mfg/recalls/{id}/quarantine` moves in-stock affected lots/units to a quarantine location (one transfer
posting per balance, perm `inventory`) and puts the lots on hold (M2).

## 7. Retention, archival, audit export

| Class | Retention (default) | Archive |
|---|---|---|
| ledger, floor events, trace edges, serials, lots, audit | indefinite (never purged by the app) | periodic JSONL.gz export |
| MRP/APS runs, simulations | M2/M3 retention (10 unpinned) | before deletion when `ARCHIVE_DIR` is set |
| notifications, replan triggers handled | 180 days | yes |
| outbox delivered events | 90 days (pull cursors older than that are rejected: 410 `INT_CURSOR_EXPIRED`) | yes |
| inbox payloads / import staging | 30 days / M1 24 h | yes |
| KPI daily cache | rebuildable, 3 years | no |

`manage.py archive --before DATE [--classes ...]` writes `ARCHIVE_DIR/<owner>/<class>/<yyyy-mm>.jsonl.gz` with a
manifest (counts, sha256) and then purges only purgeable classes; a nightly job kind `maintenance_retention`
applies the defaults (`RETENTION_ENABLED`, default true). **Audit**: `audit_events.chain_hash = sha256(prev
chain_hash of the same owner || canonical row)` maintained on insert under the owner's advisory lock;
`manage.py audit-verify` checks the chain; `GET /audit/events?from&to&entity_type&actor` (paginated) and `GET
/audit/export?format=jsonl|csv&from&to` (streamed) for owner, `plant_admin` and org admins (org-wide).

## 8. HA and deployment notes (DEPLOY.md additions, docs only)

API replicas are stateless (sessions, CSRF, rate limits in PostgreSQL) behind a load balancer; workers scale
horizontally; singleton duties (file-drop scan per plant, retention, delivery per endpoint) are serialised by the job
queue and per-key advisory locks, so any number of workers is safe. PostgreSQL HA via a managed service or Patroni
with synchronous replica; PITR backups (WAL archiving) replace dump-only backups for production; RPO/RTO targets
documented (example 5 min / 30 min). Migrations follow expand -> deploy -> contract so rolling upgrades work; 0007 is
additive only. Integration volume is shared (NFS/EFS) or mounted only on the worker that runs file-drop jobs
(`WORKER_KINDS`). OIDC/TOTP/webhook secrets via env/secret store; `SECRETS_KEY` rotation procedure.

## 9. API summary (perm column = M2 10.2 / M4 names + new)

| Area | Endpoints | Perm |
|---|---|---|
| Identity (`/api/v1/auth`) | GET `/auth/config`; GET `/auth/oidc/login`, `/auth/oidc/callback`; POST `/auth/totp/setup`, `/auth/totp/enable`, `/auth/totp/disable`, `/auth/login/totp`, `/auth/totp/recovery-codes` | session |
| Tokens (`/api/v1/tokens`) | GET, POST, DELETE `/{token_id}` | session (plant tokens: `plant_admin`) |
| Orgs (`/api/v1/orgs`) | GET `/orgs`; POST `/orgs`; GET/PUT `/orgs/{org}`; GET/POST/PUT/DELETE `/orgs/{org}/members[/{member_id}]`; GET/POST `/orgs/{org}/plants`; PUT `/orgs/{org}/plants/{plant}`; POST `/orgs/{org}/plants/{plant}/roles`; POST `/orgs/{org}/publish`; GET `/orgs/{org}/overview` | org_admin (overview: org_member, only plants they can view) |
| Integration (`/api/v1/integration`) | GET/PUT `/settings`; GET/POST/PUT/DELETE `/endpoints[/{id}]`; POST `/endpoints/{id}/test`; GET/PUT `/value-maps`; POST `/batches`, GET `/batches/{id}`, GET `/batches`; GET `/events`; GET `/deliveries`, POST `/deliveries/{id}/retry`; GET/POST `/mapping-profiles[/{id}]`; GET `/filedrop/status`; POST `/reconciliations`, GET `/reconciliations[/{id}]`, GET `/reconciliations/{id}/export` | `integration_admin` / scopes `integration.read`, `integration.write` |
| Traceability (`/api/v1/mfg`, #227..) | GET `/trace`, `/trace/where-used`; POST/GET `/recalls`, GET `/recalls/{id}`, GET `/recalls/{id}/export`, POST `/recalls/{id}/quarantine` | trace_view (quarantine: inventory) |
| ECO | GET/POST `/eco`; GET/PUT/DELETE `/eco/{id}`; POST `/eco/{id}/items`, DELETE `/eco/{id}/items/{item_id}`; GET `/eco/{id}/impact`; POST `/eco/{id}/submit` \| `approve` \| `reject` \| `cancel` \| `implement` | eco_edit / eco_approve |
| Transfers | GET/POST `/transfer-orders`; GET/PUT/DELETE `/transfer-orders/{id}`; POST `/{id}/open` \| `close` \| `cancel`; shipping and receiving use M2 postings `transfer_ship` / `transfer_receipt` | transfer_edit / inventory |
| Audit | GET `/audit/events`, `/audit/export` | owner, plant_admin, org_admin |

Exact `/mfg` numbering and the `MFG_PERMISSIONS` additions are fixed in the S0 route table (each route one
permission, as before). New permissions: `trace_view` (all plant roles), `eco_edit` (owner, plant_admin, planner),
`eco_approve` (owner, plant_admin, approver), `transfer_edit` (owner, plant_admin, planner, store_keeper),
`integration_admin` (owner, plant_admin). New roles: `plant_admin` (plant), `org_admin` / `org_member` (org).

Errors (new): 401 `AUTH_TOKEN_INVALID` / `AUTH_TOKEN_EXPIRED`; 403 `AUTH_SSO_NOT_ALLOWED`, `AUTH_SSO_REQUIRED`
(password login for an SSO-required domain), `AUTH_2FA_REQUIRED`, `TOKEN_SCOPE`; 409 `INT_ERP_OWNED`,
`INT_IDEMPOTENCY_CONFLICT`, `ECO_DOC_LOCKED`, `ECO_SELF_APPROVAL`, `TRF_PLANT_ACCESS`; 410 `INT_CURSOR_EXPIRED`; 422
`AUTH_TOTP_INVALID`, `INT_UNMAPPED_VALUE`, `INT_SOR_CONFLICT` (per record), `INT_SCHEMA`, `INT_URL_NOT_ALLOWED`,
`TRF_ITEM_UNMATCHED`, `TRACE_TOO_DEEP`, `ECO_RELEASE_BLOCKED` (`details.issues`).

## 10. Data (migration `0007_m5`)

New tables: `orgs`, `org_members`, `org_plants`, `user_identities` (issuer, sub, user_id, email, last_login_at; uq
(issuer, sub)), `user_totp` (user_id PK, secret_enc, enabled_at, last_step, recovery_hashes JSON), `oidc_states`
(state PK, nonce, verifier, next, expires_at), `api_tokens`, `int_settings`, `int_endpoints`, `int_value_maps`,
`int_mapping_profiles`, `int_inbox`, `int_outbox` (seq identity; ix (owner_id, seq)), `int_deliveries`,
`int_reconciliations`, `mfg_change_requests`, `mfg_change_request_items`, `mfg_trace_edges` (ix (owner_id,
from_kind, from_id), (owner_id, to_kind, to_id), (from_item_id), uq on source refs), `mfg_recalls`,
`mfg_transfer_orders`, `mfg_transfer_lines`. Columns: `users.kind` (`person`), `audit_events.chain_hash`,
`audit_events.owner_id` (backfilled from actor/entity where known, else null), `mfg_boms`/`mfg_routings.locked_by_cr_id`,
`mfg_inv_transactions.transfer_line_id`. Jobs: kinds `integration_import`, `integration_filedrop`,
`integration_delivery`, `integration_reconcile`, `org_publish`, `maintenance_retention`, `trace_backfill` with their
target columns (`ck_jobs_one_target` extended). All additive; downgrade drops them.

## 11. Performance targets (PostgreSQL local, developer machine class of M1-M4)

| # | Case | Target |
|---|---|---|
| IP1 | inbound batch 10,000 items (upsert, 50% unchanged) | < 30 s; full Kavach master (1,200 items, 63 BOMs, 61 routings) < 60 s |
| IP2 | outbox write overhead per business transaction | < 3 ms |
| IP3 | pull `/integration/events` 1,000 events | < 300 ms |
| IP4 | webhook delivery 100 events/s sustained, p95 event -> delivery | < 5 s (healthy endpoint) |
| IP5 | file drop of a 20,000-row stock file | picked up <= 2 polls, committed < 20 s |
| TP1 | backward trace of a KV-TPU-1000 serial (full depth, ~1,500 nodes) | < 1 s |
| TP2 | forward trace / recall of a passive supplier lot used in 2,000 units | < 3 s / report < 5 s |
| EP1 | ECO impact on KV-PCB-CPU (incl. MRP what-if delta) | < 10 s |
| AP1 | bearer token auth overhead / OIDC callback server time (excl. IdP) | < 2 ms / < 300 ms |
| AP2 | audit export 1,000,000 rows streamed | < 60 s, constant memory |
| BF1 | trace backfill of the Kavach M4 sample history | < 60 s |

## 12. Delivery plan (lean)

| WP | Role | Owns |
|---|---|---|
| **S** backend | one backend developer | `sp/identity/**`, `sp/orgs/**`, `sp/integration/**`, `sp/mfg/trace/**`, `sp/mfg/eco/**`, `sp/mfg/transfers.py`, `sp/api/mfg/{db_models_m5,repo_m5,router_m5}.py`, `services/{trace,eco,transfers}.py`, outbox/trace/SoR hooks in existing mfg services, auth deps (bearer tokens, 2FA step), `jobs/*` kinds, migration `0007_m5`, `migrate.py`, `manage.py` commands, config + pins (`PyJWT`, `cryptography`), `docs/DEPLOY.md` (8), tests `tests/identity/**`, `tests/integration_m5/**`, `tests/trace/**`, `tests/eco/**`, `tests/api_mfg_m5/**`, existing-test edits of 12.1 |
| **U** UI | one ui-developer | `frontend/src/**` new pages (security settings: SSO login button, 2FA setup, tokens; org admin; integration console; trace explorer, recall, ECO, transfers, audit viewer) and additive edits to the login page, nav and workspace switcher; `frontend/e2e/m5-*.spec.ts` (one spec) |
| LEAD | team lead | this document, S0 review, final gate |

Milestones: **S0 (day 1)** - `integration/contract.py`, models of 3-6, migration + up/down test, all routes live with
permissions answering from `backend/superplanner/integration/fixtures/example_m5.json`; U writes
`contractExamplesM5.ts`. **S1** tokens, TOTP, OIDC (tested against an in-process fake IdP with real JWKS signing),
orgs/plants/convert-plant/publish. **S2** integration: SoR, inbound REST, value maps, file drop, outbox, pull,
webhooks, reconciliation, adapter registry. **S3** trace edges + backfill + queries + recall + quarantine; ECO with
impact. **S4** transfers, retention/archive, audit chain/export, DEPLOY.md, performance. **U1** login/SSO/2FA/
tokens/org admin, **U2** integration console (settings, SoR table, endpoints, deliveries, batches, file drop,
reconciliation), **U3** trace explorer (tree + graph), recall, ECO (prepare, impact, approve, implement), **U4**
transfers, org overview, audit viewer, the e2e spec.

### 12.1 Existing code and tests touched

Auth dependencies (bearer + 2FA step; `require_user` unchanged for cookie sessions), login router, users model
(`kind`), `problem_service.audit` (chain hash), mfg services that write outbox rows/trace edges/SoR checks
(items, BOMs, routings, suppliers, purchasing, demand, WOs, inventory, floor), M2 postings (`transfer_ship`,
`transfer_receipt`), MRP snapshot (transfer lines as demand/supply), `manage.py`, `jobs/*`, config checks. Existing
tests changed only: route/permission tables and the authz sweep (new id params), auth route-coverage tables (new
auth/org/integration/token routes, also bearer-token variants), migration head/table sets, job-kind lists, audit
row shape assertions (`chain_hash`), sample hashes if the samples gain M5 data.

## 13. Testing and acceptance

**During work:** tests with the code; only touched tests and package folders run (`.venv/bin/pytest tests/identity
-q`, `tests/integration_m5 -q`, `tests/trace -q`, ...; named existing tests of 12.1); UI `npm run build`, the m5 spec
only when written. **Final gate (once, LEAD):** full backend suite on PostgreSQL incl. `-m slow`; `m5-*.spec.ts` and
the accounts-mode login spec (auth pages change); build/audit; migration 0006 -> 0007 on a populated database and
downgrade; `audit-verify` on the migrated database. Fixes with targeted reruns only, unless they touch `api/auth`,
`api/db`, migrations or `jobs`.

**Test vectors (pure / API):**

| # | Case | Expected |
|---|---|---|
| T-I1 | inbound batch of 3 items twice with the same Idempotency-Key, then changed body | replay identical; changed body 409 `INT_IDEMPOTENCY_CONFLICT` |
| T-I2 | items SoR erp: UI PUT changes description | 409 `INT_ERP_OWNED`; PUT of `safety_stock` succeeds |
| T-I3 | inbound PR record while PRs are superplanner-owned | record rejected `INT_SOR_CONFLICT`, others applied |
| T-I4 | UoM `NOS` unmapped / mapped via value map | `INT_UNMAPPED_VALUE` / applied as `EA` |
| T-I5 | WO release + po_receipt in one transaction rolled back | no outbox rows; committed -> events in seq order |
| T-I6 | webhook endpoint returns 500 three times then 200 | 4 attempts with backoff, then delivered; later events waited (FIFO) |
| T-I7 | signature | receiver verifies `v1` with the secret and timestamp |
| T-I8 | file drop: partially written file | not picked until size stable; result json written; bad file -> error/ + notification |
| T-I9 | reconciliation: ERP stock 100, SP 98 | `different` qty 2; no posting unless SoR erp |
| T-A1 | TOTP RFC 6238 test vectors; same step twice | accepted once |
| T-A2 | OIDC: wrong `aud`, expired, bad nonce, unknown kid | all refused; valid -> session, JIT user in allowed domain |
| T-A3 | token with scope `view` calls a POST | 403 `TOKEN_SCOPE`; revoked/expired 401 |
| T-O1 | user member of plants A and B in one org | workspace switcher lists both; data isolated |
| T-O2 | convert-plant of the Kavach sample owner | row counts unchanged, person is `plant_admin`, old workspace id 404 |
| T-O3 | transfer 100 of lot L from A to B | A stock -100, B +100 lot L, MRP demand in A / supply in B before shipping, trace edge A.L -> B.L |
| T-T1 | supplier lot issued to 2 PCB WOs, PCBs (serials) into 3 TPU serials, 2 shipped | forward trace lists 2 WOs, PCB serials (possible for lot->unit), 3 TPUs (exact via serial links), 2 shipments with customers |
| T-T2 | recall + quarantine | in-stock affected lots moved to quarantine and on hold; report counts per customer |
| T-E1 | ECO replacing a capacitor from 2027-01-01 | impact lists open WOs with the old part, phased-out stock value, use-up suggested date = MRP zero-crossing; implement releases with supersede; explosion before/after the date differs |
| T-E2 | ECO with a draft that fails release rules | 422 `ECO_RELEASE_BLOCKED`, nothing released |
| T-R1 | audit chain: alter one audit row in SQL | `audit-verify` reports the first broken link |

**Acceptance (Gate 5):**
1. A scripted "ERP day" with `generic_v1`: master data and POs in by REST and file drop, WOs/PR approvals/receipts/
   completions out by pull and webhook, reconciliation clean afterwards; re-sending everything changes nothing.
2. SoR rules hold for every entity in 4.4 (UI and inbound sides).
3. Genealogy of the Kavach M4 sample after backfill: backward trace of every shipped TPU serial reaches supplier lots;
   forward trace from a coating lot reaches the affected units; recall report matches a hand-built expectation.
4. ECO impact and implementation per T-E1 on the Kavach sample; ERP-sourced BOM change creates an implemented CR.
5. Multi-plant: org with two plants, a user across both, transfer order end-to-end, master-data publish idempotent.
6. Sign-in: OIDC against the fake IdP and (manual check documented) one real IdP; TOTP enforcement per org; tokens
   with scopes; all existing auth tests green.
7. Retention/archive/audit export: archive manifest checksums match, purge touches only purgeable classes,
   `audit-verify` clean; performance IP1-BF1; full backend suite green once.

## 14. Questions for the product owner

Decided by LEAD 2026-11-05 (the product owner delegated configuration-type decisions; revisit with HBL's IT):

1. **Q1 ERP and exchange method:** M5 ships `generic_v1` only (REST batch + file drop + outbox/webhooks), which any
   ERP can reach through its integration layer or middleware. A vendor adapter is added once HBL names its ERP.
2. **Q2 Where receipts and issues are booked:** default as built (SuperPlanner books, ERP receives), but goods
   receipts against POs must be switchable to ERP-owned per plant (`integration.goods_receipts_owner = erp|superplanner`),
   so either HBL process works without code changes.
3. **Q3 Sites:** keep transfers and master-data publish in M5 (enterprise readiness for multiple HBL sites).

## 15. Implementation notes

### 15.WP-S Backend

**S0 frozen (2026-11-05).** Contract: `integration/contract.py` (superplanner.v1 records, batch, event),
`integration/model.py` (console), `identity/schemas.py`, `orgs/model.py`, `mfg/model_m5.py` (trace, recall, ECO,
transfers, audit rows). Typed examples: `backend/superplanner/integration/fixtures/example_m5.json` (built and
validated by `build_example.py`). Migration `0007_m5` = `migrate.HEAD` (up/down tested). All routes of 9 are live
with their permissions (`tests/auth/route_table.py`: 28 new `/mfg` operations, 40 protected tokens / integration /
orgs / audit operations, 9 public `/auth` additions); trace / recall / ECO / transfer routes answer from the fixture
until their services land.

Built for real in this round: identity (OIDC code + PKCE against a fake IdP with real RS256 / ES256 JWKS, TOTP with
recovery codes and the pending-login step, org-forced 2FA at sign-in, SSO-required domains, API tokens with scopes,
expiry, revocation, per-token rate limit), organisations (orgs, members, plants with plant principals, plant roles,
overview, publish record), integration (settings and SoR incl. `goods_receipts_owner`, value maps, mapping profiles,
inbound batches for `item` and `po_receipt` with idempotency, outbox with emits from WOs / postings / PRs / floor /
publish, cursor pull, signed webhooks with FIFO backoff and dead state, SSRF guard, stock reconciliation), audit
hash chain with events / export. Not yet built (fixture-backed): genealogy edges and queries, recalls / quarantine,
ECO services, transfer orders, file drop worker, publish execution, retention / archive, convert-plant and the
other `manage.py` commands, scheduled delivery job, DEPLOY.md section 8.

Deviations / interpretations:
1. Jobs: target columns `int_inbox_id`, `int_reconciliation_id`, `org_publish_id`, `maintenance_run_id`; the
   duty-style kinds (`integration_filedrop`, `integration_delivery`, `maintenance_retention`, `trace_backfill`)
   target a `maintenance_runs` row (new platform table, with `org_publishes`) because the job machinery mirrors a
   run status. New platform table `auth_pending_logins` (the 5-minute TOTP step).
2. `oidc_states` stores `state_hash` (sha256 of the state) and the PKCE verifier encrypted with a key derived from
   the raw state, so the database alone reveals neither (no SECRETS_KEY needed for SSO).
3. 2FA step: `POST /auth/sign-in` answers 403 `AUTH_2FA_REQUIRED` with `details.pending_token` (and
   `setup_required` when an organisation forces 2FA and the user has none; setup / enable then accept the pending
   token in `X-SP-Pending-Login`). The M2 `SessionInfo` response stays unchanged.
4. Sessions of users without a password are valid for `kind = person` (SSO users); plant / service principals can
   never hold a session.
5. Per-token rate limit is in-process per API replica (fixed one-minute windows), not in PostgreSQL (AP1 budget).
6. Integration endpoints use `require_integration(scope)`: sessions need `integration_admin`; tokens need the scope
   (or `integration_admin`) **and** a holder with `integration_admin` in the plant (403 `TOKEN_SCOPE` /
   `MFG_FORBIDDEN`). Inbound batches with integration disabled: 409 `INT_DISABLED`. A local write of an ERP-owned
   field is enforced for items (409 `INT_ERP_OWNED`, incl. creating items while items are ERP-owned) and for PO
   receipts when `goods_receipts_owner = erp`; the other entities' local guards follow with their inbound mappers.
   `po_receipts` SoR always follows `goods_receipts_owner`.
7. Audit: `owner_id` = the bound plant (None for platform events, which share one chain); the chain is per owner by
   id order; rows written before 0007 have no hash and are skipped by `verify`. Audit routes allow the plant owner and
   `plant_admin` (tokens need scope `owner`); org-wide audit for org admins is not built yet.
8. `users.kind` keeps a server default (`users` is a platform table that already uses server defaults).
9. SSRF: besides the save-time check, the webhook URL is re-checked right before every post (a name that now
   resolves to a private address is a failed attempt with `INT_URL_NOT_ALLOWED: ...` in `last_error`, nothing is
   sent, FIFO backoff applies); redirects are never followed (a 3xx is a failed attempt). Residual: the resolve-to-
   connect window is not pinned (urllib resolves again); acceptable with the re-check, noted for a later pinned
   connection.
10. Inbound records of entities other than `item` and `po_receipt` are accepted into the batch but answered
    `INT_SCHEMA` "not processed in this build" until their mappers land.

### 15.WP-U UI
