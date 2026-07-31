"""
Blinkit Ops Intelligence — synthetic data generator.

Simulates 60 days of operations across 12 dark stores in 2 cities, spanning
three domains: Supply Chain & Replenishment, Store Operations, and Last Mile
Delivery. Root causes are embedded structurally (via warehouse lead times,
shift staffing levels, and zone distances) rather than hard-coded onto
individual rows, so the patterns have to be found analytically — same as a
real ops investigation.

Run:
    python data/generate_data.py

Outputs CSVs to data/. Loads into a Turso (libSQL) database if TURSO_URL and
TURSO_AUTH_TOKEN are set in the environment; otherwise into a local SQLite
file at db/blinkit_ops.db.
"""

import os
import sqlite3
import sys
import uuid
from pathlib import Path

import numpy as np
import pandas as pd

RNG = np.random.default_rng(42)
# Dedicated stream for warehouse case-fill draws, kept separate from RNG so
# that adding this mechanism doesn't reshuffle the demand/lead-time draws
# already consumed elsewhere in the inventory loop -- same reasoning as the
# RNG reseed before orders generation below.
FILL_RNG = np.random.default_rng(44)

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DB_PATH = ROOT / "db" / "blinkit_ops.db"
SCHEMA_SQL_PATH = ROOT / "sql" / "01_schema.sql"

sys.path.insert(0, str(ROOT))
from db_store import get_store  # noqa: E402

TURSO_URL = os.environ.get("TURSO_URL")
TURSO_AUTH_TOKEN = os.environ.get("TURSO_AUTH_TOKEN")
USING_TURSO = bool(TURSO_URL and TURSO_AUTH_TOKEN)

START_DATE = pd.Timestamp("2026-05-27")
END_DATE = pd.Timestamp("2026-07-25")
DATES = pd.date_range(START_DATE, END_DATE, freq="D")
N_DAYS = len(DATES)

# ---------------------------------------------------------------------------
# Dimension: warehouses
# ---------------------------------------------------------------------------
warehouses = pd.DataFrame(
    [
        {"warehouse_id": "WH-DEL-PRIMARY", "warehouse_name": "Delhi Primary FC", "city": "Delhi",
         "base_lead_time_days": 1, "lead_time_variability": 0.4, "case_fill_rate_mean": 0.98},
        {"warehouse_id": "WH-DEL-SECONDARY", "warehouse_name": "Delhi Overflow FC", "city": "Delhi",
         "base_lead_time_days": 3, "lead_time_variability": 1.3, "case_fill_rate_mean": 0.90},
        {"warehouse_id": "WH-BLR-PRIMARY", "warehouse_name": "Bangalore Primary FC", "city": "Bangalore",
         "base_lead_time_days": 1, "lead_time_variability": 0.5, "case_fill_rate_mean": 0.98},
    ]
)

