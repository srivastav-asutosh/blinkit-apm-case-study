-- ============================================================================
-- Cost of the fix -- not just the cost of the problem.
-- Sections 1-7 across the RCA docs and sql/02, sql/03, sql/07 quantify what
-- each problem costs. This file prices the two headline *fixes* against
-- that cost, because a recommendation without a payback number doesn't get
-- funded -- it gets discussed.
-- ============================================================================

-- ---------------------------------------------------------------------------
-- F1. Staffing fix: labor cost to close BOTH the evening picker gap AND the
--     evening rider gap to a 90% target at the 3 chronic-understaffed
--     stores, vs. the direct cost-to-serve saving that closing them would
--     produce. Originally this only priced the picker side (sql/03 Q4) --
--     sql/03 Q6/Q7 show riders are understaffed by just as much (and
--     dispatch wait, the rider-driven funnel stage, degrades *more* than
--     pick time does), so pricing pickers alone was pricing half the fix.
--     Shift length assumed 6h (consistent with M3 in sql/06_new_metrics.sql);
--     wages from business_assumptions (editable in the Admin panel).
--     "Direct saving" = (current evening cost-to-serve at each understaffed
--     store − healthy-store evening cost-to-serve baseline) × evening order
--     volume. Cost-to-serve already blends pick+pack (picker-driven) and
--     dispatch+travel (rider-driven) time, so this saving figure already
--     reflects the benefit of fixing *both* gaps -- it does not need to be
--     computed twice. This is a labor-efficiency saving only -- it does NOT
--     include SLA/customer-retention value, which this schema can't price
--     directly.
-- ---------------------------------------------------------------------------
WITH target AS (SELECT 0.90 AS target_ratio),
picker_gap AS (
    SELECT
        s.store_id,
        SUM(MAX(0.0, (t.target_ratio * s.pickers_needed) - s.pickers_present)) AS extra_picker_headcount_days
    FROM fact_staffing_daily s
    JOIN dim_stores d ON d.store_id = s.store_id
    CROSS JOIN target t
    WHERE s.shift = 'Evening' AND d.chronic_understaffed = 1
    GROUP BY s.store_id
),
rider_gap AS (
    SELECT
        s.store_id,
        SUM(MAX(0.0, (t.target_ratio * s.riders_needed) - s.riders_on_shift)) AS extra_rider_headcount_days
    FROM fact_staffing_daily s
    JOIN dim_stores d ON d.store_id = s.store_id
    CROSS JOIN target t
    WHERE s.shift = 'Evening' AND d.chronic_understaffed = 1
    GROUP BY s.store_id
),
fix_cost AS (
    SELECT
        p.store_id,
        ROUND(p.extra_picker_headcount_days * 6.0, 1)                            AS extra_picker_hours_60d,
        ROUND(r.extra_rider_headcount_days * 6.0, 1)                             AS extra_rider_hours_60d,
        ROUND(p.extra_picker_headcount_days * 6.0 * ba.picker_hourly_wage_inr
              + r.extra_rider_headcount_days * 6.0 * ba.rider_hourly_wage_inr, 0) AS fix_cost_inr_60d
    FROM picker_gap p
    JOIN rider_gap r ON r.store_id = p.store_id, business_assumptions ba
    WHERE ba.id = 1
),
healthy_evening_cts AS (
    SELECT AVG(
        (o.pick_time_min + o.pack_time_min) / 60.0 * ba.picker_hourly_wage_inr
        + (o.dispatch_wait_min + o.travel_time_min) / 60.0 * ba.rider_hourly_wage_inr
    ) AS avg_cost_to_serve_inr
    FROM fact_orders o
    JOIN dim_stores d ON d.store_id = o.store_id, business_assumptions ba
    WHERE d.chronic_understaffed = 0 AND o.shift = 'Evening' AND ba.id = 1
),
store_evening_cts AS (
    SELECT
        o.store_id,
        COUNT(*) AS evening_orders_60d,
        AVG(
            (o.pick_time_min + o.pack_time_min) / 60.0 * ba.picker_hourly_wage_inr
            + (o.dispatch_wait_min + o.travel_time_min) / 60.0 * ba.rider_hourly_wage_inr
        ) AS avg_cost_to_serve_inr
    FROM fact_orders o
    JOIN dim_stores d ON d.store_id = o.store_id, business_assumptions ba
    WHERE o.shift = 'Evening' AND d.chronic_understaffed = 1 AND ba.id = 1
    GROUP BY o.store_id
)
SELECT
    fc.store_id,
    fc.extra_picker_hours_60d,
    fc.extra_rider_hours_60d,
    fc.fix_cost_inr_60d,
    ROUND(sec.avg_cost_to_serve_inr, 2)                    AS current_evening_cts_inr,
    ROUND((SELECT avg_cost_to_serve_inr FROM healthy_evening_cts), 2) AS healthy_baseline_cts_inr,
    sec.evening_orders_60d,
    ROUND((sec.avg_cost_to_serve_inr - (SELECT avg_cost_to_serve_inr FROM healthy_evening_cts))
          * sec.evening_orders_60d, 0)                      AS direct_cts_saving_inr_60d
FROM fix_cost fc
JOIN store_evening_cts sec ON sec.store_id = fc.store_id
ORDER BY fc.store_id;

-- ---------------------------------------------------------------------------
-- F2. Warehouse-remap payback sensitivity.
--     sql/02_supply_chain_kpis.sql Q2 puts est_lost_sales_value_inr at
--     WH-DEL-SECONDARY at roughly ₹270K/60d (fast-moving SKUs) -- the
--     revenue a remap (or a lead-time and case-fill-rate fix at that
--     warehouse -- see sql/09_case_fill_rate.sql) would recover. The
--     one-time remap/negotiation cost isn't in this schema (it's a real-world
--     project cost, not an operational metric), so this prices payback
--     across a plausible range instead of asserting a single number.
-- ---------------------------------------------------------------------------
WITH recoverable AS (
    SELECT SUM(i.lost_units * k.unit_cost) / 2.0 AS recoverable_value_per_month_inr
    FROM fact_inventory_daily i
    JOIN dim_stores s ON s.store_id = i.store_id
    JOIN dim_skus k ON k.sku_id = i.sku_id
    WHERE k.is_fast_moving = 1 AND s.warehouse_id = 'WH-DEL-SECONDARY'
),
assumed_costs(one_time_cost_inr) AS (
    VALUES (100000), (200000), (350000), (500000)
)
SELECT
    a.one_time_cost_inr,
    ROUND(r.recoverable_value_per_month_inr, 0)                     AS recoverable_value_per_month_inr,
    ROUND(a.one_time_cost_inr / r.recoverable_value_per_month_inr, 1) AS payback_months
FROM assumed_costs a, recoverable r
ORDER BY a.one_time_cost_inr;
