# SuperPlanner M7 - Regulated foundation and quality (design + plan + acceptance)

Status: design for build. Milestone M7 of `docs/MEDDEV-GAP-PLAN.md`. Builds on M1-M6 as built (`docs/M1-DESIGN.md` ..
`docs/M6-DESIGN.md`, cited "M1 n" .. "M6 n", incl. implementation notes), the UX standard (`docs/UX-STANDARD.md`,
"UX n") and the platform (`docs/ARCHITECTURE.md` 25, `docs/DEPLOY.md`). Their conventions apply unchanged and are
not restated (ids, `row_version` + If-Match, error envelope, `owner_id` tenancy = one plant, one permission per
route, audit on every write, outbox events, expand migrations). Interpretations go to section 14 only.

Scope: 21 CFR Part 11 controls (electronic signatures and audit trail) for regulated records; quality module
(sampling schemes, inspection plans, inspection lots and results, holds and usage decisions, NCR/MRB with
dispositions, CAPA, complaints with field actions); equipment and calibration blocking use; QA roles; French
(Canada) UI; a medical-device sample plant; pilot hosting profile (docs).

**Position.** These controls are designed to *support* Part 11, ISO 13485 and 21 CFR 820. The customer validates
the system for its intended use and owns procedures (signature certification to FDA, training, SOPs).

## 0. Decisions

1. **Signatures are records, not flags.** `esig_signatures` stores signer (id, legal name, user name snapshot),
   server time from the database clock, meaning, auth method, policy version, the record type/id/version and the
   **sha256 of a canonical content snapshot** that is stored with it; an HMAC over the row (key from `SECRETS_KEY`)
   and an audit event in the M5 hash chain in the same transaction. A record changed after signing shows the
   signature as "record changed since signing" and signed terminal states are locked.
2. **One-call signing on the action itself.** Every signable action endpoint takes an optional `signature` object
   (meaning, user name, password, TOTP code or SSO step-up token, content hash, comment). The UI first calls
   `GET /mfg/esig/preview` (what will be signed, its hash, policy, next step), shows it in the signature dialog, and
   sends the action with the hash; a different current hash -> 409 `ESIG_CONTENT_CHANGED`. Multi-step policies
   (reviewed -> approved) call the same action per step; intermediate steps answer 202 and do not change state.
3. **Re-authentication at every signing**: user name + password (both components, every time; Part 11 11.200),
   plus TOTP when the policy says `password_totp`. SSO users sign with an **OIDC step-up** (`prompt=login`,
   `max_age=0`, same `sub`, `auth_time` fresh, optional required `amr`/`acr` for MFA) that yields a single-use
   5-minute token. Three failures in 15 minutes lock signing for that user for 30 minutes and notify plant admins
   and QA approvers.
4. **Policies per record type and action**, per plant, versioned: required steps (meaning + roles that may sign
   it, held explicitly; owner/plant_admin do not satisfy role-restricted steps), distinct signers, author excluded,
   auth level. Defaults are seeded (4.3); changing a policy is itself a signed action.
5. **Part 11 mode per plant** (`mfg_plant.part11_mode`, off by default, switched on by a signed owner action, not
   switchable off through the API). When on: policies are enforced, regulated records require a change reason,
   audit events of regulated records carry field-level old/new values, signed or referenced regulated records
   cannot be deleted. When off, the quality module works without signatures (non-regulated customers).
6. **Holds become first-class** (`mfg_lot_holds`, lot or serial, by source: inspection, NCR, recall, field action,
   manual). M2 `lots.hold` is derived (any open hold); a hold is released only by its source document. MRP nets a
   lot whose only holds are inspection holds as inspection supply (M2 3.2 timing); other holds are not nettable.
7. **Inspection lots are created by the events that need them**: PO receipt (incoming plan), start of an
   `inspection_gate` operation (in-process plan), WO receipt (final plan), or manually. Incoming and final lots hold
   the material until a usage decision; a gate operation cannot complete before acceptance. Sampling comes from
   **configurable schemes** (lot-size ranges -> code letter -> n/Ac/Re per AQL, normal and tightened, switching
   rules); SuperPlanner ships the mechanism and a test-only example, the customer loads its licensed tables.
8. **NCR dispositions move material through the existing ledger and floor log**, never beside them: scrap ->
   `issue_misc SCRAP`, return to supplier -> `issue_misc RTV` + outbox, rework -> a rework WO (`kind rework`),
   use-as-is -> hold release (stock) or good quantity (WIP). WIP nonconformances are reported on the floor as
   `qty_nc` and resolved by a new append-only floor event `nc_disposition`.
9. **CAPA and complaints are lean and switchable to an eQMS** (`qa_settings.capa_sor`, `complaint_sor`:
   `superplanner|external`; external = records hold an `external_ref` and links only). **Field actions** are built
   on M5 recall reports: scope frozen from the recall snapshot, per-unit/lot/customer status, effectiveness.
10. **Calibration blocks use where it matters**: result entry with a gauge not in calibration is refused; a line
    with invalid linked equipment cannot start operations and is unavailable to APS; tool pools with tracked units
    count only valid units. No override; the fix is a calibration or taking the equipment out of the link.
11. **French (Canada)** through the existing keyed strings: `fr-CA` dictionaries, a language preference, locale
    formatting, localized error codes; professional translation with a glossary. Server-generated notification and
    digest text uses a small backend catalog.
12. **Lean delivery**: WP-S (one backend developer), WP-U (one UI developer), S0 contract freeze, targeted tests,
    one full backend suite at the end. Migration `0010_m7` (expand). No new Python or npm packages.

## 1. Scope and principles

**Principles** (in addition to M1-M6): R1 a regulated record is never silently changed: every change has actor,
time, old/new values and (in Part 11 mode) a reason; R2 signed content is exactly what the signer saw (hash
match); R3 quality states gate material and lines through holds and blocks, never through planner discipline;
R4 hard rules have no override path, deviations are documented through NCRs.

**Out of M7** (gap plan): eDHR, labels/UDI, server-side PDF (M10); forecasting, rate planning, sterilisation
(M8); SPC charts (data captured now, charts later); supplier qualification, training records, document control
(customer eQMS); regulatory report submission (data only).

## 2. Package layout (ownership in 11)

```
backend/superplanner/
  esig/           model.py content.py (canonical JSON + per-type content) policy.py (defaults, step logic)
                  service.py (verify credentials, record, HMAC, lockout) stepup.py router.py
  qa/             model.py (pure pydantic) sampling.py (scheme resolve, switching) evaluate.py (results -> verdict)
                  holds.py ncr.py capa.py complaints.py field_actions.py equipment.py
  api/mfg/        db_models_m7.py repo_m7.py router_m7.py services/{qa_*,esig,part11}.py
  api/audit_diff.py   field-level diff + reason header handling (used by mfg services of regulated entities)
  i18n/           messages_en.json messages_fr_CA.json (notification/digest templates)
  mfg/samples/meddev_m7.py   QA, equipment and history additions to the existing `meddev` sample (12)
frontend/src/qa/**  frontend/src/components/SignatureDialog.tsx  frontend/src/lib/strings/{quality.ts, fr-CA/*.ts}
```

## 3. Data (migration `0010_m7`, expand, additive; downgrade drops)

IDs: `esp_` policy, `esg_` signature, `est_` step-up, `ssc_` scheme, `ipl_` plan, `ich_` characteristic, `ilt_`
inspection lot, `irs_` result, `hld_` hold, `ncr_`, `ncd_` disposition, `cap_` CAPA, `cpa_` CAPA action, `cmp_`
complaint, `fac_` field action, `fau_` field action unit, `eqp_` equipment, `cal_` calibration, `att_` attachment,
`qlk_` link, `p1x_` export. Numbers per plant: `IP-000001`, `IL-000001`, `NCR-000001`, `CAPA-000001`,
`CMP-000001`, `FA-000001`.