# ---------------------------------------------------------------------------
# Dimension: stores
# East-zone Delhi stores are deliberately dual-mapped to the slow secondary
# warehouse AND sit furthest from customers (longer delivery distance) --
# this is the "worst zone" whose problems compound across domains.
# Three stores are chronically understaffed on the evening shift regardless
# of city, to prove the staffing root cause isn't just a Delhi/warehouse story.
# ---------------------------------------------------------------------------
stores = pd.DataFrame(
    [
        {"store_id": "DEL-N-01", "city": "Delhi", "zone": "North", "warehouse_id": "WH-DEL-PRIMARY",
         "size_tier": "Large", "avg_distance_km": 1.9, "chronic_understaffed": False},
        {"store_id": "DEL-S-01", "city": "Delhi", "zone": "South", "warehouse_id": "WH-DEL-PRIMARY",
         "size_tier": "Medium", "avg_distance_km": 2.1, "chronic_understaffed": False},
        {"store_id": "DEL-S-02", "city": "Delhi", "zone": "South", "warehouse_id": "WH-DEL-SECONDARY",
         "size_tier": "Medium", "avg_distance_km": 2.3, "chronic_understaffed": False},
        {"store_id": "DEL-E-01", "city": "Delhi", "zone": "East", "warehouse_id": "WH-DEL-SECONDARY",
         "size_tier": "Medium", "avg_distance_km": 3.6, "chronic_understaffed": True},
        {"store_id": "DEL-E-02", "city": "Delhi", "zone": "East", "warehouse_id": "WH-DEL-SECONDARY",
         "size_tier": "Small", "avg_distance_km": 3.9, "chronic_understaffed": True},
        {"store_id": "DEL-W-01", "city": "Delhi", "zone": "West", "warehouse_id": "WH-DEL-PRIMARY",
         "size_tier": "Large", "avg_distance_km": 2.0, "chronic_understaffed": False},
        {"store_id": "BLR-N-01", "city": "Bangalore", "zone": "North", "warehouse_id": "WH-BLR-PRIMARY",
         "size_tier": "Medium", "avg_distance_km": 2.2, "chronic_understaffed": False},
        {"store_id": "BLR-S-01", "city": "Bangalore", "zone": "South", "warehouse_id": "WH-BLR-PRIMARY",
         "size_tier": "Large", "avg_distance_km": 1.8, "chronic_understaffed": False},
        {"store_id": "BLR-S-02", "city": "Bangalore", "zone": "South", "warehouse_id": "WH-BLR-PRIMARY",
         "size_tier": "Medium", "avg_distance_km": 2.0, "chronic_understaffed": True},
        {"store_id": "BLR-E-01", "city": "Bangalore", "zone": "East", "warehouse_id": "WH-BLR-PRIMARY",
         "size_tier": "Medium", "avg_distance_km": 3.1, "chronic_understaffed": False},
        {"store_id": "BLR-W-01", "city": "Bangalore", "zone": "West", "warehouse_id": "WH-BLR-PRIMARY",
         "size_tier": "Medium", "avg_distance_km": 2.4, "chronic_understaffed": False},
        {"store_id": "BLR-W-02", "city": "Bangalore", "zone": "West", "warehouse_id": "WH-BLR-PRIMARY",
         "size_tier": "Small", "avg_distance_km": 2.6, "chronic_understaffed": False},
    ]
)
SIZE_ORDER_BASE = {"Small": 60, "Medium": 90, "Large": 130}
SIZE_PICKERS_NEEDED = {"Small": 4, "Medium": 6, "Large": 9}
SIZE_RIDERS = {"Small": 6, "Medium": 9, "Large": 13}

# ---------------------------------------------------------------------------
# Dimension: SKUs
# ---------------------------------------------------------------------------
CATEGORIES = {
    "Dairy & Breakfast": {"fast_moving": True, "shelf_life": 7, "n": 14},
    "Fruits & Vegetables": {"fast_moving": True, "shelf_life": 5, "n": 16},
    "Beverages": {"fast_moving": True, "shelf_life": 180, "n": 12},
    "Snacks & Munchies": {"fast_moving": True, "shelf_life": 120, "n": 14},
    "Personal Care": {"fast_moving": False, "shelf_life": 365, "n": 12},
    "Household Care": {"fast_moving": False, "shelf_life": 365, "n": 10},
    "Baby Care": {"fast_moving": False, "shelf_life": 365, "n": 8},
    "Frozen & Ice Cream": {"fast_moving": True, "shelf_life": 90, "n": 10},
}

sku_rows = []
sku_counter = 1
for cat, meta in CATEGORIES.items():
    for i in range(meta["n"]):
        sku_rows.append(
            {
                "sku_id": f"SKU-{sku_counter:04d}",
                "sku_name": f"{cat.split(' ')[0]} Item {i + 1}",
                "category": cat,
                "is_fast_moving": meta["fast_moving"],
                "shelf_life_days": meta["shelf_life"],
                "unit_cost": round(RNG.uniform(15, 450), 2),
                "avg_daily_demand_per_store": round(
                    RNG.uniform(8, 22) if meta["fast_moving"] else RNG.uniform(1.5, 6), 2
                ),
            }
        )
        sku_counter += 1
