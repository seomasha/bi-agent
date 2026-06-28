#!/usr/bin/env python3
"""
Build all Superset virtual datasets, metrics, charts, and dashboards
for the IT 501 BI Final Project via Superset REST API.
"""

import requests
import json
import sys

BASE = "http://localhost:8088"
DATABASE_ID = 2
LOG_FILE = "/Users/smasetic/it-501-bi-ai-project/superset_build.log"

log_lines = []

def log(msg):
    print(msg)
    log_lines.append(msg)

# ─── Auth ────────────────────────────────────────────────────────────────────

session = requests.Session()
r = session.post(f"{BASE}/api/v1/security/login", json={
    "username": "admin", "password": "admin",
    "provider": "db", "refresh": True
})
r.raise_for_status()
token = r.json()["access_token"]
session.headers.update({
    "Authorization": f"Bearer {token}",
    "Content-Type": "application/json"
})
csrf_r = session.get(f"{BASE}/api/v1/security/csrf_token/")
csrf_r.raise_for_status()
csrf = csrf_r.json()["result"]
session.headers.update({"X-CSRFToken": csrf, "Referer": BASE})
log("✓ Authenticated to Superset")

# ─── Helper ──────────────────────────────────────────────────────────────────

def post(path, payload):
    r = session.post(f"{BASE}{path}", json=payload)
    if r.status_code not in (200, 201):
        log(f"  ERROR {r.status_code}: {r.text[:300]}")
        return None
    return r.json()

def put(path, payload):
    r = session.put(f"{BASE}{path}", json=payload)
    if r.status_code not in (200, 201):
        log(f"  ERROR {r.status_code}: {r.text[:300]}")
        return None
    return r.json()

# ─── Step 1: Datasets ────────────────────────────────────────────────────────

DS1_SQL = """SELECT
    fo.order_line_key, fo.order_id, fo.row_id,
    fo.sales, fo.quantity, fo.discount, fo.profit, fo.revenue_after_discount,
    dd.full_date AS order_date, dd.year AS order_year, dd.quarter AS order_quarter,
    dd.month AS order_month, dd.month_name AS order_month_name,
    dc.customer_name, dc.segment,
    dg.city, dg.state, dg.region, dg.country,
    dp.product_name, dp.category, dp.sub_category,
    ds.ship_mode
FROM public.fact_orders fo
JOIN public.dim_date      dd ON fo.order_date_key = dd.date_key
JOIN public.dim_customer  dc ON fo.customer_key   = dc.customer_key
JOIN public.dim_geography dg ON fo.geography_key  = dg.geography_key
JOIN public.dim_product   dp ON fo.product_key    = dp.product_key
JOIN public.dim_ship_mode ds ON fo.ship_mode_key  = ds.ship_mode_key"""

DS2_SQL = """SELECT
    p.category, p.sub_category, fo.discount, fo.sales, fo.profit, fo.quantity,
    c.segment, g.region,
    CASE WHEN fo.discount = 0     THEN 'No Discount'
         WHEN fo.discount <= 0.20 THEN 'Moderate (1-20%)'
         ELSE 'Heavy (>20%)' END AS discount_tier
FROM public.fact_orders fo
JOIN public.dim_product   p ON fo.product_key   = p.product_key
JOIN public.dim_customer  c ON fo.customer_key  = c.customer_key
JOIN public.dim_geography g ON fo.geography_key = g.geography_key"""

log("\n=== Step 1: Creating Virtual Datasets ===")

ds1_resp = post("/api/v1/dataset/", {
    "database": DATABASE_ID,
    "schema": "public",
    "table_name": "vds_superstore_main",
    "sql": DS1_SQL,
    "is_managed_externally": False
})
if not ds1_resp:
    log("FATAL: Could not create DS1. Aborting.")
    sys.exit(1)
DS1_ID = ds1_resp["id"]
log(f"✓ DS-1 created: vds_superstore_main (id={DS1_ID})")

