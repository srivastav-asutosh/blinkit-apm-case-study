"""
Blinkit Ops Intelligence Dashboard
Run: streamlit run dashboard/app.py
"""

import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from db_store import get_store  # noqa: E402

DB_PATH = ROOT / "db" / "blinkit_ops.db"
GENERATOR = ROOT / "data" / "generate_data.py"
LOCK_PATH = ROOT / "db" / ".generating.lock"
NEW_METRICS_SQL = ROOT / "sql" / "06_new_metrics.sql"
SAFETY_STOCK_SQL = ROOT / "sql" / "07_safety_stock_policy.sql"
FIX_ROI_SQL = ROOT / "sql" / "08_fix_roi.sql"


def get_secret(key):
    try:
        return st.secrets.get(key)
    except Exception:
        return None


TURSO_URL = get_secret("turso_url")
TURSO_AUTH_TOKEN = get_secret("turso_auth_token")
USING_TURSO = bool(TURSO_URL and TURSO_AUTH_TOKEN)
store = get_store(url=TURSO_URL, token=TURSO_AUTH_TOKEN, sqlite_path=DB_PATH)


def subprocess_env():
    """Env for the generate_data.py subprocess, relaying Turso creds if configured."""
    env = os.environ.copy()
    if USING_TURSO:
        env["TURSO_URL"] = TURSO_URL
        env["TURSO_AUTH_TOKEN"] = TURSO_AUTH_TOKEN
    return env

SIZE_PICKERS_NEEDED = {"Small": 4, "Medium": 6, "Large": 9}
SIZE_RIDERS = {"Small": 6, "Medium": 9, "Large": 13}

# Column sets accepted by the Admin panel's spreadsheet upload, and the safe
# default write mode per table (dimensions replace wholesale; facts append
# as new observations). Kept close to the actual schema in sql/01_schema.sql
# so an uploaded file is validated against the real table shape, not a guess.
UPLOADABLE_TABLES = {
    "dim_stores": {
        "columns": ["store_id", "city", "zone", "warehouse_id", "size_tier",
                    "avg_distance_km", "chronic_understaffed"],
        "default_mode": "replace",
        "bool_cols": ["chronic_understaffed"],
    },
    "dim_skus": {
        "columns": ["sku_id", "sku_name", "category", "is_fast_moving",
                    "shelf_life_days", "unit_cost", "avg_daily_demand_per_store"],
        "default_mode": "replace",
        "bool_cols": ["is_fast_moving"],
    },
    "fact_staffing_daily": {
        "columns": ["date", "store_id", "shift", "pickers_needed", "pickers_present",
                    "riders_on_shift", "picker_staffing_ratio"],
        "default_mode": "append",
        "bool_cols": [],
    },
    "fact_inventory_daily": {
        "columns": ["date", "store_id", "sku_id", "opening_stock", "demand",
                    "units_sold", "closing_stock", "stockout_flag", "lost_units", "wasted_units"],
        "default_mode": "append",
        "bool_cols": ["stockout_flag"],
    },
    "fact_replenishment": {
        "columns": ["replenishment_id", "store_id", "sku_id", "warehouse_id", "order_date",
                    "qty_ordered", "expected_lead_time_days", "actual_lead_time_days", "received_date"],
        "default_mode": "append",
        "bool_cols": [],
    },
    "fact_orders": {
        "columns": ["order_id", "store_id", "date", "order_time", "hour", "shift",
                    "is_peak_hour", "is_rain_day", "item_count", "order_value", "distance_km",
                    "picker_staffing_ratio", "riders_on_shift", "pick_time_min", "pack_time_min",
                    "dispatch_wait_min", "travel_time_min", "total_delivery_min",
                    "promised_minutes", "sla_breach"],
        "default_mode": "append",
        "bool_cols": ["is_peak_hour", "is_rain_day", "sla_breach"],
    },
}

st.set_page_config(page_title="Blinkit Ops Intelligence", page_icon="📦", layout="wide")

PROBLEM_STORES = {"DEL-E-01", "DEL-E-02", "BLR-S-02", "DEL-S-02"}

# The generated dataset is gitignored (it's fully reproducible), so a fresh
# clone -- e.g. a Streamlit Community Cloud deploy, or a fresh Turso database
# with no tables yet -- won't have it. Bootstrap on first boot rather than
# requiring a manual pre-run step. `row_count` returns 0 for both backends
# if the table doesn't exist yet, so this check works identically either way.
#
# A hosting platform can spin up more than one worker before any of them see
# data exist, so an exclusive lock file (atomic create-or-fail) makes only
# one process actually run the generator; the rest just wait for it to
# finish. generate_data.py also writes atomically on its own (SQLite path)
# or table-by-table with FK checks off (Turso path), so even if this lock
# were somehow lost, concurrent runs still can't corrupt the output -- this
# just avoids wasted duplicate work.
DB_PATH.parent.mkdir(exist_ok=True)

try:
    _needs_bootstrap = store.row_count("dim_stores") == 0
except Exception as e:
    # Streamlit Cloud redacts exception text on unhandled crashes regardless
    # of what it says, so an error here has to be written to the page via
    # st.error/st.code (rendered as normal content) rather than left to
    # propagate and hit that redaction.
    st.error(
        "Couldn't reach the configured database. If you just added Turso "
        "secrets, double-check `turso_url` and `turso_auth_token` in "
        "Settings → Secrets for typos or stray whitespace."
    )
    st.code(f"{type(e).__name__}: {e}")
    st.stop()

