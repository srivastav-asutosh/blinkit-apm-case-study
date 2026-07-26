-- ============================================================================
-- New metrics proposed beyond the original KPI set -- each ties two domains
-- together or converts ops performance into a business (₹) figure, which is
-- the kind of number that gets a recommendation funded rather than just
-- acknowledged. All four are computed from data already in the schema, with
-- explicitly labeled assumptions where the raw data doesn't fully cover the
-- textbook definition (see the comment on each).
-- ============================================================================

-- ---------------------------------------------------------------------------
-- M1. Perfect Order Rate, by store
--     Textbook "perfect order" = on-time + complete + damage-free. This
--     schema tracks orders and inventory as separate fact tables (no
--     order-line-item link), so this is a store-day-level proxy: an order
--     counts as "perfect" if it didn't breach SLA AND its store had zero
--     fast-moving-SKU stockouts that same day. Documented as a proxy, not
--     claimed as a strict line-item fulfillment rate.
-- ---------------------------------------------------------------------------
WITH store_day_stockout AS (
    SELECT
        i.store_id,
        i.date,
        MAX(i.stockout_flag) AS any_stockout
    FROM fact_inventory_daily i
    JOIN dim_skus k ON k.sku_id = i.sku_id
    WHERE k.is_fast_moving = 1
    GROUP BY i.store_id, i.date
)
SELECT
    o.store_id,
    COUNT(*)                                                                            AS orders,
    ROUND(100.0 * SUM(CASE WHEN o.sla_breach = 0 AND COALESCE(sd.any_stockout, 0) = 0
                            THEN 1 ELSE 0 END) / COUNT(*), 2)                            AS perfect_order_rate_pct
FROM fact_orders o
LEFT JOIN store_day_stockout sd ON sd.store_id = o.store_id AND sd.date = o.date
GROUP BY o.store_id
ORDER BY perfect_order_rate_pct ASC;

-- ---------------------------------------------------------------------------
-- M2. Inventory Days of Cover, by store (fast-moving SKUs, latest snapshot)
--     days_of_cover = latest closing_stock / trailing-14-day avg daily demand.
--     Distinct from stockout rate: a store can have a low stockout rate today
--     and still be running dangerously thin (about to tip into one).
-- ---------------------------------------------------------------------------
WITH latest_date AS (SELECT MAX(date) AS d FROM fact_inventory_daily),
trailing_demand AS (
    SELECT store_id, sku_id, AVG(demand) AS avg_daily_demand
    FROM fact_inventory_daily
    WHERE date > (SELECT DATE(d, '-14 days') FROM latest_date)
    GROUP BY store_id, sku_id
),
latest_stock AS (
    SELECT i.store_id, i.sku_id, i.closing_stock
    FROM fact_inventory_daily i, latest_date ld
    WHERE i.date = ld.d
)
SELECT
    ls.store_id,
    ROUND(SUM(ls.closing_stock) / NULLIF(SUM(td.avg_daily_demand), 0), 1) AS days_of_cover
FROM latest_stock ls
JOIN trailing_demand td ON td.store_id = ls.store_id AND td.sku_id = ls.sku_id
JOIN dim_skus k ON k.sku_id = ls.sku_id
WHERE k.is_fast_moving = 1
GROUP BY ls.store_id
ORDER BY days_of_cover ASC;

-- ---------------------------------------------------------------------------
-- M3. Rider Utilization -- orders delivered per scheduled rider-hour
--     Shift length isn't stored explicitly; assumed 6 hours/shift (24h / 4
--     shifts), applied consistently across stores so it's fair to compare.
-- ---------------------------------------------------------------------------
WITH shift_orders AS (
    SELECT store_id, date, shift, COUNT(*) AS orders, AVG(riders_on_shift) AS riders_on_shift
    FROM fact_orders
    GROUP BY store_id, date, shift
)
SELECT
    store_id,
    ROUND(SUM(orders) * 1.0 / NULLIF(SUM(riders_on_shift * 6.0), 0), 2) AS orders_per_rider_hour
FROM shift_orders
GROUP BY store_id
ORDER BY orders_per_rider_hour DESC;

-- ---------------------------------------------------------------------------
-- M4. Cost-to-Serve per order, by store
--     Labor-only estimate: picker time (pick+pack) at the picker wage, rider
--     time (dispatch wait + travel) at the rider wage. Wages come from
--     business_assumptions (editable in the Admin panel) -- not a claimed
--     real Blinkit cost, an explicit, adjustable modeling assumption.
-- ---------------------------------------------------------------------------
SELECT
    o.store_id,
    ROUND(AVG(
        (o.pick_time_min + o.pack_time_min) / 60.0 * ba.picker_hourly_wage_inr
        + (o.dispatch_wait_min + o.travel_time_min) / 60.0 * ba.rider_hourly_wage_inr
    ), 2) AS avg_cost_to_serve_inr
FROM fact_orders o, business_assumptions ba
WHERE ba.id = 1
GROUP BY o.store_id
ORDER BY avg_cost_to_serve_inr DESC;
