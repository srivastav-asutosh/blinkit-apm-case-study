# RCA: East-Zone Delivery Delays — Distance, Rider Load, and Rain

**Domain:** Last Mile Operations
**Data:** `fact_orders`, 75,404 orders across 12 stores × 60 days
**Queries used:** [`sql/04_last_mile_kpis.sql`](../sql/04_last_mile_kpis.sql)

## 1. Problem statement

Delivery time and SLA breach rate both vary sharply by zone. East Delhi is the network's worst
zone by a wide margin: **19.21 min average delivery (p90: 26.02 min), 39.43% SLA breach**, versus
North Delhi's 11.70 min average / 3.76% breach — the best zone in the network (`sql/04_last_mile_kpis.sql`, Q1).
(Figures throughout this document exclude cancelled orders, which have no real delivery time or
SLA outcome — see `analysis/store_ops_rca.md` Section 7.)

| Zone | City | Avg delivery | p90 delivery | SLA breach |
|---|---|---|---|---|
| East | Delhi | **19.21 min** | 26.02 min | **39.43%** |
| East | Bangalore | 15.57 min | 19.09 min | 15.80% |
| West | Bangalore | 13.54 min | 16.95 min | 8.56% |
| South | Delhi | 12.65 min | 15.93 min | 5.81% |
| North | Bangalore | 12.64 min | 15.95 min | 5.88% |
| South | Bangalore | 12.41 min | 17.21 min | 12.15% |
| West | Delhi | 11.99 min | 15.20 min | 4.20% |
| North | Delhi | 11.70 min | 14.85 min | 3.76% |

East zones are worst in *both* cities, which points at something structural to the zone (distance)
rather than a one-off local issue — but East Delhi is roughly 2x worse than East Bangalore, which
means distance alone doesn't explain the full gap.

## 2. Investigation — three independent levers, isolated one at a time

**a) Distance is a real, large driver (Q2):**

| Distance bucket | Avg travel time | SLA breach rate | Orders |
|---|---|---|---|
| < 2.0 km | 4.83 min | 3.87% | 26,083 |
| 2.0–3.0 km | 7.71 min | 9.35% | 31,514 |
| 3.0 km+ | 11.41 min | **30.38%** | 16,430 |

Breach rate rises ~7x from the shortest to longest distance bucket. East-zone stores sit at the
long end of this curve structurally (avg distance 3.1–3.9 km vs. 1.8–2.4 km elsewhere).

**b) Rain adds a large, independent penalty (Q2):**

| Condition | Avg delivery time | SLA breach rate |
|---|---|---|
| No rain | 13.19 min | 7.51% |
| Rain | 15.98 min | **38.05%** |

Rain days (~15% of days, city-level) nearly 5x the breach rate on their own, independent of zone
or staffing — this is a network-wide effect, not specific to East Delhi.

**c) Rider-load stress compounds on top of both (Q3):**

| Orders per rider (shift-level) | Avg dispatch wait | Avg SLA breach |
|---|---|---|
| < 8 | 1.94 min | 9.17% |
| 8–12 | 3.22 min | 34.61% |
| 12+ | 4.36 min | **66.79%** |

## 3. Root cause

East Delhi's headline number is **compounding, not single-cause**: it combines (1) the longest
structural delivery distance in the network, (2) the same rain exposure every Delhi store faces,
and (3) it's also home to two of the three chronically-understaffed stores from the store-ops RCA
(`analysis/store_ops_rca.md`) — so rider availability is thinnest exactly where distance is
longest. East Bangalore shows the same distance effect without the staffing compounding, which is
why it's elevated (15.80%) but not in East Delhi's territory (39.43%).

## 4. Recommendation

1. **Treat East Delhi (DEL-E-01, DEL-E-02) as the priority fix from the cross-domain view**
   (see `case_study/Blinkit_Ops_Case_Study.md`) — the staffing fix from the store-ops RCA directly
   reduces rider-load stress here too, since it's the same root cause showing up in a second
   metric. (Earlier drafts of this case study priced only the picker side of that fix; Section 6
   of `analysis/store_ops_rca.md` now prices the rider side too, which is the half that actually
   moves dispatch wait and therefore this domain's numbers.)
2. **Distance-tiered promise times**: since SLA breach is structurally ~7x higher in the 3km+
   bucket, consider zone-aware promised-delivery windows rather than a flat target, so the metric
   reflects an achievable commitment rather than one that's set up to fail for far-zone customers.
3. **Pre-position extra riders on forecast rain days** — the rain effect is large (7.51% → 38.05%
   breach) and predictable a day ahead from weather forecasts, making it a proactive-staffing lever
   rather than a reactive one.

## 5. Projected impact

Distance and rain are largely structural (a distance-aware SLA reduces breach *reporting* without
requiring operational change; rain-day surge staffing is the actionable lever there). The
staffing fix already recommended in the store-ops RCA is the one lever that moves both the SLA
breach number *and* the last-mile number for East Delhi simultaneously — reinforcing it as the
single highest-leverage fix in this case study.

## 6. A separate lever: fleet cost, not delivery time

Everything above is about *speed*. `dim_riders` also carries a vehicle-type dimension (EV
Scooter / Petrol Scooter / Bicycle) that, until now, nothing in this project used — it had no
effect on delivery time in the simulation and no query touched it. **Queries used:**
[`sql/10_fleet_cost_efficiency.sql`](../sql/10_fleet_cost_efficiency.sql)

This isn't a speed fix (vehicle mix wasn't wired into travel time, deliberately — see the caveat
below), it's a *cost* fix: network fleet running cost is ₹765,177/60d under the current mix vs. an
₹539,588 reference cost under an all-EV fleet, and cost efficiency varies more than 2x across
stores (₹1.40–₹3.30/km) purely from differences in fleet composition. **DEL-E-02 — already one of
the two highest cross-domain risk stores — also runs the least cost-efficient fleet at only 33%
EV**, meaning it's carrying both a service problem and an avoidable cost problem simultaneously.

**Caveat, stated deliberately:** vehicle type was *not* wired into the travel-time simulation
itself, specifically to avoid re-perturbing every already-cited last-mile number a second time
(the same RNG-stream lesson learned earlier in this project's build). The cost analysis is
therefore accurate; a claim that switching vehicle mix would also speed up deliveries would not
be — that causal link isn't modeled here, and would need to be verified against real telemetry
(EV vs. petrol scooter speed/reliability in actual traffic conditions) before being asserted.