| Table | Columns (plant-owned unless noted) |
|---|---|
| `esig_policies` | record_type S32, action S32, steps JSON `[{meaning, roles[]}]`, auth S16 (`password`, `password_totp`), distinct_signers Bool, exclude_author Bool, version Int; uq (owner_id, record_type, action) |
| `esig_signatures` | record_type, record_id S64, record_version Int, action, step Int, meaning S16, signer_id FK users, signer_legal_name S200, signer_username S254, signed_at DT (DB clock), auth_method S16 (`password`, `password_totp`, `sso`, `sso_mfa`), policy_id, policy_version, content_hash S64, content JSON, comment S500, status S16 (`valid`, `superseded`), audit_event_id Int, mac S80, client_ip S64, session_ref S64 (sha256 of session id); ix (owner_id, record_type, record_id), (signer_id, signed_at) |
| `esig_stepups` (platform) | token_hash PK, user_id, session_ref, amr JSON, auth_time DT, expires_at, used_at N |
| `qa_sampling_schemes` | code S32, name, kind S8 (`fixed`, `percent`, `full`, `table`), fixed_n Int N, percent Dbl N, table JSON N, switching Bool, status (`draft`, `approved`, `obsolete`), note |
| `qa_inspection_plans` | number, version Int, item_id FK, scope S16 (`incoming`, `in_process`, `final`), operation_seq Int N, supplier_id FK N, customer S100 N, scheme_id FK, inspection_level S8, aql JSON `{critical, major, minor}`, status, effective_from Date N, supersedes_id N, approved_at N, note; ix (owner_id, item_id, scope, status) |
| `qa_characteristics` | plan_id FK CASCADE, seq, code S32, name, kind (`variable`, `attribute`), severity (`critical`, `major`, `minor`), unit S16 N, nominal/lsl/usl Dbl N, method S500, equipment_class S32 N, sample_override JSON N, destructive Bool |
| `qa_inspection_lots` | number, plan_id, plan_version, scope, item_id, lot_id N, wo_id N, wo_operation_id N, posting_id N, supplier_id N, lot_size Dbl, sampling JSON (per characteristic `{n, ac, re, severity_state}`), status (`open`, `in_progress`, `ready`, `accepted`, `rejected`, `cancelled`), verdict JSON N, decision S8 N, decided_by/at N, ncr_id N, due_at DT; ix (owner_id, status, scope) |
| `qa_results` | inspection_lot_id FK, characteristic_id, sample_no Int, value Dbl N, passed Bool, defects Int, equipment_id N, note, entered_by, entered_at (DB clock), corrects_result_id N, superseded Bool, client_batch_id S64 N; ix (inspection_lot_id, characteristic_id, sample_no) |
| `qa_switching_states` | plan_id, item_id, supplier_id N, state (`normal`, `tightened`), history JSON (last 5 decisions); uq |
| `mfg_lot_holds` | lot_id N, serial_id N, item_id, source S16 (`inspection`, `ncr`, `recall`, `field_action`, `manual`), source_id S64 N, reason S500, placed_by, placed_at, released_by N, released_at N, release_signature_id N; ix (lot_id) WHERE released_at IS NULL |
| `qa_ncrs` | number, title, source S16, severity, item_id, lot_id N, serials JSON, supplier_id N, wo_id N, wo_operation_id N, inspection_lot_id N, complaint_id N, place S8 (`stock`, `wip`), qty_nc Dbl, defect_codes JSON, description, containment, investigation, status, capa_required Bool, author_id, closed_at N, external_ref N |
| `qa_ncr_dispositions` | ncr_id FK CASCADE, line_no, kind S16 (`scrap`, `rework`, `use_as_is`, `return_to_supplier`), qty, location_id N, rework_routing_id N, rework_to_seq Int N, instructions, justification, implemented_at N, refs JSON (posting ids, WO id, floor event id) |
| `qa_capas` | number, title, kind (`corrective`, `preventive`), problem, risk JSON `{severity 1-5, occurrence 1-5, level}`, owner_user_id, due_on, root_cause JSON `{method, text}`, effectiveness JSON `{criteria, check_due_on, result, evidence}`, status, external_ref N |
| `qa_capa_actions` | capa_id FK CASCADE, seq, kind (`correction`, `corrective`, `preventive`), description, owner_user_id, due_on, status (`open`, `done`, `cancelled`), done_at N, evidence, eco_id N |
| `qa_complaints` | number, received_on, aware_on, channel, customer, country S2, item_id N, lots JSON, serials JSON, qty_affected, description, event_type, reportability JSON `{assessed, reportable, regimes[], due_on, report_ref}`, investigation, status, external_ref N |
| `qa_field_actions` | number, title, kind (`recall`, `correction`, `removal`, `safety_notice`, `software_update`), class S4 N, regimes JSON, strategy, recall_id FK `mfg_recalls`, status (`draft`, `approved`, `in_progress`, `completed`, `closed`, `cancelled`) |
| `qa_field_action_units` | field_action_id FK CASCADE, kind (`serial`, `lot`), serial_id N, lot_id N, item_id, customer, demand_line_id N, qty, status (`pending`, `notified`, `acknowledged`, `returned`, `corrected`, `destroyed`, `not_reachable`), note, updated_by/at; ix (field_action_id, status) |
| `qa_equipment` | code S32 (asset tag), name, kind S16 (`gauge`, `instrument`, `fixture`, `tool`, `line_equipment`, `chamber`), equipment_class S32, line_id N, tool_pool_id N, serial_no, manufacturer, location, status (`active`, `out_of_service`, `retired`), calibration_required Bool, interval_days Int N, grace_days Int, last_calibrated_on N, due_on N, procedure_ref, provider S16 |
| `qa_calibrations` | equipment_id FK, performed_on Date, performed_by N, provider_name, result (`pass`, `adjusted_pass`, `fail`), as_found, as_left, certificate_ref, next_due_on |
| `qa_attachments` | entity_type, entity_id, filename S200, content_type S64, size Int, sha256 S64, data LargeBinary, uploaded_by, uploaded_at |
| `qa_links` | from_type, from_id, to_type, to_id, created_by/at; uq; types `ncr, capa, complaint, field_action, eco, inspection_lot, equipment` |
| `part11_exports` | params JSON, status, file_path, manifest JSON, sha256, requested_by, finished_at |

Columns: `users.legal_name` S200 N, `esig_enrolled_at` N, `esig_ack_version` S16 N, `esig_revoked_at` N,
`esig_failed` JSON (recent failure times), `esig_locked_until` N; `audit_events.changes` JSON N, `reason` S500 N,
`signature_id` S64 N, `record_version` Int N; `mfg_plant.part11_mode` Bool (false), `qa_settings` JSON;
`mfg_work_orders.kind` S8 (`standard`), `ncr_id` N; `mfg_inv_transactions.ncr_id` N; `mfg_unit_serials.hold` Bool
(false); `mfg_floor_events.qty_nc` Dbl N, `ncr_id` N, `defect_code` S32 N; `orgs.session_idle_minutes` Int N.
Jobs: kinds `part11_export`, `qa_due_scan` (daily: calibration due, CAPA/complaint due, overdue inspection lots;
target `maintenance_runs`). Retention (M5 7): all `esig_*`, `qa_*`, holds and exports = indefinite. Reset and
reassign registries include the plant-owned tables. Server defaults dropped after the add (M4 3.1 rule).

`qa_settings`: `defect_codes [{code, name, severity}]`, `mrb_location_id`, `cal_due_warning_days` (14),
`inspection_due_hours {incoming: 48, in_process: 4, final: 24}`, `reportability_rules [{regime, event_type, days}]`
(defaults: `fda_mdr` 30 all; `hc_mdpr` 10 death/serious, 30 other; customer confirms), `capa_sor`, `complaint_sor`
(`superplanner`), `final_release_role` (`qa_approver`).

## 4. Part 11 controls (`esig/`, `api/audit_diff.py`)

### 4.1 Enrolment and identity

A person signs only after enrolment: `POST /auth/esig/enroll {legal_name, password | stepup_token,
acknowledgement: true}` stores the legal name and the acknowledgement text version ("I agree that my electronic
signature is the legally binding equivalent of my handwritten signature", text in both languages). Plant/org admins
revoke (`POST /orgs/{org}/members/{id}/esig-revoke`). Users who signed anything cannot be deleted (409
`ESIG_USER_HAS_SIGNATURES`; disable instead), so user names are never reused. Plant/service principals and API
tokens never sign (403 `ESIG_NOT_ALLOWED`).

### 4.2 Signing

`SignatureInput {meaning, content_hash, username, password?, totp_code?, stepup_token?, comment (0..500)}`.
Server steps in the action's transaction: (1) part11 mode on and a policy for `(record_type, action)` -> signature
required (missing -> 422 `ESIG_REQUIRED` with the preview in `details`); mode off -> `signature` ignored; (2)
enrolled, not revoked, not locked (423 `ESIG_LOCKED`, `details.until`); (3) `username` equals the session user's
user name (case-insensitive) and credentials verify: argon2 password (local), TOTP (M5 3.2 rules, replay refused)
when `password_totp`; SSO users: valid unused step-up token of this session (with MFA `amr` when `password_totp`,
else 422 `ESIG_MFA_UNAVAILABLE`), or, when `ESIG_LOCAL_CREDENTIALS=true` (IdP
without step-up), a signing password + TOTP set at enrolment; failure -> 422 `ESIG_AUTH_FAILED` (`details.remaining`), the third failure in 15
minutes locks 30 minutes, audits `esig.lockout` and notifies; (4) next step of the policy: meaning matches (422
`ESIG_MEANING`), signer holds one of the step roles (403 `ESIG_ROLE`), distinct from earlier signers (409
`ESIG_SAME_SIGNER`), not the author when `exclude_author` (409 `ESIG_AUTHOR`); (5) current content hash ==
`content_hash` (409 `ESIG_CONTENT_CHANGED`, `details.current_hash`); (6) clock check (4.6); (7) insert signature,
audit event `esig.signed` (with `signature_id`), MAC; (8) last step -> the action runs and its response carries
`signatures`; else 202 `{status: "pending_signatures", record_type, record_id, signatures, next_step}`.

Editing a record that has pending (non-final) step signatures marks them `superseded` (audit) and the flow restarts.
After the final step, edits follow the record's state machine (signed terminal states are locked: 409
`ESIG_RECORD_LOCKED`; plans change through a new version).

**Manifestation** (11.50): every record response carries `signatures: [{id, meaning, meaning_label, signer_legal_name,
signer_username, signed_at, signed_at_local (plant zone with UTC offset), auth_method, step, status,
content_matches_current}]`; screens, print views and exports show "Approved by Marie Tremblay (mtremblay) on
2026-11-23 14:05:12 EST (UTC-05:00)".

**Linking** (11.70): `content.py` registry `content(record_type, record) -> dict`: the business fields of the
record (ids, numbers, quantities, decisions, child lines, attachment sha256 list; no `row_version`, timestamps or
signatures). Canonical JSON: sorted keys, separators `,` `:`, UTF-8, floats as `format(x, ".15g")`, dates ISO,
datetimes UTC `Z`. Snapshot <= 256 KB (422 `ESIG_CONTENT_TOO_LARGE`). `GET /mfg/esig/signatures/{id}/verify` ->
`{mac_ok, chain_ok, content_hash_ok (snapshot rehash), content_matches_current, record_version_signed,
record_version_current}`.

