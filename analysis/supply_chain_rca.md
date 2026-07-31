# RCA: Fast-Moving SKU Stockouts Concentrated in 3 Dark Stores

**Domain:** Supply Chain & Replenishment
**Data:** `fact_inventory_daily`, `fact_replenishment`, 12 stores × 96 SKUs × 60 days
**Queries used:** [`sql/02_supply_chain_kpis.sql`](../sql/02_supply_chain_kpis.sql)

## 1. Problem statement

Network-wide fill rate looks healthy at a glance (99.8% for fast-moving SKUs), but that average
hides a concentrated problem: **3 of 12 stores account for 99.2% of an estimated ₹3.22L in lost
sales value** over the 60-day window, all from fast-moving categories (Dairy & Breakfast, Fruits &
Vegetables, Beverages, Snacks, Frozen).

## 2. Investigation

Starting from the network-level fill rate, I segmented stockout rate by store, then by the
warehouse each store sources from, since replenishment lead time is the most likely lever behind
a stockout (`sql/02_supply_chain_kpis.sql`, Q1–Q2):

| Warehouse | Contracted lead time | Avg actual lead time | Stockout rate (fast movers) | Est. lost sales value |
|---|---|---|---|---|
| WH-DEL-SECONDARY | 3 days | 3.09 days | **1.40%** | ₹319,304 |
| WH-BLR-PRIMARY | 1 day | 1.17 days | 0.03% | ₹1,812 |
| WH-DEL-PRIMARY | 1 day | 1.11 days | 0.02% | ₹756 |

Store-level breakdown confirms it's not a Delhi-wide issue — it's specific to the three stores
mapped to the secondary warehouse:

| Store | Warehouse | Stockout rate | Est. lost sales value (60d) |
|---|---|---|---|
| DEL-S-02 | WH-DEL-SECONDARY | 1.49% | ₹121,168 |
| DEL-E-01 | WH-DEL-SECONDARY | 1.54% | ₹119,475 |
| DEL-E-02 | WH-DEL-SECONDARY | 1.16% | ₹78,660 |
| All other 9 stores | Primary warehouses | 0.00–0.08% | ₹0–932 each |

## 3. Root cause

**It is not a reliability problem — it's a structural lead-time problem.** The secondary
warehouse hits its contracted 3-day lead time almost exactly on average (3.09 vs. 3.0 days
expected). The three stores mapped to it are not being under-served relative to their contract;
the contract itself is 3x slower than what every other store in the network gets. Reorder points
at these three stores are sized off the same demand-forecast logic used everywhere else, which
under-provisions safety stock for a 3-day replenishment cycle versus a 1-day one — so normal
demand variability is enough to blow through available stock before the next delivery lands.

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
   review — the network-level 99.8% fill rate metric completely masked this until it was sliced by
   warehouse.

## 5. Projected impact

Re-mapping (or lead-time-adjusting safety stock for) these 3 stores addresses ~99% of the
network's fast-moving-SKU lost sales value — an estimated **₹3.19L recovered over a comparable
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
| WH-DEL-SECONDARY | **1.26 days** | **+14.5%** (under-buffered) | +₹520,529 |
| WH-BLR-PRIMARY | 0.38 days | −30.6% (over-buffered) | −₹1,453,640 |
| WH-DEL-PRIMARY | 0.32 days | −35.7% (over-buffered) | −₹1,017,767 |

The secondary warehouse isn't just slower on average — its lead time is **~3.5x more variable**
(σ = 1.26 vs. 0.32–0.38 days) than the primary warehouses. A flat buffer can't see that, so it
simultaneously under-protects the one warehouse that actually needs more cushion *and*
over-protects the two that don't.

**Root cause, restated:** the policy conflates "lead time" with "lead-time risk." Two warehouses
with the same average lead time but different variability need different safety stock, and the
current formula has no term for variability at all.

**Recommendation:** replace the flat 2-day buffer with the variability-adjusted formula above.
This is **not a spend-more recommendation** — net across the three warehouses, the correct policy
calls for **₹19.5L less** total safety-stock investment than the current one (−₹14.5L + −₹10.2L +
₹5.2L), because the over-buffering at the two stable warehouses outweighs the under-buffering at
the volatile one. The fix is a reallocation, which makes it an easier sell than a net capital
increase would be — better service at the one warehouse that needs it, funded by trimming excess
buffer at the two that don't.

## 7. A third, independent finding: shrinkage from an order-cycle/shelf-life mismatch

Stockouts and safety stock are both about not holding *enough*. Shrinkage is the opposite failure
mode, and the network has one: fast-moving SKUs are ordered on a flat 10-day cycle regardless of
category, but Dairy & Breakfast has a 7-day shelf life and Fruits & Vegetables has 5 — meaning a
routine reorder for these two categories habitually brings in more stock than can plausibly sell
before it spoils.

Modeling spoilage as a function of stock held beyond `avg_daily_demand × shelf_life_days` (the
threshold above which a unit is at real expiry risk) shows **~₹20.5L in wasted units over 60 days,
concentrated entirely in Fruits & Vegetables (₹13.2L) and Dairy & Breakfast (₹7.2L)** — every other
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
substantially less spoilage; at ₹20.5L over 60 days, this is the single largest ₹ figure in this
case study, larger than the stockout loss it sits alongside.

## 8. Cost of the fix — warehouse-remap payback

Section 2's root cause is a warehouse-mapping problem: 3 stores sit on WH-DEL-SECONDARY, which
runs a 3.09-day actual lead time against a 3-day contract, and it's this warehouse — not those
stores specifically — that drives 99% of network stockout loss (₹319,304/60d, fast-moving SKUs;
[`sql/02_supply_chain_kpis.sql`](../sql/02_supply_chain_kpis.sql) Q2). The fix is a remap (or a
lead-time renegotiation with that warehouse) — either way, a one-time project cost this schema
doesn't track, since it's a real-world contracting/logistics cost, not an operational metric.
Rather than invent a single number, SQL:
[`sql/08_fix_roi.sql`](../sql/08_fix_roi.sql) (query F2) prices payback across a plausible range:

| Assumed one-time remap cost | Payback period |
|---|---|
| ₹100,000 | 0.6 months |
| ₹200,000 | 1.3 months |
| ₹350,000 | 2.2 months |
| ₹500,000 | 3.1 months |

**This is the stronger, cleaner business case of the two fixes quantified in this project**
(compare to Section 6 of [`analysis/store_ops_rca.md`](store_ops_rca.md), where the staffing fix
only covers 42% of its own cost through labor efficiency and has to lean on an unpriced
SLA/customer-value argument for the rest). The warehouse remap pays for itself on recovered
revenue alone — even at the high end of plausible one-time cost, it clears payback in about a
quarter, and at the low end in under a month. It doesn't need a qualitative argument to close;
the recoverable revenue and the range of realistic remap costs are simply not close to each
other, in either direction.