skus = pd.DataFrame(sku_rows)

# ---------------------------------------------------------------------------
# Dimension: riders
# ---------------------------------------------------------------------------
rider_rows = []
rider_counter = 1
for _, s in stores.iterrows():
    n_riders = SIZE_RIDERS[s["size_tier"]]
    for _ in range(n_riders):
        rider_rows.append(
            {
                "rider_id": f"RID-{rider_counter:04d}",
                "store_id": s["store_id"],
                "vehicle_type": RNG.choice(["EV Scooter", "Bicycle", "Petrol Scooter"], p=[0.6, 0.15, 0.25]),
            }
        )
        rider_counter += 1
riders = pd.DataFrame(rider_rows)

# ---------------------------------------------------------------------------
# Fact: daily staffing (pickers + riders on shift)
# Chronic-understaffed stores run ~55-70% of needed pickers/riders on the
# Evening shift; all stores have mild random noise on top.
# ---------------------------------------------------------------------------
SHIFTS = ["Morning", "Afternoon", "Evening", "Night"]
staffing_rows = []
for _, s in stores.iterrows():
    pickers_needed = SIZE_PICKERS_NEEDED[s["size_tier"]]
    riders_total = SIZE_RIDERS[s["size_tier"]]
    for d in DATES:
        for shift in SHIFTS:
            is_evening = shift == "Evening"
            if s["chronic_understaffed"] and is_evening:
                staff_ratio = RNG.uniform(0.5, 0.72)
            elif is_evening:
                staff_ratio = RNG.uniform(0.85, 1.05)
            else:
                staff_ratio = RNG.uniform(0.82, 1.05)
            pickers_present = max(1, int(round(pickers_needed * staff_ratio)))
            riders_needed_shift = riders_total * (0.5 if shift in ("Morning", "Night") else 0.75)
            if s["chronic_understaffed"] and is_evening:
                rider_ratio = RNG.uniform(0.5, 0.7)
            else:
                rider_ratio = RNG.uniform(0.8, 1.05)
            riders_on_shift = max(1, int(round(riders_needed_shift * rider_ratio)))
            staffing_rows.append(
                {
                    "date": d,
                    "store_id": s["store_id"],
                    "shift": shift,
                    "pickers_needed": pickers_needed,
                    "pickers_present": pickers_present,
                    "riders_on_shift": riders_on_shift,
                    "riders_needed": max(1, round(riders_needed_shift)),
                }
            )
staffing = pd.DataFrame(staffing_rows)
staffing["picker_staffing_ratio"] = (staffing["pickers_present"] / staffing["pickers_needed"]).round(2)
staffing["rider_staffing_ratio"] = (staffing["riders_on_shift"] / staffing["riders_needed"]).round(2)

# ---------------------------------------------------------------------------
# Fact: inventory + replenishment (day-by-day simulation per store-SKU)
# Reorder-point logic: when projected stock falls below (lead_time + safety
# days) of demand, a replenishment order is placed at the store's mapped
# warehouse; slower warehouses -> longer lead time -> more stockout days.
# ---------------------------------------------------------------------------
inventory_rows = []
replenishment_rows = []
repl_counter = 1

wh_lookup = warehouses.set_index("warehouse_id")