### 4.3 Policies (defaults seeded per plant; meaning vocabulary fixed)

Meanings: `authored, reviewed, approved, released, rejected, verified, performed, closed`.

| record_type.action | Default steps (meaning: roles) | Auth |
|---|---|---|
| `inspection_plan.approve` | approved: qa_approver | password |
| `sampling_scheme.approve` | approved: qa_approver | password |
| `inspection_lot.decide` (incoming, in_process) | released or rejected: qa_inspector, qa_engineer, qa_approver | password |
| `inspection_lot.decide` (final) | released or rejected: `final_release_role` | password_totp |
| `hold.release` (manual, recall, field action) | released: qa_approver | password |
| `ncr.approve` | reviewed: qa_engineer; approved: qa_approver (distinct, author excluded) | password |
| `ncr.close` | closed: qa_approver | password |
| `capa.approve_plan` / `capa.verify` / `capa.close` | approved / verified / closed: qa_approver | password |
| `complaint.close` | closed: qa_engineer, qa_approver | password |
| `field_action.approve` / `field_action.close` | approved / closed: qa_approver | password_totp |
| `calibration.record` | performed: metrology, qa_engineer | password |
| `equipment.return_to_service` | approved: qa_engineer, qa_approver | password |
| `eco.approve` (M5) | approved: approver, qa_approver | password |
| `esig_policy.update` (fixed) | approved: qa_approver | password_totp |
| `plant.part11_on` (fixed) | approved: owner, plant_admin | password_totp |

Policies may add steps, change roles (must be plant roles) and raise auth; they cannot remove the last step of
fixed actions (422 `ESIG_POLICY_INVALID`). `inspection_lot.decide` meanings: `released` = accept, `rejected` =
reject.

### 4.4 Audit trail of regulated records

Regulated entities (registry `PART11_ENTITIES`): items, BOMs, routings and operations, plant (QA settings,
part11), locations, lots and holds, work orders (status actions), ECOs, plant members/roles, all `qa_*`, equipment,
calibrations, signature policies. For updates, deletes and status actions of these, services call
`audit(..., before=, after=, reason=)`: `changes = [{path, old, new}]` from the records' JSON dumps (lists diffed by
key `id`, else `seq`/`line_no`; path like `lines[line_no=3].qty`; max 500 changes; strings over 1,000 chars
truncated with `old_sha256`/`new_sha256`). Reason: header `X-SP-Change-Reason` (percent-encoded UTF-8, 1..500
after decoding) or the signature comment of a signed action; in Part 11 mode missing -> 422
`AUDIT_REASON_REQUIRED` (creates excepted; imports take one `change_reason` for the commit; inbound integration
uses "ERP sync <batch number>"; bulk actions UX 10.2 take `change_reason` in the body). Deletes in Part 11 mode:
regulated records that are signed, released or referenced -> 409 `PART11_DELETE_NOT_ALLOWED` (obsolete/cancel
instead). Ledger, floor events, results and trace edges are already append-only.

`GET /mfg/audit/record?entity_type=&entity_id=` -> the record's events with changes, reasons and signatures
(paged, oldest first), perm `audit_view`.

### 4.5 Inspection readiness export

`GET /mfg/part11/records/{record_type}/{record_id}` -> package `{record, signatures (with manifestation), audit
(events with changes), attachments [{id, filename, size, sha256}], links, generated_at, generated_by,
package_sha256}`; the UI has a print view of it. `POST /mfg/part11/exports {from, to, record_types[]}` -> job
`part11_export` writing `ARCHIVE_DIR/<owner>/part11/<id>.zip` (`manifest.json` with counts and sha256 per file,
`records.jsonl`, `signatures.jsonl`, `audit.jsonl`, `attachments/`), download via `GET .../exports/{id}/download`
(422 `PART11_NO_ARCHIVE_DIR` when unset). Also `manage.py part11-export`.

### 4.6 Time and sessions

All signature, decision and result times come from the database clock (`clock_timestamp()`), stored UTC, shown in
the plant zone with offset. App/DB skew is measured at start and every 5 minutes; `GET /meta/time` -> `{app_utc,
db_utc, skew_ms}`; readiness gains `clock_skew_ms`; skew > `ESIG_MAX_CLOCK_SKEW_MS` (2,000) -> signing refused with
503 `ESIG_CLOCK_SKEW`. DEPLOY adds: chrony/NTP to an approved source on every host, monitored. Org setting
`session_idle_minutes` (Part 11 plants: recommended 15) ends idle sessions of the org's people (min with
`SESSION_IDLE_DAYS`). Config check: `ESIG_ENABLED` (default true) requires `SECRETS_KEY(S)` when any plant is in
Part 11 mode.

## 5. Inspection (`qa/sampling.py`, `qa/evaluate.py`)

### 5.1 Schemes and plans

`table` scheme: `{levels: ["S-1".."S-4","I","II","III"], lot_size_ranges: [{min, max, letters: {level: letter}}],
plans: {normal|tightened: {letter: {aql: {n, ac, re}}}}, switching: {to_tightened: {rejected: 2, of_last: 5},
to_normal: {consecutive_accepted: 5}}}`; values entered resolved (no arrows); validation: ranges contiguous from 1,
`n >= 1`, `0 <= ac < re <= n + 1` (422 `QA_SCHEME_INVALID` with `details.loc`). Resolve(lot_size, level, aql,
state) -> `{n, ac, re}`; `n >= lot_size` -> 100% (`n = lot_size`, ac/re kept). `fixed` -> n, ac 0, re 1;
`percent` -> ceil(lot_size x p); `full` -> lot_size. Approved schemes are immutable (new code to change).

Plans: one approved plan per (item, scope, operation_seq, supplier/customer) on a date; specific (supplier for
incoming, customer for final) beats generic. Approve (signed) checks: >= 1 characteristic, scheme approved, item
lot-controlled for incoming/final (422 `QA_ITEM_NOT_LOT_CONTROLLED`), `operation_seq` present on a released
routing of the item for in-process (`QA_PLAN_OPERATION_UNKNOWN`), lsl <= nominal <= usl; previous approved version
with the same key becomes `obsolete` at `effective_from`. Copy = new draft version. Characteristic AQL = plan
`aql[severity]` unless `sample_override {scheme_id, level, aql}`.

### 5.2 Inspection lots

| Trigger (same transaction) | Lot | Effect |
|---|---|---|
| `po_receipt` line of an item with an effective incoming plan | lot size = received qty; supplier = PO supplier | `inspection` hold on the received lot |
| floor `start` of an `inspection_gate` operation with an effective in-process plan (first start only) | size = operation input qty | `complete` of that operation refused until accepted: 409 `QA_INSPECTION_OPEN` |
| `wo_receipt` (manual or floor auto) of an item with an effective final plan | per (WO, lot); later receipts add to the size while not decided; after a decision 409 `QA_LOT_DECIDED` (use a new lot code) | `inspection` hold on the lot |
| `POST /qa/inspection-lots` (re-inspection, customer request) | given | hold if `hold: true` |

Sampling frozen on creation from the plan, scheme, size and switching state. Due time = creation +
`inspection_due_hours[scope]` (overdue -> notification).

Results (append-only): `POST /qa/inspection-lots/{id}/results {client_batch_id, results: [{characteristic_id,
sample_no, value? | passed?, defects?, equipment_id?, note?, corrects_result_id?, reason?}]}` (batch <= 2,000;
replay of `client_batch_id` -> stored response). Rules: `sample_no` 1..n (422 `QA_SAMPLE_OUT_OF_RANGE`); variable
needs `value` (defective iff outside [lsl, usl]); attribute needs `passed` (+ `defects`); `equipment_class` set ->
equipment of that class required, active and valid at entry time (409 `QA_EQUIPMENT_NOT_CALIBRATED`, `details
{equipment, due_on, status}`); corrections need a reason and supersede the earlier row; decided lots refuse results
(409 `QA_LOT_DECIDED`). Evaluation per characteristic: defective units d over its entered samples; `d >= re` ->
`reject`; all n entered and `d <= ac` -> `accept`; lot verdict = reject if any characteristic rejects, accept when
all accept, else pending. Status `ready` when the verdict is final.

Decision `POST /qa/inspection-lots/{id}/decision {decision: accept|reject, note, ncr_id?, signature}`: accept
against a reject verdict only with `ncr_id` of an approved NCR with a `use_as_is` disposition for this lot (else 409
`QA_DECISION_CONTRADICTS`); accept before verdict 409 `QA_LOT_NOT_READY`. Accept -> releases the lot's
`inspection` hold / unblocks the gate operation; reject -> NCR created (`source inspection`, qty = lot size, status
`open`, hold moved to source `ncr`), gate operation stays blocked until the NCR is implemented. Switching state is
updated (incoming per supplier). Outbox `qa.inspection_decided`.

### 5.3 Holds (`qa/holds.py`)

Every hold row places/keeps `lots.hold = true` (serials: `mfg_unit_serials.hold`); `lots.hold` recomputed on each
place/release. M2 `PUT /lots/{id} {hold}` maps to `manual` holds (place / release own manual holds); releasing
while other holds exist -> 409 `QA_HOLD_ACTIVE` (`details.holds`). M5 recall quarantine places `recall` holds.
Held serials cannot be consumed, shipped or transferred (422 `INV_SERIAL_ON_HOLD`). `POST /qa/holds {lot_id |
serial_id, reason}` (manual), `POST /qa/holds/{id}/release {signature}` (manual/recall/field_action sources only;
inspection and NCR holds 409 `QA_HOLD_OWNED` - release through the document). MRP snapshot (M2 8.2): a lot whose open
holds are all `inspection` is an `inspection` supply (avail = max(as_of, received_on + receiving_days)); kitting
never reserves held lots.

