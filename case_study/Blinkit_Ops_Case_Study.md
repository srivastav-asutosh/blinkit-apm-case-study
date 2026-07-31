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
| Supply Chain | 99.8% fill rate | 3 stores carry 99% of ₹3.22L lost sales | 3 stores mapped to a 3-day-lead-time warehouse; safety stock isn't sized for that lead time |
| Store Ops | 87.6% SLA adherence | 3 stores hit 62–70% evening breach | Evening-shift picker staffing at 50–72% of need, concentrated in the 7–9pm peak |
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
| DEL-E-01 / DEL-E-02 | 1.5% / 1.2% | 40.3% / 40.6% | 19.2 / 19.5 | **8 / 8** | Fails all three — compounding risk |
| BLR-S-02 | 0.08% | 26.8% | 14.2 | 4 | Staffing-only — proves it's not a Delhi/warehouse issue |
| DEL-S-02 | 1.49% | 6.0% | 13.0 | 3 | Supply-chain-only — isolates the warehouse as the driver |
| BLR-E-01 | 0.05% | 15.7% | 15.6 | 2 | Distance-only — East-zone effect without staffing on top |
| Every other store | ≤0.03% | ≤8.8% | ≤13.8 | **0** | Clean baseline |

**The takeaway an APM would bring to a review:** DEL-E-01 and DEL-E-02 aren't three separate small
problems — they're one staffing gap showing up in three different KPIs at once (pick time → SLA
breach; rider load → last-mile delay; and the same store pair happens to sit on the slow
warehouse too). Fixing evening-shift staffing at those two stores moves *two* of the three
headline metrics simultaneously, which makes it the single highest-leverage recommendation in this
case study — a materially different conclusion than "fix all three domains independently," and
the kind of prioritization insight that only shows up once you connect the domains instead of
reviewing them in separate meetings.

## How this was built

- **Data**: Python (pandas/numpy) reorder-point inventory simulation + order-funnel time
  simulation, seeded so results are reproducible. Root causes are structural (warehouse mapping,
  shift staffing levels, zone distance) — not hand-coded onto rows — so they had to be *found*,
  not verified. See [`data/generate_data.py`](../data/generate_data.py).
- **Analysis**: SQLite + SQL — CTEs, window functions, and bucketed RCA queries across four files
  in [`sql/`](../sql/), one per domain plus the cross-domain composite.
- **Dashboard**: Streamlit + Plotly, five views (Overview, Supply Chain, Store Ops, Last Mile,
  Cross-Domain RCA) with the same findings as the write-ups, interactively explorable. See
  [`dashboard/app.py`](../dashboard/app.py) — run with `streamlit run dashboard/app.py`.

## Beyond the demo: an ingestion layer and four new metrics

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
  worth a ₹19.5L reallocation, and a ~₹20.5L shrinkage finding from an order-cycle/shelf-life
  mismatch in the two shortest-dated categories — a structurally different problem from the
  stockout one (network-wide, not store-concentrated), found by asking what the *existing* data
  could show once someone looked for it, not by adding new instrumentation.
- **A cost-of-the-fix pass on both headline recommendations** (SQL:
  [`sql/08_fix_roi.sql`](../sql/08_fix_roi.sql)), because a recommendation without a payback number
  gets discussed, not funded. The two fixes turned out to look very different once priced: the
  warehouse remap pays for itself on recovered revenue alone in 0.6–3.1 months across a wide range
  of assumed project cost (Section 8 of
  [`analysis/supply_chain_rca.md`](../analysis/supply_chain_rca.md)), while the evening-staffing
  fix's ₹203,760 labor cost is only 42% covered by direct cost-to-serve savings — the rest has to
  be justified on SLA/customer-retention grounds this schema can't price directly (Section 6 of
  [`analysis/store_ops_rca.md`](../analysis/store_ops_rca.md)). Presenting the gap honestly, rather
  than manufacturing a clean payback story, was a deliberate choice.

## Using this for your application

- **Resume bullet (pick one):**
  - *"Built an end-to-end operational analytics case study simulating a 12-store dark-store
    network; used SQL-based RCA to identify a warehouse-mapping issue responsible for 99% of
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
    highest-risk warehouse and over-protected two stable ones, worth a ₹19.5L reallocation with no
    net increase in inventory spend."*
  - *"Quantified payback, not just cost, for two operational fixes — a warehouse remap (0.6–3.1
    month payback across a range of assumed project cost) and an evening-staffing gap (only 42%
    covered by direct cost-to-serve savings, requiring an explicit SLA/customer-value case for the
    remainder) — prioritizing recommendations by ROI, not just problem size."*
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
