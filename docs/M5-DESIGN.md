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
hash chain with events / export.

**Round 2 (S2-S4, 2026-11-05): no route answers from the fixture any more.** Built: inbound mappers for every v1
entity with field-level SoR on both sides, file drop worker, scheduler and the delivery / export / retention jobs,
pinned webhook connections, genealogy (writers in the posting / floor transactions, backfill, traces, where-used,
recalls, quarantine), ECO services, transfer orders (`transfer_ship` / `transfer_receipt` postings, MRP demand /
supply), master-data publish execution, `convert-plant`, retention / archive, `audit-verify` (CLI + endpoint),
DEPLOY.md section 13 (HA notes; the design's "section 8" - DEPLOY.md already had a section 8, Backups). The
example fixture stays the UI's typed contract example; live shapes are supersets (additive keys listed below).

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
   `MFG_FORBIDDEN`). Inbound batches with integration disabled: 409 `INT_DISABLED`. Local writes of ERP-owned data
   -> 409 `INT_ERP_OWNED` (`details.fields`, `details.entity`; `["document"]` = the whole document): items (ERP
   fields, incl. creating items), BOMs and routings (create / update / copy / release / obsolete / delete),
   suppliers (all), item-suppliers (all fields except `preferred`), purchase orders (create / update / delete /
   status actions / PR -> PO conversion; PRs stay local), demand orders (create / delete / actions; updates that
   change anything but the header / line priorities), work orders (when their SoR is set to `erp`), PO receipts
   (`goods_receipts_owner = erp`; `po_receipts` SoR always follows it). `shared` SoR passes local writes (last writer
   wins); the "changed on both sides" conflict log of 4.4 is not built (reconciliation reports `sor_conflicts` for
   SuperPlanner-owned entities only).
7. Audit: `owner_id` = the bound plant (None for platform events, which share one chain); the chain is per owner by
   id order; rows written before 0007 have no hash and are skipped by `verify`. Audit routes allow the plant owner and
   `plant_admin` (tokens need scope `owner`); org-wide audit for org admins is not built yet.