## 6. NCR / MRB (`qa/ncr.py`)

States: `draft -> open -> proposed -> approved -> implemented -> closed`, `cancelled` from draft/open/proposed.
Open places an `ncr` hold on the lot or serials (stock); WIP NCRs come from the floor: `report`/`complete` gain
`qty_nc` and `defect_code` (counted against input like scrap; `qty_nc > 0` creates or appends to an open NCR of
that operation, returned in the event response). Propose: dispositions with `sum(qty) == qty_nc` (422
`QA_DISPOSITION_QTY`); `use_as_is` needs `justification` (422 `QA_JUSTIFICATION_REQUIRED`); `rework` needs
`rework_routing_id` (stock) or `rework_to_seq <= operation seq` (WIP); `return_to_supplier` only with a supplier.
Approve: signed (`ncr.approve`, two steps by default). Implement (`ncr_edit`; one transaction, M2 lock order):

| Kind | Stock | WIP |
|---|---|---|
| scrap | `issue_misc` reason `SCRAP` from `location_id` (lot) | floor event `nc_disposition` adds `qty_scrap` |
| rework | rework WO (`kind rework`, `ncr_id`, item, qty, routing, component = the item itself 1:1; the held lot may be issued to this WO only) received back into the same lot code | `nc_disposition` adds `qty_rework_in` at `rework_to_seq` |
| use_as_is | nothing posted | `nc_disposition` adds `qty_good` (last operation -> `wo_receipt`, M4 4.3) |
| return_to_supplier | `issue_misc` reason `RTV`, outbox `qa.rtv` | not allowed (422) |

All postings and events carry `ncr_id`. Hold release: when every stock disposition is implemented and no rework WO is
open the `ncr` hold is released, unless the lot is fully consumed. Close (signed): all implemented, rework WOs
completed or closed, `capa_required` -> a linked CAPA exists (409 `QA_NCR_NOT_CLOSABLE`, `details.missing`).

## 7. CAPA, complaints, field actions

**CAPA** (`capa_sor = superplanner`): `draft -> investigation -> plan_approval -> implementation ->
effectiveness_check -> closed` (+ `cancelled`). `approve_plan` (signed) needs root cause and >= 1 action;
`implementation -> effectiveness_check` needs all actions done/cancelled; `verify` (signed) records the result -
`not_effective` returns to `investigation`; `close` (signed). Actions may reference an ECO (M5) and are shown in
the owner's approvals list (M6 route M5, `GET /mfg/approvals` gains QA kinds: inspection lots due, NCR/CAPA/field action
steps the user can sign). `external` SoR: CAPA records become link stubs (`external_ref`, title, status free text).

**Complaints**: `open -> investigation -> closed` (close signed). Lots/serials typed in are resolved to records
(unknown kept as text with a warning). Reportability is decision support: `due_on = aware_on + days` of the matching
rule per regime; the regulatory team records `reportable` and `report_ref`; overdue -> notification. Actions from a
complaint: open trace (M5), create NCR, create CAPA, create recall (M5 #recalls with the complaint's lots/serials as
sources) -> field action. Inbound `superplanner.v1` gains record `complaint` (from CRM/eQMS; SoR rule applies).

**Field actions**: created from a recall report (`recall_id`); units copied from the report (finished serials and
lots, customer, demand line). `approve` (signed) places `field_action` holds on affected in-stock lots/serials and
sets `in_progress`. Unit status updates single or bulk (`POST .../units/bulk {items: [{unit_id, status, note}]}`
<= 1,000, or CSV import by serial/lot code); effectiveness = share of units in `acknowledged` or later, per customer
and overall; `complete` when no `pending`/`notified` units (or with a reason); `close` (signed) releases its holds.
Export xlsx/JSON (customer letters are produced outside). Remediation by serial = units `corrected` with a
reference (rework WO, ECO).

## 8. Equipment and calibration (`qa/equipment.py`)

Valid(e, t) = `status == active` and (`not calibration_required` or `date(t) <= due_on + grace_days`). Recording a
calibration (signed): `due_on = next_due_on or performed_on + interval_days`; `fail` -> `out_of_service`,
notification, and `GET /qa/equipment/{id}/impact` lists results measured with it since its last passing calibration
(inspection lots, decisions, lots released) with "Create NCR" from the list. Back to `active` from
`out_of_service`: signed `equipment.return_to_service`, and a passing calibration after the failure when required
(409 `QA_CALIBRATION_REQUIRED`).

