# RCA: Fast-Moving SKU Stockouts Concentrated in 3 Dark Stores

**Domain:** Supply Chain & Replenishment
**Data:** `fact_inventory_daily`, `fact_replenishment`, 12 stores × 96 SKUs × 60 days
**Queries used:** [`sql/02_supply_chain_kpis.sql`](../sql/02_supply_chain_kpis.sql)

## 1. Problem statement

Network-wide fill rate looks healthy at a glance (99.9% for fast-moving SKUs), but that average
hides a concentrated problem: **3 of 12 stores account for 98.0% of an estimated ₹2.75L in lost
sales value** over the 60-day window, all from fast-moving categories (Dairy & Breakfast, Fruits &
Vegetables, Beverages, Snacks, Frozen).

## 2. Investigation

Starting from the network-level fill rate, I segmented stockout rate by store, then by the
warehouse each store sources from, since replenishment lead time is the most likely lever behind
a stockout (`sql/02_supply_chain_kpis.sql`, Q1–Q2):

| Warehouse | Contracted lead time | Avg actual lead time | Stockout rate (fast movers) | Est. lost sales value |
|---|---|---|---|---|
| WH-DEL-SECONDARY | 3 days | 3.02 days | **1.18%** | ₹269,680 |
| WH-BLR-PRIMARY | 1 day | 1.16 days | 0.01% | ₹4,575 |
| WH-DEL-PRIMARY | 1 day | 1.10 days | 0.03% | ₹926 |

Store-level breakdown confirms it's not a Delhi-wide issue — it's specific to the three stores
mapped to the secondary warehouse:

| Store | Warehouse | Stockout rate | Est. lost sales value (60d) |
|---|---|---|---|
| DEL-E-01 | WH-DEL-SECONDARY | 1.24% | ₹105,007 |
| DEL-S-02 | WH-DEL-SECONDARY | 1.34% | ₹99,016 |
| DEL-E-02 | WH-DEL-SECONDARY | 0.96% | ₹65,657 |
| All other 9 stores | Primary warehouses | 0.00–0.05% | ₹0–3,274 each |

## 3. Root cause

**It is not purely a lead-time problem — it's two independent reliability failures at the same
warehouse.** The secondary warehouse hits its contracted 3-day lead time almost exactly on
average (3.02 vs. 3.0 days expected), so lead-time *length* alone doesn't fully explain the loss.
Section 9 below adds the second mechanism: the same warehouse also under-fills the quantity it
ships, on nearly every order. Reorder points at these three stores are sized off the same
demand-forecast logic used everywhere else, which under-provisions safety stock for a 3-day
replenishment cycle versus a 1-day one — so normal demand variability, compounded by consistently
short-shipped quantities, is enough to blow through available stock before the next delivery lands.

Category breakdown at the affected stores (Q4) confirms the risk is concentrated in genuinely
perishable/short-cycle categories (Dairy & Breakfast, Fruits & Vegetables) rather than spread
evenly — exactly what you'd expect if the mechanism is "can't hold enough safety stock to bridge
a 3-day gap" rather than a general operational problem at those stores.

## 4. Recommendation

1. **Re-map DEL-S-02, DEL-E-01, DEL-E-02 to a primary (1-day) warehouse** where fulfillment center
   capacity allows — this is the direct fix and removes the root cause entirely.
2. **If re-mapping isn't feasible short-term, raise the safety-stock multiplier specifically for
   fast-moving/perishable SKUs at secondary-warehouse stores** — the reorder point formula should
   scale with lead time, and currently treats all stores the same regardless of which warehouse
   they're mapped to. (Section 6 below turns this into a precise, quantified fix.)
3. **Track stockout rate by warehouse, not just by store or network average**, in the standing ops
   review — the network-level 99.9% fill rate metric completely masked this until it was sliced by
   warehouse.

## 5. Projected impact

Re-mapping (or fixing lead-time and case-fill reliability for) these 3 stores addresses ~98% of
the network's fast-moving-SKU lost sales value — an estimated **₹2.70L recovered over a comparable
60-day period**, without any change to the other 9 stores.

## 6. A second, independent finding: the safety-stock formula itself

Recommendation 2 above says "raise the safety-stock multiplier for secondary-warehouse stores" —
digging into *how much* to raise it surfaced a sharper finding than a simple multiplier bump.
**Queries used:** [`sql/07_safety_stock_policy.sql`](../sql/07_safety_stock_policy.sql)

The network's actual reorder-point formula is `demand × (contracted lead time + 2 days)` — a flat
buffer that only accounts for lead-time *length*, never lead-time or demand *variability*.
Computing demand and lead-time variance empirically from the same 60 days of data (mean and
standard deviation per store-SKU and per warehouse) and applying the standard combined-variability
safety-stock formula — `Z × √(mean_leadtime × var_demand + mean_demand² × var_leadtime)`, with Z
segmented by service-level target (1.96 for fast-moving SKUs, ~97.5%; 1.28 for slow movers, ~90%)
— gives a very different picture:

