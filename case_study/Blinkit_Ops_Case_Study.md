# Blinkit Ops Intelligence: A Cross-Domain RCA Case Study

**A portfolio project built for the Blinkit Associate Program Manager role**
(Supply Chain & Replenishment · Store Operations · Last Mile Operations)

---

## Why this project

The APM job description asks for someone who can drive execution across Supply Chain &
Replenishment, Store Operations, and Last Mile — using RCA and data-driven decision-making to
solve day-to-day operational problems, not just report on them. Rather than write a generic
data-analysis project, I built a simulated 12-dark-store network (2 cities, 60 days of
operations, ~75K orders, ~69K inventory-days, ~7K replenishment orders) with realistic operational
dynamics, then ran the same kind of investigation an APM would actually run: **start from a
network-level KPI, segment until the anomaly concentrates, isolate the driver, and quantify the
fix.**

The three findings below were not hard-coded — they emerged from a reorder-point inventory
simulation and an order-funnel time simulation, and had to be found by querying the data, the same
way real operational problems hide inside real operational data.

## The investigation, in one table

| Domain | Network KPI (looks fine) | Where it breaks down | Root cause |
|---|---|---|---|
| Supply Chain | 99.9% fill rate | 3 stores carry 98% of ₹2.75L lost sales | 3 stores mapped to a 3-day-lead-time warehouse that also under-ships quantity on ~every order |
| Store Ops | 87.6% SLA adherence | 3 stores hit 62–70% evening breach | Evening-shift picker AND rider staffing at 50–72% / 56–68% of need, concentrated in the 7–9pm peak |
| Last Mile | 13.6 min avg delivery | East Delhi hits 40.4% breach, 19.3 min avg | Compounding: longest structural distance + same rain exposure + the same 2 understaffed stores |

Full detail and SQL for each: [`analysis/supply_chain_rca.md`](../analysis/supply_chain_rca.md) ·
[`analysis/store_ops_rca.md`](../analysis/store_ops_rca.md) ·
[`analysis/last_mile_rca.md`](../analysis/last_mile_rca.md)

## The cross-domain finding (the part a network-average dashboard would never show you)

Scoring every store 0–8 across all three domains (methodology in
[`sql/05_cross_domain_rca.sql`](../sql/05_cross_domain_rca.sql)) surfaces a pattern that no
single-domain view can:

| Store | Stockout % | SLA breach % | Avg delivery (min) | Risk score | Story |
|---|---|---|---|---|---|
| DEL-E-01 | 1.24% | 40.3% | 19.2 | **8** | Fails all three — compounding risk |
| DEL-E-02 | 0.96% | 40.6% | 19.5 | **6** | Fails SLA + delivery outright; stockout rate sits right at the scoring threshold |
| BLR-S-02 | 0.0% | 26.8% | 14.2 | 4 | Staffing-only — proves it's not a Delhi/warehouse issue |
| DEL-S-02 | 1.34% | 6.0% | 13.0 | 3 | Supply-chain-only — isolates the warehouse as the driver |
| BLR-E-01 | 0.05% | 15.7% | 15.6 | 2 | Distance-only — East-zone effect without staffing on top |
| Every other store | ≤0.05% | ≤8.8% | ≤13.8 | **0** | Clean baseline |

**The takeaway an APM would bring to a review:** DEL-E-01 and DEL-E-02 aren't three separate small
problems — they're one staffing gap showing up in three different KPIs at once (pick time → SLA
breach; rider load → last-mile delay; and the same store pair happens to sit on the slow
warehouse too). DEL-E-02's stockout rate (0.96%) happens to fall just under the scoring rubric's
1.0% "severe" cutoff — worth naming explicitly rather than rounding it up to match its sibling
store, since a threshold this close is itself a useful thing to flag in a review, not smooth over.
It's still ~19x the network's healthy-store stockout rate. Fixing evening-shift staffing at these
two stores moves *two* of the three headline metrics simultaneously, which makes it the single
highest-leverage recommendation in this case study — a materially different conclusion than "fix
all three domains independently," and the kind of prioritization insight that only shows up once
you connect the domains instead of reviewing them in separate meetings.

