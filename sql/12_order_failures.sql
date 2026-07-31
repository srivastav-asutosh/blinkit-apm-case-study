-- ============================================================================
-- Order-failure lifecycle: cancellations, returns, and refunds -- a complete
-- gap in this project until this round (no cancellation, return, or refund
-- field existed anywhere in the schema). Modeled causally, not as an
-- unrelated random layer: cancellations tied to severe peak-hour
-- understaffing, returns tied to SLA breach (late delivery) and rain
-- (transit damage) -- see data/generate_data.py RETURNS_RNG block.
-- ============================================================================

-- ---------------------------------------------------------------------------
-- Q1. Cancellation rate under severe peak-hour understaffing vs. everywhere
--     else -- an order that can't realistically be fulfilled in time
--     sometimes gets cancelled rather than delivered extremely late.
-- ---------------------------------------------------------------------------
SELECT
    CASE WHEN picker_staffing_ratio < 0.70 AND is_peak_hour = 1 THEN 'Severe understaffing + peak'
         ELSE 'All other conditions' END                AS condition,
    COUNT(*)                                              AS orders,
    ROUND(100.0 * SUM(is_cancelled) / COUNT(*), 2)        AS cancellation_rate_pct
FROM fact_orders
GROUP BY condition;

-- ---------------------------------------------------------------------------
-- Q2. Return rate by SLA breach and rain, delivered (non-cancelled) orders
--     only -- both drivers already exist elsewhere in this case study
--     (store-ops and last-mile RCA); this shows they carry a return-rate
--     cost too, not just a delivery-time cost.
-- ---------------------------------------------------------------------------
SELECT
    sla_breach,
    is_rain_day,
    COUNT(*)                                                                      AS orders,
    ROUND(100.0 * SUM(is_returned) / COUNT(*), 2)                                 AS return_rate_pct,
    ROUND(SUM(CASE WHEN is_returned = 1 THEN refund_amount_inr ELSE 0 END), 0)    AS refund_value_inr
FROM fact_orders
WHERE is_cancelled = 0
GROUP BY sla_breach, is_rain_day
ORDER BY return_rate_pct DESC;

-- ---------------------------------------------------------------------------
-- Q3. Return reason breakdown, network-wide.
-- ---------------------------------------------------------------------------
SELECT
    return_reason,
    COUNT(*)                             AS orders,
    ROUND(SUM(refund_amount_inr), 0)     AS refund_value_inr
FROM fact_orders
WHERE is_returned = 1
GROUP BY return_reason
ORDER BY orders DESC;

-- ---------------------------------------------------------------------------
-- Q4. Total order-failure cost by store, ranked -- ties directly back to the
--     same 3 chronic-understaffed stores already flagged everywhere else in
--     this case study.
-- ---------------------------------------------------------------------------
SELECT
    store_id,
    COUNT(*)                                                                          AS total_orders,
    SUM(is_cancelled)                                                                  AS cancelled,
    SUM(is_returned)                                                                   AS returned,
    ROUND(100.0 * (SUM(is_cancelled) + SUM(is_returned)) / COUNT(*), 2)               AS failure_rate_pct,
    ROUND(SUM(CASE WHEN is_cancelled = 1 THEN order_value ELSE 0 END), 0)             AS cancelled_value_inr,
    ROUND(SUM(CASE WHEN is_returned = 1 THEN refund_amount_inr ELSE 0 END), 0)        AS refund_value_inr
FROM fact_orders
GROUP BY store_id
ORDER BY failure_rate_pct DESC;