| Warehouse | Lead-time std dev | Correct ROP vs. current | Gap value |
|---|---|---|---|
| WH-DEL-SECONDARY | **1.23 days** | **+12.0%** (under-buffered) | +₹429,437 |
| WH-BLR-PRIMARY | 0.37 days | −31.2% (over-buffered) | −₹1,480,311 |
| WH-DEL-PRIMARY | 0.30 days | −36.9% (over-buffered) | −₹1,054,014 |

The secondary warehouse isn't just slower on average — its lead time is **~3.5x more variable**
(σ = 1.23 vs. 0.30–0.37 days) than the primary warehouses. A flat buffer can't see that, so it
simultaneously under-protects the one warehouse that actually needs more cushion *and*
over-protects the two that don't.

**Root cause, restated:** the policy conflates "lead time" with "lead-time risk." Two warehouses
with the same average lead time but different variability need different safety stock, and the
current formula has no term for variability at all.

**Recommendation:** replace the flat 2-day buffer with the variability-adjusted formula above.
This is **not a spend-more recommendation** — net across the three warehouses, the correct policy
calls for **₹21.0L less** total safety-stock investment than the current one (+₹4.3L − ₹14.8L −
₹10.5L), because the over-buffering at the two stable warehouses outweighs the under-buffering at
the volatile one. The fix is a reallocation, which makes it an easier sell than a net capital
increase would be — better service at the one warehouse that needs it, funded by trimming excess
buffer at the two that don't.

**Book value isn't the number that gets this funded — annualized carrying cost is.** ₹21.0L is a
balance-sheet figure. Converted to an annual P&L impact using an editable carrying-cost assumption
(20%/year, covering cost of capital + warehousing + obsolescence risk;
[`sql/07_safety_stock_policy.sql`](../sql/07_safety_stock_policy.sql) Q3): the two over-buffered
warehouses cost **~₹506,865/year** in carrying cost that fixing the policy would recover; bringing
WH-DEL-SECONDARY up to its correct level adds back **~₹85,887/year** — a **net annual saving of
~₹420,978**. That net-annual number, not the book-value gap, is what an S&OP or finance review
would actually put in a budget request.

## 7. A third, independent finding: shrinkage from an order-cycle/shelf-life mismatch

Stockouts and safety stock are both about not holding *enough*. Shrinkage is the opposite failure
mode, and the network has one: fast-moving SKUs are ordered on a flat 10-day cycle regardless of
category, but Dairy & Breakfast has a 7-day shelf life and Fruits & Vegetables has 5 — meaning a
routine reorder for these two categories habitually brings in more stock than can plausibly sell
before it spoils.

Modeling spoilage as a function of stock held beyond `avg_daily_demand × shelf_life_days` (the
threshold above which a unit is at real expiry risk) shows **~₹18.5L in wasted units over 60 days,
concentrated entirely in Fruits & Vegetables (₹12.2L) and Dairy & Breakfast (₹6.4L)** — every other
fast-moving category has a shelf life (90–180+ days) far longer than the order cycle, so the model
correctly shows zero waste there.

**This is a different shape of problem from the stockout finding.** Stockouts are concentrated in
3 stores on one warehouse; waste is spread close to evenly across all 12 stores, because it's
driven by a category-level *ordering policy* (order cycle vs. shelf life), not a store-specific or
warehouse-specific cause. Fixing it doesn't require touching warehouse mapping or staffing —
it requires a shorter order cycle (or smaller order quantity) specifically for short-shelf-life
categories, independent of everything else in this case study.

**Recommendation:** cap the order cycle at (or below) shelf life for any category with
shelf life under ~14 days — concretely, cut Dairy & Breakfast and Fruits & Vegetables from a
10-day to a 5–6 day order cycle. This trades more frequent, smaller replenishment orders for
substantially less spoilage; at ₹18.5L over 60 days, this is the single largest ₹ figure in this
case study, larger than the stockout loss it sits alongside.

## 8. Cost of the fix — warehouse-remap payback

Section 2's root cause is a warehouse-mapping problem: 3 stores sit on WH-DEL-SECONDARY, which
runs a 3.02-day actual lead time against a 3-day contract, and it's this warehouse — not those
stores specifically — that drives 98% of network stockout loss (₹269,680/60d, fast-moving SKUs;
[`sql/02_supply_chain_kpis.sql`](../sql/02_supply_chain_kpis.sql) Q2). The fix is a remap (or a
lead-time and case-fill-rate renegotiation with that warehouse — see Section 9) — either way, a
one-time project cost this schema doesn't track, since it's a real-world contracting/logistics
cost, not an operational metric. Rather than invent a single number, SQL:
[`sql/08_fix_roi.sql`](../sql/08_fix_roi.sql) (query F2) prices payback across a plausible range:

