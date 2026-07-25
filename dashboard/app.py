"""
Blinkit Ops Intelligence Dashboard
Run: streamlit run dashboard/app.py
"""

import os
import subprocess
import sys
import time
import sqlite3
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "db" / "blinkit_ops.db"
GENERATOR = ROOT / "data" / "generate_data.py"
LOCK_PATH = ROOT / "db" / ".generating.lock"

st.set_page_config(page_title="Blinkit Ops Intelligence", page_icon="📦", layout="wide")

PROBLEM_STORES = {"DEL-E-01", "DEL-E-02", "BLR-S-02", "DEL-S-02"}

# The generated DB/CSVs are gitignored (they're fully reproducible), so a fresh
# clone -- e.g. a Streamlit Community Cloud deploy -- won't have them yet.
# Bootstrap on first boot rather than requiring a manual pre-run step.
#
# A hosting platform can spin up more than one worker before any of them see
# the DB file exist, so an exclusive lock file (atomic create-or-fail) makes
# only one process actually run the generator; the rest just wait for it to
# finish. generate_data.py also writes atomically on its own, so even if this
# lock were somehow lost, concurrent runs still can't corrupt the output --
# this just avoids wasted duplicate work.
if not DB_PATH.exists():
    DB_PATH.parent.mkdir(exist_ok=True)
    try:
        lock_fd = os.open(LOCK_PATH, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(lock_fd)
        got_lock = True
    except FileExistsError:
        got_lock = False

    if got_lock:
        with st.spinner("First run: generating the simulated 60-day ops dataset (~15s)..."):
            result = subprocess.run(
                [sys.executable, str(GENERATOR)], capture_output=True, text=True
            )
            LOCK_PATH.unlink(missing_ok=True)
            if result.returncode != 0:
                st.error("Data generation failed:")
                st.code(result.stderr or result.stdout)
                st.stop()
    else:
        with st.spinner("Another session is generating the dataset, waiting..."):
            for _ in range(60):
                if DB_PATH.exists():
                    break
                time.sleep(1)
            else:
                st.error("Timed out waiting for the dataset to be generated.")
                st.stop()


@st.cache_data
def load_data():
    conn = sqlite3.connect(DB_PATH)
    stores = pd.read_sql("SELECT * FROM dim_stores", conn)
    warehouses = pd.read_sql("SELECT * FROM dim_warehouses", conn)
    skus = pd.read_sql("SELECT * FROM dim_skus", conn)
    inventory = pd.read_sql(
        "SELECT * FROM fact_inventory_daily", conn, parse_dates=["date"]
    )
    replenishment = pd.read_sql(
        "SELECT * FROM fact_replenishment", conn, parse_dates=["order_date", "received_date"]
    )
    staffing = pd.read_sql("SELECT * FROM fact_staffing_daily", conn, parse_dates=["date"])
    orders = pd.read_sql(
        "SELECT * FROM fact_orders", conn, parse_dates=["date", "order_time"]
    )
    conn.close()

    inventory = inventory.merge(stores, on="store_id").merge(
        skus[["sku_id", "category", "is_fast_moving", "unit_cost"]], on="sku_id"
    )
    orders = orders.merge(stores, on="store_id")
    replenishment = replenishment.merge(stores[["store_id", "zone", "city"]], on="store_id")
    staffing = staffing.merge(stores[["store_id", "zone", "city", "chronic_understaffed"]], on="store_id")
    return stores, warehouses, skus, inventory, replenishment, staffing, orders


stores, warehouses, skus, inventory, replenishment, staffing, orders = load_data()

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

tab_overview, tab_supply, tab_store_ops, tab_last_mile, tab_rca = st.tabs(
    ["🏠 Overview", "📦 Supply Chain", "🏬 Store Operations", "🛵 Last Mile", "🔎 Cross-Domain RCA"]
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
st.caption("Built as a portfolio project for Blinkit's Associate Program Manager role · Data is fully synthetic/simulated.")