for _, s in stores.iterrows():
    wh = wh_lookup.loc[s["warehouse_id"]]
    for _, sku in skus.iterrows():
        base_demand = sku["avg_daily_demand_per_store"] * (
            1.3 if s["size_tier"] == "Large" else (1.0 if s["size_tier"] == "Medium" else 0.7)
        )
        safety_days = 2
        order_cycle_days = 10 if sku["is_fast_moving"] else 16
        reorder_point = base_demand * (wh["base_lead_time_days"] + safety_days)
        order_qty = base_demand * order_cycle_days

        stock = round(reorder_point * RNG.uniform(1.2, 1.8))
        pending_orders = []  # list of (arrival_date_index, qty)

        for day_idx, d in enumerate(DATES):
            dow_factor = 1.3 if d.dayofweek in (4, 5, 6) else 1.0
            demand = max(0, RNG.normal(base_demand * dow_factor, base_demand * 0.25))

            arrivals = [q for (arr_idx, q) in pending_orders if arr_idx == day_idx]
            if arrivals:
                stock += sum(arrivals)
                pending_orders = [(a, q) for (a, q) in pending_orders if a != day_idx]

            opening_stock = stock
            units_sold = min(stock, demand)
            stockout_flag = demand > stock + 1e-9
            lost_units = max(0.0, demand - stock)
            closing_stock = max(0, stock - units_sold)

            # Shrinkage/waste: stock held beyond what could plausibly sell
            # within the SKU's shelf life is at spoilage risk. Uses
            # shelf_life_days directly rather than a hardcoded "perishable"
            # list, so it naturally applies only where it should -- for
            # long-shelf-life SKUs, base_demand * shelf_life_days is far
            # larger than any stock level ever reached, so excess is always
            # zero. A fixed fraction of the excess spoils each day it's held
            # above that threshold (not all at once), so waste tapers
            # naturally as stock is sold or ages out.
            max_sellable_before_expiry = base_demand * sku["shelf_life_days"]
            excess_at_risk = max(0.0, closing_stock - max_sellable_before_expiry)
            wasted_units = excess_at_risk * 0.015
            closing_stock = max(0.0, closing_stock - wasted_units)

            has_pending = len(pending_orders) > 0
            if closing_stock < reorder_point and not has_pending:
                lead_time = max(1, round(RNG.normal(wh["base_lead_time_days"], wh["lead_time_variability"])))
                arrival_idx = day_idx + lead_time
                qty_ordered = round(order_qty)
                # Case-fill shortfall: the warehouse doesn't always ship the
                # full ordered quantity. Drawn from a dedicated RNG stream
                # (FILL_RNG) at the warehouse's own case_fill_rate_mean, so
                # WH-DEL-SECONDARY -- already the slow warehouse -- is also
                # modeled as the least reliable on quantity, independent of
                # its lead-time variability.
                fill_fraction = min(1.0, max(0.5, FILL_RNG.normal(wh["case_fill_rate_mean"], 0.03)))
                qty_received = round(qty_ordered * fill_fraction)
                pending_orders.append((arrival_idx, qty_received))
                replenishment_rows.append(
                    {
                        "replenishment_id": f"REPL-{repl_counter:06d}",
                        "store_id": s["store_id"],
                        "sku_id": sku["sku_id"],
                        "warehouse_id": s["warehouse_id"],
                        "order_date": d,
                        "qty_ordered": qty_ordered,
                        "qty_received": qty_received,
                        "expected_lead_time_days": wh["base_lead_time_days"],
                        "actual_lead_time_days": lead_time,
                        "received_date": d + pd.Timedelta(days=lead_time)
                        if arrival_idx < N_DAYS
                        else pd.NaT,
                    }
                )
                repl_counter += 1

            inventory_rows.append(
                {
                    "date": d,
                    "store_id": s["store_id"],
                    "sku_id": sku["sku_id"],
                    "opening_stock": round(opening_stock, 1),
                    "demand": round(demand, 1),
                    "units_sold": round(units_sold, 1),
                    "closing_stock": round(closing_stock, 1),
                    "stockout_flag": bool(stockout_flag),
                    "lost_units": round(lost_units, 1),
                    "wasted_units": round(wasted_units, 1),
                }
            )
            stock = closing_stock

inventory = pd.DataFrame(inventory_rows)
replenishment = pd.DataFrame(replenishment_rows)

