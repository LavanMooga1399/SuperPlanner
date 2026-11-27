# M9 country-of-origin reconciliation (hand sheet)

Purpose: reconcile the domestic-content roll-up, the tariff-milestone status and the landed cost by hand against
the system (M9-DESIGN 8.2-8.4; Gate 9 acceptance 4). Every figure below is reproduced by a scripted test; the test
name is given so a reviewer can re-run it (`pytest -k <name>`). All data are fictional.

## 1. Needle lot roll-up (M9-TRD-02)

Finished lot `N1` of `NDL-25G` (1,000 needles) consumed, through its work order:

| Input | Kind | Qty | COO | Unit value | Value | Weight kg | Domestic |
|---|---|---|---|---|---|---|---|
| Steel A (lot KA) | exact | 2.0 kg | US | 15.00 | 30.00 | 2.0 | 1 |
| Steel B (lot AB) | exact | 1.0 kg | CN | 10.00 | 10.00 | 1.0 | 0 |
| Resin (lot R1) | exact | 0.5 kg | CA | 10.00 | 5.00 | 0.5 | 0 |
| Cap (stock, no lot) | possible | 1,000 | JP | 0.008 | 8.00 | 0.4 | 0 |
| **Total** | | | | | **53.00** | **3.9** | |

- Value share = 30 / 53 = **0.566**; weight share = 2.0 / 3.9 = **0.513**; `estimated` (a `possible` input).
- Steel only (milestone `NDL-US-STEEL`, classes `steel`): value 30 / (30 + 10) = **0.75**, weight 2 / 3 =
  **0.667**, not estimated (the cap is outside the filter).
- Test: `tests/trade/test_trade_content.py::test_needle_lot_value_weight_and_steel_only`.

## 2. Made sub-assembly (M9-TRD-03)

Sub-assembly lot `S1` = 1 x X (US, 2.00) + 1 x Y (CN, 2.00) -> share 0.5. Finished lot `F1` = 1 x S1 (value 4.00,
share 0.5) + 1 x Z (US, 6.00): share = (0.5 x 4 + 1 x 6) / 10 = **0.80**.
Test: `test_made_subassembly_share_is_value_weighted`.

## 3. Milestone status (M9-TRD-05)

Minimum 100 %, effective 2027-07-01: a month at 100 % is `met`, 97 % `at_risk` (within 5 points), 80 % `missed`;
months before the effective date have no status. Month cell with lots 1.0 x 30 (600 units) and 0.5 x 10 (400 units,
estimated): share = (30 + 5) / 40 = **87.5 %** -> `missed`; lots below 1, quantity below 40 %, estimated 40 %.
Test: `tests/trade/test_trade_pure.py::test_milestone_status_met_at_risk_missed`.

Projection with a dual-source scenario (steel 60 % KT / US, 40 % AT / CN) shows **60 %** for future months, 50 % with
the two active suppliers unweighted. Test: `test_made_lot_content_transfer_carries_coo_and_shares_and_report`.

## 4. Landed cost (M9-TRD-06)

Cannula steel from ATUBE (CN) into a CAD plant (CA), FOB, other costs 0.5 %:

| Line | Calculation | CAD per unit |
|---|---|---|
| Price | 100 USD / 1,000 units x 1.40 | 0.1400 |
| Freight | item-supplier freight | 0.0050 |
| Customs value | FOB = price | 0.1400 |
| Duty `mfn` | 0 % x 0.14 | 0.0000 |
| Duty `surtax` (CN) | 25 % x 0.14 | 0.0350 |
| Other | 0.5 % x 0.14 | 0.0007 |
| **Total** | | **0.1807** |

Missing FX (a JPY supplier with no JPY rate): total **null** with `FX_MISSING` - never priced at 1.
Tests: `test_landed_cost_hand_example`, `test_fx_inverse_via_usd_stale_missing`,
`test_tables_landed_cost_and_receipt_coo`.

## 5. COO capture (M9-TRD-01, M9-TRD-04)

Receipt with `coo MX` -> lot `MX` / `receipt`; receipt without -> item-supplier `CN` / `supplier`; item trade COO
next; else null + `TRADE_COO_MISSING`. A made lot takes the plant country (`plant`). A transfer US1 -> QC carries
COO `US`, the domestic shares and the unit value converted 30 USD x 1.40 = 42 CAD (`transfer`). A correction after
receipt needs a reason and is audited (`coo_change`).

Reviewed by: ____________________  Date: ____________
