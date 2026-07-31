-- ============================================================================
-- Fleet cost efficiency by vehicle type -- turns dim_riders.vehicle_type
-- (EV Scooter / Petrol Scooter / Bicycle) from an unused dimension into an
-- actual cost lever. Cost-to-Serve (sql/06_new_metrics.sql M4) prices labor
-- time only; it has never accounted for the vehicle running cost itself.
-- Per-km costs come from business_assumptions (editable in the Admin panel),
-- clearly labeled as modeling assumptions.
-- ============================================================================

-- ---------------------------------------------------------------------------
-- Q1. Current fleet running cost vs. an all-EV reference cost, by store.
--     Round-trip distance approximated as 2x each order's one-way
--     distance_km (rider returns to store between deliveries). The all-EV
--     figure is a reference ceiling on potential savings, not a literal
--     recommendation -- bicycles have real range/capacity limits that make
--     100% EV conversion impractical on the longer routes.
-- ---------------------------------------------------------------------------
WITH fleet AS (
    SELECT
        store_id,
        SUM(CASE WHEN vehicle_type = 'EV Scooter' THEN 1 ELSE 0 END)     AS ev_riders,
        SUM(CASE WHEN vehicle_type = 'Petrol Scooter' THEN 1 ELSE 0 END) AS petrol_riders,
        SUM(CASE WHEN vehicle_type = 'Bicycle' THEN 1 ELSE 0 END)        AS bicycle_riders,
        COUNT(*)                                                          AS total_riders
    FROM dim_riders
    GROUP BY store_id
),
store_km AS (
    SELECT store_id, SUM(distance_km) * 2 AS total_km_60d
    FROM fact_orders
    GROUP BY store_id
),
ba AS (SELECT * FROM business_assumptions WHERE id = 1)
SELECT
    f.store_id,
    f.ev_riders, f.petrol_riders, f.bicycle_riders,
    ROUND(100.0 * f.ev_riders / f.total_riders, 1)          AS ev_pct,
    ROUND(
        (f.ev_riders * ba.ev_scooter_cost_per_km_inr
         + f.petrol_riders * ba.petrol_scooter_cost_per_km_inr
         + f.bicycle_riders * ba.bicycle_cost_per_km_inr) / f.total_riders, 2
    )                                                          AS blended_cost_per_km_inr,
    ROUND(sk.total_km_60d, 0)                                   AS total_km_60d,
    ROUND(
        sk.total_km_60d * (f.ev_riders * ba.ev_scooter_cost_per_km_inr
                            + f.petrol_riders * ba.petrol_scooter_cost_per_km_inr
                            + f.bicycle_riders * ba.bicycle_cost_per_km_inr) / f.total_riders, 0
    )                                                          AS current_fleet_cost_inr_60d,
    ROUND(sk.total_km_60d * ba.ev_scooter_cost_per_km_inr, 0)   AS all_ev_reference_cost_inr_60d,
    ROUND(
        sk.total_km_60d * (f.ev_riders * ba.ev_scooter_cost_per_km_inr
                            + f.petrol_riders * ba.petrol_scooter_cost_per_km_inr
                            + f.bicycle_riders * ba.bicycle_cost_per_km_inr) / f.total_riders
        - sk.total_km_60d * ba.ev_scooter_cost_per_km_inr, 0
    )                                                          AS potential_saving_inr_60d
FROM fleet f
JOIN store_km sk ON sk.store_id = f.store_id, ba
ORDER BY potential_saving_inr_60d DESC;