print(f"Generated inventory rows: {len(inventory):,}")
print(f"Generated replenishment orders: {len(replenishment):,}")

# ---------------------------------------------------------------------------
# Fact: orders (store ops + last mile combined per order)
#
# Reseeded here, deliberately: the inventory/replenishment loop above
# consumes a data-dependent number of RNG draws (one per replenishment event
# triggered, and the number of those depends on stock levels -- e.g. the
# waste model reducing closing_stock makes reorders trigger slightly more
# often). Continuing to draw from the same shared stream would mean any
# future tweak upstream silently reshuffles every order in the network,
# perturbing already-reported, already-cited headline numbers (fill rate,
# SLA adherence, lost sales value) for no real reason. Reseeding here
# decouples the two -- orders generation is now stable regardless of how
# many replenishment events the inventory phase produces.
# ---------------------------------------------------------------------------
RNG = np.random.default_rng(43)

CITY_RAIN_DAYS = {
    city: set(RNG.choice(N_DAYS, size=int(N_DAYS * 0.15), replace=False))
    for city in stores["city"].unique()
}

HOUR_WEIGHTS = np.array(
    [0.2, 0.1, 0.1, 0.1, 0.1, 0.2, 0.6, 1.2, 1.5, 1.3, 1.1, 1.4,
     2.0, 1.8, 1.2, 1.0, 1.1, 1.5, 2.2, 2.6, 2.3, 1.6, 1.0, 0.5]
)
HOUR_WEIGHTS = HOUR_WEIGHTS / HOUR_WEIGHTS.sum()


def shift_for_hour(hour: int) -> str:
    if 6 <= hour < 12:
        return "Morning"
    if 12 <= hour < 17:
        return "Afternoon"
    if 17 <= hour < 22:
        return "Evening"
    return "Night"


staffing_idx = staffing.set_index(["store_id", "date", "shift"])

order_rows = []
order_counter = 1
for _, s in stores.iterrows():
    base_orders = SIZE_ORDER_BASE[s["size_tier"]]
    pickers_needed = SIZE_PICKERS_NEEDED[s["size_tier"]]
    for day_idx, d in enumerate(DATES):
        dow_factor = 1.25 if d.dayofweek in (4, 5, 6) else 1.0
        n_orders = max(10, int(RNG.normal(base_orders * dow_factor, base_orders * 0.08)))
        is_rain = day_idx in CITY_RAIN_DAYS[s["city"]]

        hours = RNG.choice(24, size=n_orders, p=HOUR_WEIGHTS)
        for hour in hours:
            minute = int(RNG.integers(0, 60))
            order_time = d + pd.Timedelta(hours=int(hour), minutes=minute)
            shift = shift_for_hour(int(hour))
            row = staffing_idx.loc[(s["store_id"], d, shift)]
            picker_ratio = row["picker_staffing_ratio"]
            riders_on_shift = row["riders_on_shift"]

            is_peak = hour in (12, 13, 19, 20, 21)
            item_count = max(1, int(RNG.poisson(4.5)))
            distance_km = max(0.3, RNG.normal(s["avg_distance_km"], 0.6))

            pick_time = RNG.normal(2.1, 0.4)
            if picker_ratio < 0.7 and is_peak:
                pick_time += RNG.uniform(3.0, 6.5)
            elif picker_ratio < 0.85 and is_peak:
                pick_time += RNG.uniform(0.8, 2.2)
            pick_time = max(1.0, pick_time + item_count * 0.12)

            pack_time = max(0.5, RNG.normal(1.1, 0.25))

            concurrent_load_factor = n_orders / max(1, riders_on_shift * 16)
            dispatch_wait = RNG.normal(0.8, 0.3)
            if concurrent_load_factor > 1.3 and is_peak:
                dispatch_wait += RNG.uniform(3.0, 6.5)
            elif concurrent_load_factor > 1.0:
                dispatch_wait += RNG.uniform(0.8, 2.2)
            dispatch_wait = max(0.3, dispatch_wait)

            avg_speed_kmph = 21.0
            if is_rain:
                avg_speed_kmph *= 0.72
            if is_peak:
                avg_speed_kmph *= 0.9
            travel_time = (distance_km / avg_speed_kmph) * 60 + RNG.normal(0, 0.8)
            travel_time = max(2.0, travel_time)

            total_delivery_min = pick_time + pack_time + dispatch_wait + travel_time
            promised_minutes = min(28, max(13, round(12 + distance_km * 1.8)))
            sla_breach = total_delivery_min > promised_minutes

            order_rows.append(
                {
                    "order_id": f"ORD-{order_counter:07d}",
                    "store_id": s["store_id"],
                    "date": d,
                    "order_time": order_time,
                    "hour": int(hour),
                    "shift": shift,
                    "is_peak_hour": bool(is_peak),
                    "is_rain_day": bool(is_rain),
                    "item_count": item_count,
                    "order_value": round(item_count * RNG.uniform(45, 140), 2),
                    "distance_km": round(distance_km, 2),
                    "picker_staffing_ratio": picker_ratio,
                    "riders_on_shift": int(riders_on_shift),
                    "pick_time_min": round(pick_time, 2),
                    "pack_time_min": round(pack_time, 2),
                    "dispatch_wait_min": round(dispatch_wait, 2),
                    "travel_time_min": round(travel_time, 2),
                    "total_delivery_min": round(total_delivery_min, 2),
                    "promised_minutes": promised_minutes,
                    "sla_breach": bool(sla_breach),
                }
            )
            order_counter += 1