Blocking: (1) results entry (5.2); (2) floor `setup_start`/`start` on a line with linked equipment not valid -> 409
`QA_LINE_EQUIPMENT_INVALID` (`details.equipment`), no supervisor force; (3) APS/health: a line with invalid
equipment at `as_of` is unavailable (open-ended downtime-like block, explanation "EQ-0042 calibration overdue since
20 Nov"); equipment due inside the horizon blocks the line from `due_on + grace_days + 1`; tool pools with linked
equipment use `min(quantity, valid units at as_of)`. Health issues: `QA_LINE_BLOCKED` (error), `QA_TOOL_POOL_REDUCED`
(warning), `QA_EQUIPMENT_DUE_IN_HORIZON` (info). Scan codes `E:<code>` (equipment) and `IL:<number>` (inspection lot)
join the M4 resolver.

## 9. API (`/api/v1`, `router_m7.py`; every route one permission, route table at S0)

| # | Method and path | Perm |
|---|---|---|
| P1-P3 | GET `/auth/esig/status`; POST `/auth/esig/enroll`; GET `/auth/oidc/stepup?purpose=esig` (popup; callback reuses `/auth/oidc/callback`, then `/esig/stepup-done` posts the token to the opener) | session |
| P4 | POST `/orgs/{org}/members/{member_id}/esig-revoke` | org_admin |
| P5 | GET `/meta/time` | session |
| E1-E2 | GET `/mfg/esig/policies`; PUT `/mfg/esig/policies/{record_type}/{action}` (signed) | view / esig_policy_edit |
| E3 | GET `/mfg/esig/preview?record_type&record_id&action[&decision]` | view |
| E4-E5 | GET `/mfg/esig/signatures` (record, signer, from/to); GET `/mfg/esig/signatures/{id}/verify` | audit_view |
| E6 | GET `/mfg/audit/record?entity_type&entity_id` | audit_view |
| E7-E10 | GET `/mfg/part11/records/{record_type}/{record_id}`; POST, GET `/mfg/part11/exports`; GET `/mfg/part11/exports/{id}/download` | audit_view |
| E11-E12 | GET `/mfg/plant/part11`; PUT `/mfg/plant/part11 {enabled: true, signature}` | view / owner |
| Q1-Q2 | GET, PUT `/mfg/plant/qa-settings` | view / qa_plan_edit |
| Q3-Q7 | GET, POST `/mfg/qa/schemes`; GET, PUT, DELETE `/mfg/qa/schemes/{id}`; POST `/{id}/approve` | view / qa_plan_edit |
| Q8-Q14 | GET, POST `/mfg/qa/plans`; GET, PUT, DELETE `/mfg/qa/plans/{id}` (characteristics inline); POST `/{id}/copy`, `/{id}/approve`, `/{id}/obsolete` | view / qa_plan_edit |
| Q15-Q20 | GET `/mfg/qa/inspection-lots` (status, scope, item, supplier, overdue, sort); POST (manual); GET `/{id}` (with results, verdict); POST `/{id}/results`; POST `/{id}/decision`; POST `/{id}/cancel` | view / qa_inspect (decision: qa_decide; cancel: qa_decide) |
| Q21-Q23 | GET, POST `/mfg/qa/holds`; POST `/mfg/qa/holds/{id}/release` | view / qa_decide |
| Q24-Q31 | GET, POST `/mfg/qa/ncrs`; GET, PUT `/{id}`; POST `/{id}/open`, `/propose`, `/approve`, `/implement`, `/close`, `/cancel` | view / ncr_edit (approve, close: ncr_approve) |
| Q32-Q39 | GET, POST `/mfg/qa/capas`; GET, PUT `/{id}`; POST, PUT, DELETE `/{id}/actions[/{action_id}]`; POST `/{id}/advance {to}`, `/approve-plan`, `/verify`, `/close`, `/cancel` | view / capa_edit (approve-plan, verify, close: capa_approve) |
| Q40-Q44 | GET, POST `/mfg/qa/complaints`; GET, PUT `/{id}`; POST `/{id}/advance`, `/close` | view / complaint_edit |
| Q45-Q52 | GET, POST `/mfg/qa/field-actions`; GET, PUT `/{id}`; POST `/{id}/approve`, `/complete`, `/close`, `/cancel`; GET `/{id}/units`; POST `/{id}/units/bulk`; GET `/{id}/export` | view / field_action_edit (approve, close: capa_approve) |
| Q53-Q59 | GET, POST `/mfg/qa/equipment`; GET, PUT `/{id}`; POST `/{id}/status`; GET `/{id}/impact`; GET, POST `/{id}/calibrations` | view / equipment_edit |
| Q60-Q62 | POST `/mfg/qa/attachments` (multipart: entity_type, entity_id, file); GET `/mfg/qa/attachments/{id}` (download); DELETE `/{id}` | qa_inspect / view / qa_inspect |
| Q63-Q64 | POST, DELETE `/mfg/qa/links` | view-of-both + edit perm of `from` type |

Changed: floor events (`qty_nc`, `defect_code`; type `nc_disposition` internal only), scan resolver, `/lots/{id}`
PUT (holds), postings with `ncr_id` (read), WO records (`kind`, `ncr_id`), `/mfg/approvals`, `/summary` (`qa
{open_lots, overdue_lots, open_ncrs, overdue_capas, equipment_due}`), health issues, all regulated update routes
accept `X-SP-Change-Reason`, signable actions accept `signature` and return `signatures`. Records: every QA record
has `id, row_version, created_at, updated_at, signatures[], links[], attachments[]`. Lists: `limit/offset/q/sort`
and CSV export of the loaded rows (UX 4). Attachments: <= 10 MB, <= 50 per record, types pdf/png/jpeg/csv/xlsx/txt
by content sniffing (415 `QA_ATTACHMENT_TYPE`, 413 `QA_ATTACHMENT_TOO_LARGE`), served `attachment` +
`nosniff`; immutable once the parent leaves draft/open (409 `QA_ATTACHMENT_LOCKED`).

Errors (new): 403 `ESIG_ROLE`, `ESIG_NOT_ALLOWED`, `ESIG_NOT_ENROLLED`; 409 `ESIG_CONTENT_CHANGED`,
`ESIG_SAME_SIGNER`, `ESIG_AUTHOR`, `ESIG_RECORD_LOCKED`, `ESIG_USER_HAS_SIGNATURES`, `PART11_DELETE_NOT_ALLOWED`,
`PART11_MODE_LOCKED`, `QA_INSPECTION_OPEN`, `QA_LOT_DECIDED`, `QA_DECISION_CONTRADICTS`, `QA_LOT_NOT_READY`,
`QA_HOLD_ACTIVE`, `QA_HOLD_OWNED`, `QA_EQUIPMENT_NOT_CALIBRATED`, `QA_LINE_EQUIPMENT_INVALID`,
`QA_CALIBRATION_REQUIRED`, `QA_NCR_NOT_CLOSABLE`, `QA_ATTACHMENT_LOCKED`, `MFG_INVALID_STATE` (transitions); 413/415
attachments; 422 `ESIG_REQUIRED`, `ESIG_AUTH_FAILED`, `ESIG_MEANING`, `ESIG_MFA_UNAVAILABLE`, `ESIG_POLICY_INVALID`,
`ESIG_CONTENT_TOO_LARGE`, `AUDIT_REASON_REQUIRED`, `QA_SCHEME_INVALID`, `QA_ITEM_NOT_LOT_CONTROLLED`,
`QA_PLAN_OPERATION_UNKNOWN`, `QA_SAMPLE_OUT_OF_RANGE`, `QA_DISPOSITION_QTY`, `QA_JUSTIFICATION_REQUIRED`,
`INV_SERIAL_ON_HOLD`, `PART11_NO_ARCHIVE_DIR`; 423 `ESIG_LOCKED`; 503 `ESIG_CLOCK_SKEW`. Outbox events:
`qa.inspection_decided`, `qa.hold.placed|released`, `qa.ncr.approved|implemented|closed`, `qa.rtv`,
`qa.capa.closed`, `qa.field_action.approved|closed`, `qa.equipment.status`.

### 9.1 Roles and permissions

New plant roles: `qa_inspector` (receiving/line inspector), `qa_engineer`, `qa_approver` (QA manager / quality
release), `metrology` (calibration technician). New permissions:

| Permission | Roles (plus owner, plant_admin as today) | Covers |
|---|---|---|
| `qa_inspect` | qa_inspector, qa_engineer, qa_approver, operator, supervisor | results, manual inspection lots, attachments |
| `qa_decide` | qa_inspector, qa_engineer, qa_approver | usage decisions (policy narrows signers), holds |
| `qa_plan_edit` | qa_engineer, qa_approver | schemes, plans, QA settings |
| `ncr_edit` | qa_inspector, qa_engineer, qa_approver, supervisor | NCR create/edit/propose/implement |
| `ncr_approve` | qa_engineer, qa_approver | NCR approve/close (policy defines steps) |
| `capa_edit`, `complaint_edit`, `field_action_edit` | qa_engineer, qa_approver | CAPA, complaints, field actions |
| `capa_approve` | qa_approver | CAPA and field action approvals |
| `equipment_edit` | metrology, qa_engineer | equipment, calibrations |
| `audit_view` | qa_engineer, qa_approver | record audit trails, signatures, exports |
| `esig_policy_edit` | qa_approver | policies (signed) |

`view` (all roles) covers GETs. Signing is decided by the policy roles (4.3), so owner/plant_admin can administer
but not release product unless they also hold the QA role. `assistant_use` gains the QA roles; assistant tools stay
read-only and get `qa_lots`, `ncrs`, `equipment_status` tools (permission `view`).

## 10. UI (UX standard; strings in `lib/strings/quality.ts` + `fr-CA`)

Navigation: new sidebar group **Quality** (after Production): Inspection (worklist), Holds, NCRs, CAPA, Complaints,
Field actions, Equipment and calibration, Inspection plans, Sampling schemes. **Control** gains Signature policies,
Part 11 settings, Part 11 export. Command palette searches IL/NCR/CAPA/CMP/FA numbers and equipment codes.

- **Worklists** (`/mfg/qa/inspection-lots`, `/ncrs`, `/capas`, `/complaints`, `/field-actions`, `/equipment`,
  `/holds`): shared VirtualTable, FilterBar with saved views ("My lots due today", "Overdue", "Awaiting my
  signature"), status chips (icon + text), due dates in plant time, bulk none in M7.
- **Record pages** share one anatomy: page header (number, status chip, key facts, one primary action = next step
  for this user), tabs Details | Results/Dispositions/Actions/Units | Links | Attachments | **History** (audit trail
  with old -> new values, reasons, signatures) | **Signatures** (manifestations, verify). Print view per record
  (`/mfg/print/qa/:type/:id`) = the Part 11 package rendered (browser print/save as PDF).
- **SignatureDialog** (shared component): shows the preview summary lines, meaning (fixed or a choice), "You are
  signing as Marie Tremblay (mtremblay)", user name + password (+ TOTP code) fields or "Re-authenticate with your
  company account" (step-up popup), comment/reason, the legal statement; handles 202 (pending next step: who may
  sign next), 409 content changed (reload preview), 423 lockout. Focus trapped; no password managers autofill of the
  user name field (`autocomplete="off"` on user name, `current-password` on password).
- **Change reason prompt**: in Part 11 plants every save of a regulated record opens a small reason dialog (recent
  reasons offered) and sends `X-SP-Change-Reason`.
- **Floor (tablet)**: `/mfg/floor/inspect/:lotId` - characteristic cards, sample grid, numeric pad, pass/fail big
  buttons, live verdict per characteristic, gauge scan field (`E:` codes, calibration state shown), offline queue
  as M4 (results batch keyed by `client_batch_id`); operation screen shows the inspection gate state and the NC
  quantity pad (`qty_nc` + defect code). Receiving: after a PO receipt the confirmation links the new inspection lot.
- **Plans editor**: characteristic table with inline edit, limits, gauge class, sampling preview for a lot size
  ("lot 3,200 at level II, AQL 0.65 -> sample 125, accept 2, reject 3").
- **Equipment**: due calendar, overdue banner, calibration entry with certificate upload, impact list after failure.
- **Field action**: unit table with status per customer, effectiveness bar per customer, bulk status from CSV.
- **Language**: account menu -> Language (English, Français (Canada)); stored in `/me/preferences/display`
  (`locale`); `lib/i18n.ts` gains `setLocale`, fallback to English per key; `lib/locale.ts` gains `fr-CA` (narrow
  no-break space thousands, comma decimal, 24 h, ISO dates); API error `code` -> `errors.<CODE>` keys with the server
  message as fallback; `npm run i18n:check` asserts key and placeholder parity. Glossary
  `docs/i18n/fr-CA-glossary.md` (OQLF terminology: bon de travail, lot, non-conformité, mesure corrective et
  préventive, étalonnage).

Test ids: `qa-lot-row` (`data-status`), `qa-result-cell`, `qa-verdict`, `qa-decision-{accept|reject}`,
`esig-dialog`, `esig-password`, `esig-totp`, `esig-submit`, `esig-manifest`, `change-reason`, `ncr-disposition-row`,
`ncr-implement`, `hold-chip`, `eq-status` (`data-valid`), `fa-unit-row`, `lang-select`.

## 11. Delivery plan (lean)

| WP | Role | Owns |
|---|---|---|
| **S** backend | one backend developer | `sp/esig/**`, `sp/qa/**`, `sp/api/audit_diff.py`, `sp/i18n/**`, `sp/api/mfg/{db_models_m7,repo_m7,router_m7}.py`, `services/{qa_*,esig,part11}.py`, hooks in existing services (postings, floor, WOs, lots, recall, ECO approve, MRP snapshot, APS line availability, health, scan, approvals, summary, users delete), auth (enrol, step-up), jobs, migration `0010_m7`, `migrate.py`, `manage.py part11-export`, sample `meddev_m7`, `docs/DEPLOY.md` (time sync, Part 11 config, Canada-region pilot profile), tests `tests/esig/**`, `tests/qa/**`, `tests/api_mfg_m7/**`, edits of 11.1 |
| **U** UI | one UI developer | `frontend/src/qa/**`, `SignatureDialog`, change-reason prompt, floor inspect screen and NC pad, nav/palette/approvals additions, language switch, `fr-CA` dictionaries (with translator), `frontend/e2e/m7-quality.spec.ts` (one spec) |
| LEAD | team lead | this document, S0 review, final gate |

**S0 (day 1-2)**: pydantic contract (`esig/model.py`, `qa/model.py`), canonical content registry signatures,
migration + up/down test, all routes live with permissions answering from `backend/superplanner/qa/fixtures/
example_m7.json` (built and validated by `build_example.py`); U writes `contractExamplesM7.ts`. **S1** esig core
(enrol, credentials, policies, preview, signing, lockout, step-up with the M5 fake IdP, MAC + chain, verify),
audit diffs + reasons + delete rules, Part 11 mode, time checks. **S2** schemes, plans, inspection lots from
receipts/floor/WO receipts, results, evaluation, switching, decisions, holds + MRP/kitting rules. **S3** NCR with
ledger/floor implementation and rework WOs, CAPA, complaints, field actions from recalls, links, attachments.
**S4** equipment/calibration with floor/APS/health blocking, impact, due scan job, Part 11 package and export job,
sample `meddev_m7`, notifications catalog fr/en, performance, DEPLOY. **U1** signature dialog, change reason,
enrolment, policies, Part 11 settings, History/Signatures tabs. **U2** plans/schemes editors, inspection worklist,
floor inspect, receiving link, holds. **U3** NCR (incl. floor NC pad), CAPA, complaints, field actions.
**U4** equipment, print views, fr-CA switch + dictionaries + i18n check, e2e spec.

### 11.1 Existing code and tests touched

M2 postings (`ncr_id`, held-serial rule, inspection lot creation hook on `po_receipt`/`wo_receipt`), lots PUT,
kitting, MRP snapshot (inspection-hold supply); M4 floor (`qty_nc`, gate block, equipment block, `nc_disposition`,
scan codes); M3 APS snapshot (line availability, tool pool quantity); M1 health registry; M5 recall quarantine
(holds), ECO approve (signature), users delete; M6 approvals, assistant tools; common `audit()` (changes, reason);
route/permission tables and the authz sweep, migration head/table sets, job-kind lists, reset/reassign registries,
health code lists, sample registry. Existing tests change only in those tables and in assertions on audit row shape.

## 12. Sample, performance, testing, acceptance

**Sample `meddev`** (exists: `backend/superplanner/mfg/samples/meddev*.py`, fictional single-use device plant in
Quebec with moulding, cleanroom assembly, packaging, EtO and a QC release hold; being added in the working tree at
design time). M7 extends it with `meddev_m7.py` (no change to its M1-M4 content or health expectations): schemes
`EXAMPLE-TABLE` (marked "test only - load your licensed tables"), `FIXED-5`, `FULL`; incoming plans for two bought
lot-controlled parts (one supplier-specific), an in-process plan on the cleanroom assembly gate (needle pull force,
gauge class `FORCE`), a final plan for one syringe and one customer-specific final plan for a prefillable syringe;
12 equipment items (calipers, force gauges, line equipment on one assembly line) with one due in 3 days and one
overdue; history: 20 inspection lots, 3 NCRs (scrap, rework, use-as-is), 1 CAPA in implementation, 2 complaints,
1 field action from a recall; QC release holds of the sample become `inspection` holds of final inspection lots.

**Performance** (local PostgreSQL 16, development machine as M5/M6):

| # | Case | Target |
|---|---|---|
| QP1 | signing (argon2 verify + hash + insert + chain), server time | p95 < 400 ms |
| QP2 | audit diff + reason overhead per regulated update | < 3 ms |
| QP3 | inspection lot creation overhead on a 50-line PO receipt | < 50 ms |
| QP4 | results batch 2,000 values with evaluation | < 1 s |
| QP5 | NCR implement with 50 postings | < 2 s |
| QP6 | lists of 100,000 inspection lots / 10,000 NCRs, filtered page | < 300 ms |
| QP7 | equipment block check at floor start | < 5 ms |
| QP8 | record audit trail with 2,000 events / Part 11 package with 200 attachments manifest | < 400 ms / < 1 s |
| QP9 | Part 11 export of one year of the sample x 50 | < 5 min, constant memory |

**During work:** tests with the code; only touched packages and named existing tests (`.venv/bin/pytest tests/esig
-q`, `tests/qa -q`, `tests/api_mfg_m7 -q`, ...); UI `npm run build`, `npm run i18n:check`, the m7 spec when written.
**Final gate (once, LEAD):** full backend suite on PostgreSQL incl. `-m slow`; `m7-quality.spec.ts`, the floor spec
and the accounts-mode login spec; migration 0009 -> 0010 on a populated database and downgrade; `audit-verify`.

**Test vectors:**

| # | Case | Expected |
|---|---|---|
| T-S1 | sign with wrong password 3x | 422 x2 then lockout 423 for 30 min; audit `esig.lockout`; admins notified |
| T-S2 | NCR approve: engineer signs `reviewed`, then same user tries `approved` | 202 pending; 409 `ESIG_SAME_SIGNER` |
| T-S3 | record edited between preview and sign | 409 `ESIG_CONTENT_CHANGED` with current hash |
| T-S4 | SSO user signs with step-up token twice / token of another session | first ok; reuse and foreign 422 `ESIG_AUTH_FAILED` |
| T-S5 | change a signed field in SQL | verify: `content_matches_current` false, `content_hash_ok` true; alter signature row -> `mac_ok` false |
| T-S6 | Part 11 mode on: item description update without reason / with reason | 422 `AUDIT_REASON_REQUIRED` / audit `changes [{path: description, old, new}]` + reason |
| T-S7 | clock skew 3 s injected | sign 503 `ESIG_CLOCK_SKEW` |
| T-Q1 | lot size 3,200, level II, AQL 0.65 in the example table | n/ac/re as table; 100% when n >= lot |
| T-Q2 | 2 rejections in 5 lots of one supplier | state `tightened`; 5 accepted -> `normal` |
| T-Q3 | PO receipt of a planned item | inspection lot + hold; MRP sees it as inspection supply; issue refused `INV_LOT_ON_HOLD` |
| T-Q4 | gate operation complete with open lot | 409 `QA_INSPECTION_OPEN`; after accept ok |
| T-Q5 | force gauge overdue used in a result | 409 `QA_EQUIPMENT_NOT_CALIBRATED` |
| T-Q6 | reject -> NCR -> dispositions scrap 100 / rework 200 / use-as-is 2,900 | postings `issue_misc SCRAP` 100 with `ncr_id`; rework WO consuming the held lot, received back; hold released after rework completes; close requires CAPA when flagged |
| T-Q7 | WIP: `qty_nc` 20 at op 30 -> scrap 5, rework to op 20 15 | op 30 scrap +5, op 20 rework_in +15; input balance holds |
| T-Q8 | manual `PUT /lots {hold:false}` with an NCR hold | 409 `QA_HOLD_ACTIVE` |
| T-Q9 | line with overdue line equipment | floor start 409; APS run leaves the line empty with the explanation; health `QA_LINE_BLOCKED` |
| T-Q10 | complaint -> recall -> field action approve | holds on in-stock affected lots; bulk unit status; effectiveness per customer; close releases holds |
| T-Q11 | calibration fail | equipment out of service; impact lists lots measured since last pass |
| T-I1 | fr-CA | every key present with same placeholders; numbers `1 234,5`; error code localized |

**Acceptance (Gate 7):**
1. Part 11 controls on the `meddev` sample: enrolment, signing with password, password + TOTP and SSO step-up
   (fake IdP + one real IdP documented), manifestation on screen/print/package, linking verify, policy edit signed,
   lockout, change reasons and old/new values, delete rules, time check; a supplier-style "Part 11 checklist" in
   DEPLOY mapping each 11.10/11.50/11.70/11.100/11.200/11.300 clause to the control or to the customer's procedure.
2. Incoming -> in-process -> final inspection end to end with holds, sampling, switching, signed release; MRP and
   kitting respect holds.
3. NCR stock and WIP dispositions post correctly (ledger reconciles, trace edges include rework), CAPA through
   effectiveness, complaint to field action with effectiveness.
4. Calibration blocks results, floor and APS as specified; due notifications.
5. A Quebec City user works the floor inspect, NCR and signature flows entirely in French.
6. Performance QP1-QP9; full backend suite green once; m7 spec green.

## 13. Questions for the product owner

Defaults decided by LEAD 2026-11-23 (configuration, changeable per plant): CAPA/complaints native with an eQMS
switch; final release signed with password + TOTP by `qa_approver`; whole-lot holds for NCRs; no supervisor
override of calibration blocks. Genuinely open (see `docs/MEDDEV-GAP-PLAN.md` 6): whether BD's pilot plant wants
CAPA/complaints native or linked to its eQMS, and whether its IdP supports step-up re-authentication with MFA
claims (else signing uses local password + TOTP credentials for SSO users, `ESIG_LOCAL_CREDENTIALS=true`).

**Decided by the product owner 2026-11-23:** (1) CAPA and complaints are native, with the per-plant switch
`qa_settings.capa_sor` / `complaint_sor = external` ("external eQMS" mode: link stubs with `external_ref`); (2) SSO
users sign through an OIDC step-up (`prompt=login`, `max_age=0`), with the `ESIG_LOCAL_CREDENTIALS=true` fallback
(signing password set at enrolment + TOTP) for IdPs without step-up.

## 14. Implementation notes

**S0 frozen (2026-11-23).** Contract: `backend/superplanner/esig/model.py`, `backend/superplanner/qa/model.py`;
typed examples `backend/superplanner/qa/fixtures/example_m7.json` (built and validated by `build_example.py`, test
`tests/api_mfg_m7/test_m7_s0_contract.py`); migration `0010_m7` (`migrate.HEAD`); all 95 M7 operations live with
their permissions (`router_m7.py`, route table in `tests/auth/route_table.py`). Until a service function is
implemented it answers from the example file (`services/m7_examples.py`, PEP 562 fallback per service module);
real implementations replace them phase by phase. The UI can build against the examples and the routes now.

S0 interpretations and deviations:
- Every M7 table is plant-owned (`owner_id`, the central ownership filter applies), also child tables
  (characteristics, dispositions, CAPA actions, field action units) - tenancy by the ownership filter only.
- Extra table `qa_result_batches` (replay record of a results batch, `client_batch_id` -> stored response, 5.2).
- Extra columns: `users.esig_password_hash` (ESIG_LOCAL_CREDENTIALS signing password); `qa_inspection_plans.name`,
  `author_id`; `qa_sampling_schemes.approved_at`, `author_id`; `qa_inspection_lots.decision_note`, `hold`, `source`,
  `customer`; `qa_ncrs.operation_seq`, `location_id`; `qa_capas.author_id`, `closed_at`; `qa_complaints.author_id`,
  `closed_at`; `qa_field_actions.complete_reason`, `author_id`, `closed_at`; `qa_field_action_units.code`, `in_stock`;
  `qa_equipment.failed_on`, `note`; `mfg_lot_holds.release_note`; `part11_exports.error`;
  `qa_switching_states.plan_key`/`plan_number` (state per plan number + supplier, shared by plan versions).
- Migration: lots held before M7 get one `manual` hold row each (the derived `lots.hold` stays true).
- Attachments upload as the raw request body (`POST /mfg/qa/attachments?entity_type&entity_id&filename`, file
  bytes with their Content-Type): no multipart package is installed and 0.12 forbids new packages. The body limit
  for that path is 10 MB (+1 byte, 413 above).
- Extra read route `GET /mfg/qa/schemes/{id}/preview?lot_size&level&aql&state` (plan editor sampling preview, 10).
- Links are deleted by id: `DELETE /mfg/qa/links/{link_id}`.
- `X-SP-Change-Reason` is parsed by the mfg principal dependency and recorded on every mfg audit event of the
  request (`audit_events.reason`); regulated services add `changes`. The audit hash chain includes `changes`,
  `reason`, `signature_id`, `record_version` when set (rows without them hash exactly as before).
- A plant reset is refused in Part 11 mode (409 `PART11_DELETE_NOT_ALLOWED`); otherwise it deletes the M7 rows.

S1 (esig core) notes:
- Credentials are verified before the action's write transaction (no plant lock held during argon2); failures are
  counted in their own transaction under the user's row lock, so concurrent wrong attempts lock exactly once
  (`test_m7_esig.py::test_t_s1_concurrent_wrong_attempts_lock_exactly_once`). A consumed TOTP step or step-up token
  stays consumed if the action then fails (stricter single use). Consequently a reused step-up token answers 422
  `ESIG_AUTH_FAILED` before any state check.
- `inspection_lot.decide` is stored as two policies: `decide` (incoming, in-process) and `decide_final`.
- `esig_policy.update` and `calibration.record` sign a pre-image: the preview hash is the current policy /
  equipment; the stored snapshot is `{before, after}` (policy) or the new calibration record, with its own hash.
  `calibration.record` policies are limited to one step (the record is created by the signature).
- `plant.part11_on` is always signed (also while the mode is off) and needs SECRETS_KEY(S) (409
  `PART11_SECRETS_REQUIRED`); `PUT /plant/part11` when already on: 409 `PART11_MODE_LOCKED`.
- Signature MAC: HMAC-SHA256 (`k1:`) with a key derived from the first SECRETS_KEY over every column except
  `status` and bookkeeping stamps; all configured keys verify (rotation). `chain_ok` re-checks the signature's audit
  event link against its predecessor.
- Change reasons: every regulated entity action except creates (`EXEMPT_ACTIONS`) needs a reason in Part 11 mode,
  enforced centrally in `services/common.audit`; field-level changes are recorded where services pass
  before/after (items, M7 records, QA settings, policies; other M1-M6 entities record the reason without a diff -
  extend per entity as needed).
- `qa_approver` also holds `eco_approve` (it is a default signer of `eco.approve`).
- There is no user-delete operation in the product; `esig_signatures.signer_id` is `ON DELETE RESTRICT`, so a
  signer cannot be deleted at the database level either.
- Step-up: `GET /auth/oidc/stepup` stores `stepup:<user>:<session_ref>` as the OIDC state's next URL and adds
  `prompt=login&max_age=0`; the shared callback checks the identity (`iss`, `sub`) maps to the session user, the
  browser session is the same and `auth_time` is fresh, then redirects to `/esig/stepup-done#token=...` (fragment).

S2-S4 notes (as built):
- Holds: `mfg_lots.hold` / `mfg_unit_serials.hold` are derived from open hold rows under the lot row lock; the
  derived flag does not bump the lot's `row_version`. `PUT /lots {hold}` places / releases `manual` holds (409
  `QA_HOLD_ACTIVE` with other holds; in Part 11 mode manual holds are released only through the signed
  `POST /qa/holds/{id}/release`, 409 `QA_HOLD_OWNED`). Recall quarantine places `recall` holds.
