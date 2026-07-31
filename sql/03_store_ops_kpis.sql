-- ============================================================================
-- Store Operations — KPIs and RCA
-- ============================================================================

-- ---------------------------------------------------------------------------
-- Q1. SLA adherence and pick time by store, evening shift only (this is
--     where the chronic-understaffed stores are expected to show up)
-- ---------------------------------------------------------------------------
SELECT
    o.store_id,
    s.chronic_understaffed,
    ROUND(AVG(o.picker_staffing_ratio), 2)        AS avg_picker_staffing_ratio,
    ROUND(AVG(o.pick_time_min), 2)                AS avg_pick_time_min,
    ROUND(100.0 * SUM(o.sla_breach) / COUNT(*), 2) AS sla_breach_pct,
    COUNT(*)                                        AS orders
FROM fact_orders o
JOIN dim_stores s ON s.store_id = o.store_id
WHERE o.shift = 'Evening'
GROUP BY o.store_id, s.chronic_understaffed
ORDER BY sla_breach_pct DESC;

-- ---------------------------------------------------------------------------
-- Q2. Root cause: SLA breach rate by picker-staffing-ratio bucket
--     (the core RCA query — buckets orders by how understaffed the shift
--      was at the moment the order was picked, independent of which store)
-- ---------------------------------------------------------------------------
SELECT
    CASE
        WHEN picker_staffing_ratio < 0.70 THEN '1. Severely understaffed (<70%)'
        WHEN picker_staffing_ratio < 0.85 THEN '2. Understaffed (70-85%)'
        WHEN picker_staffing_ratio < 1.00 THEN '3. Near full staffing (85-100%)'
        ELSE '4. Fully staffed (100%+)'
    END                                             AS staffing_bucket,
    COUNT(*)                                         AS orders,
    ROUND(AVG(pick_time_min), 2)                     AS avg_pick_time_min,
    ROUND(100.0 * SUM(sla_breach) / COUNT(*), 2)     AS sla_breach_pct
FROM fact_orders
WHERE is_peak_hour = 1
GROUP BY staffing_bucket
ORDER BY staffing_bucket;

-- ---------------------------------------------------------------------------
-- Q3. Peak vs. off-peak SLA breach, split by chronic-understaffed flag
--     (shows the problem is peak-hours-specific, not an all-day issue —
--      i.e. it's a staffing/scheduling problem, not a store capability one)
-- ---------------------------------------------------------------------------
SELECT
    s.chronic_understaffed,
    o.is_peak_hour,
    ROUND(100.0 * SUM(o.sla_breach) / COUNT(*), 2) AS sla_breach_pct,
    COUNT(*)                                        AS orders
FROM fact_orders o
JOIN dim_stores s ON s.store_id = o.store_id
GROUP BY s.chronic_understaffed, o.is_peak_hour
ORDER BY s.chronic_understaffed DESC, o.is_peak_hour DESC;

-- ---------------------------------------------------------------------------
-- Q4. Shift-level staffing shortfall ranking — which store/shift combos run
--     furthest below their needed picker headcount, on average
-- ---------------------------------------------------------------------------
SELECT
    store_id,
    shift,
    ROUND(AVG(picker_staffing_ratio), 2)        AS avg_staffing_ratio,
    ROUND(AVG(pickers_needed - pickers_present), 1) AS avg_picker_shortfall,
    COUNT(*)                                       AS shift_days
FROM fact_staffing_daily
GROUP BY store_id, shift
HAVING avg_staffing_ratio < 0.85
ORDER BY avg_staffing_ratio ASC;

-- ---------------------------------------------------------------------------
-- Q5. Order funnel breakdown (pick / pack / dispatch / travel) for the three
--     worst SLA-breach stores vs. the fleet average — isolates which stage
--     of the funnel is actually driving the gap
-- ---------------------------------------------------------------------------
SELECT
    CASE WHEN store_id IN ('DEL-E-01', 'DEL-E-02', 'BLR-S-02') THEN 'Worst 3 stores' ELSE 'Fleet average' END AS store_group,
    ROUND(AVG(pick_time_min), 2)       AS avg_pick_min,
    ROUND(AVG(pack_time_min), 2)       AS avg_pack_min,
    ROUND(AVG(dispatch_wait_min), 2)   AS avg_dispatch_wait_min,
    ROUND(AVG(travel_time_min), 2)     AS avg_travel_min,
    ROUND(AVG(total_delivery_min), 2)  AS avg_total_min
FROM fact_orders
GROUP BY store_group;

-- ---------------------------------------------------------------------------
-- Q6. Rider staffing shortfall ranking — the exact mirror of Q4, but for
--     riders instead of pickers. Q5 shows dispatch wait (+49%) actually
--     jumps *more* than pick time (+36%) at the worst 3 stores -- this query
--     checks whether that's because riders are understaffed too, not just
--     pickers.
-- ---------------------------------------------------------------------------
SELECT
    store_id,
    shift,
    ROUND(AVG(rider_staffing_ratio), 2)          AS avg_rider_staffing_ratio,
    ROUND(AVG(riders_needed - riders_on_shift), 1) AS avg_rider_shortfall,
    COUNT(*)                                        AS shift_days
FROM fact_staffing_daily
GROUP BY store_id, shift
HAVING avg_rider_staffing_ratio < 0.85
ORDER BY avg_rider_staffing_ratio ASC;

-- ---------------------------------------------------------------------------
-- Q7. Dispatch wait & SLA breach by rider-staffing bucket, peak hours —
--     the exact mirror of Q2, confirming dispatch wait is just as
--     staffing-sensitive as pick time, via a *different* headcount lever.
-- ---------------------------------------------------------------------------
SELECT
    CASE
        WHEN o.riders_on_shift * 1.0 / s.riders_needed < 0.70 THEN '1. Severely understaffed (<70%)'
        WHEN o.riders_on_shift * 1.0 / s.riders_needed < 0.85 THEN '2. Understaffed (70-85%)'
        WHEN o.riders_on_shift * 1.0 / s.riders_needed < 1.00 THEN '3. Near full staffing (85-100%)'
        ELSE '4. Fully staffed (100%+)'
    END                                             AS rider_staffing_bucket,
    COUNT(*)                                         AS orders,
    ROUND(AVG(o.dispatch_wait_min), 2)               AS avg_dispatch_wait_min,
    ROUND(100.0 * SUM(o.sla_breach) / COUNT(*), 2)   AS sla_breach_pct
FROM fact_orders o
JOIN fact_staffing_daily s ON s.store_id = o.store_id AND s.date = o.date AND s.shift = o.shift
WHERE o.is_peak_hour = 1
GROUP BY rider_staffing_bucket
ORDER BY rider_staffing_bucket;