## How this was built

- **Data**: Python (pandas/numpy) reorder-point inventory simulation + order-funnel time
  simulation, seeded so results are reproducible. Root causes are structural (warehouse mapping,
  shift staffing levels, zone distance) — not hand-coded onto rows — so they had to be *found*,
  not verified. See [`data/generate_data.py`](../data/generate_data.py).
- **Analysis**: SQLite + SQL — CTEs, window functions, and bucketed RCA queries across thirteen
  files in [`sql/`](../sql/): one per domain, the cross-domain composite, four new metrics, and
  follow-on findings (safety stock, cost-of-fix ROI, case-fill rate, fleet cost efficiency,
  contribution margin, order failures, ABC/XYZ segmentation).
- **Dashboard**: Streamlit + Plotly, seven tabs (Overview, Supply Chain, Store Ops, Last Mile,
  Cross-Domain RCA, New Metrics, Admin) with the same findings as the write-ups, interactively
  explorable. See [`dashboard/app.py`](../dashboard/app.py) — run with
  `streamlit run dashboard/app.py`.

## Beyond the demo: an ingestion layer, new metrics, and three rounds of review

The original version was a fixed, read-only snapshot — realistic data, but nowhere to put new
data in. Two additions turn it into an actual tool rather than a one-time report:

- **A password-gated Admin panel** (`🔐 Admin` tab) with spreadsheet upload (CSV/XLSX, validated
  against the real schema before commit), manual single-record entry, editable business
  assumptions, an audit log of every change, and a reset-to-baseline button. See
  [`dashboard/app.py`](../dashboard/app.py) and the *Admin panel* section of
  [`README.md`](../README.md).
- **Four new metrics** beyond the original KPI set — Perfect Order Rate, Inventory Days of Cover,
  Rider Utilization, and Cost-to-Serve per order — each proposed because it ties two domains
  together or converts ops performance into a ₹ figure (the kind of number that gets a
  recommendation funded, not just acknowledged). SQL in
  [`sql/06_new_metrics.sql`](../sql/06_new_metrics.sql); each query's comments are explicit about
  which parts are real schema data and which are labeled modeling assumptions (e.g. an assumed
  6-hour shift length, editable wage rates) — the kind of honesty about proxies vs. ground truth
  that matters more in a real ops review than in a demo.
- **A safety-stock policy review and a shrinkage finding**, both added after a supply-chain-domain
  review of the original analysis — the flat-buffer reorder formula and the stockout root cause
  were both real, but neither was the full picture. Section 6 and 7 of
  [`analysis/supply_chain_rca.md`](../analysis/supply_chain_rca.md) cover a variability-adjusted
  safety-stock formula (SQL: [`sql/07_safety_stock_policy.sql`](../sql/07_safety_stock_policy.sql))
  worth a ₹21.0L reallocation, and a ~₹18.5L shrinkage finding from an order-cycle/shelf-life
  mismatch in the two shortest-dated categories — a structurally different problem from the
  stockout one (network-wide, not store-concentrated), found by asking what the *existing* data
  could show once someone looked for it, not by adding new instrumentation.
- **A cost-of-the-fix pass on both headline recommendations** (SQL:
  [`sql/08_fix_roi.sql`](../sql/08_fix_roi.sql)), because a recommendation without a payback number
  gets discussed, not funded. The two fixes turned out to look very different once priced: the
  warehouse remap pays for itself on recovered revenue alone in 0.7–3.7 months across a wide range
  of assumed project cost (Section 8 of
  [`analysis/supply_chain_rca.md`](../analysis/supply_chain_rca.md)), while the evening-staffing
  fix's ₹404,160 labor cost is only 21% covered by direct cost-to-serve savings — the rest has to
  be justified on SLA/customer-retention grounds this schema can't price directly (Section 6 of
  [`analysis/store_ops_rca.md`](../analysis/store_ops_rca.md)). Presenting the gap honestly, rather
  than manufacturing a clean payback story, was a deliberate choice.
