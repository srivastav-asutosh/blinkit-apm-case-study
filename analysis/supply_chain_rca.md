# RCA: Fast-Moving SKU Stockouts Concentrated in 3 Dark Stores

**Domain:** Supply Chain & Replenishment
**Data:** `fact_inventory_daily`, `fact_replenishment`, 12 stores × 100 SKUs × 60 days
**Queries used:** [`sql/02_supply_chain_kpis.sql`](../sql/02_supply_chain_kpis.sql)

## 1. Problem statement

Network-wide fill rate looks healthy at a glance (99.8% for fast-moving SKUs), but that average
hides a concentrated problem: **3 of 12 stores account for 93% of an estimated ₹2.97L in lost
sales value** over the 60-day window, all from fast-moving categories (Dairy & Breakfast, Fruits &
Vegetables, Beverages, Snacks, Frozen).

## 2. Investigation

Starting from the network-level fill rate, I segmented stockout rate by store, then by the
warehouse each store sources from, since replenishment lead time is the most likely lever behind
a stockout (`sql/02_supply_chain_kpis.sql`, Q1–Q2):

| Warehouse | Contracted lead time | Avg actual lead time | Stockout rate (fast movers) | Est. lost sales value |
|---|---|---|---|---|
| WH-DEL-SECONDARY | 3 days | 3.06 days | **1.36%** | concentrated here |
| WH-BLR-PRIMARY | 1 day | 1.16 days | 0.03% | — |
| WH-DEL-PRIMARY | 1 day | 1.11 days | 0.01% | — |

Store-level breakdown confirms it's not a Delhi-wide issue — it's specific to the three stores
mapped to the secondary warehouse:

| Store | Warehouse | Stockout rate | Est. lost sales value (60d) |
|---|---|---|---|
| DEL-S-02 | WH-DEL-SECONDARY | 1.49% | ₹98,372 |
| DEL-E-01 | WH-DEL-SECONDARY | 1.31% | ₹96,168 |
| DEL-E-02 | WH-DEL-SECONDARY | 1.29% | ₹83,244 |
| All other 9 stores | Primary warehouses | 0.00–0.05% | ₹494–5,730 each |

## 3. Root cause

**It is not a reliability problem — it's a structural lead-time problem.** The secondary
warehouse hits its contracted 3-day lead time almost exactly on average (3.06 vs. 3.0 days
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
   they're mapped to.
3. **Track stockout rate by warehouse, not just by store or network average**, in the standing ops
   review — the network-level 99.8% fill rate metric completely masked this until it was sliced by
   warehouse.

## 5. Projected impact

Re-mapping (or lead-time-adjusting safety stock for) these 3 stores addresses ~93% of the
network's fast-moving-SKU lost sales value — an estimated **₹2.78L recovered over a comparable
60-day period**, without any change to the other 9 stores.