| Assumed one-time remap cost | Payback period |
|---|---|
| ₹100,000 | 0.7 months |
| ₹200,000 | 1.5 months |
| ₹350,000 | 2.6 months |
| ₹500,000 | 3.7 months |

**This is the stronger, cleaner business case of the two fixes quantified in this project**
(compare to Section 6 of [`analysis/store_ops_rca.md`](store_ops_rca.md), where the corrected
staffing fix only covers 21% of its own cost through labor efficiency and has to lean on an
unpriced SLA/customer-value argument for the rest). The warehouse remap pays for itself on
recovered revenue alone — even at the high end of plausible one-time cost, it clears payback in
under 4 months, and at the low end in under a month. It doesn't need a qualitative argument to
close; the recoverable revenue and the range of realistic remap costs are simply not close to
each other, in either direction.

## 9. A fourth, independent finding: case-fill rate — the warehouse's second reliability failure

Section 3 treated WH-DEL-SECONDARY's problem as purely a lead-time issue. It isn't the whole
picture: the same warehouse also under-ships the *quantity* it sends, on nearly every order.
**Queries used:** [`sql/09_case_fill_rate.sql`](../sql/09_case_fill_rate.sql)

| Warehouse | Case-fill rate | % of orders shorted | Avg shortfall when shorted |
|---|---|---|---|
| WH-DEL-SECONDARY | **89.97%** | **99.9%** | **9.98%** |
| WH-DEL-PRIMARY | 97.56% | 69.5% | 3.5% |
| WH-BLR-PRIMARY | 97.57% | 68.4% | 3.55% |

Every warehouse ships slightly under the ordered quantity most of the time — that alone isn't
unusual. What's different at WH-DEL-SECONDARY is the *severity*: when it shorts an order (which is
nearly always), it shorts it by roughly 3x as much as the primary warehouses do. This is a
**second, independent driver behind the same warehouse's stockout numbers** — not a restatement of
the lead-time finding. A store on this warehouse is fighting both a longer replenishment cycle
*and* consistently receiving less than it ordered within that cycle, which compounds faster than
either problem would alone.

**Recommendation:** whatever fix is chosen for the lead-time problem (remap or renegotiation)
needs to explicitly include a case-fill-rate service-level target, not just a lead-time SLA — a
warehouse that ships on time but consistently short has not actually been fixed. If a remap isn't
immediately feasible, a warehouse-side inventory-accuracy or allocation-priority audit at
WH-DEL-SECONDARY specifically is a lower-cost interim lever, since ~10% average shortfall on
effectively every order suggests a systemic allocation issue rather than isolated stockouts at the
warehouse itself.

## 10. A fifth, independent finding: the safety-stock Z-factor isn't real ABC/XYZ

Section 6's safety-stock formula splits its Z-factor (1.96 vs. 1.28) purely by the `is_fast_moving`
flag, with a comment calling this "same as real ABC/XYZ inventory segmentation." It isn't one —
real ABC/XYZ crosses **value** (A/B/C, by revenue contribution) with **variability** (X/Y/Z, by
demand coefficient of variation) as two independent dimensions, not a single binary flag standing
in for both. **Queries used:**
[`sql/13_abc_xyz_segmentation.sql`](../sql/13_abc_xyz_segmentation.sql)

Building the real 3×3 matrix and checking where the binary policy disagrees with it:

| Classification | SKUs | Revenue (60d) |
|---|---|---|
| Under-protected: mid/high-value, high-variability slow-mover | 2 | ₹37.77L |
| Over-protected: low-value fast-mover | 9 | ₹67.48L |
| Correctly classified | 85 | ₹25.16Cr |

Two SKUs sit in the mid/high-value, high-variability quadrant but are flagged `is_fast_moving = 0`
— they're getting the lower (1.28) Z-factor when their true demand volatility calls for the higher
(1.96) one. Nine SKUs are flagged `is_fast_moving = 1` and getting the higher Z-factor despite
sitting in the lowest-value tercile, where that level of protection isn't justified by their
revenue contribution.

**This is a real but modest refinement, not a second version of the Section 6 finding.** The vast
majority of the catalog (85 of 96 SKUs, ~97% of revenue) is already correctly classified by the
binary flag — is_fast_moving happens to correlate well with true ABC/XYZ class for most of this
catalog, because fast-moving SKUs are disproportionately the high-revenue ones. The mismatch is
real and worth fixing (11 SKUs, ~₹1.05Cr combined revenue affected), but it's the smallest-impact
finding in this document — the shape of a genuine analytical refinement, not a repeat of the
warehouse-level safety-stock story.