ds2_resp = post("/api/v1/dataset/", {
    "database": DATABASE_ID,
    "schema": "public",
    "table_name": "vds_superstore_discount",
    "sql": DS2_SQL,
    "is_managed_externally": False
})
if not ds2_resp:
    log("FATAL: Could not create DS2. Aborting.")
    sys.exit(1)
DS2_ID = ds2_resp["id"]
log(f"✓ DS-2 created: vds_superstore_discount (id={DS2_ID})")

# ─── Step 2: Metrics on DS-1 ─────────────────────────────────────────────────

log("\n=== Step 2: Adding Metrics to DS-1 ===")

metrics = [
    {"metric_name": "total_revenue",         "expression": "SUM(sales)",                                              "verbose_name": "Total Revenue",       "d3format": ",.2f"},
    {"metric_name": "total_profit",          "expression": "SUM(profit)",                                             "verbose_name": "Total Profit",        "d3format": ",.2f"},
    {"metric_name": "profit_margin_pct",     "expression": "SUM(profit) / NULLIF(SUM(sales), 0) * 100",              "verbose_name": "Profit Margin %",     "d3format": ",.1f"},
    {"metric_name": "total_quantity",        "expression": "SUM(quantity)",                                           "verbose_name": "Units Sold",          "d3format": ",.0f"},
    {"metric_name": "avg_order_value",       "expression": "SUM(sales) / NULLIF(COUNT(DISTINCT order_id), 0)",       "verbose_name": "Avg Order Value",     "d3format": ",.2f"},
    {"metric_name": "revenue_after_discount","expression": "SUM(revenue_after_discount)",                             "verbose_name": "Net Revenue",         "d3format": ",.2f"},
    {"metric_name": "total_discount_impact", "expression": "SUM(sales * discount)",                                   "verbose_name": "Discount Impact $",   "d3format": ",.2f"},
    {"metric_name": "order_count",           "expression": "COUNT(DISTINCT order_id)",                                "verbose_name": "Number of Orders",    "d3format": ",.0f"},
]

m_resp = put(f"/api/v1/dataset/{DS1_ID}", {"metrics": metrics})
if m_resp:
    log(f"✓ Metrics added to DS-1 ({len(metrics)} metrics)")
else:
    log("! Warning: metrics PUT failed — continuing anyway")

# ─── Step 3: Charts ──────────────────────────────────────────────────────────

log("\n=== Step 3: Creating Charts ===")

chart_ids = {}

def make_chart(name, viz_type, ds_id, params, fallback_params=None):
    payload = {
        "slice_name": name,
        "viz_type": viz_type,
        "datasource_id": ds_id,
        "datasource_type": "table",
        "params": json.dumps(params)
    }
    resp = post("/api/v1/chart/", payload)
    if resp is None and fallback_params is not None:
        log(f"  Retrying {name!r} with simplified params...")
        payload["params"] = json.dumps(fallback_params)
        resp = post("/api/v1/chart/", payload)
    if resp:
        cid = resp["id"]
        log(f"  ✓ Chart '{name}' created (id={cid})")
        return cid
    else:
        log(f"  ✗ Chart '{name}' FAILED")
        return None

# Dashboard 1 — Executive Overview

c1 = make_chart(
    "Total Revenue KPI", "big_number_total", DS1_ID,
    {"metric": "total_revenue", "subheader": "Gross Sales"}
)

c2 = make_chart(
    "Total Profit & Margin", "big_number_total", DS1_ID,
    {"metric": "total_profit", "subheader": "Overall Profit"}
)

c3 = make_chart(
    "Annual Revenue vs Profit Trend", "mixed_timeseries", DS1_ID,
    {
        "metrics": ["total_revenue"],
        "metrics_b": ["total_profit"],
        "groupby": [],
        "x_axis": "order_date",
        "granularity_sqla": "order_date",
        "time_grain_sqla": "P1Y"
    },
    fallback_params={
        "metrics": ["total_revenue"],
        "groupby": [],
        "granularity_sqla": "order_date",
        "time_grain_sqla": "P1Y"
    }
)

