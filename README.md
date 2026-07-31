# Blinkit Ops Intelligence

A cross-domain operational analytics case study — built as a portfolio project for Blinkit's
**Associate Program Manager** role (Supply Chain & Replenishment, Store Operations, Last Mile
Operations).

Simulates 60 days of dark-store operations across 12 stores in 2 cities (~75K orders, ~69K
inventory-days, ~7K replenishment orders), then runs SQL-based root-cause analysis to find and
quantify three operational problems that a network-average KPI hides — and one that only shows up
when you look across all three domains at once.

**Live dashboard:** [blinkit-apm-case-study.streamlit.app](https://blinkit-apm-case-study.streamlit.app)

**Start here:** [`case_study/Blinkit_Ops_Case_Study.md`](case_study/Blinkit_Ops_Case_Study.md) —
the full write-up, findings, and how to use this for your application.

## Quickstart

Just want to explore it? Use the [live dashboard](https://blinkit-apm-case-study.streamlit.app) —
no setup required (first load takes ~15s while it generates the dataset).

To run it locally instead:

```bash
pip install -r requirements.txt
python data/generate_data.py       # generates data/*.csv and db/blinkit_ops.db
streamlit run dashboard/app.py     # interactive dashboard at localhost:8501
```

To use the Admin panel (spreadsheet upload, manual entry, business assumptions), set an admin
password before launching — locally via `.streamlit/secrets.toml`:

```toml
admin_password = "choose-something"
```

On Streamlit Community Cloud: App settings → Secrets, same key. Without it configured, the Admin
tab shows setup instructions instead of a login form.

## Structure

```
data/generate_data.py        Synthetic data generator (reorder-point inventory simulation +
                              order-funnel time simulation). Root causes are structural, not
                              hard-coded onto rows. Writes to Turso if configured, else local SQLite.
db_store.py                   Data-access layer: uniform read_sql/execute/write_df interface over
                              either backend -- see "Persistent storage" below.
db/blinkit_ops.db             Local SQLite database (generated, used when Turso isn't configured)
sql/01_schema.sql             Table definitions (incl. business_assumptions, upload_log)
sql/02_supply_chain_kpis.sql  Fill rate, stockout rate, lead-time RCA
sql/03_store_ops_kpis.sql     SLA adherence, picker + rider staffing-ratio RCA
sql/04_last_mile_kpis.sql     Delivery time, zone/rain/rider-load RCA
sql/05_cross_domain_rca.sql   Composite store-level risk score across all 3 domains
sql/06_new_metrics.sql        Perfect Order Rate, Days of Cover, Rider Utilization, Cost-to-Serve
sql/07_safety_stock_policy.sql  Variability-adjusted safety-stock formula vs. current flat buffer
sql/08_fix_roi.sql            Cost/payback of the two headline fixes -- staffing gap and warehouse remap
sql/09_case_fill_rate.sql     Warehouse case-fill rate -- a second reliability dimension beyond lead time
sql/10_fleet_cost_efficiency.sql  Fleet running cost by vehicle type (EV/petrol/bicycle) and store
sql/11_contribution_margin.sql  Revenue x Cost-to-Serve -- net contribution margin per order, by store
sql/12_order_failures.sql     Cancellation/return/refund RCA -- tied to understaffing, SLA breach, rain
sql/13_abc_xyz_segmentation.sql  True value x variability SKU segmentation vs. the binary Z-factor policy
dashboard/app.py              Streamlit + Plotly dashboard (7 tabs, incl. Admin)
analysis/*.md                 Per-domain RCA write-ups (problem → investigation → root cause →
                               recommendation → projected impact)
case_study/Blinkit_Ops_Case_Study.md   Top-level summary + resume/interview guidance
```

## Admin panel

A password-gated tab (`🔐 Admin`) that turns this from a read-only demo into an actual
data-ingestion tool:

- **Spreadsheet upload** — CSV/XLSX per table, validated against the real schema (missing columns,
  bad booleans, non-numeric values all rejected with specific errors) before commit, append or
  replace mode
- **Manual entry** — log a single staffing shift without a file
- **Business assumptions** — editable picker/rider hourly wage inputs, feeding the Cost-to-Serve metric
- **Audit log** — every upload/edit/reset recorded with timestamp and row count
- **Reset to baseline** — regenerates the original demo dataset on demand

**Persistence:** with no external database configured, this runs on local SQLite — uploads survive
as long as the app instance keeps running, but a reboot or redeploy on Streamlit Community Cloud's
free tier (no persistent disk) resets to the generated baseline. With Turso configured (see below),
every upload/edit persists permanently, including across reboots and redeploys.

## Persistent storage (optional): Turso

By default this runs on local SQLite, which is why the caveat above exists. To make Admin-panel
changes actually permanent, connect it to a free [Turso](https://turso.tech) database instead —
no code changes needed, just two secrets:

1. Create a free account at [turso.tech](https://turso.tech) and a database:
   ```bash
   turso db create blinkit-ops
   turso db show blinkit-ops --url
   turso db tokens create blinkit-ops
   ```
2. Add both values to secrets — locally in `.streamlit/secrets.toml`, and on Streamlit Cloud under
   App settings → Secrets:
   ```toml
   turso_url = "libsql://blinkit-ops-yourname.turso.io"
   turso_auth_token = "..."
   ```
3. That's it. On next boot, [`data/generate_data.py`](data/generate_data.py) and
   [`dashboard/app.py`](dashboard/app.py) both detect the secrets automatically and target Turso
   instead of local SQLite — the entire app, including the Admin panel's uploads, edits, and
   audit log, now persists permanently.

**Why HTTP instead of Turso's native Python client:** `libsql-experimental` (the native client's
underlying binding) ships no prebuilt wheels for any platform — installing it means compiling a
Rust extension locally, which needs a full Rust+MSVC toolchain and isn't guaranteed to succeed in
Streamlit Cloud's build step either. [`db_store.py`](db_store.py) instead talks to Turso's HTTP
"pipeline" API (Hrana-over-HTTP) directly via `requests`, which has zero compiled dependencies and
behaves identically on every platform. Bulk loads batch up to 1,000 rows per SQL statement (~20,000
placeholders, empirically verified safe) and up to 5 statements per HTTP round trip, so the initial
~155K-row load takes roughly a minute rather than hundreds of individual round trips.

## Dataset design

12 dark stores across Delhi and Bangalore, 4 zones each, sized Small/Medium/Large. Three
warehouses (2 in Delhi — one 1-day lead time, one 3-day; 1 in Bangalore). Three problems are
embedded structurally in the generation logic and have to be *found* through analysis, not
verified against a known answer:

1. **3 stores** are mapped to the slow (3-day) Delhi warehouse → higher stockout risk on
   fast-moving SKUs.
2. **3 stores** run chronically understaffed evening shifts (50–72% of needed pickers/riders) →
   SLA breaches concentrated in the 7–9pm peak.
3. **East-zone stores** in both cities sit furthest from customers → structurally longer delivery
   times, independent of staffing — but two of the three East Delhi stores also carry the
   staffing problem, so the effects compound.

See [`data/generate_data.py`](data/generate_data.py) for the full generation logic.

## Notes

- Data is fully synthetic and generated for this project only — no connection to Blinkit's actual
  operations or systems.
- `streamlit` and `python` may resolve to different installations on a given machine if multiple
  Python versions are present. If `streamlit run` fails with `ModuleNotFoundError`, run it as
  `python -m streamlit run dashboard/app.py` using the interpreter that has `requirements.txt`
  installed.
