-- ============================================================================
-- Case-fill rate: a second, independent reliability dimension for each
-- warehouse, alongside lead time. sql/02_supply_chain_kpis.sql Q2 already
-- shows WH-DEL-SECONDARY runs a slower lead time than contracted -- this
-- checks whether it's also less reliable on *quantity*: does it consistently
-- ship the full amount a store orders, or does it routinely short the order?
-- These are two different failure modes with two different fixes (lead-time
-- is a routing/capacity problem; case-fill is a warehouse-inventory-accuracy
-- or allocation problem), so they need to be seen separately, not conflated
-- into "that warehouse is bad."
-- ============================================================================

-- ---------------------------------------------------------------------------
-- Q1. Case-fill rate and total units shorted, by warehouse
-- ---------------------------------------------------------------------------
SELECT
    w.warehouse_id,
    w.base_lead_time_days,
    ROUND(AVG(r.actual_lead_time_days), 2)                    AS avg_actual_lead_time_days,
    ROUND(100.0 * SUM(r.qty_received) / SUM(r.qty_ordered), 2) AS case_fill_rate_pct,
    ROUND(SUM(r.qty_ordered - r.qty_received), 0)               AS total_units_shorted,
    COUNT(*)                                                      AS replenishment_orders
FROM fact_replenishment r
JOIN dim_warehouses w ON w.warehouse_id = r.warehouse_id
GROUP BY w.warehouse_id
ORDER BY case_fill_rate_pct ASC;

-- ---------------------------------------------------------------------------
-- Q2. Frequency and severity of shorted orders, by warehouse — distinguishes
--     "shorts often but only slightly" from "shorts rarely but badly" (the
--     two look identical in Q1's aggregate fill-rate number, but call for
--     different fixes -- the former is a systemic allocation policy issue,
--     the latter is more like isolated stockouts at the warehouse itself).
-- ---------------------------------------------------------------------------
SELECT
    warehouse_id,
    ROUND(100.0 * SUM(CASE WHEN qty_received < qty_ordered THEN 1 ELSE 0 END) / COUNT(*), 1) AS pct_orders_shorted,
    ROUND(AVG(CASE WHEN qty_received < qty_ordered
                   THEN 100.0 * (qty_ordered - qty_received) / qty_ordered END), 2)            AS avg_shortfall_pct_when_shorted
FROM fact_replenishment
GROUP BY warehouse_id
ORDER BY pct_orders_shorted DESC;
