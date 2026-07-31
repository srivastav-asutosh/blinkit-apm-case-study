-- ============================================================================
-- Contribution margin / profitability per store -- the number every other
-- finding in this project has implicitly served but none had ever computed.
-- order_value (fixed this round to derive from real dim_skus economics --
-- see data/generate_data.py, NETWORK_AVG_SELLING_PRICE / BASKET_PRICE_FACTOR)
-- is revenue; Cost-to-Serve (sql/06_new_metrics.sql M4) is cost. They had
-- never been joined until now.
-- ============================================================================

-- ---------------------------------------------------------------------------
-- Q1. Margin implied by the catalog itself (selling_price_inr vs. unit_cost),
--     derived from the data rather than hardcoded -- used below to back out
--     an implied COGS from realized revenue.
-- ---------------------------------------------------------------------------
SELECT ROUND(AVG(selling_price_inr / unit_cost) - 1, 4) AS implied_margin_pct FROM dim_skus;

-- ---------------------------------------------------------------------------
-- Q2. Per-store contribution margin: revenue net of returns, implied COGS,
--     and Cost-to-Serve (labor). Cancelled orders are excluded from revenue
--     (never fulfilled) but this model still assumes pick/pack/dispatch
--     effort was spent before the cancellation was known, so their labor
--     cost is still counted -- a cancellation is a pure loss, not a wash.
-- ---------------------------------------------------------------------------
WITH margin AS (
    SELECT AVG(selling_price_inr / unit_cost) - 1 AS margin_pct FROM dim_skus
),
order_econ AS (
    SELECT
        o.store_id,
        COUNT(*)                                                              AS total_orders,
        SUM(o.is_cancelled)                                                    AS cancelled_orders,
        SUM(o.is_returned)                                                     AS returned_orders,
        SUM(CASE WHEN o.is_cancelled = 0 THEN o.order_value ELSE 0 END)       AS gross_revenue_inr,
        SUM(CASE WHEN o.is_returned = 1 THEN o.refund_amount_inr ELSE 0 END)  AS refunds_inr,
        SUM(
            (o.pick_time_min + o.pack_time_min) / 60.0 * ba.picker_hourly_wage_inr
            + (o.dispatch_wait_min + o.travel_time_min) / 60.0 * ba.rider_hourly_wage_inr
        )                                                                      AS cost_to_serve_total_inr
    FROM fact_orders o, business_assumptions ba
    WHERE ba.id = 1
    GROUP BY o.store_id
)
SELECT
    oe.store_id,
    oe.total_orders,
    oe.cancelled_orders,
    oe.returned_orders,
    ROUND(oe.gross_revenue_inr, 0)                                                              AS gross_revenue_inr,
    ROUND(oe.refunds_inr, 0)                                                                      AS refunds_inr,
    ROUND(oe.gross_revenue_inr - oe.refunds_inr, 0)                                               AS net_revenue_inr,
    ROUND((oe.gross_revenue_inr - oe.refunds_inr) * m.margin_pct / (1 + m.margin_pct), 0)         AS gross_margin_inr,
    ROUND(oe.cost_to_serve_total_inr, 0)                                                           AS cost_to_serve_total_inr,
    ROUND(
        (oe.gross_revenue_inr - oe.refunds_inr) * m.margin_pct / (1 + m.margin_pct) - oe.cost_to_serve_total_inr, 0
    )                                                                                              AS net_contribution_inr,
    ROUND(
        ((oe.gross_revenue_inr - oe.refunds_inr) * m.margin_pct / (1 + m.margin_pct) - oe.cost_to_serve_total_inr)
        / oe.total_orders, 2
    )                                                                                              AS net_contribution_per_order_inr
FROM order_econ oe, margin m
ORDER BY net_contribution_per_order_inr ASC;
