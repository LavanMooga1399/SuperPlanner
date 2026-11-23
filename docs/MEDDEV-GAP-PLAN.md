# SuperPlanner for medical-device manufacturing: gap plan M7-M10

Status: roadmap, 23 November 2026. Target: high-volume medical-device makers. Reference prospect: BD (Medical
Essentials: syringes, needles, IV catheters, flushes, blood collection tubes; BioPharma Systems: prefillable
syringes; Connected Care: infusion sets and pumps; Interventional). Plants include Quebec City. Regulation: Health
Canada MDR / MDSAP, ISO 13485, FDA 21 CFR 820 (QMSR, aligned with ISO 13485 since February 2026), 21 CFR Part 11.
Builds on M1-M6 as built and the UX standard (`docs/MANUFACTURING-GAP-ANALYSIS.md` 7, `docs/M1-DESIGN.md` ..
`docs/M6-DESIGN.md`, `docs/UX-STANDARD.md`, `docs/DEPLOY.md`).

**Compliance position.** SuperPlanner never claims compliance. It provides controls that *support* Part 11 and QMSR
(signatures, audit trails, record export, access control, validation evidence). The customer decides the intended
use, qualifies the vendor, validates the system and owns its procedures. Every document says "designed to support".

## 1. Decisions

1. **Goal = a demo that covers 70-80% of what BD expects, then a shadow pilot, then GxP use.** The order is chosen
   so that each milestone adds demo-visible coverage and the foundations (signatures, audit, holds) come first,
   because everything regulated later (field actions, S&OP approval, eDHR release, label approval) signs through it.
2. **Four milestones instead of three.** BD's situation (make-to-stock consumables at billions of units, network
   expansion and tariff milestones, consent-decree-grade quality linkage) adds forecasting, S&OP/IBP, network
   planning and country-of-origin. Putting them into M8/M9 next to the rate engine keeps each milestone the M5-M6
   size (one backend + one UI developer, about four weeks each). eDHR, UDI/labels, validation package and enterprise
   rollout form M10, the step from shadow pilot to GxP use.
3. **Planning stays the core; MES/QMS functions are "lite + integrate".** BD runs SAP (QM, PP) and an enterprise
   eQMS. Quality, CAPA and complaints are built natively and lean (enough for a plant without them and for the demo)
   and each gets a system-of-record switch (M5 4.4 pattern) so a plant can point CAPA/complaints to its eQMS and
   inspection lots to SAP QM. Default: SuperPlanner-owned.
4. **French (Canada) in M7, not later.** Quebec's Charter of the French language (as amended by Bill 96) expects
   French for software used by workers. Copy is already keyed (`lib/strings`), so fr-CA is a translation and locale
   track that costs the UI developer about three days plus a professional translator.
5. **High volume = a new rate-planning engine beside M3, not a rewrite of M2/M3.** Repetitive lines (molding,
   assembly, packaging) are planned as run-rate campaigns in shift buckets; discrete areas keep M3 APS. MRP gains
   forecasts, daily buckets, packaging UoM and kanban exclusion. Units never become tasks (5M units/day = a few
   thousand campaign blocks per month).
6. **Hosting.** Pilot hosting profile in a Canadian cloud region (data residency) is a deployment document in M7
   (no code); full data-residency controls, HA rehearsal and multi-plant rollout are M10.

## 2. What BD will expect (coverage map)

Today = M1-M6 as built. "Demo" = first milestone after which the item can be shown end to end in the video.
Weights: P = planning core, Q = quality/regulatory, E = enterprise.

