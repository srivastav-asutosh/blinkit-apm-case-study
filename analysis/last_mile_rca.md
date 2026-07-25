# RCA: East-Zone Delivery Delays — Distance, Rider Load, and Rain

**Domain:** Last Mile Operations
**Data:** `fact_orders`, 75,377 orders across 12 stores × 60 days
**Queries used:** [`sql/04_last_mile_kpis.sql`](../sql/04_last_mile_kpis.sql)

## 1. Problem statement

Delivery time and SLA breach rate both vary sharply by zone. East Delhi is the network's worst
zone by a wide margin: **19.24 min average delivery (p90: 26.11 min), 39.59% SLA breach**, versus
North Delhi's 11.64 min average / 2.90% breach — the best zone in the network (`sql/04_last_mile_kpis.sql`, Q1).

| Zone | City | Avg delivery | p90 delivery | SLA breach |
|---|---|---|---|---|
| East | Delhi | **19.24 min** | 26.11 min | **39.59%** |
| East | Bangalore | 15.77 min | 19.56 min | 18.65% |
| West | Bangalore | 13.52 min | 16.90 min | 8.11% |
| North | Bangalore | 12.79 min | 16.13 min | 6.83% |
| South | Delhi | 12.65 min | 15.88 min | 4.99% |
| South | Bangalore | 12.52 min | 17.37 min | 13.00% |
| West | Delhi | 11.95 min | 15.12 min | 4.27% |
| North | Delhi | 11.64 min | 14.75 min | 2.90% |

East zones are worst in *both* cities, which points at something structural to the zone (distance)
rather than a one-off local issue — but East Delhi is roughly 2x worse than East Bangalore, which
means distance alone doesn't explain the full gap.

## 2. Investigation — three independent levers, isolated one at a time

**a) Distance is a real, large driver (Q2):**

| Distance bucket | Avg travel time | SLA breach rate | Orders |
|---|---|---|---|
| < 2.0 km | 4.83 min | 4.15% | 26,340 |
| 2.0–3.0 km | 7.71 min | 9.40% | 32,045 |
| 3.0 km+ | 11.43 min | **30.90%** | 16,992 |

Breach rate rises ~7x from the shortest to longest distance bucket. East-zone stores sit at the
long end of this curve structurally (avg distance 3.1–3.9 km vs. 1.8–2.4 km elsewhere).

**b) Rain adds a large, independent penalty (Q2):**

| Condition | Avg delivery time | SLA breach rate |
|---|---|---|
| No rain | 13.26 min | 7.95% |
| Rain | 16.04 min | **37.96%** |

Rain days (~15% of days, city-level) nearly 5x the breach rate on their own, independent of zone
or staffing — this is a network-wide effect, not specific to East Delhi.

**c) Rider-load stress compounds on top of both (Q3):**

| Orders per rider (shift-level) | Avg dispatch wait | Avg SLA breach |
|---|---|---|
| < 8 | 1.93 min | 8.81% |
| 8–12 | 3.13 min | 34.64% |
| 12+ | 4.13 min | **60.02%** |

## 3. Root cause

East Delhi's headline number is **compounding, not single-cause**: it combines (1) the longest
structural delivery distance in the network, (2) the same rain exposure every Delhi store faces,
and (3) it's also home to two of the three chronically-understaffed stores from the store-ops RCA
(`analysis/store_ops_rca.md`) — so rider availability is thinnest exactly where distance is
longest. East Bangalore shows the same distance effect without the staffing compounding, which is
why it's elevated (18.65%) but not in East Delhi's territory (39.59%).

## 4. Recommendation

1. **Treat East Delhi (DEL-E-01, DEL-E-02) as the priority fix from the cross-domain view**
   (see `case_study/Blinkit_Ops_Case_Study.md`) — the staffing fix from the store-ops RCA directly
   reduces rider-load stress here too, since it's the same root cause showing up in a second metric.
2. **Distance-tiered promise times**: since SLA breach is structurally ~7x higher in the 3km+
   bucket, consider zone-aware promised-delivery windows rather than a flat target, so the metric
   reflects an achievable commitment rather than one that's set up to fail for far-zone customers.
3. **Pre-position extra riders on forecast rain days** — the rain effect is large (7.95% → 37.96%
   breach) and predictable a day ahead from weather forecasts, making it a proactive-staffing lever
   rather than a reactive one.

## 5. Projected impact

Distance and rain are largely structural (a distance-aware SLA reduces breach *reporting* without
requiring operational change; rain-day surge staffing is the actionable lever there). The
staffing fix already recommended in the store-ops RCA is the one lever that moves both the SLA
breach number *and* the last-mile number for East Delhi simultaneously — reinforcing it as the
single highest-leverage fix in this case study.