- MRP: a lot whose open holds are all `inspection` is netted as `inspection` supply (avail = max(as_of,
  last receipt + receiving days)) wherever it is stored.
- Inspection lots are row-locked (`write_tx(lock=False)`), results of different lots run in parallel. A second
  results batch for an already entered sample is 409 `QA_RESULT_EXISTS` (corrections use `corrects_result_id` +
  reason). Result entry is exempt from the change-reason rule (append-only creation). `client_batch_id` replays
  the stored response; a different body with the same id is 409 `QA_BATCH_CONFLICT`.
- Plan approval obsoletes the previous approved version with the same key at approval time (not at
  `effective_from`); `find_plan` honours `effective_from` of the new version.
- Final lots are not created for rework WOs (the material is under its NCR).
- NCR WIP: `qty_nc` counts as scrap in the operation state until dispositioned (so WO `qty_scrapped` includes
  undispositioned NC). `nc_disposition` events convert: scrap -> unchanged, rework -> scrap -1 / rework_out +1 to
  `rework_to_seq`, use-as-is -> scrap -1 / good +1 (last operation: the floor receipt follows the state).
- NCR stock scrap / RTV postings are exempt from the lot hold for that posting only; a rework WO may consume the
  lots its NCR holds (`hold_exempt` in the posting context). Rework WOs are `kind rework` with the item itself as
  the 1:1 component; the receipt lot code is the operator's choice (same code recommended, not enforced).
