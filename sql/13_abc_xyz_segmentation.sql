-- ============================================================================
-- True ABC/XYZ segmentation. sql/07_safety_stock_policy.sql's Z-score split
-- (1.96 for is_fast_moving=1, 1.28 for is_fast_moving=0) was commented as
-- "same as real ABC/XYZ inventory segmentation" -- it isn't one. It's a
-- binary flag. Real ABC/XYZ crosses VALUE (revenue contribution: A/B/C) with
-- VARIABILITY (demand coefficient of variation: X/Y/Z, X=low/stable,
-- Z=high/volatile) independently. This builds the real matrix and checks
-- where the binary policy over- or under-protects relative to it.
-- ============================================================================

-- ---------------------------------------------------------------------------
-- Q1. The full 3x3 value x variability matrix, with the current binary
--     is_fast_moving flag overlaid, and revenue contribution per segment.
-- ---------------------------------------------------------------------------
WITH sku_value AS (
    SELECT
        k.sku_id, k.category, k.is_fast_moving,
        SUM(i.units_sold * k.selling_price_inr) AS total_revenue_inr
    FROM fact_inventory_daily i
    JOIN dim_skus k ON k.sku_id = i.sku_id
    GROUP BY k.sku_id, k.category, k.is_fast_moving
),
sku_variability AS (
    SELECT
        sku_id,
        CASE WHEN AVG(demand) > 0
             THEN SQRT(MAX(0, AVG(demand * demand) - AVG(demand) * AVG(demand))) / AVG(demand)
             ELSE 0 END AS cv_demand
    FROM fact_inventory_daily
    GROUP BY sku_id
),
ranked AS (
    SELECT
        v.sku_id, v.category, v.is_fast_moving, v.total_revenue_inr, vb.cv_demand,
        NTILE(3) OVER (ORDER BY v.total_revenue_inr DESC) AS value_tercile,
        NTILE(3) OVER (ORDER BY vb.cv_demand DESC)         AS variability_tercile
    FROM sku_value v
    JOIN sku_variability vb ON vb.sku_id = v.sku_id
),
classified AS (
    SELECT *,
        CASE value_tercile WHEN 1 THEN 'A' WHEN 2 THEN 'B' ELSE 'C' END        AS value_class,
        CASE variability_tercile WHEN 1 THEN 'Z' WHEN 2 THEN 'Y' ELSE 'X' END  AS variability_class
    FROM ranked
)
SELECT
    value_class, variability_class, is_fast_moving,
    COUNT(*)                              AS n_skus,
    ROUND(SUM(total_revenue_inr), 0)      AS segment_revenue_inr
FROM classified
GROUP BY value_class, variability_class, is_fast_moving
ORDER BY value_class, variability_class;

-- ---------------------------------------------------------------------------
-- Q2. Mismatch summary: where the binary is_fast_moving policy disagrees
--     with the true value x variability class. "Under-protected" = high/mid
--     value AND high variability, but currently getting the lower (1.28)
--     Z-factor because it's flagged slow-moving. "Over-protected" = low
--     value (bottom tercile) but currently getting the higher (1.96)
--     Z-factor because it's flagged fast-moving, regardless of how volatile
--     its demand actually is.
-- ---------------------------------------------------------------------------
WITH sku_value AS (
    SELECT
        k.sku_id, k.is_fast_moving,
        SUM(i.units_sold * k.selling_price_inr) AS total_revenue_inr
    FROM fact_inventory_daily i
    JOIN dim_skus k ON k.sku_id = i.sku_id
    GROUP BY k.sku_id, k.is_fast_moving
),
sku_variability AS (
    SELECT
        sku_id,
        CASE WHEN AVG(demand) > 0
             THEN SQRT(MAX(0, AVG(demand * demand) - AVG(demand) * AVG(demand))) / AVG(demand)
             ELSE 0 END AS cv_demand
    FROM fact_inventory_daily
    GROUP BY sku_id
),
ranked AS (
    SELECT
        v.sku_id, v.is_fast_moving, v.total_revenue_inr,
        NTILE(3) OVER (ORDER BY v.total_revenue_inr DESC) AS value_tercile,
        NTILE(3) OVER (ORDER BY vb.cv_demand DESC)         AS variability_tercile
    FROM sku_value v
    JOIN sku_variability vb ON vb.sku_id = v.sku_id
)
SELECT
    CASE
        WHEN value_tercile <= 2 AND variability_tercile = 1 AND is_fast_moving = 0
            THEN 'Under-protected: mid/high-value, high-variability slow-mover'
        WHEN value_tercile = 3 AND is_fast_moving = 1
            THEN 'Over-protected: low-value fast-mover'
        ELSE 'Correctly classified (binary policy matches true ABC/XYZ)'
    END                                     AS classification,
    COUNT(*)                                AS n_skus,
    ROUND(SUM(total_revenue_inr), 0)        AS revenue_inr
FROM ranked
GROUP BY classification;
