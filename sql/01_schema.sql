-- ============================================================================
-- Blinkit Ops Intelligence — Schema
-- SQLite. Tables are populated by data/generate_data.py (pandas .to_sql);
-- this file documents the canonical structure and is safe to re-run to
-- rebuild an empty schema by hand if needed.
-- ============================================================================

-- ---------------------------------------------------------------------------
-- Dimensions
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dim_warehouses (
    warehouse_id           TEXT PRIMARY KEY,
    warehouse_name         TEXT NOT NULL,
    city                    TEXT NOT NULL,
    base_lead_time_days    INTEGER NOT NULL,
    lead_time_variability  REAL NOT NULL,
    case_fill_rate_mean    REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS dim_stores (
    store_id               TEXT PRIMARY KEY,
    city                   TEXT NOT NULL,
    zone                   TEXT NOT NULL,
    warehouse_id           TEXT NOT NULL REFERENCES dim_warehouses(warehouse_id),
    size_tier               TEXT NOT NULL CHECK (size_tier IN ('Small','Medium','Large')),
    avg_distance_km         REAL NOT NULL,
    chronic_understaffed    INTEGER NOT NULL CHECK (chronic_understaffed IN (0,1))
);

CREATE TABLE IF NOT EXISTS dim_skus (
    sku_id                       TEXT PRIMARY KEY,
    sku_name                     TEXT NOT NULL,
    category                     TEXT NOT NULL,
    is_fast_moving               INTEGER NOT NULL CHECK (is_fast_moving IN (0,1)),
    shelf_life_days              INTEGER NOT NULL,
    unit_cost                    REAL NOT NULL,
    avg_daily_demand_per_store   REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS dim_riders (
    rider_id      TEXT PRIMARY KEY,
    store_id      TEXT NOT NULL REFERENCES dim_stores(store_id),
    vehicle_type  TEXT NOT NULL
);

-- ---------------------------------------------------------------------------
-- Facts
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fact_staffing_daily (
    date                    TEXT NOT NULL,
    store_id                TEXT NOT NULL REFERENCES dim_stores(store_id),
    shift                   TEXT NOT NULL CHECK (shift IN ('Morning','Afternoon','Evening','Night')),
    pickers_needed          INTEGER NOT NULL,
    pickers_present         INTEGER NOT NULL,
    riders_on_shift         INTEGER NOT NULL,
    riders_needed           INTEGER NOT NULL,
    picker_staffing_ratio   REAL NOT NULL,
    rider_staffing_ratio    REAL NOT NULL,
    PRIMARY KEY (date, store_id, shift)
);

CREATE TABLE IF NOT EXISTS fact_inventory_daily (
    date            TEXT NOT NULL,
    store_id        TEXT NOT NULL REFERENCES dim_stores(store_id),
    sku_id          TEXT NOT NULL REFERENCES dim_skus(sku_id),
    opening_stock   REAL NOT NULL,
    demand          REAL NOT NULL,
    units_sold      REAL NOT NULL,
    closing_stock   REAL NOT NULL,
    stockout_flag   INTEGER NOT NULL CHECK (stockout_flag IN (0,1)),
    lost_units      REAL NOT NULL,
    wasted_units    REAL NOT NULL,
    PRIMARY KEY (date, store_id, sku_id)
);

CREATE TABLE IF NOT EXISTS fact_replenishment (
    replenishment_id          TEXT PRIMARY KEY,
    store_id                  TEXT NOT NULL REFERENCES dim_stores(store_id),
    sku_id                    TEXT NOT NULL REFERENCES dim_skus(sku_id),
    warehouse_id              TEXT NOT NULL REFERENCES dim_warehouses(warehouse_id),
    order_date                TEXT NOT NULL,
    qty_ordered                INTEGER NOT NULL,
    qty_received                INTEGER NOT NULL,
    expected_lead_time_days    INTEGER NOT NULL,
    actual_lead_time_days      INTEGER NOT NULL,
    received_date              TEXT
);

CREATE TABLE IF NOT EXISTS fact_orders (
    order_id                 TEXT PRIMARY KEY,
    store_id                 TEXT NOT NULL REFERENCES dim_stores(store_id),
    date                      TEXT NOT NULL,
    order_time                TEXT NOT NULL,
    hour                      INTEGER NOT NULL,
    shift                     TEXT NOT NULL,
    is_peak_hour              INTEGER NOT NULL CHECK (is_peak_hour IN (0,1)),
    is_rain_day               INTEGER NOT NULL CHECK (is_rain_day IN (0,1)),
    item_count                INTEGER NOT NULL,
    order_value               REAL NOT NULL,
    distance_km               REAL NOT NULL,
    picker_staffing_ratio     REAL NOT NULL,
    riders_on_shift           INTEGER NOT NULL,
    pick_time_min             REAL NOT NULL,
    pack_time_min             REAL NOT NULL,
    dispatch_wait_min         REAL NOT NULL,
    travel_time_min           REAL NOT NULL,
    total_delivery_min        REAL NOT NULL,
    promised_minutes          INTEGER NOT NULL,
    sla_breach                INTEGER NOT NULL CHECK (sla_breach IN (0,1))
);

CREATE INDEX IF NOT EXISTS idx_fact_inventory_daily_store_sku_date ON fact_inventory_daily (store_id, sku_id, date);
CREATE INDEX IF NOT EXISTS idx_fact_orders_store_date_hour ON fact_orders (store_id, date, hour);
CREATE INDEX IF NOT EXISTS idx_fact_replenishment_store_warehouse ON fact_replenishment (store_id, warehouse_id);
CREATE INDEX IF NOT EXISTS idx_fact_staffing_daily_store_date_shift ON fact_staffing_daily (store_id, date, shift);

-- ---------------------------------------------------------------------------
-- Admin / config -- editable at runtime from the dashboard's Admin panel,
-- not regenerated by generate_data.py except on a deliberate reset.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS business_assumptions (
    id                              INTEGER PRIMARY KEY,
    picker_hourly_wage_inr          REAL NOT NULL,
    rider_hourly_wage_inr           REAL NOT NULL,
    ev_scooter_cost_per_km_inr      REAL NOT NULL,
    petrol_scooter_cost_per_km_inr  REAL NOT NULL,
    bicycle_cost_per_km_inr         REAL NOT NULL,
    updated_by                      TEXT NOT NULL,
    updated_at                       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS upload_log (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    event_time       TEXT NOT NULL,
    action           TEXT NOT NULL,
    target_table     TEXT,
    rows_affected    INTEGER,
    note             TEXT
);