- Workflow actions accept If-Match optionally (as M5 ECO actions); edits require it.
- CAPA `verify` with `effective` keeps the CAPA in `effectiveness_check` until `close`; external SoR
  (`capa_sor` / `complaint_sor = external`) refuses workflow actions with 409 `QA_EXTERNAL_SOR`; status is free text.
- Complaint close needs the reportability assessed (409 `QA_COMPLAINT_NOT_ASSESSED`); `reporting_due` per regime
  from the QA settings rules (event-type rule wins over `all`).
- Field action units: shipped serials, shipments (customer, demand line) and in-stock lots of the recall report;
  `approve` holds the in-stock lots; effectiveness counts shipped units only.
- Equipment: `calibration.record` creates the calibration and signs it in one transaction (single-step policies
  only). `fail` -> out of service + notification; return to service needs a passing calibration after the
  failure and a valid due date. APS: lines with invalid linked equipment get open-ended `qa:<equipment>` closures in
  the snapshot (planned=true); the APS explanation of the empty line is the closure, the health issue
  `QA_LINE_BLOCKED` carries the text ("EQ-0042 calibration overdue since ..."). Tool pools with linked equipment
  are reduced to the valid units in the APS dataset. The APS inputs token includes equipment changes.
- Held serials are refused on floor consumption (422 `INV_SERIAL_ON_HOLD`); M2 shipments and transfers are not
  serial-addressed, so they are unaffected.
- `/approvals` gains kinds `qa_lot`, `qa_ncr`, `qa_capa`, `qa_field_action` (in Part 11 mode only steps the user's
  roles may sign); `/summary.qa`; scan codes `IL:` and `E:`; health issue codes are listed in `/meta`.
- Notifications use a small backend catalog (`superplanner/i18n`, en / fr-CA) by the plant's `attributes.locale`.
- Not built in M7 (left for the gate review): assistant read tools `qa_lots`, `ncrs`, `equipment_status`; inbound
  `superplanner.v1` record `complaint`; field action CSV import is supported only inline (`units/bulk {csv}`).
- Sample: `mfg/samples/meddev_m7.py` + `services/qa_sample.py`, applied after the meddev history (no ledger postings;
  equipment due dates relative to the real day; QC release holds become final inspection lots with holds for items
  with a final plan, else manual holds).

**Measured performance** (`tests/api_mfg_m7/test_m7_perf.py`, local PostgreSQL, in-process TestClient, argon2
"fast" test profile): QP1 signed action p95 81 ms (median 52 ms; the production argon2 profile adds its verify time);
QP2 diff 0.03 ms per regulated update; QP4 2,000 results with evaluation 259 ms; QP6 filtered page of 100,000
inspection lots 84 ms; QP7 line equipment check 0.8 ms; QP8 record audit trail of 2,000 events 65 ms. QP3, QP5 and
QP9 were not measured separately (covered functionally by the receipt, NCR and export tests).