orders = pd.DataFrame(order_rows)
print(f"Generated orders: {len(orders):,}")

# ---------------------------------------------------------------------------
# Business assumptions (single-row config table)
# Editable later from the dashboard's Admin panel -- these are the wage and
# per-km fleet-cost inputs the Cost-to-Serve and fleet-cost metrics are
# computed from. Defaults are rough industry-plausible Indian quick-commerce
# figures (electricity for EV, petrol + maintenance for petrol scooters,
# near-zero running cost for bicycles), clearly labeled as assumptions
# rather than sourced figures.
# ---------------------------------------------------------------------------
business_assumptions = pd.DataFrame(
    [
        {
            "id": 1,
            "picker_hourly_wage_inr": 120.0,
            "rider_hourly_wage_inr": 100.0,
            "ev_scooter_cost_per_km_inr": 1.5,
            "petrol_scooter_cost_per_km_inr": 4.2,
            "bicycle_cost_per_km_inr": 0.3,
            "updated_by": "system_default",
            "updated_at": pd.Timestamp.utcnow().tz_localize(None),
        }
    ]
)

# ---------------------------------------------------------------------------
# Persist: CSVs always written locally; the database goes to Turso if
# TURSO_URL/TURSO_AUTH_TOKEN are set, otherwise to a local SQLite file.
# ---------------------------------------------------------------------------
DATA_DIR.mkdir(exist_ok=True)
run_id = f"{os.getpid()}_{uuid.uuid4().hex[:8]}"
tmp_data_dir = DATA_DIR / f".tmp_{run_id}"
tmp_data_dir.mkdir()
# Parents before children -- dim_stores.warehouse_id references
# dim_warehouses, and the fact tables reference stores/skus/warehouses.
# Local SQLite never enforced this (foreign_keys is off by default there),
# but Turso does enforce it, so the write order has to be correct for both.
TABLES = [
    ("dim_warehouses", warehouses),
    ("dim_stores", stores),
    ("dim_skus", skus),
    ("dim_riders", riders),
    ("fact_staffing_daily", staffing),
    ("fact_inventory_daily", inventory),
    ("fact_replenishment", replenishment),
    ("fact_orders", orders),
    ("business_assumptions", business_assumptions),
]
for name, df in TABLES:
    df.to_csv(tmp_data_dir / f"{name}.csv", index=False)
