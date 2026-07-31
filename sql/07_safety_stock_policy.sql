-- ============================================================================
-- Safety Stock Policy Review — the network's current reorder-point formula
-- is a flat "+2 days" buffer regardless of how volatile a SKU's demand is or
-- how variable its warehouse's lead time is. This isn't a data anomaly to
-- fix in the generator (that would retroactively change every number already
-- cited in the case study) -- it's a POLICY finding: the formula itself
-- needs to change. This file computes what the textbook variability-adjusted
-- formula would recommend, using demand and lead-time variability estimated
-- empirically from the same 60 days of data an analyst would actually have,
-- and quantifies the gap against the current policy.
--
-- Formula (standard combined demand+lead-time-variability safety stock,
-- assuming both are independent and roughly normal):
--   safety_stock = Z * sqrt(mean_leadtime * var_demand + mean_demand^2 * var_leadtime)
--   reorder_point = mean_demand * mean_leadtime + safety_stock
-- Z is the service-level factor: 1.96 (~97.5% service level) for
-- fast-moving/perishable SKUs, 1.28 (~90%) for slow movers -- higher-value,
-- higher-visibility items get a higher target, same as real ABC/XYZ
-- inventory segmentation.
-- ============================================================================

-- ---------------------------------------------------------------------------
-- Q1. Empirical demand statistics per store-SKU (mean + variance, computed
--     from the actual 60-day demand history, not the generator's hidden
--     parameters -- this is what a real analyst would have to work with).
-- ---------------------------------------------------------------------------
WITH demand_stats AS (
    SELECT
        store_id,
        sku_id,
        AVG(demand)                                       AS mean_demand,
        AVG(demand * demand) - AVG(demand) * AVG(demand)   AS var_demand
    FROM fact_inventory_daily
    GROUP BY store_id, sku_id
),

-- ---------------------------------------------------------------------------
-- Empirical lead-time statistics per warehouse (mean + variance, from actual
-- replenishment history).
-- ---------------------------------------------------------------------------
leadtime_stats AS (
    SELECT
        warehouse_id,
        AVG(actual_lead_time_days) AS mean_leadtime,
        AVG(actual_lead_time_days * actual_lead_time_days)
            - AVG(actual_lead_time_days) * AVG(actual_lead_time_days) AS var_leadtime
    FROM fact_replenishment
    GROUP BY warehouse_id
),

-- ---------------------------------------------------------------------------
-- Per store-SKU: correct (variability-adjusted) vs. current (flat-buffer)
-- reorder point. One row per store-SKU pair -- demand_stats is already
-- aggregated, so this is a plain dimensional join, no fan-out.
-- ---------------------------------------------------------------------------
comparison AS (
    SELECT
        s.store_id,
        s.warehouse_id,
        k.sku_id,
        k.category,
        k.is_fast_moving,
        k.unit_cost,
        ds.mean_demand,
        lt.mean_leadtime,
        sqrt(lt.var_leadtime)                              AS leadtime_stddev,
        (CASE WHEN k.is_fast_moving = 1 THEN 1.96 ELSE 1.28 END) AS z_factor,
        (CASE WHEN k.is_fast_moving = 1 THEN 1.96 ELSE 1.28 END) *
            sqrt(lt.mean_leadtime * ds.var_demand + ds.mean_demand * ds.mean_demand * lt.var_leadtime)
            AS correct_safety_stock,
        ds.mean_demand * lt.mean_leadtime +
            (CASE WHEN k.is_fast_moving = 1 THEN 1.96 ELSE 1.28 END) *
            sqrt(lt.mean_leadtime * ds.var_demand + ds.mean_demand * ds.mean_demand * lt.var_leadtime)
            AS correct_reorder_point,
        -- Current policy, as actually implemented: mean demand x (contracted
        -- lead time + flat 2-day buffer) -- see data/generate_data.py
        ds.mean_demand * (w.base_lead_time_days + 2) AS current_reorder_point
    FROM demand_stats ds
    JOIN dim_skus k ON k.sku_id = ds.sku_id
    JOIN dim_stores s ON s.store_id = ds.store_id
    JOIN dim_warehouses w ON w.warehouse_id = s.warehouse_id
    JOIN leadtime_stats lt ON lt.warehouse_id = s.warehouse_id
)

-- ---------------------------------------------------------------------------
-- Q2. Warehouse-level rollup: the gap between what the network should be
--     holding (correct, variability-adjusted) and what it actually targets
--     (current, flat-buffer policy) -- fast-moving SKUs only, since that's
--     where stockout cost concentrates.
-- ---------------------------------------------------------------------------
SELECT
    warehouse_id,
    ROUND(AVG(mean_leadtime), 2)                                             AS avg_lead_time_days,
    ROUND(AVG(leadtime_stddev), 2)                                            AS lead_time_stddev_days,
    ROUND(AVG(correct_reorder_point), 1)                                      AS avg_correct_rop_units,
    ROUND(AVG(current_reorder_point), 1)                                      AS avg_current_rop_units,
    ROUND(AVG(correct_reorder_point - current_reorder_point), 1)              AS avg_gap_units,
    ROUND(100.0 * AVG(correct_reorder_point - current_reorder_point)
          / NULLIF(AVG(current_reorder_point), 0), 1)                        AS gap_pct,
    ROUND(SUM((correct_reorder_point - current_reorder_point) * unit_cost), 0) AS gap_value_inr
FROM comparison
WHERE is_fast_moving = 1
GROUP BY warehouse_id
ORDER BY gap_pct DESC;