if _needs_bootstrap:
    try:
        lock_fd = os.open(LOCK_PATH, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(lock_fd)
        got_lock = True
    except FileExistsError:
        got_lock = False

    if got_lock:
        spinner_msg = (
            "First run: generating the simulated 60-day ops dataset and loading it into "
            "Turso (~60-90s, one-time)..." if USING_TURSO else
            "First run: generating the simulated 60-day ops dataset (~15s)..."
        )
        with st.spinner(spinner_msg):
            result = subprocess.run(
                [sys.executable, str(GENERATOR)], capture_output=True, text=True,
                env=subprocess_env(),
            )
            LOCK_PATH.unlink(missing_ok=True)
            if result.returncode != 0:
                st.error("Data generation failed:")
                st.code(result.stderr or result.stdout)
                st.stop()
    else:
        with st.spinner("Another session is generating the dataset, waiting..."):
            for _ in range(120):
                if store.row_count("dim_stores") > 0:
                    break
                time.sleep(1)
            else:
                st.error("Timed out waiting for the dataset to be generated.")
                st.stop()


@st.cache_data
def load_data():
    stores = store.read_sql("SELECT * FROM dim_stores")
    warehouses = store.read_sql("SELECT * FROM dim_warehouses")
    skus = store.read_sql("SELECT * FROM dim_skus")
    inventory = store.read_sql("SELECT * FROM fact_inventory_daily", parse_dates=["date"])
    replenishment = store.read_sql(
        "SELECT * FROM fact_replenishment", parse_dates=["order_date", "received_date"]
    )
    staffing = store.read_sql("SELECT * FROM fact_staffing_daily", parse_dates=["date"])
    orders = store.read_sql("SELECT * FROM fact_orders", parse_dates=["date", "order_time"])
    assumptions = store.read_sql("SELECT * FROM business_assumptions WHERE id = 1")
    upload_log = store.read_sql("SELECT * FROM upload_log ORDER BY id DESC LIMIT 25")

    inventory = inventory.merge(stores, on="store_id").merge(
        skus[["sku_id", "category", "is_fast_moving", "unit_cost"]], on="sku_id"
    )
    orders = orders.merge(stores, on="store_id")
    replenishment = replenishment.merge(stores[["store_id", "zone", "city"]], on="store_id")
    staffing = staffing.merge(stores[["store_id", "zone", "city", "chronic_understaffed"]], on="store_id")
    return stores, warehouses, skus, inventory, replenishment, staffing, orders, assumptions, upload_log


@st.cache_data
def load_new_metrics():
    sql = NEW_METRICS_SQL.read_text(encoding="utf-8")
    stmts = [
        s.strip() for s in
        "\n".join(l for l in sql.splitlines() if not l.strip().startswith("--")).split(";")
        if s.strip()
    ]
    return [store.read_sql(stmt) for stmt in stmts]  # [perfect_order, days_of_cover, rider_utilization, cost_to_serve]


@st.cache_data
def load_safety_stock_policy():
    sql = SAFETY_STOCK_SQL.read_text(encoding="utf-8")
    stmt = "\n".join(l for l in sql.splitlines() if not l.strip().startswith("--")).strip().rstrip(";")
    return store.read_sql(stmt)


@st.cache_data
def load_fix_roi():
    sql = FIX_ROI_SQL.read_text(encoding="utf-8")
    stmts = [
        s.strip() for s in
        "\n".join(l for l in sql.splitlines() if not l.strip().startswith("--")).split(";")
        if s.strip()
    ]
    return [store.read_sql(stmt) for stmt in stmts]  # [staffing_fix_roi, remap_payback]


def log_admin_action(action, target_table=None, rows_affected=None, note=None):
    store.execute(
        "INSERT INTO upload_log (event_time, action, target_table, rows_affected, note) VALUES (?, ?, ?, ?, ?)",
        [datetime.now(timezone.utc).isoformat(timespec="seconds"), action, target_table, rows_affected, note],
    )


def refresh_after_write():
    load_data.clear()
    load_new_metrics.clear()
    st.cache_data.clear()


def read_uploaded_file(uploaded_file):
    if uploaded_file.name.lower().endswith(".csv"):
        return pd.read_csv(uploaded_file)
    return pd.read_excel(uploaded_file)


def validate_upload(df, table_name):
    spec = UPLOADABLE_TABLES[table_name]
    expected = set(spec["columns"])
    got = set(df.columns)
    missing = expected - got
    extra = got - expected
    errors = []
    if df.empty:
        errors.append("The uploaded file has no rows.")
    if missing:
        errors.append(f"Missing required column(s): {', '.join(sorted(missing))}")
    df = df[[c for c in spec["columns"] if c in df.columns]].copy()
    for col in spec["bool_cols"]:
        if col in df.columns:
            df[col] = (
                df[col].astype(str).str.strip().str.lower()
                .map({"true": 1, "1": 1, "yes": 1, "false": 0, "0": 0, "no": 0})
            )
            if df[col].isna().any():
                errors.append(f"Column '{col}' has values that aren't recognizable as true/false.")
    numeric_candidates = [c for c in df.columns if c not in spec["bool_cols"]
                           and df[c].dtype == object and c not in ("date", "order_date",
                                                                     "received_date", "order_time",
                                                                     "shift", "store_id", "sku_id",
                                                                     "warehouse_id", "order_id",
                                                                     "replenishment_id", "city",
                                                                     "zone", "size_tier", "category",
                                                                     "sku_name")]
    for col in numeric_candidates:
        coerced = pd.to_numeric(df[col], errors="coerce")
        if coerced.isna().sum() > df[col].isna().sum():
            errors.append(f"Column '{col}' has non-numeric values that couldn't be parsed.")
        else:
            df[col] = coerced
    return df, extra, errors


stores, warehouses, skus, inventory, replenishment, staffing, orders, assumptions, upload_log = load_data()

# ---------------------------------------------------------------------------
# Sidebar filters
# ---------------------------------------------------------------------------
st.sidebar.title("📦 Blinkit Ops Intelligence")
st.sidebar.caption("Associate Program Manager portfolio project — Supply Chain, Store Ops & Last Mile")

cities = ["All"] + sorted(stores["city"].unique().tolist())
city_filter = st.sidebar.selectbox("City", cities)

if city_filter != "All":
    inv_f = inventory[inventory["city"] == city_filter]
    ord_f = orders[orders["city"] == city_filter]
    repl_f = replenishment[replenishment["city"] == city_filter]
    staff_f = staffing[staffing["city"] == city_filter]
    stores_f = stores[stores["city"] == city_filter]
else:
    inv_f, ord_f, repl_f, staff_f, stores_f = inventory, orders, replenishment, staffing, stores

st.sidebar.markdown("---")
st.sidebar.markdown(
    "**Dataset**: 12 dark stores · 2 cities · 60 days simulated ops data\n\n"
    "**Domains**: Supply Chain & Replenishment · Store Operations · Last Mile Delivery"
)

# ---------------------------------------------------------------------------
# Header KPI row
# ---------------------------------------------------------------------------
st.title("Blinkit Operations Intelligence Dashboard")
st.caption(
    "A cross-domain operational analytics case study — root-cause analysis across "
    "supply chain, store operations, and last-mile delivery for a simulated Blinkit dark-store network."
)

fast_inv = inv_f[inv_f["is_fast_moving"] == 1]
fill_rate = 100 * fast_inv["units_sold"].sum() / fast_inv["demand"].sum()
stockout_rate = 100 * fast_inv["stockout_flag"].sum() / len(fast_inv)
lost_sales_value = (fast_inv["lost_units"] * fast_inv["unit_cost"]).sum()
sla_adherence = 100 * (1 - ord_f["sla_breach"].mean())
avg_delivery = ord_f["total_delivery_min"].mean()

k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Fill Rate (fast movers)", f"{fill_rate:.1f}%")
k2.metric("Stockout Rate (fast movers)", f"{stockout_rate:.2f}%")
k3.metric("Est. Lost Sales (60d)", f"₹{lost_sales_value:,.0f}")
k4.metric("SLA Adherence", f"{sla_adherence:.1f}%")
k5.metric("Avg Delivery Time", f"{avg_delivery:.1f} min")

st.markdown("---")

tab_overview, tab_supply, tab_store_ops, tab_last_mile, tab_rca, tab_metrics, tab_admin = st.tabs(
    ["🏠 Overview", "📦 Supply Chain", "🏬 Store Operations", "🛵 Last Mile", "🔎 Cross-Domain RCA",
     "📈 New Metrics", "🔐 Admin"]
)

# ---------------------------------------------------------------------------
# Overview tab
# ---------------------------------------------------------------------------
with tab_overview:
    st.subheader("Store-level composite risk")
    st.caption("Each store scored 0-8 across three independent risk signals — see the RCA tab for methodology.")

    sc = (
        fast_inv.groupby("store_id")
        .apply(lambda d: 100 * d["stockout_flag"].sum() / len(d), include_groups=False)
        .rename("stockout_rate_pct")
    )
    so = ord_f.groupby("store_id")["sla_breach"].mean().mul(100).rename("sla_breach_pct")
    lm = ord_f.groupby("store_id")["total_delivery_min"].mean().rename("avg_delivery_min")
    risk = pd.concat([sc, so, lm], axis=1).reset_index().merge(stores, on="store_id")

    def risk_score(row):
        s = 0
        s += 3 if row["stockout_rate_pct"] > 1.0 else (1 if row["stockout_rate_pct"] > 0.1 else 0)
        s += 3 if row["sla_breach_pct"] > 25 else (1 if row["sla_breach_pct"] > 10 else 0)
        s += 2 if row["avg_delivery_min"] > 18 else (1 if row["avg_delivery_min"] > 14 else 0)
        return s

    risk["composite_risk_score"] = risk.apply(risk_score, axis=1)
    risk = risk.sort_values("composite_risk_score", ascending=False)

    fig = px.bar(
        risk, x="store_id", y="composite_risk_score", color="composite_risk_score",
        color_continuous_scale="Reds", labels={"composite_risk_score": "Risk score (0-8)"},
        title="Composite operational risk score by store",
    )
    fig.update_layout(coloraxis_showscale=False, height=420)
    st.plotly_chart(fig, use_container_width=True)

    st.dataframe(
        risk[["store_id", "city", "zone", "chronic_understaffed", "stockout_rate_pct",
              "sla_breach_pct", "avg_delivery_min", "composite_risk_score"]]
        .rename(columns={
            "stockout_rate_pct": "Stockout %", "sla_breach_pct": "SLA breach %",
            "avg_delivery_min": "Avg delivery (min)", "chronic_understaffed": "Chronic understaffed",
            "composite_risk_score": "Risk score",
        }),
        use_container_width=True, hide_index=True,
    )

# ---------------------------------------------------------------------------
# Supply Chain tab
# ---------------------------------------------------------------------------
with tab_supply:
    st.subheader("Stockout rate & lost sales by warehouse")
    st.caption("Root cause: stores mapped to the slower secondary warehouse carry structurally higher stockout risk.")

    wh_view = (
        fast_inv.groupby(["store_id", "warehouse_id"])
        .agg(stockout_rate_pct=("stockout_flag", lambda x: 100 * x.sum() / len(x)),
             lost_sales_value=("lost_units", "sum"))
        .reset_index()
    )
    wh_view["lost_sales_value"] = (
        fast_inv.groupby("store_id").apply(lambda d: (d["lost_units"] * d["unit_cost"]).sum(), include_groups=False).values
    )

    c1, c2 = st.columns(2)
    with c1:
        fig = px.bar(
            wh_view.sort_values("stockout_rate_pct", ascending=False),
            x="store_id", y="stockout_rate_pct", color="warehouse_id",
            title="Stockout rate by store, colored by source warehouse",
            labels={"stockout_rate_pct": "Stockout rate (%)", "store_id": "Store"},
        )
        st.plotly_chart(fig, use_container_width=True)
    with c2:
        fig = px.bar(
            wh_view.sort_values("lost_sales_value", ascending=False),
            x="store_id", y="lost_sales_value", color="warehouse_id",
            title="Estimated lost sales value (60d) by store",
            labels={"lost_sales_value": "Lost sales value (₹)", "store_id": "Store"},
        )
        st.plotly_chart(fig, use_container_width=True)

    st.subheader("Lead time: contracted vs. actual, by warehouse")
    lt = repl_f.groupby("warehouse_id").agg(
        avg_expected=("expected_lead_time_days", "mean"),
        avg_actual=("actual_lead_time_days", "mean"),
    ).reset_index()
    lt_melt = lt.melt(id_vars="warehouse_id", var_name="metric", value_name="days")
    fig = px.bar(lt_melt, x="warehouse_id", y="days", color="metric", barmode="group",
                 title="Contracted vs. actual replenishment lead time")
    st.plotly_chart(fig, use_container_width=True)

    st.subheader("Category-level stockout risk (secondary-warehouse stores)")
    cat_view = (
        fast_inv[fast_inv["warehouse_id"] == "WH-DEL-SECONDARY"]
        .groupby("category")
        .agg(stockout_rate_pct=("stockout_flag", lambda x: 100 * x.sum() / len(x)))
        .reset_index()
        .sort_values("stockout_rate_pct", ascending=False)
    )
    fig = px.bar(cat_view, x="category", y="stockout_rate_pct",
                 title="Stockout rate by category — WH-DEL-SECONDARY stores")
    st.plotly_chart(fig, use_container_width=True)

    st.markdown("---")
    st.subheader("Safety stock policy review")
    st.caption(
        "The network's current reorder-point formula is a flat \"+2 days\" buffer, regardless of "
        "how volatile a SKU's demand is or how variable its warehouse's lead time is. This isn't "
        "the root cause found above -- it's a second, independent finding: the *policy itself* "
        "doesn't scale with variability. SQL: sql/07_safety_stock_policy.sql."
    )
    ss = load_safety_stock_policy()
    ss_view = ss.copy()
    ss_view["direction"] = ss_view["gap_pct"].apply(lambda v: "Under-buffered" if v > 0 else "Over-buffered")

    c1, c2 = st.columns(2)
    with c1:
        fig = px.bar(
            ss_view, x="warehouse_id", y="lead_time_stddev_days",
            title="Lead-time variability (std dev, days) by warehouse",
            labels={"lead_time_stddev_days": "Lead-time std dev (days)", "warehouse_id": "Warehouse"},
        )
        st.plotly_chart(fig, use_container_width=True)
    with c2:
        fig = px.bar(
            ss_view.sort_values("gap_pct"), x="warehouse_id", y="gap_pct", color="direction",
            color_discrete_map={"Under-buffered": "#d03b3b", "Over-buffered": "#1c5cab"},
            title="Correct vs. current reorder point: gap %",
            labels={"gap_pct": "Gap (correct vs. current, %)", "warehouse_id": "Warehouse"},
        )
        st.plotly_chart(fig, use_container_width=True)

    st.dataframe(
        ss_view[["warehouse_id", "avg_lead_time_days", "lead_time_stddev_days",
                 "avg_correct_rop_units", "avg_current_rop_units", "gap_pct", "gap_value_inr", "direction"]]
        .rename(columns={
            "avg_lead_time_days": "Avg lead time (days)", "lead_time_stddev_days": "Lead-time std dev (days)",
            "avg_correct_rop_units": "Correct ROP (units)", "avg_current_rop_units": "Current ROP (units)",
            "gap_pct": "Gap (%)", "gap_value_inr": "Gap value (₹)", "direction": "Direction",
        }),
        use_container_width=True, hide_index=True,
    )
    net_gap = ss["gap_value_inr"].sum()
    st.markdown(
        f"**Net effect:** the network could shift its total safety-stock investment by "
        f"**₹{abs(net_gap):,.0f}** ({'net reduction' if net_gap < 0 else 'net increase'}) while "
        f"*improving* service at the highest-variability warehouse — this is a reallocation finding, "
        f"not a spend-more finding. The current policy over-buffers the two low-variability primary "
        f"warehouses and under-buffers the one volatile secondary warehouse, because it only accounts "
        f"for lead-time *length*, never lead-time or demand *variability*."
    )

    st.markdown("---")
    st.subheader("Shrinkage: an order-cycle vs. shelf-life mismatch")
    st.caption(
        "Stockouts and safety stock are both about not holding enough. This is the opposite failure "
        "mode: fast-moving SKUs are ordered on a flat 10-day cycle regardless of category, but Dairy "
        "(7-day shelf life) and Fruits & Vegetables (5-day) routinely receive more stock than can "
        "plausibly sell before it spoils. Modeled as spoilage on stock held beyond "
        "avg_daily_demand × shelf_life_days -- see data/generate_data.py."
    )
    waste_by_cat = (
        fast_inv.groupby("category")
        .apply(lambda d: (d["wasted_units"] * d["unit_cost"]).sum(), include_groups=False)
        .rename("waste_value_inr").reset_index()
        .sort_values("waste_value_inr", ascending=False)
    )
    waste_by_store = (
        fast_inv.groupby("store_id")
        .apply(lambda d: (d["wasted_units"] * d["unit_cost"]).sum(), include_groups=False)
        .rename("waste_value_inr").reset_index()
        .sort_values("waste_value_inr", ascending=False)
    )
    c1, c2 = st.columns(2)
    with c1:
        fig = px.bar(
            waste_by_cat, x="category", y="waste_value_inr",
            title="Waste value (60d) by category",
            labels={"waste_value_inr": "Waste value (₹)", "category": "Category"},
        )
        st.plotly_chart(fig, use_container_width=True)
    with c2:
        fig = px.bar(
            waste_by_store, x="store_id", y="waste_value_inr",
            title="Waste value (60d) by store — spread network-wide, unlike stockouts",
            labels={"waste_value_inr": "Waste value (₹)", "store_id": "Store"},
        )
        st.plotly_chart(fig, use_container_width=True)

    total_waste = waste_by_cat["waste_value_inr"].sum()
    st.markdown(
        f"**₹{total_waste:,.0f} in modeled shrinkage over 60 days** — entirely in the two "
        f"short-shelf-life categories, and spread close to evenly across all 12 stores rather than "
        f"concentrated like the stockout problem, because it's driven by a category-level ordering "
        f"policy (10-day cycle vs. 5–7 day shelf life), not a store- or warehouse-specific cause. "
        f"Fixing it means shortening the order cycle for these two categories specifically — it "
        f"doesn't touch warehouse mapping or staffing."
    )

# ---------------------------------------------------------------------------
# Store Operations tab
# ---------------------------------------------------------------------------
with tab_store_ops:
    st.subheader("SLA breach rate vs. picker staffing ratio")
    st.caption("Root cause: SLA breaches spike sharply once picker staffing drops below ~85% during peak hours.")

    peak = ord_f[ord_f["is_peak_hour"] == 1].copy()
    bins = [0, 0.70, 0.85, 1.00, 999]
    labels = ["<70%", "70-85%", "85-100%", "100%+"]
    peak["staffing_bucket"] = pd.cut(peak["picker_staffing_ratio"], bins=bins, labels=labels)
    bucket_view = peak.groupby("staffing_bucket", observed=True).agg(
        sla_breach_pct=("sla_breach", lambda x: 100 * x.mean()),
        avg_pick_time=("pick_time_min", "mean"),
        orders=("order_id", "count"),
    ).reset_index()

    c1, c2 = st.columns(2)
    with c1:
        fig = px.bar(bucket_view, x="staffing_bucket", y="sla_breach_pct",
                     title="SLA breach % by picker-staffing bucket (peak hours)",
                     labels={"staffing_bucket": "Picker staffing ratio", "sla_breach_pct": "SLA breach (%)"})
        st.plotly_chart(fig, use_container_width=True)
    with c2:
        fig = px.bar(bucket_view, x="staffing_bucket", y="avg_pick_time",
                     title="Avg pick time (min) by picker-staffing bucket",
                     labels={"staffing_bucket": "Picker staffing ratio", "avg_pick_time": "Avg pick time (min)"})
        st.plotly_chart(fig, use_container_width=True)

    st.subheader("Evening-shift SLA breach by store")
    eve = ord_f[ord_f["shift"] == "Evening"].groupby(["store_id", "chronic_understaffed"]).agg(
        sla_breach_pct=("sla_breach", lambda x: 100 * x.mean())
    ).reset_index().sort_values("sla_breach_pct", ascending=False)
    fig = px.bar(eve, x="store_id", y="sla_breach_pct", color="chronic_understaffed",
                 title="Evening-shift SLA breach % by store",
                 labels={"sla_breach_pct": "SLA breach (%)", "chronic_understaffed": "Chronic understaffed"})
    st.plotly_chart(fig, use_container_width=True)

    st.subheader("Staffing ratio heatmap: store x shift")
    heat = staff_f.groupby(["store_id", "shift"])["picker_staffing_ratio"].mean().reset_index()
    heat_pivot = heat.pivot(index="store_id", columns="shift", values="picker_staffing_ratio")
    shift_order = ["Morning", "Afternoon", "Evening", "Night"]
    heat_pivot = heat_pivot[[c for c in shift_order if c in heat_pivot.columns]]
    fig = go.Figure(data=go.Heatmap(
        z=heat_pivot.values, x=heat_pivot.columns, y=heat_pivot.index,
        colorscale="RdYlGn", zmid=0.85, text=heat_pivot.round(2).values,
        texttemplate="%{text}",
    ))
    fig.update_layout(title="Avg picker staffing ratio by store & shift", height=420)
    st.plotly_chart(fig, use_container_width=True)

# ---------------------------------------------------------------------------
# Last Mile tab
# ---------------------------------------------------------------------------
with tab_last_mile:
    st.subheader("Delivery time & SLA breach by zone")
    zone_view = ord_f.groupby(["zone", "city"]).agg(
        avg_delivery_min=("total_delivery_min", "mean"),
        sla_breach_pct=("sla_breach", lambda x: 100 * x.mean()),
        orders=("order_id", "count"),
    ).reset_index().sort_values("avg_delivery_min", ascending=False)
    zone_view["zone_city"] = zone_view["zone"] + " - " + zone_view["city"]

    c1, c2 = st.columns(2)
    with c1:
        fig = px.bar(zone_view, x="zone_city", y="avg_delivery_min",
                     title="Avg delivery time by zone", labels={"zone_city": "Zone", "avg_delivery_min": "Avg delivery (min)"})
        st.plotly_chart(fig, use_container_width=True)
    with c2:
        fig = px.bar(zone_view, x="zone_city", y="sla_breach_pct",
                     title="SLA breach % by zone", labels={"zone_city": "Zone", "sla_breach_pct": "SLA breach (%)"})
        st.plotly_chart(fig, use_container_width=True)

    st.subheader("Rain-day effect")
    rain_view = ord_f.groupby("is_rain_day").agg(
        avg_delivery_min=("total_delivery_min", "mean"),
        sla_breach_pct=("sla_breach", lambda x: 100 * x.mean()),
    ).reset_index()
    rain_view["is_rain_day"] = rain_view["is_rain_day"].map({0: "No rain", 1: "Rain"})
    c1, c2 = st.columns(2)
    with c1:
        fig = px.bar(rain_view, x="is_rain_day", y="avg_delivery_min", title="Avg delivery time: rain vs. no rain")
        st.plotly_chart(fig, use_container_width=True)
    with c2:
        fig = px.bar(rain_view, x="is_rain_day", y="sla_breach_pct", title="SLA breach %: rain vs. no rain")
        st.plotly_chart(fig, use_container_width=True)

    st.subheader("East Delhi deep dive — hour-by-hour SLA breach")
    east_del = ord_f[(ord_f["zone"] == "East") & (ord_f["city"] == "Delhi")]
    hourly = east_del.groupby("hour").agg(
        sla_breach_pct=("sla_breach", lambda x: 100 * x.mean()),
        orders=("order_id", "count"),
    ).reset_index()
    fig = px.line(hourly, x="hour", y="sla_breach_pct", markers=True,
                  title="East Delhi: SLA breach % by hour of day")
    st.plotly_chart(fig, use_container_width=True)

# ---------------------------------------------------------------------------
# Cross-domain RCA tab
# ---------------------------------------------------------------------------
with tab_rca:
    st.subheader("Composite risk ranking")
    st.markdown(
        """
        Each store is scored **0–8** across three independent risk signals, so a store that fails on
        every axis stands out from one that fails on only one:

        | Signal | 0 pts | 1 pt | 3 pts (supply/staffing) or 2 pts (delivery) |
        |---|---|---|---|
        | Stockout rate (fast movers) | ≤ 0.1% | 0.1–1.0% | > 1.0% |
        | SLA breach rate | ≤ 10% | 10–25% | > 25% |
        | Avg delivery time | ≤ 14 min | 14–18 min | > 18 min |
        """
    )
    st.dataframe(
        risk[["store_id", "city", "zone", "warehouse_id", "chronic_understaffed",
              "stockout_rate_pct", "sla_breach_pct", "avg_delivery_min", "composite_risk_score"]]
        .sort_values("composite_risk_score", ascending=False)
        .rename(columns={
            "stockout_rate_pct": "Stockout %", "sla_breach_pct": "SLA breach %",
            "avg_delivery_min": "Avg delivery (min)", "chronic_understaffed": "Chronic understaffed",
            "composite_risk_score": "Risk score",
        }),
        use_container_width=True, hide_index=True,
    )

    st.subheader("Reading the ranking")
    st.markdown(
        """
        - **DEL-E-01 / DEL-E-02** (risk score 8): compounding risk — on the slow secondary warehouse
          *and* chronically understaffed *and* the farthest zone. These are the two stores an ops
          review should act on first, and a single fix (e.g. warehouse remap) won't be enough on its own.
        - **BLR-S-02** (risk score 4): staffing-only risk — proves the SLA problem is a
          scheduling issue, not a Delhi-specific or warehouse-specific one.
        - **DEL-S-02** (risk score 3): supply-chain-only risk — same warehouse issue as the East
          stores, but staffing and distance are both healthy, isolating the warehouse as the driver.
        - **BLR-E-01** (risk score 2): distance-only risk — East zones run longer delivery times
          structurally, even with healthy staffing and supply chain.
        - Every other store scores **0** — a clean baseline that makes the above four stand out
          rather than the whole network looking uniformly stressed.
        """
    )

    st.markdown("---")
    st.subheader("Cost of the fix — not just cost of the problem")
    st.caption(
        "Every finding above prices the problem. This section prices the two headline fixes "
        "against it, because a recommendation without a payback number gets discussed, not funded. "
        "SQL: sql/08_fix_roi.sql."
    )
    staffing_roi, remap_payback = load_fix_roi()

    st.markdown("**1. Staffing fix — evening picker gap at the 3 chronic-understaffed stores**")
    staffing_roi_view = staffing_roi.copy()
    total_cost = staffing_roi_view["fix_cost_inr_60d"].sum()
    total_saving = staffing_roi_view["direct_cts_saving_inr_60d"].sum()
    coverage_pct = 100.0 * total_saving / total_cost

    c1, c2 = st.columns(2)
    with c1:
        melted = staffing_roi_view.melt(
            id_vars="store_id", value_vars=["fix_cost_inr_60d", "direct_cts_saving_inr_60d"],
            var_name="metric", value_name="inr",
        )
        melted["metric"] = melted["metric"].map({
            "fix_cost_inr_60d": "Fix cost (labor)", "direct_cts_saving_inr_60d": "Direct CTS saving",
        })
        fig = px.bar(
            melted, x="store_id", y="inr", color="metric", barmode="group",
            title="Staffing-fix cost vs. direct cost-to-serve saving (60d)",
            labels={"inr": "₹ (60 days)", "store_id": "Store", "metric": ""},
        )
        st.plotly_chart(fig, use_container_width=True)
    with c2:
        st.dataframe(
            staffing_roi_view[["store_id", "extra_picker_hours_60d", "fix_cost_inr_60d",
                                "direct_cts_saving_inr_60d"]]
            .rename(columns={
                "store_id": "Store", "extra_picker_hours_60d": "Extra picker-hours (60d)",
                "fix_cost_inr_60d": "Fix cost (₹)", "direct_cts_saving_inr_60d": "Direct CTS saving (₹)",
            }),
            use_container_width=True, hide_index=True,
        )
    st.markdown(
        f"**₹{total_cost:,.0f} labor cost to close the evening staffing gap to a 90% target, "
        f"vs. ₹{total_saving:,.0f} in direct cost-to-serve savings — only {coverage_pct:.0f}% of the "
        f"investment pays for itself through labor efficiency alone.** This is the honest number, "
        f"not a manufactured payback story: closing this gap is still the right call, but the "
        f"business case for the remaining ~₹{total_cost - total_saving:,.0f} has to rest on SLA and "
        f"customer-retention value (fewer breached deliveries at the 3 worst-performing stores in the "
        f"network) — value this schema can't price directly, so it shouldn't be asserted as a ₹ "
        f"figure it doesn't have. A recommendation that names its own limits is more credible than "
        f"one that doesn't."
    )

    st.markdown("**2. Warehouse-remap payback — sensitivity across assumed project cost**")
    st.caption(
        "The ₹319,304/60d in lost sales at WH-DEL-SECONDARY (sql/02_supply_chain_kpis.sql, Q2) is "
        "the revenue a remap would recover. The one-time remap/negotiation cost isn't an operational "
        "metric this schema tracks, so payback is shown across a plausible range instead of one "
        "invented number."
    )
    fig = px.bar(
        remap_payback, x="one_time_cost_inr", y="payback_months",
        title="Payback period by assumed one-time remap cost",
        labels={"one_time_cost_inr": "Assumed one-time cost (₹)", "payback_months": "Payback (months)"},
        text="payback_months",
    )
    fig.update_traces(texttemplate="%{text:.1f}mo", textposition="outside")
    st.plotly_chart(fig, use_container_width=True)
    st.markdown(
        f"**Even at the high end of plausible remap costs (₹500,000), payback is {remap_payback['payback_months'].max():.1f} "
        f"months — under {remap_payback['payback_months'].min():.1f} months at the low end (₹100,000).** "
        f"This is the stronger, cleaner business case of the two: unlike the staffing fix, it doesn't "
        f"need an SLA/customer-value argument to close — it pays for itself on recovered revenue alone, "
        f"and fast, across the entire range of reasonable cost assumptions."
    )

# ---------------------------------------------------------------------------
# New Metrics tab
# ---------------------------------------------------------------------------
with tab_metrics:
    st.subheader("Beyond the original KPI set")
    st.caption(
        "Four metrics proposed on top of the base dashboard — each ties two domains together or "
        "converts ops performance into a ₹ figure. SQL: sql/06_new_metrics.sql."
    )

    perfect_order, days_of_cover, rider_util, cost_to_serve = load_new_metrics()
    wage = assumptions.iloc[0]

    st.markdown(
        f"**Current wage assumptions** (editable in the Admin tab): "
        f"picker ₹{wage['picker_hourly_wage_inr']:.0f}/hr · rider ₹{wage['rider_hourly_wage_inr']:.0f}/hr"
    )

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("##### Perfect Order Rate, by store")
        st.caption(
            "Proxy metric: order wasn't SLA-breached AND its store had zero fast-moving stockouts "
            "that day. Not a strict line-item fulfillment rate (this schema doesn't link orders to "
            "specific SKUs) — a transparent, honestly-labeled composite instead."
        )
        fig = px.bar(
            perfect_order.sort_values("perfect_order_rate_pct"),
            x="store_id", y="perfect_order_rate_pct",
            color="perfect_order_rate_pct", color_continuous_scale="RdYlGn",
            labels={"perfect_order_rate_pct": "Perfect order rate (%)"},
        )
        fig.update_layout(coloraxis_showscale=False, height=360)
        st.plotly_chart(fig, use_container_width=True)

    with c2:
        st.markdown("##### Inventory Days of Cover, by store")
        st.caption(
            "Latest closing stock ÷ trailing-14-day avg demand, fast-moving SKUs. A different signal "
            "from stockout rate — measures buffer size, not breach frequency."
        )
        fig = px.bar(
            days_of_cover.sort_values("days_of_cover"),
            x="store_id", y="days_of_cover",
            labels={"days_of_cover": "Days of cover"},
        )
        fig.update_layout(height=360)
        st.plotly_chart(fig, use_container_width=True)

    c3, c4 = st.columns(2)
    with c3:
        st.markdown("##### Rider Utilization, by store")
        st.caption(
            "Orders delivered per scheduled rider-hour (6h/shift assumed). Notice the understaffed "
            "stores run the *highest* utilization — their riders are overworked, not idle."
        )
        fig = px.bar(
            rider_util.sort_values("orders_per_rider_hour", ascending=False),
            x="store_id", y="orders_per_rider_hour",
            labels={"orders_per_rider_hour": "Orders / rider-hour"},
        )
        fig.update_layout(height=360)
        st.plotly_chart(fig, use_container_width=True)

    with c4:
        st.markdown("##### Cost-to-Serve per order, by store")
        st.caption(
            "Labor-only estimate from pick/pack/dispatch/travel time × wage assumptions above — "
            "converts operational dysfunction into a ₹ figure a business case can use."
        )
        fig = px.bar(
            cost_to_serve.sort_values("avg_cost_to_serve_inr", ascending=False),
            x="store_id", y="avg_cost_to_serve_inr",
            labels={"avg_cost_to_serve_inr": "Avg cost to serve (₹)"},
        )
        fig.update_layout(height=360)
        st.plotly_chart(fig, use_container_width=True)

# ---------------------------------------------------------------------------
# Admin tab
# ---------------------------------------------------------------------------
with tab_admin:
    configured_password = get_secret("admin_password")

    if not configured_password:
        st.warning(
            "No admin password configured. Set `admin_password` in Streamlit secrets "
            "(locally: `.streamlit/secrets.toml`; on Streamlit Cloud: App settings → Secrets) "
            "to enable the Admin panel."
        )
    else:
        if "admin_authed" not in st.session_state:
            st.session_state.admin_authed = False

        if not st.session_state.admin_authed:
            st.subheader("🔐 Admin sign-in")
            pw = st.text_input("Password", type="password")
            if st.button("Sign in"):
                if pw == configured_password:
                    st.session_state.admin_authed = True
                    st.rerun()
                else:
                    st.error("Incorrect password.")
        else:
            top = st.columns([5, 1])
            with top[0]:
                st.subheader("🔐 Admin panel")
            with top[1]:
                if st.button("Sign out"):
                    st.session_state.admin_authed = False
                    st.rerun()

            if USING_TURSO:
                st.caption("Connected to Turso — uploads and edits persist permanently, including across reboots and redeploys.")
            else:
                st.caption(
                    "Note: no external database configured, so this is running on local SQLite — "
                    "uploads persist for as long as this app instance keeps running, but a reboot or "
                    "redeploy resets to the generated baseline."
                )

            # --- Business assumptions ---
            st.markdown("#### Business assumptions")
            with st.form("assumptions_form"):
                ac1, ac2 = st.columns(2)
                picker_wage = ac1.number_input(
                    "Picker hourly wage (₹)", min_value=0.0, value=float(wage["picker_hourly_wage_inr"]), step=5.0
                )
                rider_wage = ac2.number_input(
                    "Rider hourly wage (₹)", min_value=0.0, value=float(wage["rider_hourly_wage_inr"]), step=5.0
                )
                if st.form_submit_button("Save assumptions"):
                    store.execute(
                        "UPDATE business_assumptions SET picker_hourly_wage_inr=?, rider_hourly_wage_inr=?, "
                        "updated_by=?, updated_at=? WHERE id=1",
                        [picker_wage, rider_wage, "admin_panel", datetime.now(timezone.utc).isoformat(timespec="seconds")],
                    )
                    log_admin_action("update_assumptions", "business_assumptions", 1,
                                      f"picker=₹{picker_wage}/hr, rider=₹{rider_wage}/hr")
                    refresh_after_write()
                    st.success("Saved. Cost-to-Serve will recompute with the new wages.")
                    st.rerun()

            st.markdown("---")

            # --- Spreadsheet upload ---
            st.markdown("#### Upload a spreadsheet")
            target_table = st.selectbox("Target table", list(UPLOADABLE_TABLES.keys()))
            spec = UPLOADABLE_TABLES[target_table]
            st.caption(f"Expected columns: `{'`, `'.join(spec['columns'])}`")
            uploaded = st.file_uploader("CSV or Excel file", type=["csv", "xlsx", "xls"], key=f"upload_{target_table}")

            if uploaded is not None:
                try:
                    raw_df = read_uploaded_file(uploaded)
                except Exception as e:
                    st.error(f"Couldn't read that file: {e}")
                    raw_df = None

                if raw_df is not None:
                    clean_df, extra_cols, errors = validate_upload(raw_df, target_table)
                    if extra_cols:
                        st.info(f"Ignoring unexpected column(s): {', '.join(sorted(extra_cols))}")
                    if errors:
                        for e in errors:
                            st.error(e)
                    else:
                        st.success(f"{len(clean_df):,} row(s) validated.")
                        st.dataframe(clean_df.head(20), use_container_width=True)
                        mode = st.radio(
                            "Write mode", ["append", "replace"],
                            index=0 if spec["default_mode"] == "append" else 1,
                            horizontal=True, key=f"mode_{target_table}",
                        )
                        confirm_ok = True
                        if mode == "replace":
                            confirm_text = st.text_input(
                                f"Replacing {target_table} deletes its existing rows. Type REPLACE to confirm.",
                                key=f"confirm_{target_table}",
                            )
                            confirm_ok = confirm_text.strip() == "REPLACE"
                        if st.button("Commit to database", disabled=not confirm_ok, key=f"commit_{target_table}"):
                            store.write_df(target_table, clean_df, mode=mode)
                            log_admin_action(f"upload_{mode}", target_table, len(clean_df), uploaded.name)
                            refresh_after_write()
                            st.success(f"Committed {len(clean_df):,} row(s) to {target_table}.")
                            st.rerun()

            st.markdown("---")

            # --- Manual entry: log a staffing shift ---
            st.markdown("#### Log a staffing shift manually")
            with st.form("staffing_form"):
                sc1, sc2, sc3 = st.columns(3)
                m_store = sc1.selectbox("Store", stores["store_id"].tolist())
                m_date = sc2.date_input("Date")
                m_shift = sc3.selectbox("Shift", ["Morning", "Afternoon", "Evening", "Night"])
                sc4, sc5 = st.columns(2)
                size_tier = stores.loc[stores["store_id"] == m_store, "size_tier"].iloc[0]
                needed = SIZE_PICKERS_NEEDED[size_tier]
                m_present = sc4.number_input("Pickers present", min_value=0, value=needed, step=1)
                m_riders = sc5.number_input("Riders on shift", min_value=0, value=SIZE_RIDERS[size_tier] // 2, step=1)
                if st.form_submit_button("Log shift"):
                    ratio = round(m_present / needed, 2) if needed else 0
                    store.execute(
                        "INSERT OR REPLACE INTO fact_staffing_daily "
                        "(date, store_id, shift, pickers_needed, pickers_present, riders_on_shift, picker_staffing_ratio) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        [m_date.isoformat(), m_store, m_shift, needed, m_present, m_riders, ratio],
                    )
                    log_admin_action("manual_entry", "fact_staffing_daily", 1,
                                      f"{m_store} {m_date} {m_shift}")
                    refresh_after_write()
                    st.success(f"Logged {m_shift} shift for {m_store} on {m_date}.")
                    st.rerun()

            st.markdown("---")

            # --- Reset to baseline ---
            st.markdown("#### Reset to demo baseline")
            st.caption("Regenerates the original simulated dataset, discarding any uploads or manual entries.")
            reset_confirm = st.text_input("Type RESET to confirm", key="reset_confirm")
            if st.button("Reset to baseline", disabled=reset_confirm.strip() != "RESET"):
                reset_msg = "Regenerating baseline dataset in Turso (~60-90s)..." if USING_TURSO else "Regenerating baseline dataset..."
                with st.spinner(reset_msg):
                    result = subprocess.run(
                        [sys.executable, str(GENERATOR)], capture_output=True, text=True,
                        env=subprocess_env(),
                    )
                if result.returncode != 0:
                    st.error("Reset failed:")
                    st.code(result.stderr or result.stdout)
                else:
                    log_admin_action("reset_baseline", None, None, "Regenerated via Admin panel")
                    refresh_after_write()
                    st.success("Reset to baseline complete.")
                    st.rerun()

            st.markdown("---")
            st.markdown("#### Recent activity")
            if upload_log.empty:
                st.caption("No admin actions logged yet.")
            else:
                st.dataframe(upload_log, use_container_width=True, hide_index=True)

st.markdown("---")
st.caption("Built as a portfolio project for Blinkit's Associate Program Manager role · Data is fully synthetic/simulated.")