**Demo findings fixed after M7 (backend):**
1. OEE: `mfg/kpi.oee` caps performance at 100 % (and availability / quality at 100 %), so OEE <= 100 %; a plant may
   allow more with `plant.attributes.kpi_performance_cap` (1.0-2.0). The `performance` KPI shows the capped value
   and carries `raw_value` when the run standards are slower than reality. Adherence: published operations of WOs
   that are not tracked on the floor are not compared (adherence is null = n/a, not 0); each day is measured
   against the plan in force that day (latest run published before the day ended, else the current published run).
2. Recall reports: shipments carry the shipped lot (`lots`), `by_customer` carries `qty` and `lots`, counts gain
   `qty_shipped`, `qty_in_stock`, `qty_affected`, `customers` (lot-controlled, non-serialised material).
3. Floor "issue component lot": `POST /mfg/floor/issue-lot {wo_operation_id, scan | lot_id, wo_component_id?, qty?,
   location_id?}` (perm `floor_report`) -> one `wo_issue` posting through the ledger (default quantity = the
   component's remaining requirement); holds (incl. M7) 422 `INV_LOT_ON_HOLD`, expiry by the ledger, quarantine-only
   stock 409 `FLR_LOT_QUARANTINED`, wrong item 422 `FLR_LOT_NOT_A_COMPONENT`, several lines 422
   `FLR_CHOOSE_COMPONENT`.
4. `meddev` sample: a pinned "Sample history plan" APS run (published before the history, not the current
   published run) holds the history operations at planned times (every fifth one late), so history adherence/OEE
   are realistic; the load ends with an MRP run and refreshes that run's staleness token (no "out of date" after a
   load). The sample still has no current published schedule (run APS to get one).


**WP-U notes (UI, as built).**
- Code: `frontend/src/mfg/qa/**` (worklists, record pages, floor inspect, print, Part 11 pages),
  `frontend/src/components/SignatureDialog.tsx`, `frontend/src/auth/SignatureEnrolPage.tsx` (`/account/signature`),
  `frontend/src/mfg/api/{typesM7,clientM7,contractExamplesM7}.ts` (types mirror `esig/model.py` + `qa/model.py`; the
  fixture is typed against them, inputs as `Partial`), strings `frontend/src/lib/strings/quality.ts` and
  `frontend/src/lib/strings/fr-CA/*.ts`. The QA package lives under `src/mfg/qa/` (not `src/qa/`) so it shares the
  Manufacturing layout, routes and helpers.
- Routes: `/mfg/qa/{inspection-lots,holds,ncrs,capas,complaints,field-actions,equipment,plans,schemes}[/:id]`
  (`new` for create), `/mfg/qa/settings`, `/mfg/esig/policies`, `/mfg/part11`, `/mfg/part11/exports`,
  `/mfg/print/qa/:type/:id`, `/mfg/floor/inspect/:lotId`. Navigation group "Quality" after Production (plus
  "Quality settings"); Control gains Signature policies, Part 11 settings, Part 11 export. The command palette
  searches IL/NCR/CAPA/CMP/FA numbers and equipment codes through the list endpoints (`q`).
- Signature dialog: always previews first (E3) and shows the server summary, record version and full SHA-256 with an
  expandable canonical content; meaning fixed or chosen; "You are signing as <legal name> (<user name>)"; user name
  is never prefilled (`autocomplete=off`), password `current-password`, TOTP `one-time-code` when the step's auth is
  `password_totp`; SSO users (no password method in `signer.methods`) re-authenticate in a popup and the token is
  cleared after every attempt; passwords are cleared after every attempt. 409 `ESIG_CONTENT_CHANGED` reloads the
  preview and says nothing was signed; 422 `ESIG_AUTH_FAILED` shows the attempts left (`details.remaining`); 423 shows
  the unlock time and that admins and QA approvers were notified; `next_step.blocked_reason` disables signing with
  the reason. 202 answers end with a toast naming the next step and its roles. With Part 11 off (or no policy) the
  same dialog is a plain confirmation (title without "Sign:"). The statement shown is the UI's own localized
  sentence with the chosen meaning (server `legal_statement` is the enrolment acknowledgement). No compliance claims.
- Change reasons: `useChangeReason()` asks only in Part 11 mode (from `GET /plant/part11`), offers the last six reasons
  (server preference `qa.reasons`), sends `X-SP-Change-Reason`; the signature comment doubles as the reason of
  signed actions.
- Floor: results are posted one sample per batch with a fresh `client_batch_id`; network failures queue the batch in
  `localStorage` (`sp.qa.results.<workspace>`) and replay on `online`/every 15 s (4xx moves it to "needs attention").
  The operation screen gains a "Nonconforming" stepper with a defect code (`qty_nc`, `defect_code`), shows
  `result.ncr` when the server returns it, and an inspection-gate card when `operation.inspection_lot` is present.
- Language: display menu "Language" (`lang-select`) stores `locale` in the `display` preference (and `sp.locale`);
  `main.tsx` loads the French dictionary before importing the app (`boot.tsx`), so module-level labels are French;
  switching reloads the page. Numbers/dates use `fr-CA` Intl (Chromium uses U+00A0 as the group separator, not the
  narrow U+202F of the design; text dates are "23 nov. 2026" rather than ISO, consistent with the UX rule that UI text
  never shows ISO dates). Quebec typography is applied by the build script of the dictionaries (no-break space before
  ":", inside « »; none before ? ! ;). API errors: `errors.<CODE>` (45 codes) in French sessions, the server message in
  English sessions. `npm run i18n:check` now also fails on any missing/extra fr-CA key or differing placeholders
  (8,280 keys, 0 problems).
- Asks for the backend (the UI degrades gracefully meanwhile): (1) records carry user ids only (`author_id`,
  `placed_by`, `decided_by`, `owner_user_id`); the member list is owner-only, so other users see ids - please add
  display names next to the ids (or a `GET /mfg/people` for any plant member). (2) The PO receipt response could
  carry `inspection_lots: [{id, number}]` (the UI uses it when present; else it looks the received lot codes up).
  (3) `GET /floor/operations/{id}` could carry `inspection_lot {id, number, status}` for gate operations and the
  floor event result `ncr {id, number}` (both read when present). (4) The equipment status route needs a preview
  for `equipment.return_to_service` under `action=return_to_service` (the UI asks for it under that name).
  (5) Assistant citations: `citations.resolve` matches only `[R7]`; models sometimes write grouped markers
  (`[R7, R8]`, `[R7; R8]`). The UI renders each known ref of a grouped marker as its own link, but refs used only
  in a grouped marker never reach `citations` - please accept the grouped form in `MARKER` (and lower-case `r7`).
- Demo polish (as built): quantities via `formatQty(x, uom)` in `lib/locale.ts` (count UoMs such as EA/PCS as
  integers, others at most 3 decimals, trailing zeros trimmed); Gantt bar labels only inside the widest visible
  piece when they fit (part number dropped first, then ellipsis, else no label); schedule compare headers
  "A: run" / "B: run" / "Change from A to B" with signed deltas and "better/worse in B" text; recall tiles switch
  to quantities for lot-controlled items (affected qty = shipped + in stock, shipments to customers, lots on hand;
  per-customer shipments/qty/lots) from `report.counts`, `by_customer.qty/lots`.
- Tests: `frontend/e2e/m7-quality.spec.ts` (2 tests: results -> live verdict -> decision through the dialog ->
  history; NCR dispositions, equipment validity, French switch) passes against the real routes.

**fr-CA glossary (OQLF usage, medical-device manufacturing).** work order = bon de travail; purchase order = bon de
commande; purchase request = demande d'achat; demand order = commande client; item = article; BOM = nomenclature;
routing = gamme; lot = lot; serial number = numéro de série; shop floor = atelier; shift = quart; changeover =
changement de série; scrap = rebut; rework = retouche; backflush = consommation à rebours; kitting = préparation;
inspection lot = lot d'inspection; inspection plan = plan d'inspection; sampling scheme = schéma d'échantillonnage;
AQL = NQA; usage decision = décision d'utilisation; hold = blocage (bloqué); NCR = rapport de non-conformité (RNC);
disposition = disposition; use as is = utiliser tel quel; CAPA = CAPA (mesures correctives et préventives);
root cause = cause fondamentale; complaint = plainte; reportability = déclarabilité; awareness date = date de prise de
connaissance; field action = action sur le terrain; recall = rappel; calibration = étalonnage; gauge = instrument /
jauge; equipment = équipement; electronic signature = signature électronique; audit trail = piste d'audit; legal
name = nom légal; enrol = s'inscrire; meanings: Rédigé, Révisé, Approuvé, Libéré, Rejeté, Vérifié, Effectué, Fermé
(same as the backend catalog).

**fr-CA review list (terms a Quebec regulatory/quality reviewer should confirm).** "CAPA" kept as the acronym (some
sites use "ACP"/"MCP"); "RNC" for NCR; "Action sur le terrain" for field action (Health Canada texts also use
"mesure corrective de sécurité" / "avis de sécurité"); "blocage" for hold (alternatives "retenue", "mise en
quarantaine"); "Libéré" as the meaning of release; "schéma d'échantillonnage" vs "plan d'échantillonnage" (ISO 2859 FR
uses both); "MRP" kept (OQLF: PBM); "trousse/préparation" for kitting; "Enceinte" for chamber; "Montage" for
fixture; "Partie 11" in "mode Partie 11"; the gender of generated nouns in "Nouveau {task}" / "Nouvelle {resource}"
(Studio). The finance and studio examples were localized to Canadian amounts; Indian "lakh" mentions remain where the
parser expects them.
