# RCA: Evening-Peak SLA Breaches Driven by Picker AND Rider Understaffing

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
Four cuts confirm it's causal, not coincidental:

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

Pack time is identical — confirming the packing stage isn't implicated at all. Dispatch wait
(rider-driven, **+49%**) degrades *more* than pick time (picker-driven, **+36%**) — the largest
relative jump of any stage — which raised the question answered in cut (d): is dispatch wait
elevated because riders are understaffed too, or just because pickers are?

**d) Riders are understaffed by just as much as pickers, at the same 3 stores (Q6/Q7):**

| Rider staffing (peak hours) | Orders | Avg dispatch wait | SLA breach rate |
|---|---|---|---|
| < 70% | 2,969 | 5.42 min | **99.73%** |
| 70–85% | 4,505 | 2.96 min | 34.30% |
| 85–100% | 12,475 | 1.58 min | 10.78% |
| 100%+ | 9,140 | 1.31 min | 10.81% |

| Store | Evening rider staffing ratio | Evening rider shortfall (avg) |
|---|---|---|
| DEL-E-01 | 57% | 3.0 riders |
| BLR-S-02 | 56% | 3.0 riders |
| DEL-E-02 | 68% | 1.3 riders |

This is the exact mirror of cut (a) for pickers — same 3 stores, same magnitude of shortfall, same
collapse in the severely-understaffed bucket. **The original version of this RCA treated the
problem as picker-only.** It wasn't: riders are short by just as much, and dispatch wait — the
stage riders drive — degrades more than pick time does.

## 3. Root cause

Evening-shift scheduling at DEL-E-01, DEL-E-02, and BLR-S-02 runs at 50–72% of required picker
headcount **and 56–68% of required rider headcount** (vs. 85–105% picker / 89%+ rider at every
other store/shift), concentrated specifically in the 7–9pm demand peak. This is a
**scheduling/staffing-allocation gap affecting both roles**, not a demand-forecasting or
store-capacity problem — order volume at these stores isn't structurally different from peers.

## 4. Recommendation

1. **Fix evening-shift roster coverage at these 3 stores first — pickers AND riders** — bring both
   staffing ratios to ≥85–90% for the 6–9pm window specifically; that's where the 99%+ breach
   buckets live for both roles. A picker-only fix leaves dispatch wait (the larger of the two
   funnel-stage jumps) largely unaddressed.
2. **Add a staffing-ratio threshold alert** (e.g., picker or rider ratio < 80% during a peak
   window) to the ops dashboard, rather than relying on end-of-day SLA numbers to surface the
   problem after the fact.
3. **Investigate why these 3 specific stores under-roster evenings on both roles** — likely
   candidates are local attrition or a scheduling-template gap; BLR-S-02 shares the pattern despite
   a different city and warehouse, which rules out a city- or supply-chain-specific cause and
   points at store-level scheduling practice.

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

**This section originally priced picker headcount only.** Cut (d) above shows that was pricing
half the fix — riders are understaffed by just as much, and dispatch wait (the rider-driven
funnel stage) degrades *more* than pick time does. The numbers below now include both.

**Fix cost:** closing the evening picker gap AND the evening rider gap at the 3
chronic-understaffed stores to a 90% staffing target — at current wages (picker ₹120/hr, rider
₹100/hr, both editable in the Admin panel) and a 6-hour shift assumption — costs **₹404,160 in
incremental labor over 60 days**, roughly double the picker-only figure this RCA originally cited.

**Direct saving:** the same staffing fix lowers cost-to-serve at these stores' evening shift
(cost-to-serve blends pick+pack time, picker-driven, with dispatch+travel time, rider-driven — so
this saving figure was already implicitly pricing the benefit of fixing *both* gaps, even before
the fix cost caught up to include both). Valued against the network's healthy-store evening
baseline (₹22.41/order) and applied to each store's evening order volume, that's **₹85,029 in
direct cost-to-serve savings over 60 days — unchanged from before, but now only 21% of the true
fix cost, not 42%.**