| # | Expectation (source) | W | Today (M1-M6) | Closed in | Demo |
|---|---|---|---|---|---|
| 1 | Multi-level BOMs, routings, lines, shifts, tooling | P | Built (M1) | - | now |
| 2 | MRP with pegging, purchasing, shortages | P | Built (M2), order-driven | M8 (forecast-driven) | now |
| 3 | Finite scheduling, overtime, what-if, explanations | P | Built (M3) | - | now |
| 4 | Shop-floor execution, scrap/rework, KPIs, OEE-lite | P | Built (M4) | - | now |
| 5 | Lot/serial genealogy, recall report, quarantine | Q | Built (M5) | M7 (linked to field actions) | now |
| 6 | ECO / design and process change control | Q | Built (M5), unsigned | M7 (signed, Part 11) | M7 |
| 7 | SSO, 2FA, roles, hash-chained audit, retention | E | Built (M5) | M7 (old/new values, reasons) | now |
| 8 | Mobile approvals, dashboards, planning assistant | P | Built (M6) | - | now |
| 9 | Part 11 e-signatures (manifestation, re-auth, linking, policies) | Q | Missing | M7 | M7 |
| 10 | Inspection plans, AQL sampling, results on tablet, auto hold/release | Q | Lot hold only | M7 | M7 |
| 11 | NCR with disposition posted to inventory (MRB) | Q | Scrap/rework counts only | M7 | M7 |
| 12 | Complaint -> investigation -> CAPA -> field action / remediation by lot and serial (Alaris, Pyxis, infusion set recall) | Q | Recall report only | M7 | M7 |
| 13 | Calibration and equipment status blocking use | Q | Missing | M7 | M7 |
| 14 | French (Canada) UI for Quebec City | E | English, keyed strings | M7 | M7 |
| 15 | Statistical demand forecasting, forecast consumption | P | Missing | M8 | M8 |
| 16 | Inventory optimisation (safety stock by service level, ABC/XYZ) | P | Fixed safety stock | M8 | M8 |
| 17 | Rate-based line planning, campaigns, cleaning/changeover matrices | P | Setup matrix in APS only | M8 | M8 |
| 18 | Sterilisation (EtO) load planning, aeration, release wait | P | Generic batching (M4) | M8 | M8 |
| 19 | Cases/pallets, kanban/supermarket replenishment | P | Missing | M8 | M8 |
| 20 | SAP S/4HANA integration | E | Generic contract (M5) | M8 | M8 |
| 21 | Scale: millions of units/day, tens of lines, load-tested | E | Untested at this scale | M8 (test), M10 (sign-off) | M8 |
| 22 | S&OP / IBP monthly cycle with constrained plan and signed scenario approval | P | Missing | M9 | M9 |
| 23 | Network supply planning across plants and DCs (DRP) | P | Transfers only (M5) | M9 | M9 |
| 24 | Capacity expansion what-if: new lines/plants, ramp-up curves, rough-cut capacity (US $3B expansion, +5B units/yr) | P | Line what-if only | M9 | M9 |
| 25 | Make-vs-buy, sourcing scenarios, supplier risk and dual sourcing | P | Alternates only | M9 | M9 |
| 26 | Country of origin / domestic content per lot (US steel needles, HTS codes), tariff milestone report, landed cost | E | Missing | M9 | M9 |
| 27 | eDHR / batch record per lot, review by exception, signed QC release, PDF | Q | Data exists, no record | M10 | M10 |
| 28 | Customer-specific specs, quality agreements, CoA and batch packs (prefillable syringes for pharma) | Q | Missing | M7 (customer-scoped plans), M10 (CoA, packs) | M10 |
| 29 | UDI (GS1 DI+PI), label templates under change control, print reconciliation, GUDID / Health Canada data | Q | Code 128 travellers only | M10 | M10 |
| 30 | Validation package (trace matrix, IQ/OQ/PQ, CSA risk, config baseline) | Q | Missing | M8 (kit v1), M10 (complete) | M8 |
| 31 | Data residency (Canada), HA failover rehearsed, multi-plant rollout | E | HA designed and built (M6) | M7 (hosting profile), M10 | M10 |

Coverage of these 31 expectations shown end to end in a demo: **now 7 (23%)**, after **M7 14 (45%)**, after **M8
22 (71%)**, after **M9 27 (87%)**, after **M10 31**. The "70-80% demo" is reachable after M8; after M9 it also
covers BD's 2026 strategic topics (network expansion, domestic content, S&OP).

## 3. Milestones

Sizing relative to M5 (= 1.0; M5 took one backend + one UI developer about four weeks). Every milestone keeps the
lean process: design -> S0 contract freeze -> build with targeted tests -> security review -> one full suite ->
acceptance gate.

### M7 - Regulated foundation and quality (size 1.2) - design: `docs/M7-DESIGN.md`

