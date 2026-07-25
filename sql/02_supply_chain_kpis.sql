-- ============================================================================
-- Supply Chain & Replenishment — KPIs and RCA
-- ============================================================================

-- ---------------------------------------------------------------------------
-- Q1. Fill rate & stockout rate by store, fast-moving SKUs only
--     (fast-movers are where stockouts actually cost sales day to day)
-- ---------------------------------------------------------------------------
SELECT
    i.store_id,
    s.zone,
    s.warehouse_id,
    ROUND(100.0 * SUM(i.units_sold) / NULLIF(SUM(i.demand), 0), 2) AS fill_rate_pct,
    ROUND(100.0 * SUM(i.stockout_flag) / COUNT(*), 2)              AS stockout_rate_pct,
    ROUND(SUM(i.lost_units), 0)                                     AS total_lost_units,
    COUNT(*)                                                         AS store_sku_days
FROM fact_inventory_daily i
JOIN dim_stores s ON s.store_id = i.store_id
JOIN dim_skus k ON k.sku_id = i.sku_id
WHERE k.is_fast_moving = 1
GROUP BY i.store_id, s.zone, s.warehouse_id
ORDER BY stockout_rate_pct DESC;

-- ---------------------------------------------------------------------------
-- Q2. Root cause: stockout rate and lost sales value by warehouse
--     (the headline RCA finding — isolates the warehouse, not the store, as
--      the driver by aggregating across every store each warehouse serves).
--     Inventory and replenishment are aggregated in separate CTEs first —
--     joining them directly on warehouse_id alone would fan out every
--     inventory row across every replenishment order for that warehouse.
-- ---------------------------------------------------------------------------
WITH inventory_by_wh AS (
    SELECT
        s.warehouse_id,
        SUM(i.stockout_flag)              AS stockout_days,
        COUNT(*)                          AS store_sku_days,
        SUM(i.lost_units * k.unit_cost)   AS est_lost_sales_value_inr
    FROM fact_inventory_daily i
    JOIN dim_stores s ON s.store_id = i.store_id
    JOIN dim_skus k ON k.sku_id = i.sku_id
    WHERE k.is_fast_moving = 1
    GROUP BY s.warehouse_id
),
replenishment_by_wh AS (
    SELECT
        warehouse_id,
        AVG(actual_lead_time_days) AS avg_actual_lead_time_days
    FROM fact_replenishment
    GROUP BY warehouse_id
)
SELECT
    w.warehouse_id,
    w.base_lead_time_days                                AS contracted_lead_time_days,
    ROUND(r.avg_actual_lead_time_days, 2)                AS avg_actual_lead_time_days,
    ROUND(100.0 * i.stockout_days / i.store_sku_days, 3)  AS stockout_rate_pct,
    ROUND(i.est_lost_sales_value_inr, 0)                  AS est_lost_sales_value_inr
FROM dim_warehouses w
JOIN inventory_by_wh i ON i.warehouse_id = w.warehouse_id
JOIN replenishment_by_wh r ON r.warehouse_id = w.warehouse_id
ORDER BY stockout_rate_pct DESC;

-- ---------------------------------------------------------------------------
-- Q3. Lead time variance by warehouse (SLA-vs-actual gap; variability is as
--     costly as the average, since it forces higher safety stock)
-- ---------------------------------------------------------------------------
SELECT
    warehouse_id,
    COUNT(*)                                                         AS replenishment_orders,
    ROUND(AVG(expected_lead_time_days), 2)                           AS avg_expected_days,
    ROUND(AVG(actual_lead_time_days), 2)                             AS avg_actual_days,
    ROUND(AVG(actual_lead_time_days - expected_lead_time_days), 2)   AS avg_slippage_days,
    ROUND(
        SQRT(AVG((actual_lead_time_days - expected_lead_time_days) * 1.0
                 * (actual_lead_time_days - expected_lead_time_days))), 2
    )                                                                 AS lead_time_stddev
FROM fact_replenishment
GROUP BY warehouse_id
ORDER BY avg_slippage_days DESC;

-- ---------------------------------------------------------------------------
-- Q4. Category-level breakdown for the affected warehouse's stores — which
--     categories carry the stockout risk (perishables vs. shelf-stable)
-- ---------------------------------------------------------------------------
SELECT
    k.category,
    ROUND(100.0 * SUM(i.stockout_flag) / COUNT(*), 2) AS stockout_rate_pct,
    ROUND(SUM(i.lost_units * k.unit_cost), 0)          AS est_lost_sales_value_inr
FROM fact_inventory_daily i
JOIN dim_stores s ON s.store_id = i.store_id
JOIN dim_skus k ON k.sku_id = i.sku_id
WHERE s.warehouse_id = 'WH-DEL-SECONDARY'
GROUP BY k.category
ORDER BY stockout_rate_pct DESC;

-- ---------------------------------------------------------------------------
-- Q5. Replenishment order-frequency vs. lead time — do slow-warehouse stores
--     end up reordering more often (a sign of thrash from tight safety stock)?
-- ---------------------------------------------------------------------------
SELECT
    s.warehouse_id,
    s.store_id,
    COUNT(*)                                    AS replenishment_orders_60d,
    ROUND(AVG(r.actual_lead_time_days), 2)      AS avg_lead_time_days
FROM fact_replenishment r
JOIN dim_stores s ON s.store_id = r.store_id
GROUP BY s.warehouse_id, s.store_id
ORDER BY replenishment_orders_60d DESC;
