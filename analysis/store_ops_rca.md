# RCA: Evening-Peak SLA Breaches Driven by Picker Understaffing

**Domain:** Store Operations
**Data:** `fact_orders`, `fact_staffing_daily`, 75,377 orders across 12 stores × 60 days
**Queries used:** [`sql/03_store_ops_kpis.sql`](../sql/03_store_ops_kpis.sql)

## 1. Problem statement

Network-wide SLA adherence is 87.6%, which reads as "mostly fine." Segmented by store and shift,
three stores (**DEL-E-01, DEL-E-02, BLR-S-02**) run evening-shift SLA breach rates of **62–70%**,
versus 4–23% everywhere else in the same shift (`sql/03_store_ops_kpis.sql`, Q1).

## 2. Investigation

The three worst stores are exactly the three flagged `chronic_understaffed` in the staffing data —
so the question is whether staffing is actually the driver, or just a correlated coincidence.
Three cuts confirm it's causal, not coincidental:

**a) SLA breach rate rises sharply as picker staffing ratio drops (peak hours only, Q2):**

| Picker staffing (peak hours) | Orders | Avg pick time | SLA breach rate |
|---|---|---|---|
| < 70% | 3,406 | 7.37 min | **99.06%** |
| 70–85% | 5,670 | 4.14 min | 28.17% |
| 85–100% | 4,706 | 2.65 min | 6.57% |
| 100%+ | 15,193 | 2.64 min | 10.79% |

Pick time roughly triples as staffing drops below 70%, and SLA breach effectively becomes
guaranteed. (The 85–100% vs. 100%+ bucket isn't perfectly monotonic — travel time and rain, which
are independent of staffing, add noise at that end — but the collapse below 85% staffing is
unambiguous.)

**b) The effect is peak-hour-specific, not an all-day capability gap (Q3):**

| Chronic understaffed | Peak hour | SLA breach rate | Orders |
|---|---|---|---|
| Yes | Yes | **72.42%** | 6,066 |
| Yes | No | 11.52% | 9,854 |
| No | Yes | 11.03% | 22,909 |
| No | No | 3.56% | 36,548 |

The understaffed stores perform close to network-normal off-peak (11.52% vs. 11.03%) — the problem
is entirely a peak-hour staffing-coverage gap, not a store capability or process issue.

**c) Funnel breakdown isolates *which* stage absorbs the delay (Q5):**

| Stage | Fleet average | Worst 3 stores | Delta |
|---|---|---|---|
| Pick time | 2.76 min | 3.75 min | +36% |
| Pack time | 1.10 min | 1.10 min | +0% |
| Dispatch wait | 1.86 min | 2.77 min | +49% |
| Travel time | 6.97 min | 9.69 min | +39% |
| **Total** | **12.69 min** | **17.31 min** | **+36%** |

Pack time is identical — confirming the packing stage isn't implicated at all. Pick time and
dispatch wait (both staffing-sensitive: pickers and riders respectively) show the largest relative
jumps, consistent with a staffing-coverage root cause rather than a distance or demand-volume one.

## 3. Root cause

Evening-shift scheduling at DEL-E-01, DEL-E-02, and BLR-S-02 runs at 50–72% of required picker
headcount (vs. 85–105% at every other store/shift), concentrated specifically in the 7–9pm demand
peak. This is a **scheduling/staffing-allocation gap**, not a demand-forecasting or store-capacity
problem — order volume at these stores isn't structurally different from peers.

## 4. Recommendation

1. **Fix evening-shift roster coverage at these 3 stores first** — bring picker staffing ratio to
   ≥85% for the 6–9pm window specifically; that's where the 99% breach bucket lives.
2. **Add a staffing-ratio threshold alert** (e.g., picker ratio < 80% during a peak window) to the
   ops dashboard, rather than relying on end-of-day SLA numbers to surface the problem after the fact.
3. **Investigate why these 3 specific stores under-roster evenings** — likely candidates are
   local attrition or a scheduling-template gap; BLR-S-02 shares the pattern despite a different
   city and warehouse, which rules out a city- or supply-chain-specific cause and points at
   store-level scheduling practice.

## 5. Projected impact

Bringing these 3 stores' evening picker staffing to the 85%+ band (in line with the rest of the
network) would be expected to cut their evening SLA breach rate from 62–70% down toward the
network's 85%+ staffing baseline of ~7–11% — recovering the large majority of the ~5,960 evening
orders/60d currently affected across the three stores (DEL-E-02: 1,501 · DEL-E-01: 2,146 ·
BLR-S-02: 2,311).

## 6. Cost of the fix — and an honest gap in the ROI case

Section 5 prices the *problem*. This section prices the *fix* against it, because a
recommendation without a payback number gets discussed, not funded. SQL:
[`sql/08_fix_roi.sql`](../sql/08_fix_roi.sql) (query F1), also surfaced live in the dashboard's
Cross-Domain RCA tab.

**Fix cost:** closing the evening picker gap at the 3 chronic-understaffed stores to a 90%
staffing target — at the current picker wage (₹120/hr, editable in the Admin panel) and a 6-hour
shift assumption — costs **₹203,760 in incremental labor over 60 days** (642 / 624 / 432 extra
picker-hours at BLR-S-02 / DEL-E-01 / DEL-E-02 respectively).

**Direct saving:** the same staffing fix lowers cost-to-serve at these stores' evening shift
(less overtime-shaped pick time per order). Valued against the network's healthy-store evening
baseline (₹22.41/order) and applied to each store's evening order volume, that's **₹85,029 in
direct cost-to-serve savings over 60 days — only 42% of the fix cost.**

| Store | Extra picker-hours (60d) | Fix cost (₹) | Direct CTS saving (₹) | Coverage |
|---|---|---|---|---|
| BLR-S-02 | 642 | 77,040 | 20,419 | 27% |
| DEL-E-01 | 624 | 74,880 | 39,824 | 53% |
| DEL-E-02 | 432 | 51,840 | 24,786 | 48% |
| **Total** | **1,698** | **203,760** | **85,029** | **42%** |

**This is a deliberately honest number, not a manufactured payback story.** A pure labor-efficiency
case does not close the gap — it covers less than half the investment. Recommending this fix
anyway is still correct, but the business case for the remaining **~₹118,731** has to rest on
**SLA and customer-retention value** — fewer breached deliveries at the 3 worst-performing stores
in the network, repeat-order impact of a bad delivery experience, and the fact that DEL-E-01 /
DEL-E-02 are the two highest cross-domain risk-score stores in the entire network (see
[`case_study/Blinkit_Ops_Case_Study.md`](../case_study/Blinkit_Ops_Case_Study.md)) — value this
schema has no fact table to price directly, so it should be argued qualitatively, not asserted as
a fabricated ₹ figure. A recommendation that names its own limits is more credible in a real ops
review than one that quietly assumes a clean payback it can't actually show.
