-- ============================================================================
-- Last Mile Operations — KPIs and RCA
-- ============================================================================

-- ---------------------------------------------------------------------------
-- Q1. Delivery time percentiles and SLA breach by zone
--     (SQLite has no native PERCENTILE_CONT; approximate p90 via a
--      cumulative-distribution window function instead)
--     Excludes cancelled orders throughout this file -- a cancelled order
--     has no real delivery time or SLA outcome even though this model still
--     computes hypothetical values for it before the cancellation is
--     decided (see sql/12_order_failures.sql). Same fix as sql/03 Q1-Q3/Q5/Q7
--     and sql/06_new_metrics.sql M1/M3.
-- ---------------------------------------------------------------------------
WITH ranked AS (
    SELECT
        s.zone,
        s.city,
        o.total_delivery_min,
        o.sla_breach,
        PERCENT_RANK() OVER (PARTITION BY s.zone, s.city ORDER BY o.total_delivery_min) AS pct_rank
    FROM fact_orders o
    JOIN dim_stores s ON s.store_id = o.store_id
    WHERE o.is_cancelled = 0
)
SELECT
    zone,
    city,
    ROUND(AVG(total_delivery_min), 2)                                             AS avg_delivery_min,
    ROUND(MIN(CASE WHEN pct_rank >= 0.90 THEN total_delivery_min END), 2)         AS p90_delivery_min,
    ROUND(100.0 * SUM(sla_breach) / COUNT(*), 2)                                   AS sla_breach_pct,
    COUNT(*)                                                                        AS orders
FROM ranked
GROUP BY zone, city
ORDER BY avg_delivery_min DESC;

-- ---------------------------------------------------------------------------
-- Q2. Root cause split: distance vs. rain vs. rider availability
--     (three independent levers, isolated one at a time)
-- ---------------------------------------------------------------------------
SELECT
    CASE
        WHEN distance_km < 2.0 THEN '1. <2.0 km'
        WHEN distance_km < 3.0 THEN '2. 2.0-3.0 km'
        ELSE '3. 3.0 km+'
    END                                             AS distance_bucket,
    ROUND(AVG(travel_time_min), 2)                   AS avg_travel_min,
    ROUND(100.0 * SUM(sla_breach) / COUNT(*), 2)     AS sla_breach_pct,
    COUNT(*)                                          AS orders
FROM fact_orders
WHERE is_cancelled = 0
GROUP BY distance_bucket
ORDER BY distance_bucket;

SELECT
    is_rain_day,
    ROUND(AVG(travel_time_min), 2)                 AS avg_travel_min,
    ROUND(AVG(total_delivery_min), 2)               AS avg_total_min,
    ROUND(100.0 * SUM(sla_breach) / COUNT(*), 2)     AS sla_breach_pct,
    COUNT(*)                                          AS orders
FROM fact_orders
WHERE is_cancelled = 0
GROUP BY is_rain_day;

-- ---------------------------------------------------------------------------
-- Q3. Rider-load stress: dispatch wait time vs. orders-per-rider ratio
-- ---------------------------------------------------------------------------
WITH shift_load AS (
    SELECT
        o.store_id,
        o.date,
        o.shift,
        COUNT(*)                          AS orders_in_shift,
        AVG(o.riders_on_shift)             AS riders_on_shift,
        AVG(o.dispatch_wait_min)            AS avg_dispatch_wait_min,
        100.0 * SUM(o.sla_breach) / COUNT(*) AS sla_breach_pct
    FROM fact_orders o
    WHERE o.is_cancelled = 0
    GROUP BY o.store_id, o.date, o.shift
)
SELECT
    CASE
        WHEN orders_in_shift * 1.0 / riders_on_shift < 8  THEN '1. <8 orders/rider'
        WHEN orders_in_shift * 1.0 / riders_on_shift < 12 THEN '2. 8-12 orders/rider'
        ELSE '3. 12+ orders/rider'
    END                                          AS load_bucket,
    ROUND(AVG(avg_dispatch_wait_min), 2)          AS avg_dispatch_wait_min,
    ROUND(AVG(sla_breach_pct), 2)                 AS avg_sla_breach_pct,
    COUNT(*)                                       AS shift_instances
FROM shift_load
GROUP BY load_bucket
ORDER BY load_bucket;

-- ---------------------------------------------------------------------------
-- Q4. Worst zone deep dive: East Delhi hour-by-hour breach profile
--     (pinpoints exactly which hours drive the zone's headline number)
-- ---------------------------------------------------------------------------
SELECT
    o.hour,
    ROUND(100.0 * SUM(o.sla_breach) / COUNT(*), 2) AS sla_breach_pct,
    ROUND(AVG(o.total_delivery_min), 2)             AS avg_delivery_min,
    COUNT(*)                                          AS orders
FROM fact_orders o
JOIN dim_stores s ON s.store_id = o.store_id
WHERE s.zone = 'East' AND s.city = 'Delhi' AND o.is_cancelled = 0
GROUP BY o.hour
ORDER BY o.hour;