c4 = make_chart(
    "Revenue by Region", "pie", DS1_ID,
    {"metric": "total_revenue", "groupby": ["region"]}
)

c5 = make_chart(
    "Revenue & Profit by Category", "bar", DS1_ID,
    {"metrics": ["total_revenue", "total_profit"], "groupby": ["category"]}
)

# Dashboard 2 — Detailed Operations

c6 = make_chart(
    "Top 10 Customers by Profit", "bar", DS1_ID,
    {
        "metrics": ["total_profit"],
        "groupby": ["customer_name"],
        "row_limit": 10,
        "order_desc": True,
        "orientation": "horizontal"
    },
    fallback_params={"metrics": ["total_profit"], "groupby": ["customer_name"], "row_limit": 10}
)

c7 = make_chart(
    "Quarterly Revenue by Segment", "line", DS1_ID,
    {
        "metrics": ["total_revenue"],
        "groupby": ["segment"],
        "x_axis": "order_date",
        "granularity_sqla": "order_date",
        "time_grain_sqla": "P3M"
    },
    fallback_params={
        "metrics": ["total_revenue"],
        "groupby": ["segment"],
        "granularity_sqla": "order_date",
        "time_grain_sqla": "P3M"
    }
)

c8 = make_chart(
    "Shipping Mode Performance", "table", DS1_ID,
    {
        "metrics": ["order_count", "total_revenue", "total_profit", "avg_order_value"],
        "groupby": ["ship_mode"],
        "order_desc": True
    }
)

c9 = make_chart(
    "Discount vs Margin by Sub-Category", "bubble_v2", DS2_ID,
    {
        "entity": "sub_category",
        "x": {"expressionType": "SIMPLE", "aggregate": "AVG", "column": {"column_name": "discount"}},
        "y": {"expressionType": "SIMPLE", "aggregate": "SUM", "column": {"column_name": "profit"}},
        "size": {"expressionType": "SIMPLE", "aggregate": "SUM", "column": {"column_name": "sales"}},
        "series": "category"
    },
    fallback_params={
        "metrics": [{"expressionType": "SIMPLE", "aggregate": "SUM", "column": {"column_name": "profit"}, "label": "Profit"}],
        "groupby": ["sub_category", "category"]
    }
)

c10 = make_chart(
    "Discount Tier Profitability", "bar", DS2_ID,
    {
        "metrics": [{"expressionType": "SIMPLE", "aggregate": "SUM", "column": {"column_name": "profit"}, "label": "Total Profit"}],
        "groupby": ["discount_tier", "segment"]
    }
)

# Dashboard 3 — Anomaly Alerts

c11 = make_chart(
    "Loss-Making States Table", "table", DS1_ID,
    {
        "metrics": ["total_revenue", "total_profit", "order_count"],
        "groupby": ["state", "region"],
        "order_desc": False,
        "row_limit": 50
    }
)

c12 = make_chart(
    "Sub-Category Profit Margin Ranking", "bar", DS2_ID,
    {
        "metrics": [{"expressionType": "SIMPLE", "aggregate": "SUM", "column": {"column_name": "profit"}, "label": "Profit"}],
        "groupby": ["sub_category"],
        "order_desc": False
    }
)

c13 = make_chart(
    "Heavy Discount Damage by Region", "bar", DS2_ID,
    {
        "metrics": [{"expressionType": "SIMPLE", "aggregate": "SUM", "column": {"column_name": "profit"}, "label": "Total Profit"}],
        "groupby": ["region"],
        "adhoc_filters": [{
            "expressionType": "SIMPLE",
            "subject": "discount_tier",
            "operator": "==",
            "comparator": "Heavy (>20%)",
            "clause": "WHERE"
        }]
    },
    fallback_params={
        "metrics": [{"expressionType": "SIMPLE", "aggregate": "SUM", "column": {"column_name": "profit"}, "label": "Total Profit"}],
        "groupby": ["region"]
    }
)