Part 11 controls (signature policies, re-authentication with password/TOTP or SSO step-up, manifestation, content
hash linking, locked signed records, audit with old/new values and change reasons, inspection export, time-source
checks, Part 11 plant mode), quality (inspection plans with configurable AQL sampling schemes, inspection lots on
receipt / gate operation / WO receipt, tablet results entry, holds and usage decisions), NCR/MRB with dispositions
posted to the ledger and floor, CAPA, complaints with field actions tied to M5 recalls, equipment and calibration
blocking lines, gauges and tool pools, QA roles, fr-CA translation, pilot hosting profile (Canada region, docs).
**Depends on:** M5 identity/audit/recall, M4 floor, M2 ledger. **Gate 7:** section 12 of the M7 design.

### M8 - Make-to-stock planning at volume (size 1.3)

- **Forecasting** (`mfg/forecast`, numpy only): monthly/weekly history from shipments and demand, models moving
  average, Holt-Winters (additive/multiplicative), Croston/SBA for intermittent, seasonal naive; best fit by
  holdout WAPE; forecast versions with planner overrides; consumption of forecast by customer orders (backward then
  forward window). Forecast lines feed MRP as `forecast` demand (M2 demand types gain it).
- **Inventory optimisation**: ABC/XYZ classification, safety stock = z(service level) x sqrt(LT x sigma_d^2 +
  d^2 x sigma_LT^2) per item/location, proposals approved into M1 `safety_stock` (audited, reason).
- **MRP changes (M2)**: daily buckets beyond the detailed horizon, packaging UoM hierarchy (each -> inner -> case ->
  pallet, M1 UoM conversions per item) with order multiples in cases, `kanban` items excluded from planned orders
  (replenished by kanban signals: cards per loop, container qty, trigger on scan/consumption), rate supplies from
  the rate plan instead of discrete planned WOs.
- **Rate engine** (`mfg/rate`, new): lines flagged `flow` with run rates per item family (units/hour, OEE factor),
  shift buckets, campaign sequencing per line with a sequence-dependent cleaning/changeover matrix (time + cost,
  e.g. colour or gauge changes, line clearance), min/max campaign length, CP-SAT per line-horizon with a greedy
  + LNS fallback; output = run schedule (line x bucket x item x qty) that becomes repetitive WOs (one per campaign
  block) for M4 execution; validator and explanations as M3. M3 APS remains for discrete/batch work centers.
- **Sterilisation**: EtO chambers as batch resources (capacity in pallets, cycle hours), aeration rooms as
  cumulative capacity (hours), release wait (BI incubation or parametric) as an automatic M7 hold with planned
  release date; sterilisation load genealogy (lots -> load -> lots).
- **SAP S/4HANA adapter** on M5 `generic_v1`: OData v4 / IDoc-free REST (material, BOM, routing, stock, PO, sales
  order, planned order out, production order confirmations, QM usage decision optional), mapping profiles,
  reconciliation; tested against recorded payloads (no SAP in CI).
- **Validation kit v1**: requirement IDs in designs, `manage.py trace-matrix` (requirements -> tests from markers
  `@pytest.mark.req("M7-ESIG-03")` and e2e tags -> CSV/HTML), CSA risk classification per feature, configuration
  baseline export (plant settings, policies, roles, versions, hash).
- **Load test** (k6 or locust scripts in `scripts/load`): 40 lines, 3,000 SKUs, 5M units/day, 2,000 floor events/h,
  300 concurrent users, MRP + rate plan nightly; targets set in the M8 design.
**Depends on:** M7 holds (sterility release), M5 integration. **Gate 8:** forecast accuracy report on BD-like
history, rate plan validator-clean for 40 lines x 30 days < 5 min, MRP with forecasts + kanban matches hand cases,
SAP round trip on recorded payloads, load test report.

### M9 - Network, S&OP/IBP and sourcing (size 1.1)

- **S&OP/IBP cycle**: monthly calendar (demand review -> supply review -> pre-S&OP -> executive), consensus demand
  plan from forecast versions, rough-cut capacity by plant/line family/month, constrained supply plan, scenario
  comparison (revenue, service, inventory, capacity), executive approval signed (M7 e-signature, meaning
  `approved`), approved plan published as MPS targets to the plants.
- **Network planning (DRP)**: plants and distribution centers (`dc` plant kind) in an organisation, sourcing rules
  (primary/secondary plant, quotas), transit lead times, multi-echelon netting that creates M5 transfer orders;
  one org-level run over plant snapshots (read replica).