- **A second supply-chain review that found the "picker fix" was only half a fix, plus two more
  findings from data that already existed but nothing had queried.** Going back through this
  project like a 20-year supply-chain reviewer would surfaced three more things: (1) the
  evening-staffing recommendation above priced picker headcount only — riders at the same 3 stores
  are understaffed just as badly (56–68% vs. 89%+ elsewhere), and dispatch wait, the rider-driven
  funnel stage, degrades *more* than pick time does; correcting this roughly doubled the true fix
  cost and dropped its labor-efficiency coverage from a reported 42% to an honest 21% (Section 2
  and 6 of [`analysis/store_ops_rca.md`](../analysis/store_ops_rca.md)); (2) the same warehouse
  behind the stockout finding also ships incomplete orders ~99.9% of the time, short by ~10% on
  average — a second, independent reliability failure alongside its slow lead time (Section 9 of
  [`analysis/supply_chain_rca.md`](../analysis/supply_chain_rca.md), SQL:
  [`sql/09_case_fill_rate.sql`](../sql/09_case_fill_rate.sql)); (3) `dim_riders.vehicle_type`
  (EV/petrol/bicycle) had been generated since the very first version of this project and never
  used — it's now a fleet cost-efficiency finding worth ~₹2.26L/60d network-wide, concentrated at
  the same highest-risk East Delhi store (Section 6 of
  [`analysis/last_mile_rca.md`](../analysis/last_mile_rca.md), SQL:
  [`sql/10_fleet_cost_efficiency.sql`](../sql/10_fleet_cost_efficiency.sql)). Catching that a
  previous version of your own analysis was incomplete, and correcting it in the open rather than
  quietly, is itself the finding worth telling in an interview.