| Store | Extra picker-hours (60d) | Extra rider-hours (60d) | Fix cost (₹) | Direct CTS saving (₹) | Coverage |
|---|---|---|---|---|---|
| BLR-S-02 | 642 | 846 | 161,640 | 20,419 | 13% |
| DEL-E-01 | 624 | 834 | 158,280 | 39,824 | 25% |
| DEL-E-02 | 432 | 324 | 84,240 | 24,786 | 29% |
| **Total** | **1,698** | **2,004** | **404,160** | **85,029** | **21%** |

**This is a deliberately honest number, not a manufactured payback story — and it's a more honest
number than this RCA originally reported.** Pricing pickers alone made the fix look like it
covered 42% of its own cost; pricing the fix completely shows it actually covers 21%. The
labor-efficiency case was weaker than first stated, not stronger — a correction worth surfacing
explicitly rather than quietly. Recommending this fix anyway is still correct, but the business
case for the remaining **~₹319,131** has to rest even more heavily on **SLA and customer-retention
value** — fewer breached deliveries at the 3 worst-performing stores in the network, repeat-order
impact of a bad delivery experience, and the fact that DEL-E-01 / DEL-E-02 are the two highest
cross-domain risk-score stores in the entire network (see
[`case_study/Blinkit_Ops_Case_Study.md`](../case_study/Blinkit_Ops_Case_Study.md)) — value this
schema has no fact table to price directly, so it should be argued qualitatively, not asserted as
a fabricated ₹ figure. A recommendation that names its own limits — and corrects them when a
deeper look finds more — is more credible in a real ops review than one that quietly assumes a
clean payback it can't actually show.

## 7. The SLA/customer-value argument from Section 6, quantified: order failures

Section 6 says the remaining ~₹319,131 has to rest on SLA and customer-retention value "this
schema can't price directly." That was true before this round — this section closes part of that
gap. Until now, nothing in this project tracked cancellations, returns, or refunds at all.
**Queries used:** [`sql/12_order_failures.sql`](../sql/12_order_failures.sql)

Modeled causally rather than as an unrelated random layer: cancellations are elevated under severe
peak-hour understaffing (an order that can't realistically be fulfilled sometimes gets cancelled
rather than delivered extremely late); returns are elevated by SLA breach (late delivery) and rain
(transit damage) — both drivers already established elsewhere in this case study.

| Condition | Orders | Cancellation rate |
|---|---|---|
| Severe understaffing + peak | 3,490 | **8.22%** |
| All other conditions | 71,914 | 1.52% |

| Store | Total orders | Cancelled | Returned | Failure rate | Cancelled value | Refund value |
|---|---|---|---|---|---|---|
| DEL-E-01 | 5,891 | 206 | 249 | **7.72%** | ₹92,778 | ₹111,448 |
| BLR-S-02 | 5,977 | 189 | 215 | **6.76%** | ₹88,909 | ₹103,308 |
| DEL-E-02 | 3,925 | 82 | 168 | **6.37%** | ₹38,294 | ₹80,044 |
| Next-highest (BLR-W-01) | 5,944 | 102 | 192 | 4.95% | ₹42,817 | ₹81,650 |

**The same 3 chronic-understaffed stores are, again, the top 3 by order-failure rate** — clearly
separated from the rest of the network (4.95% next-highest vs. 6.37%+ for the three). Network-wide:
**₹618,980 in cancelled order value plus ₹1,006,360 in refunds — ~₹1,625,340 over 60 days.**

**This doesn't create a new recommendation** — the fix is the same evening-staffing fix already
priced in Section 6. What it does is convert part of the "SLA and customer-retention value" the
staffing-fix ROI case rests on from a qualitative argument into a partial ₹ figure: fixing the
staffing gap would be expected to reduce order failures at these 3 stores toward the network's
~4% baseline, recovering a meaningful share of the ~₹1.6L/60d currently lost to cancellations and
refunds — on top of, not instead of, the SLA/retention value that still can't be priced directly
(repeat-order impact, brand trust). It doesn't fully close the ₹319,131 gap, but it's no longer a
purely qualitative argument either.
