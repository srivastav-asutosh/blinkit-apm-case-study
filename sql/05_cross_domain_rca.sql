-- ============================================================================
-- Cross-Domain RCA — the composite view a Program Manager would actually
-- bring to a review: does one store carry risk across multiple domains at
-- once (compounding), or are the three problems independent?
-- ============================================================================

WITH supply_chain AS (
    SELECT
        i.store_id,
        ROUND(100.0 * SUM(i.stockout_flag) / COUNT(*), 3) AS stockout_rate_pct
    FROM fact_inventory_daily i
    JOIN dim_skus k ON k.sku_id = i.sku_id
    WHERE k.is_fast_moving = 1
    GROUP BY i.store_id
),
store_ops AS (
    SELECT
        store_id,
        ROUND(AVG(picker_staffing_ratio), 2)            AS avg_picker_staffing_ratio,
        ROUND(100.0 * SUM(sla_breach) / COUNT(*), 2)     AS overall_sla_breach_pct
    FROM fact_orders
    GROUP BY store_id
),
last_mile AS (
    SELECT
        store_id,
        ROUND(AVG(total_delivery_min), 2)  AS avg_delivery_min,
        ROUND(AVG(distance_km), 2)          AS avg_distance_km
    FROM fact_orders
    GROUP BY store_id
)
SELECT
    s.store_id,
    s.city,
    s.zone,
    s.warehouse_id,
    s.chronic_understaffed,
    sc.stockout_rate_pct,
    so.avg_picker_staffing_ratio,
    so.overall_sla_breach_pct,
    lm.avg_delivery_min,
    -- Simple composite risk score: each metric normalized to a 0-3 "risk
    -- points" scale by percentile threshold, then summed. Not a statistical
    -- model — a transparent, explainable scoring an ops review can act on.
    (CASE WHEN sc.stockout_rate_pct > 1.0 THEN 3 WHEN sc.stockout_rate_pct > 0.1 THEN 1 ELSE 0 END) +
    (CASE WHEN so.overall_sla_breach_pct > 25 THEN 3 WHEN so.overall_sla_breach_pct > 10 THEN 1 ELSE 0 END) +
    (CASE WHEN lm.avg_delivery_min > 18 THEN 2 WHEN lm.avg_delivery_min > 14 THEN 1 ELSE 0 END)
        AS composite_risk_score
FROM dim_stores s
JOIN supply_chain sc ON sc.store_id = s.store_id
JOIN store_ops so ON so.store_id = s.store_id
JOIN last_mile lm ON lm.store_id = s.store_id
ORDER BY composite_risk_score DESC, so.overall_sla_breach_pct DESC;