for csv_file in tmp_data_dir.iterdir():
    csv_file.replace(DATA_DIR / csv_file.name)
tmp_data_dir.rmdir()

INDEXES = [
    ("fact_inventory_daily", ["store_id", "sku_id", "date"]),
    ("fact_orders", ["store_id", "date", "hour"]),
    ("fact_replenishment", ["store_id", "warehouse_id"]),
    ("fact_staffing_daily", ["store_id", "date", "shift"]),
]

if USING_TURSO:
    print(f"\nWriting to Turso: {TURSO_URL}")
    store = get_store(url=TURSO_URL, token=TURSO_AUTH_TOKEN)
    # Turso enforces FK constraints by default; local SQLite never has
    # (foreign_keys is off there unless a PRAGMA turns it on). Matching that
    # existing, already-relied-on behavior rather than fighting it -- the
    # write order above is still correct regardless, this is belt and braces.
    store.execute("PRAGMA foreign_keys = OFF")

    # CREATE TABLE IF NOT EXISTS is a no-op against a table that already
    # exists with an older shape -- it does NOT add new columns. A schema
    # change (like this run's new wasted_units column) would silently fail
    # every subsequent insert with "no such column" until the table is
    # dropped and recreated. Caught live against the real Turso database.
    # FK enforcement is already off, so drop order doesn't matter.
    all_managed_tables = [name for name, _ in TABLES] + ["upload_log"]
    store.execute_script([f"DROP TABLE IF EXISTS {t}" for t in all_managed_tables])

    schema_sql = SCHEMA_SQL_PATH.read_text(encoding="utf-8")
    schema_statements = [
        s.strip() for s in
        "\n".join(l for l in schema_sql.splitlines() if not l.strip().startswith("--")).split(";")
        if s.strip()
    ]
    store.execute_script(schema_statements)

    for name, df in TABLES:
        print(f"  {name}: {len(df):,} rows...")
        store.write_df(name, df, mode="replace")
    store.execute("DELETE FROM upload_log")

    print(f"\nTurso database updated: {TURSO_URL}")
else:
    # Written to a temp file (unique per process) and atomically moved into
    # place at the end. This matters because dashboard/app.py may launch
    # this script from more than one concurrent process on a cold start
    # (e.g. a hosting platform spinning up multiple workers before either
    # sees the DB file exists). Writing in place with if_exists="replace"
    # under that race lets one process's DROP land between another's
    # INSERT statements, silently duplicating dimension-table rows (which
    # then fans out every join against them). A private temp file swapped
    # in with a single atomic rename means concurrent runs can never
    # interleave -- the last writer simply wins outright, cleanly.
    DB_PATH.parent.mkdir(exist_ok=True)
    tmp_db_path = DB_PATH.parent / f".tmp_{run_id}.db"
    conn = sqlite3.connect(tmp_db_path)
    for name, df in TABLES:
        df.to_sql(name, conn, if_exists="replace", index=False)

    # Admin-panel ingestion audit log -- created empty here (schema only);
    # the dashboard's Admin tab appends one row per upload/manual
    # entry/reset so there's a visible history of who changed what and when.
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS upload_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_time TEXT NOT NULL,
            action TEXT NOT NULL,
            target_table TEXT,
            rows_affected INTEGER,
            note TEXT
        )
        """
    )

    for tbl, cols in INDEXES:
        idx_name = f"idx_{tbl}_{'_'.join(cols)}"
        conn.execute(f"CREATE INDEX IF NOT EXISTS {idx_name} ON {tbl} ({', '.join(cols)})")

    conn.commit()
    conn.close()
    tmp_db_path.replace(DB_PATH)

    print(f"\nSQLite DB written to: {DB_PATH}")

print("Tables: dim_stores, dim_warehouses, dim_skus, dim_riders, "
      "fact_staffing_daily, fact_inventory_daily, fact_replenishment, fact_orders, "
      "business_assumptions, upload_log")