- **A third supply-chain review found the single biggest gap of all: `order_value` — revenue on
  every order — had never once been used in any analysis.** Grepping all SQL files and the
  dashboard turned up exactly one reference, in an admin-upload column list. Cost-to-Serve
  (labor cost) had sat in the same `fact_orders` table as `order_value` (revenue) since this
  project's first version; nothing had ever joined them. Fixing this properly took two steps, not
  one: first, `order_value` was rebuilt to derive from real `dim_skus` economics (`unit_cost` +
  margin) instead of an arbitrary flat range — done in a way that preserves the exact RNG draw
  sequence, so no other order's pick/dispatch/travel-time fields shifted (see the
  `BASKET_PRICE_FACTOR` comment in [`data/generate_data.py`](../data/generate_data.py) for the
  realism recalibration this required, the same discipline applied earlier to the shrinkage rate).
  Second, a genuine contribution-margin view was built on top of it (New Metrics tab; SQL:
  [`sql/11_contribution_margin.sql`](../sql/11_contribution_margin.sql)): net revenue, implied
  COGS, Cost-to-Serve, and net contribution per order, by store. Every store is profitable, but
  **DEL-E-01 and DEL-E-02 — the same two highest cross-domain risk stores — post the lowest net
  contribution per order in the network** (₹41 and ₹42 vs. the healthiest store's ₹57), closing
  the loop that every other finding in this project had left open: the problem isn't just service
  metrics, it's a measurable margin gap at the same two stores.
- **Two more findings surfaced by the same review**, both previously complete blind spots: (1) this
  project had never once tracked order cancellations, returns, or refunds — added a causally-modeled
  order-failure lifecycle (cancellations tied to severe understaffing, returns tied to SLA breach
  and rain) showing **~₹16.25L/60d** in cancelled/refunded value, concentrated in the same 3
  chronic-understaffed stores (Section 7 of
  [`analysis/store_ops_rca.md`](../analysis/store_ops_rca.md), SQL:
  [`sql/12_order_failures.sql`](../sql/12_order_failures.sql)) — converting part of the
  "SLA/customer-value" argument in the staffing-fix ROI case from a qualitative claim into a
  partial ₹ figure; (2) the safety-stock Z-factor was audited against a real value×variability
  ABC/XYZ matrix rather than the binary flag it had been using, finding an 11-SKU, modest but real
  mismatch (Section 10 of
  [`analysis/supply_chain_rca.md`](../analysis/supply_chain_rca.md), SQL:
  [`sql/13_abc_xyz_segmentation.sql`](../sql/13_abc_xyz_segmentation.sql)) — and the safety-stock
  reallocation itself was reframed from a book-value number into an annualized carrying-cost
  impact (**~₹4.21L/year net saving**), because that's the number that actually gets a
  working-capital change funded, not the balance-sheet figure.
- **A fourth pass caught two of this project's own metrics going stale relative to its own new
  work.** Perfect Order Rate and Rider Utilization (SQL:
  [`sql/06_new_metrics.sql`](../sql/06_new_metrics.sql) M1/M3) predated the order-failure fields
  added above and had never been updated to exclude cancelled/returned orders — 3.8% of orders
  this project's own dashboard was calling "perfect" had actually been cancelled or returned
  (network Perfect Order Rate overstated 79.72% vs. a corrected 76.70%; Rider Utilization
  overstated ~2–3%). Fixed with a two-line filter change, no schema or data regeneration required.
  Worth including because catching your own metric definitions drifting out of sync with your own
  new fields — and fixing it rather than leaving it — is a smaller but real version of the same
  discipline as the bigger corrections above.

## Using this for your application

- **Resume bullet (pick one):**
  - *"Built an end-to-end operational analytics case study simulating a 12-store dark-store
    network; used SQL-based RCA to identify a warehouse-mapping issue responsible for 98% of
    network stockout losses and a staffing gap driving 3 stores' SLA breach rates to 5–7x network
    average."*
  - *"Designed and queried a relational dataset spanning supply chain, store ops, and last-mile
    delivery; built a composite cross-domain risk score that surfaced 2 stores compounding
    problems across all three domains, invisible in any single-domain KPI view."*
  - *"Extended a read-only analytics dashboard into an admin-managed tool — schema-validated
    spreadsheet ingestion, audit logging, and configurable business assumptions — and proposed 4
    additional KPIs (incl. a labor-cost-to-serve metric) grounded in the existing data model."*
  - *"Reviewed a network's safety-stock policy against demand and lead-time variability computed
    empirically from the data; found the flat-buffer formula simultaneously under-protected the
    highest-risk warehouse and over-protected two stable ones, worth a ₹21.0L reallocation with no
    net increase in inventory spend."*
  - *"Quantified payback, not just cost, for two operational fixes — a warehouse remap (0.7–3.7
    month payback across a range of assumed project cost) and an evening-staffing gap (only 21%
    covered by direct cost-to-serve savings, requiring an explicit SLA/customer-value case for the
    remainder) — prioritizing recommendations by ROI, not just problem size."*
  - *"Re-audited my own prior RCA and found an incomplete fix: a staffing recommendation had priced
    picker headcount only, missing that riders at the same stores were understaffed just as badly
    and drove the larger share of the delay — correcting it roughly doubled the true fix cost and
    halved its reported ROI coverage. Also surfaced a second warehouse reliability failure
    (case-fill rate, not just lead time) and a ₹2.26L/60d fleet cost-efficiency finding from an
    existing but previously unused data field."*
  - *"Found that a dataset's revenue field had never been joined to its cost field across 20+
    analytical queries; rebuilt it to derive from real product economics and shipped a
    contribution-margin view that reframed the case study's headline operational findings as a
    measurable per-order profitability gap — the same two highest-risk stores turned out to be the
    two least profitable, closing the loop between service metrics and margin."*
- **In an interview**, walk the funnel: network KPI → segmentation → isolation → root cause →
  quantified recommendation. That's the structure every finding in this project follows, and it's
  the structure the JD is explicitly asking for ("Analyze data, perform RCA, and identify
  improvement opportunities").
- **If asked "is this real data"**: be upfront that it's simulated — the value being demonstrated
  is the analytical method (how you'd investigate), not a claim about Blinkit's actual operations.

## Caveat

All data is synthetic, generated for this project — it has no connection to Blinkit's actual
operations, systems, or performance. The numbers, store names, and findings above describe this
simulation only.