c14 = make_chart(
    "Profit by State", "table", DS1_ID,
    {
        "metrics": ["total_profit", "total_revenue", "order_count"],
        "groupby": ["state"],
        "order_desc": False
    }
)

c15 = make_chart(
    "Revenue & Profit by Sub-Category", "bar", DS1_ID,
    {
        "metrics": ["total_revenue", "total_profit"],
        "groupby": ["sub_category"],
        "order_desc": True
    }
)

charts_d1 = [c for c in [c1, c2, c3, c4, c5] if c]
charts_d2 = [c for c in [c6, c7, c8, c9, c10] if c]
charts_d3 = [c for c in [c11, c12, c13, c14, c15] if c]

# ─── Step 4: Dashboards ──────────────────────────────────────────────────────

log("\n=== Step 4: Creating Dashboards ===")

def build_position_json(chart_ids):
    """Build a simple grid layout for the given chart IDs."""
    COLS = 12
    CHART_W = 6
    CHART_H = 50
    positions = {
        "DASHBOARD_VERSION_KEY": "v2",
        "ROOT_ID": {"type": "ROOT", "id": "ROOT_ID", "children": ["GRID_ID"]},
        "GRID_ID": {"type": "GRID", "id": "GRID_ID", "children": [], "parents": ["ROOT_ID"]}
    }
    row_ids = []
    for i, cid in enumerate(chart_ids):
        col = i % 2
        row = i // 2
        row_id = f"ROW-{row}"
        if row_id not in positions:
            positions[row_id] = {"type": "ROW", "id": row_id, "children": [], "parents": ["GRID_ID"]}
            row_ids.append(row_id)
        chart_key = f"CHART-{cid}"
        positions[chart_key] = {
            "type": "CHART",
            "id": chart_key,
            "children": [],
            "parents": ["GRID_ID", row_id],
            "meta": {
                "chartId": cid,
                "width": CHART_W,
                "height": CHART_H
            }
        }
        positions[row_id]["children"].append(chart_key)
    positions["GRID_ID"]["children"] = row_ids
    return json.dumps(positions)

dashboards = [
    {
        "title": "Executive Overview",
        "slug": "executive-overview",
        "charts": charts_d1
    },
    {
        "title": "Detailed Operations",
        "slug": "detailed-operations",
        "charts": charts_d2
    },
    {
        "title": "Anomaly Alerts",
        "slug": "anomaly-alerts",
        "charts": charts_d3
    }
]

dashboard_urls = []

for db_spec in dashboards:
    db_resp = post("/api/v1/dashboard/", {
        "dashboard_title": db_spec["title"],
        "published": True,
        "slug": db_spec["slug"]
    })
    if not db_resp:
        log(f"  ✗ Dashboard '{db_spec['title']}' FAILED")
        continue
    db_id = db_resp["id"]
    log(f"  ✓ Dashboard '{db_spec['title']}' created (id={db_id})")

    # Assign charts via position_json
    if db_spec["charts"]:
        pos_json = build_position_json(db_spec["charts"])
        upd_resp = put(f"/api/v1/dashboard/{db_id}", {
            "position_json": pos_json,
            "published": True
        })
        if upd_resp:
            log(f"    ✓ Charts laid out: {db_spec['charts']}")
        else:
            log(f"    ! Warning: layout update failed for '{db_spec['title']}'")

    url = f"{BASE}/superset/dashboard/{db_spec['slug']}/"
    dashboard_urls.append(f"  {db_spec['title']}: {url}")
    log(f"    URL: {url}")

# ─── Write log ───────────────────────────────────────────────────────────────

log("\n=== Summary ===")
log(f"Datasets: DS-1 id={DS1_ID}, DS-2 id={DS2_ID}")
log(f"Charts created: d1={charts_d1}, d2={charts_d2}, d3={charts_d3}")
log("\nDashboard URLs:")
for u in dashboard_urls:
    log(u)

with open(LOG_FILE, "w") as f:
    f.write("\n".join(log_lines) + "\n")

print(f"\nLog saved to {LOG_FILE}")