8. `users.kind` keeps a server default (`users` is a platform table that already uses server defaults).
9. SSRF: the URL is checked when saved and again right before every post; the post then connects to exactly the
   checked address (`outbox.pinned_post`: a socket to the IP literal, no second DNS lookup, TLS with SNI and
   certificate verification for the URL's host name), so the DNS-rebinding window is closed. Redirects are never
   followed (a 3xx is a failed attempt); HTTP proxies are not used for webhooks (DEPLOY 13). A refused or failing
   post is a failed attempt with `last_error`, FIFO backoff applies.
10. Inbound processing (`integration/inbound.py`): `supplier`, `item_supplier`, `purchase_order`, `demand_order`,
    `work_order` map to the M1 bundle sheets and go through `plan_import` + `writer.apply` in chunks of 2,000
    records per transaction; every bundle row carries a `Source` naming its record, so a plan row error rejects
    exactly that record (`INT_SCHEMA` with the plan errors in `details`) and the chunk is re-planned without it.
    Unknown references -> `INT_UNMAPPED_VALUE` (`field`, `value`). Status: `created` (natural key new), `updated`
    (the plan changed the document or a child), `unchanged`. `mode: replace_children` = M1 `replace_children`;
    `delete` is refused per record (`INT_SCHEMA`; deactivate / close instead). v1 demand types map to M2 ones
    (`forecast`/`safety` -> `internal`, `program` -> `project`); inbound demand orders are `open`.
    SuperPlanner-owned fields are written on create only (item-supplier `preferred`, line `priority`; item planning
    fields as before).
11. ERP BOMs / routings: one transaction per record. The same structure as the current released document (or as
    the given `version`) -> `unchanged`; else a new draft version (next number unless `version` is given) is
    written through the import plan and released by an auto-approved ECO (`source erp`, kind `ecn`, approver
    `erp`) with supersede at `effective_from` (BOMs; routings and BOMs without a date: plant today when a
    previous version exists, else no supersede). The record result carries `eco {id, number}`. A release failure
    rejects the record (`ECO_RELEASE_BLOCKED` with `issues`), nothing of it stays. `status: obsolete` obsoletes the
    released version; `draft` only writes the draft. Routing `group_code`s must exist in the plant. Contract
    additions (optional, found with the Kavach master in IP1): `routing.priority` (alternate routings) and
    `operation.units_per_panel` (`run_per: panel`).
12. Stock snapshots (`stock_snapshot` records, stock files): with stock SoR `superplanner` -> one reconciliation
    run (records answered `unchanged` with `id` = reconciliation id); with `erp` -> the reconciliation plus one
    `count` posting reason `ERP_SYNC` (records whose balance changed -> `updated`). New `POST
    /integration/reconciliations/{id}/post-counts` (reason `ERP_RECON`) is the reviewed follow-up of 4.8.
    Reconciliation also covers `items` (ERP fields) and `purchase_orders` (schedule qty / dates / received qty,
    status). Snapshot `file` reads `{entity: [records]}` JSON from the plant inbox; `adapter` asks the adapter
    (`generic_v1` has none -> 422). Reconciliations run synchronously (the `integration_reconcile` job handler
    exists for queued rows but the API does not queue).
13. Batches > 500 records -> 202 with the batch (`status queued`), job `integration_import`; `GET /batches/{id}`
    shows the results when done.
14. File drop (`integration/filedrop.py`): complete = `<name>.done` marker or size + mtime unchanged since the
    previous poll (kept in the last run's `results.seen`). `.json` -> adapter `inbound` -> the REST path
    (`int_inbox.source = filedrop`, idempotency key from the file hash); `.csv/.xlsx/.zip` -> M1 reader + the first
    mapping profile whose `file_pattern` (fnmatch, case-insensitive) matches (profile `mapping` = M1 mapping JSON,
    or the shorthand `{target, columns, options}` applied to every sheet; no profile -> the M1 suggestion), planned
    and committed with zero row errors in one transaction under the plant lock. Sheets of SuperPlanner-owned
    entities fail the file (`INT_SOR_CONFLICT`); stock sheets reconcile unless stock SoR is `erp`. Bad files ->
    `error/` + `.result.json` + notification `INTEGRATION_FILE_ERROR`. BOM / routing sheets in files are imported
    as M1 does (no ERP ECO; use v1 JSON for that).
15. Scheduling (`integration/scheduler.py`, started by every worker that runs a duty kind): every
    `INTEGRATION_DELIVERY_POLL_SECONDS` (new, default 2 s; IP4) deliveries, every `FILEDROP_POLL_SECONDS` also file
    drop and the daily `maintenance_retention`; one scheduler at a time (`pg_try_advisory_xact_lock`), one active
    run per kind and plant. `integration_delivery` delivers due events of all endpoints (up to 10,000 per run) and
    writes the periodic file export (`outbox/events-<stamp>-<from>-<to>.jsonl` plus one CSV per event type, temp
    name + rename; `export_cursor`, last export time kept in `int_settings.sor["_exported_at"]`).
16. Deliveries: new `POST /integration/deliveries/{id}/park` (status `parked`: the endpoint cursor moves past it,
    FIFO continues) and `/unpark` (= `retry`; a parked event behind the cursor becomes `retry` and is sent once on
    the next run, out of order; failing again parks it). Delivery statuses gain `parked`, `retry`.
17. `GET /integration/ownership` (any plant role, new): `{enabled, sor, goods_receipts_owner, erp_fields}` for the
    ERP-owned indicators (WP-U request 2). `GET /integration/reconciliations/{id}/export?format=xlsx|csv` (xlsx: a
    summary sheet plus one sheet per entity x kind).
18. Genealogy (`services/trace.py`, `mfg/trace/query.py`): node ids - lot / serial / WO / demand line row ids,
    `item_stock` = the non-lot balance row id (the design's `(item, location)`), `transfer` = the source transfer
    line id (one node id in both plants; edges carry `plant_owner_id` of the other plant). Edges in material-flow
    direction; `source_key` = `<posting>:<txn>` / `ser:<serial>:p|c|pp` (idempotent writers and backfill).
    Reversals and WO returns write negative-quantity edges; a pair whose net quantity is <= 0 is not shown.
    Non-lot WO receipts are `WO -> item_stock (possible)`, so forward traces reach shipments of untracked stock.
    Precision is per link (relative to the parent node): lot / stock -> WO -> serial, serial -> WO -> lot / stock
    and serial -> WO -> another serial are `possible`; a child -> parent serial link is `exact`. Recall units carry
    the cumulative precision of their path. Traversal is a per-level indexed walk (one query per level and plant),
    not a recursive CTE (same result; precision and cross-plant visibility are applied per step). Cross-plant
    transfer nodes continue in the other plant when the user is its owner or an active member, else a node
    `{kind: transfer, label: "in plant X, not visible", plant: {visible: false}}`.
19. Trace responses: root `qty` 1 for serials / the WO qty; `where-used` returns every forward node (`depth`,
    `status`, `link`, cumulative `precision`) plus `lots` (the matching lot ids). Recall `report` (additive keys):
    `units[{serial_id, serial, item, status, precision, customer, demand_order, shipped_on, plant, path}]`,
    `lots[{lot_id, lot_code, supplier_lot, item, item_id, on_hand, location, location_id, location_kind, hold,
    precision}]`, `wos`, `shipments[{demand_line_id, demand_order, customer, program, qty, precision, shipped_on,
    item, path}]`, `by_customer[{customer, units, shipments, qty}]`, `by_program`, `open_pos`, `counts`,
    `truncated`, `computed_ms`. A unit's customer comes from shipments downstream of it; M2 shipments carry no
    serials, so units shipped from untracked stock reach their shipments only as `possible` links through the WO's
    receipt stock. `GET /recalls/{id}/export` = xlsx (`?format=json`: the report). Quarantine: one `transfer`
    posting (reason `RECALL`) per affected lot balance outside quarantine locations, then the lots on hold; body
    `{location_id?, lot_ids?, note}` (`lot_ids` new, as the UI sends it); serialized units without lots are not
    moved. Recall numbers: series `RCL-`.
20. ECO (`services/eco.py`): the lock stays on released documents after implementation (they name their CR); lock
    checks (409 `ECO_DOC_LOCKED`) on BOM / routing update (only while the CR is a draft), release and delete.
    BOM / routing records gain `locked_by_cr_id` and `locked_by_cr {id, number, status}` (WP-U request 7). CR
    records gain `submitted_by`. Supersede follows M1: the old document's `effective_to` = the new
    `effective_from` (exclusive end). Serial effectivity sets the draft's `serial_from` and closes an open range
    of the superseded document at `serial_from - 1`. Dispositions flag through M4 notifications
    (`ECO_WO_DIFFERS` for open WOs due on/after the effectivity whose components differ, `ECO_PO_NOT_NEEDED` per
    open PO line of a removed component), not APS replan triggers; `refresh_planned` regenerates the components of
    planned WOs without issues (`workorders.regenerate_components`). Impact: the MRP what-if runs two in-memory
    MRP runs (current vs drafts released at the effectivity) and lists demand lines whose projected date moves;
    the use-up date is computed from the current-state run (not the stored live run): the first date the
    phased-out components' projected existing balance reaches zero (earliest over the removed / changed components).
21. Transfers (`services/transfers.py`, `mfg/transfers.py`): new posting types `transfer_ship` / `transfer_receipt`
    (lines `{transfer_line_id, item_id, location_id, qty, lot_code, expires_on?}` - as the UI sends them; added to
    the M2 posting union and planner, txn `transfer_line_id` set). Receipts only up to what is in transit per lot
    (409 `TRF_OVER_QUANTITY`, also over-shipping); expiry and supplier lot carried over. Transfer postings cannot
    be reversed (409; correct in both plants). Create needs `transfer_edit` in the source and membership in the
    destination (403 `TRF_PLANT_ACCESS`); the destination location is `to_location_code` or its receipt default.
    Statuses derived from the lines (`shipped` partly or fully, `received` when all received); `close` from
    `shipped`/`received`, `cancel` only before shipping; edit/delete only as draft in the source. MRP: open source
    lines are demand type `transfer` (priority 5, customer = destination plant code), open destination lines
    supply typed like PO schedules (`ScheduleSnap` doc type `po`, number `TO-...`; MRP actions on them are not
    meaningful). Lines carry `mirror_line_id`, `in_transit[{lot_code, qty, expires_on, supplier_lot, posting}]`.
    Outbox `transfer_order.shipped|received` in the acting plant. Number series `TO-` shared by both plants.
22. Publish: `POST /orgs/{org}/publish` resolves plants by id / owner id / code, enqueues `org_publish`; new
    `GET /orgs/{org}/publish/{id}` returns the run with per-target `{ok, counts, skipped, row_errors}`. Bundle =
    the source master (`scope items`: items only; `part_number_prefix` filters items and their documents /
    supplier links; no plant sheet), imported with `release=True`. Targets with ERP-owned entities skip those
    sheets, and items are published without their ERP fields. Released documents that differ in a target are
    row errors (M1 rule), the target result is `ok: false`.
23. `convert-plant --from-user EMAIL --org SLUG --code C [--name] [--dry-run]` (`orgs.service.convert_plant`): new
    plant principal + `org_plants` row; every `mfg_*` / `int_*` owned row moves (members included); audit rows stay
    on the old owner (their chain hashes include the owner); the person becomes `plant_admin` and an org member.
24. Org admins: `PUT /orgs/{org}/members/{id}` accepts `{org_role?, disabled?}` (`disabled` disables / enables the
    account and revokes its sessions; not oneself) (WP-U request 6). `/workspaces` items gain `org {id, slug, name}`
    or null and `plant_code` (WP-U request 1).
25. Retention / archive (`services/maintenance.py`, `manage.py archive`): classes `ledger, floor_events,
    trace_edges, serials, lots, audit` (export only) and `notifications, replan_triggers (handled/ignored),
    outbox, inbox_payloads (payload column nulled), kpi_daily` (purgeable after 180 / 180 / 90 / 30 / 1095 days).
    Outbox rows are purged only up to the lowest active endpoint cursor (and the export cursor), then
    `_purged_through` drives 410 `INT_CURSOR_EXPIRED`. Files `ARCHIVE_DIR/<owner>/<class>/<yyyy-mm>[.n].jsonl.gz`,
    one `manifest-<stamp>.json` per run (rows, files, sha256, purged). MRP / APS run archiving before their own
    retention deletes and the "inbox payloads / import staging" M1 24 h purge are unchanged (not archived).
    `maintenance_retention` runs per plant daily (job owner = the plant).
26. Audit: `GET /audit/verify` (owner / plant_admin) -> `{ok, checked, first_broken: {id, at} | null}` (WP-U
    request 4); `manage.py audit-verify [--owner]` checks every chain (exit 1 on a break). Org-wide audit for org
    admins is still not built.
27. `manage.py trace-backfill [--owner]` (idempotent); job kind `trace_backfill` exists (maintenance run) but no
    route enqueues it. The Kavach M4 sample issues no lots to its history WOs (backflush effects are cleared
    without postings), so its serial traces reach WOs and receipts but not supplier lots: acceptance 3 needs the
    sample to post component issues (a sample change with new pinned hashes; left to LEAD).
28. Performance changes: `repo_m2.lock_or_create_balances` creates many new balances (> 20) with one
    `INSERT .. ON CONFLICT DO NOTHING` per chunk instead of one savepoint each (IP5); trace writers skip posting
    types without edges.
29. Not built: specific ERP adapters (generic_v1 only, 14 Q1).

**Round 3 (2026-11-06).**
30. `aps.exceptions` read its rows after the read session's rollback (which expires them): the counts and the
    page are now built inside the session (fixes `test_m3_runs_api::test_run_lifecycle_views_publish`).
31. Kavach M4 sample: each history WO receives its lot-controlled components as a supplier lot
    (`receipt_misc`, lot `Hnn-<part>`, supplier lot `SUP-Hnn-<part>`) issued to the WO the same day (net-zero
    stock; M2 / M3 / M4 pinned outcomes unchanged). Every captured CPU serial now traces back to supplier lots
    (possible for the unit), a coating lot forward to its WO's 12 units (acceptance 3; `tests/trace/
    test_kavach_genealogy.py`). Item 27's caveat is void.
32. Org overview (`orgs.service.plant_health`, visible plants only): `kpis {otd, oee, adherence, utilisation,
    fpy}` (M4 KPIs, default period), `late_demand` (open lines past due), `open_triggers`, `integration {enabled,
    pending_deliveries, dead_deliveries, failed_batches_7d, failed_files_7d, last_batch_at, status ok|error|off}`.
33. `shared` SoR conflict log (table `int_sync_state`, per record the row version the last inbound write left):
    an inbound write that changes an item / supplier which was also changed locally since that sync records a
    conflict (the ERP value is applied - last writer wins); reconciliations of `items` list them in
    `sor_conflicts` (`{entity, record_id, ref, synced_version, local_version, erp_version, message,
    detected_at}`).
34. Org-wide audit: `GET /audit/events|export|verify?org_id=` for org admins (sessions only): every plant of the
    organisation; `verify` returns `plants[]` per chain.
35. File drop: `boms`/`bom_lines`/`routings`/`operations` sheets are turned into v1 `bom` / `routing` records and
    go through `inbound.documents` (ERP ECO per changed document, item 11); other sheets as before. The result
    file carries `documents {bom: [...], routing: [...]}`.
36. Webhook proxy: `WEBHOOK_PROXY` (else `HTTPS_PROXY` / `https_proxy`; `direct` forces direct) -> HTTP CONNECT
    tunnel to the checked IP (`WEBHOOK_PROXY_CONNECT=host`: the host name), TLS inside with SNI / certificate check
    for the host, `Proxy-Authorization` from the URL, `NO_PROXY` honoured; the target's address check always runs
    first. No proxy configured -> direct (DEPLOY 13).
37. `slow` tests are deselected unless `-m` is given (`tests/conftest.py`; README "Tests").
38. Migration 0007 was extended in place before release (not yet deployed; a dev database at the earlier 0007
    needs `migrate downgrade 0006_mfg_m4` + `upgrade`): tables `int_sync_state`, `audit_chain_heads`; unique index
    `uq_int_settings_plant_code` on `lower(plant_code)`; `audit_events.chain_hash` 80 chars; UPDATE / DELETE on
    `audit_events` revoked from every role but the owner (also in `scripts/pg_setup_roles.sql`).

**Security review (LEAD, 2026-11-06) - decisions as built.**
- M1 Bearer tokens only on `/api/v1/mfg/`, `/integration/`, `/audit/`; elsewhere 403 `TOKEN_SCOPE` before the
  token is resolved.
- M2 Plant tokens need a workspace principal with `kind = plant`; listed / revocable by every current
  `plant_admin` of that plant; a plant token stops working (401 `AUTH_TOKEN_INVALID`) when its creator is no
  longer an active `plant_admin` there or is disabled.
- M3 `managed_by(org, user)`: the user's only organisation is this one, or JIT-created through `OIDC_ORG_SLUG`
  (no password, an SSO identity). Disable / enable of non-managed members -> 403 `ORG_USER_NOT_MANAGED`; org
  `require_2fa` applies to managed users only. Residual (for LEAD): anybody may still create an organisation and
  add an organisation-less user, which then "manages" that user; restricting org creation is a product decision.
- M4 M1 import commit (`integration.check_import_plan`): sheets of ERP-owned entities -> 409 `INT_ERP_OWNED`
  (purchase sheets: PO rows only); items while ERP-owned: no new items, no ERP-field change (planning fields
  import); BOM / routing rows of a document held by a submitted / approved CR -> 409 `ECO_DOC_LOCKED`.
  `DELETE /items/{id}` while items are ERP-owned -> 409. (Released ERP documents are covered by the sheet rule.)
- M5 Plant codes unique across plants, case-insensitive (index + 409 `INT_PLANT_CODE_TAKEN`); folders come from
  the stored code.
- M6 Password sign-up and sign-in refused (403 `AUTH_SSO_REQUIRED`) for `OIDC_REQUIRED_DOMAINS` and
  `OIDC_ALLOWED_DOMAINS`; the first SSO link to an existing password account clears its password and revokes
  all its sessions.
- minor 1 OIDC state bound to the browser: `sp_oidc` cookie (HttpOnly, SameSite=Lax, path `/api/v1/auth/oidc`,
  10 min) = sha256(state), compared in the callback (400 `AUTH_SSO_STATE` otherwise).
- minor 2 Webhook targets must be global unicast (`ip.is_global`: also CGNAT, documentation, benchmarking),
  including IPv4 embedded in v4-mapped, NAT64 (64:ff9b::/96, 64:ff9b:1::/48 refused), 6to4 and Teredo.
- minor 3 Delivery: one deliverer per endpoint by a session advisory lock on its own connection; each event's
  preparation and its result are separate short transactions (committed per event), the HTTP call runs outside
  any transaction and without row locks, signed with the time of that post.
- minor 4 A batch whose processing raises is stored `failed`; the same key and body (or a `running` row older
  than 15 min) is processed again.
- minor 5 File drop / snapshot files: symlinks are skipped and refused (`O_NOFOLLOW`), size checked by `lstat`
  before reading.
- minor 6 Audit: append-only for the app role (above); keyed chain `k1:<hmac>` with a key derived from the first
  `SECRETS_KEY(S)` (all keys verify; rows after the first keyed one must be keyed); per-owner head row with a
  keyed MAC at commit detects truncation of the newest rows. Without `SECRETS_KEY` the chain stays plain SHA-256
  (tamper evidence only against careless edits). `reassign-owner` no longer rewrites `audit_events.owner_id`.

Performance (local PostgreSQL 16, development machine, `tests/integration_m5/test_m5_perf_s3.py -m slow`):
| # | Measured | Target |
|---|---|---|
| IP1 | 10,000 items (5,000 unchanged) 11.8 s (a batch > 500 -> job); full Kavach master as v1 batches: 1,200 items 2.1 s + 64 BOMs 21.5 s + 61 routings 24.9 s = 48.5 s (every document released through an ERP ECO, one transaction each) | < 30 s / < 60 s |
| IP2 | repeated: posting median 20.8 ms off vs 24.5 / 23.0 ms on -> +2.9 ms (the cost is building the posting record for the event; the earlier S2 figure was +4.85 ms before the trace writers skipped edge-less postings) | < 3 ms (at the limit) |
| IP4 | 1,000 events at 100/s to a healthy in-process endpoint, scheduler every 2 s: p95 event -> delivery 1.29 s, max 1.37 s | p95 < 5 s |
| IP5 | 20,000-row stock file (stock SoR erp -> 40 `count` postings): picked up at the 2nd poll, committed in 19.0 s (38.6 s before the bulk balance insert of item 28) | <= 2 polls, < 20 s (at the limit) |
| TP1 | backward trace of a synthetic unit with 1,382 nodes: 78 ms (median of 3: 88 ms) | < 1 s |
| TP2 | forward trace of a supplier lot in 20 WOs x 100 units (2,021 nodes) 108 ms; recall report of the 2,000 units 155 ms | < 3 s / < 5 s |
| AP2 | 1,000,002 audit rows (209 MB JSONL) streamed in 45.4 s; the server pages 5,000 rows per query (constant memory); the 398 MB RSS growth measured is the in-process TestClient buffering the body, not the generator | < 60 s, constant memory |
| BF1 | Kavach M4 sample: 21 postings with edges + 35 serials -> 40 edges in 0.03 s (the sample has no lot issues, item 27) | < 60 s |
| EP1 | ECO impact on KV-PCB-CPU (draft with one component removed, one qty changed) incl. two in-memory MRP runs: 1.51 s | < 10 s |

IP3 / AP1 as measured in S2 (`test_m5_perf.py`).

### 15.WP-U UI

**Built (2026-11-05); types aligned to `integration/fixtures/example_m5.json` and the live S1/S2 routes.**

Screens:
- **U1 sign-in and identity:**
  - Sign-in page:
    - "Sign in with <label>" button when `/auth/config.sso_enabled`; the required domains are named.
    - The password form is hidden when `password_login` is false.
    - OIDC callback errors (`?sso_error=`/`?error=`) are shown in plain words.
    - Second step after the password (403 `AUTH_2FA_REQUIRED` + `pending_token`): a 6-digit code or a recovery code.
  - `/account/security` (two-step verification):
    - Turning it on shows the QR code, drawn in the browser by our own encoder (`src/lib/qrcode.ts`, byte mode, level M, v1-20). It is verified by an independent decoder (format bits, Reed-Solomon syndromes, payload) on 5 strings.
    - The key is also shown as text; the user confirms with a code, and recovery codes are shown once (copy / download / "I saved them").
    - Once on: new codes, or turn off.
    - Forced setup (`setup_required`) runs before a session exists, using the `X-SP-Pending-Login` header. It ends with one more code via `/auth/login/totp`; the same 30 s step cannot be used twice.
    - `totp_setup_required` in a session sends the guard to this page.
  - `/account/tokens` (personal) and Integration, Plant tokens (plant): guided presets (read only, ERP / middleware, events only), the full scope list behind "Choose permissions", 30/90/180/365 days, the token shown once, revoke.
  - `/orgs` and `/orgs/:orgId`:
    - Overview: per-plant OTD/OEE, late demand, open triggers, integration health.
    - Plants: create, rename, people and roles incl. `plant_admin`, open.
    - People: add by email, admin/member, remove.
    - Master data publish.
    - Settings: name, require 2FA.
  - The plant switcher groups plants under their organisation when `/workspaces` sends `org`.
- **U2 integration console** (`/mfg/integration/*`, `integration_admin`):
  - Overview: failed / waiting deliveries, last data in, file drop, and who owns what.
  - Settings: on/off, plant code, format (`generic_v1` only, 14 Q1), a system-of-record table per entity, goods receipts booked here or in the ERP (14 Q2), file drop and export.
  - Webhooks:
    - The signing secret is generated in the browser and shown once (the API requires one on create).
    - Edit can rotate the secret; "Send now" calls `/endpoints/{id}/test`.
    - Address-guard errors are shown.
  - Deliveries: `pending` with attempts > 0 is shown as "Retrying". Dead and retrying ones can be retried.
  - Data in: batches, and per-record results with the reason. `INT_UNMAPPED_VALUE` links to Code mappings.
  - Events out: the pull feed with each event's data.
  - File drop: the inbox list, recent files, mapping profiles.
  - Code mappings: `{rows}`.
  - Reconciliation:
    - Upload the ERP stock list (CSV `item_ref,location_code,lot_code,qty` or v1 JSON; `ref`/`as_at` are filled in) and send it inline.
    - Results are listed per entity and kind.
    - "Review as stock count" opens the count posting form prefilled from router state; nothing is posted until the user confirms.
- **ERP-owned indicators:**
  - Item form: the ERP fields (4.4) are disabled with a "From ERP" badge, plus a banner.
  - BOM, routing, PO, demand and supplier pages: a banner.
  - The receive dialog says who books goods receipts and disables posting when the ERP does.
  - 409 `INT_ERP_OWNED` is explained with its fields everywhere (`errorText`).
  - The indicators read `GET /integration/settings`. When the role cannot read it, nothing is marked and the 409 still explains a refused save.
- **U3:**
  - `/mfg/trace`:
    - Scan or type `S:`/`L:`/WO (resolved by #200, else a serial search).
    - Backward / forward, depth, include possible.
    - Tree and layered SVG graph. Exact = solid line, "exact" tag; possible = dashed line with "?", "possible" tag.
    - Trace again from a node, or start a recall.
  - `/mfg/trace/where-used`.
  - `/mfg/recalls` (new from a trace node or lot, list) and `/:id`:
    - Units by status with precision and path.
    - Per customer and programme.
    - Lots on hand, and quarantine to a quarantine location with a confirmation (`inventory`).
    - Excel and print.
  - `/mfg/eco` and `/:id`:
    - Create with effectivity (date / use-up / serial).
    - Add draft BOM / routing (picker of an item's drafts), with dispositions per document.
    - Submit; approve (blocked for the submitter unless owner / plant admin); reject with a reason; cancel; implement. `ECO_RELEASE_BLOCKED` issues are listed.
    - Impact tab: structure delta, open WOs / planned orders, purchases no longer needed, phased-out stock, MRP date moves, and the use-up date with "Take effect on that date".
- **U4:**
  - `/mfg/transfers`: outgoing / incoming, create (destination = another plant of the same org from `/workspaces`), open / cancel / close.
  - Ship and receive post `transfer_ship` / `transfer_receipt` with `transfer_line_id`.
  - `/mfg/audit`: filters, CSV / JSON-lines export, chain check, and the chain hash per row.
  - Nav: a new "Control" group (ECO, transfers, integration, audit); "Trace and recall" under Execution.

Interpretations:
- **Orgs are addressed by id** in the API, and so in the UI routes.
- **Transfer `direction`** is `out`/`in` in the fixture; the UI accepts both forms.
- **ID-only payloads:**
  - ECO items carry only document ids; their labels are loaded per id.
  - Transfer lines carry `item_id`; part numbers come from the item cache.
- **Recalls** use the fixture's flat `report` (`units/lots/wos/by_customer/by_program/open_pos`); the counts are computed in the UI.
- **Shared code changed (additive):**
  - `mfgRequest` gained `v1Request` / `v1Download` for the non-`/mfg` areas.
  - `PostingForm` accepts a router-state prefill.
  - The accounts e2e config sets a test-only `SECRETS_KEY`.

Requested from WP-S (none blocking the screens):
1. `/workspaces` items with `org {id, slug, name}` and `plant_code`, so the switcher can group by organisation and transfers can pick the destination plant reliably.
2. A read of the system of record for every role (e.g. in `/mfg/plant` or `/meta`). The ERP-owned indicators currently need `integration_admin`.
3. `POST /integration/deliveries/{id}/park`, to unblock a FIFO endpoint without deleting it. The UI has only Retry.
4. `GET /audit/verify` (the `audit-verify` check as an endpoint). The UI explains when it is missing.
5. `GET /integration/reconciliations/{id}/export` (design 9). The button is hidden until it exists.
6. Org member disable (design 6: org admins can disable users). `OrgMemberUpdate` takes only `org_role`.
7. `locked_by_cr_id` on BOM / routing reads, for a "part of ECO-…" notice. `ECO_DOC_LOCKED` is already explained when saving.
8. Trace, recall, ECO and transfer data are still fixture-backed (S3 / S4).

e2e:
- `frontend/e2e/m5-integration.spec.ts` (2 tests, main config).
  - Test 1 covers:
    - settings and SoR;
    - the ERP-owned item form plus the API's 409;
    - an inbound batch with one record rejected for an unmapped unit;
    - the code mapping, after which the record is accepted;
    - the webhook private-address guard message;
    - a reconciliation from an uploaded CSV showing exactly one difference.
  - Test 2 covers trace tree and graph, recall from a trace node, ECO impact, transfers, and audit rows with a CSV download.
- `frontend/e2e/accounts/m5-login.spec.ts` (accounts config).
  - The SSO button follows `/auth/config`.
  - 2FA enrolment uses the QR code and key; codes are computed in the test (RFC 6238).
  - Sign-in works with a recovery code; a wrong code shows a message; then a TOTP code signs in.
  - A personal token is created, shown once, and revoked.