- **Capacity expansion what-if**: virtual lines/plants with start dates and ramp-up curves (rate % by week, yield
  learning curve), capex note, comparison against the baseline network; make-vs-buy and supplier allocation
  scenarios.
- **Country of origin and landed cost**: COO and HTS code on items and item-suppliers, COO captured per lot at
  receipt, domestic-content roll-up per finished lot via genealogy (value and weight share, rule configurable),
  tariff milestone report (domestic share by product family and period), landed cost = price + freight + duty
  (% by HTS/COO table) + other; supplier risk score, single-source flags, dual-sourcing suggestions.
**Depends on:** M8 forecasting/rate, M5 orgs/transfers/trace, M7 signatures. **Gate 9:** a two-plant + one-DC
network demo dataset, signed S&OP cycle, expansion scenario with ramp-up, COO report reconciled by hand.

### M10 - eDHR, UDI/labels, validation and enterprise rollout (size 1.4)

- **eDHR / batch record** per lot or WO assembled from M2 ledger, M4 floor events and serials, M5 genealogy, M7
  inspection/NCR/deviation/calibration references, M10 labels; review by exception (only exceptions need review:
  deviations, NCRs, overrides, out-of-window times, supervisor corrections), signed QC release (M7 policy) that
  lifts the final hold; server-side PDF (`reportlab`, PDF/A-2b) and JSON export; customer CoA and batch packs per
  customer quality agreement.
- **UDI and labels**: GS1 GTIN per packaging level, AIs (01)(17)(10)(21)(11), GS1-128 and DataMatrix rendering,
  label templates versioned and approved through ECO with signatures, print jobs (issued / printed / used /
  destroyed reconciliation per lot), verification scan with grade-free match check, GUDID and Health Canada (MDALL
  device identifiers) data export as files (no submission).
- **Validation package complete**: IQ/OQ/PQ templates filled from the trace matrix, release and change-control
  procedure, CSA records, periodic review report.
- **Enterprise**: data-residency controls (region tag per organisation, backups/archives in region, assistant AI
  opt-out enforced for regulated plants by default), HA failover rehearsal (M6 runbooks R1-R11 executed and
  recorded), load test at BD scale signed off, multi-plant rollout kit (plant template, master-data publish, role
  templates, cutover checklist), org-wide audit.
**Depends on:** M7 (signatures, holds, NCR), M5 ECO/trace, M8 packaging levels. **Gate 10:** eDHR of a sample
lot reviewed by exception and released with signature, label reconciliation balanced, GUDID file validated against
the published schema, executed OQ in a test environment, failover rehearsal record.

## 4. Dependencies and order

```
M5 identity/audit/recall --+--> M7 Part 11 + quality --+--> M8 volume planning --> M9 network + S&OP --+
M4 floor, M2 ledger -------+                           +-------------------------------------------------> M10 eDHR + UDI + GxP
```

Why this order: M7 first because signatures, holds and NCRs are inputs to everything after (sterility release in
M8, signed S&OP in M9, eDHR in M10) and a BD vendor assessment asks about Part 11 before anything else; M8 second
because make-to-stock planning at volume is the core of a planning product for BD and lifts demo coverage over
70%; M9 third for BD's 2026 strategic topics; M10 last because eDHR/UDI overlap BD's existing MES and only matter
when moving from shadow pilot to GxP use.

## 5. Assumptions

1. A shadow-mode pilot (plans compared with the plant's real plans; no GxP decisions) can start after M8 without
   formal validation; GxP use starts after M10 with customer validation.
2. AQL tables (ANSI/ASQ Z1.4, ISO 2859-1) are copyrighted: SuperPlanner ships the mechanism and a test-only example;
   the customer loads its licensed tables.
3. Training records, document control and supplier qualification stay in the customer's eQMS/LMS.
4. Demand history for forecasting comes from SAP (M8 adapter) or files; two years monthly minimum.

## 6. Open questions for the product owner (defaults apply if unanswered)

1. **Does BD's plant want CAPA/complaints in SuperPlanner or linked to its eQMS?** Default: native lean module with
   a system-of-record switch per plant (external reference mode).
2. **Which identity provider will the pilot use, and can it enforce re-authentication (`prompt=login`, `max_age=0`)
   with MFA claims for signing?** Default: OIDC step-up; fallback local password + TOTP signing credentials.
