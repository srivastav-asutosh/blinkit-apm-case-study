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
| Supply Chain | 99.8% fill rate | 3 stores carry 93% of ₹2.97L lost sales | 3 stores mapped to a 3-day-lead-time warehouse; safety stock isn't sized for that lead time |
| Store Ops | 87.6% SLA adherence | 3 stores hit 62–70% evening breach | Evening-shift picker staffing at 50–72% of need, concentrated in the 7–9pm peak |
| Last Mile | 13.7 min avg delivery | East Delhi hits 39.6% breach, 19.2 min avg | Compounding: longest structural distance + same rain exposure + the same 2 understaffed stores |

Full detail and SQL for each: [`analysis/supply_chain_rca.md`](../analysis/supply_chain_rca.md) ·
[`analysis/store_ops_rca.md`](../analysis/store_ops_rca.md) ·
[`analysis/last_mile_rca.md`](../analysis/last_mile_rca.md)

## The cross-domain finding (the part a network-average dashboard would never show you)

Scoring every store 0–8 across all three domains (methodology in
[`sql/05_cross_domain_rca.sql`](../sql/05_cross_domain_rca.sql)) surfaces a pattern that no
single-domain view can:

| Store | Stockout % | SLA breach % | Avg delivery (min) | Risk score | Story |
|---|---|---|---|---|---|
| DEL-E-01 / DEL-E-02 | 1.3% | 38.5% / 41.2% | 19.0 / 19.6 | **8 / 8** | Fails all three — compounding risk |
| BLR-S-02 | 0.05% | 26.6% | 14.1 | 4 | Staffing-only — proves it's not a Delhi/warehouse issue |
| DEL-S-02 | 1.49% | 5.4% | 12.9 | 3 | Supply-chain-only — isolates the warehouse as the driver |
| BLR-E-01 | 0.00% | 18.7% | 15.8 | 2 | Distance-only — East-zone effect without staffing on top |
| Every other store | ≤0.05% | ≤8.9% | ≤13.8 | **0** | Clean baseline |

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

## Using this for your application

- **Resume bullet (pick one):**
  - *"Built an end-to-end operational analytics case study simulating a 12-store dark-store
    network; used SQL-based RCA to identify a warehouse-mapping issue responsible for 93% of
    network stockout losses and a staffing gap driving 3 stores' SLA breach rates to 5–7x network
    average."*
  - *"Designed and queried a relational dataset spanning supply chain, store ops, and last-mile
    delivery; built a composite cross-domain risk score that surfaced 2 stores compounding
    problems across all three domains, invisible in any single-domain KPI view."*
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
