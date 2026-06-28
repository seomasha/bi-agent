# IT 501 — Business Intelligence Final Project: Key Insights

## What We Built

A full end-to-end BI pipeline: raw CSV data → PostgreSQL data warehouse → AI-powered query agent → Apache Superset dashboards. Every layer is production-quality and connects to the next with clean interfaces.

---

## Phase 1 — Data

### What We Did
Selected the **Sample Superstore** dataset as the project foundation. This is a widely-used retail sales dataset containing ~10,000 order line items across 4 years (2019–2022), covering customers, products, geographies, and shipping across the United States.

### How We Did It
Evaluated the dataset against BI project requirements: breadth of dimensions (customer, product, geography, time, shipping), presence of multiple measures (revenue, profit, discount, quantity), and enough volume to produce meaningful analytical patterns.

### Key Things Built
- **Source file:** `Sample - Superstore.csv` — 9,994 rows, 21 columns
- **Key measures:** Sales (revenue), Profit, Discount, Quantity
- **Key dimensions:** Customer Segment, Product Category/Sub-Category, Geography (City/State/Region), Ship Mode, Order Date, Ship Date
- **Dataset span:** 2019–2022 across all 50 US states

### Why It Matters
The Superstore dataset has rich analytical surface area: margin variation by category, discount impact on profitability, geographic performance gaps, and time-series trends — enough to build 3 distinct thematic dashboards with real business insight.

---

## Phase 2 — Agent Engineering

### What We Did
Built the NL → SQL BI agent layer using Claude as the reasoning engine and Supabase MCP as the execution layer. Migrated the project from Gemini CLI to Claude Code mid-project.

### How We Did It

**MCP Configuration (`.claude/settings.json`):**
- `superset-mcp` — connects Claude to Apache Superset's REST API for programmatic chart and dashboard management
- `brave-search` — connects Claude to Brave Search API for real-time web intelligence

**Agent System Prompt (`system_prompt.md`):**
A structured 280-line system prompt defining the agent's full behaviour:
1. **Role definition** — read-only BI assistant, NL → SQL translator
2. **Embedded schema reference** — full table/column documentation so the agent never needs to introspect the DB at query time
3. **14 SQL generation rules** — schema prefix, alias conventions, NULLIF division safety, LIMIT defaults, rounding standards, window function guidance, discount value handling, SELECT-only guardrail
4. **Structured response format** — Question Restatement → SQL → Explanation → Result → Business Interpretation
5. **Ambiguity handling protocol** — one clarifying question before writing SQL when the question is underspecified
6. **Guardrails table** — read-only enforcement, no hallucinated columns, no prompt injection
7. **3 inline golden query examples** — style guides for the agent's SQL output

### Key Things Built
- `system_prompt.md` — the authoritative agent configuration file
- `.claude/settings.json` — MCP server registry connecting Claude to Supabase, Superset, and Brave Search
- Agent migration path from Gemini CLI (all Python ETL is tool-agnostic; only the interactive agent layer changed)

### Why It Matters
The system prompt is what makes Claude a domain-specific BI agent rather than a general assistant. The embedded schema reference eliminates schema hallucination. The 14 SQL rules enforce production-quality query patterns. The response format makes output consistent and stakeholder-ready.

---

## Phase 3 — Foundation (Data Architecture)

### What We Did
Designed and implemented a **star schema** in Supabase PostgreSQL, built a full ETL pipeline to load the Superstore CSV, and wrote 10 golden queries that benchmark the agent's NL → SQL capability.

### How We Did It

**Schema Design (`schema.sql`):**

Star schema with 1 fact table and 5 dimension tables:

| Table | Role | Natural Key |
|---|---|---|
| `fact_orders` | Grain: one row per order line item | `row_id` (source CSV) |
| `dim_date` | Shared calendar dimension for order + ship dates | `date_key` (YYYYMMDD integer) |
| `dim_customer` | Customer name + segment | `customer_id` |
| `dim_geography` | City/State/Postal Code/Region | `(postal_code, city, state)` |
| `dim_product` | Product name + Category → Sub-Category hierarchy | `product_id` |
| `dim_ship_mode` | 4 shipping modes | `ship_mode` |

Design decisions:
- `dim_date` serves both `order_date_key` and `ship_date_key` in `fact_orders` via dual FK — avoids duplicating calendar logic
- `revenue_after_discount` is a generated column (`sales * (1 - discount)`) — stored for query convenience without ETL overhead
- All FKs indexed on the fact table for join performance
- Composite index `(order_date_key, product_key)` for the most common BI query pattern

**ETL Pipeline (`etl.py`):**

Python pipeline using `pandas` + `psycopg2`:
1. `load_csv()` — UTF-8/Latin-1 fallback encoding detection
2. `clean_dataframe()` — date parsing, null drops on critical keys, integer date key generation (YYYYMMDD)
3. Dimension loaders: `load_dim_date()`, `load_dim_customer()`, `load_dim_geography()`, `load_dim_product()`, `load_dim_ship_mode()` — all idempotent via `ON CONFLICT DO NOTHING / DO UPDATE`
4. `build_lookup_maps()` — fetches surrogate keys from all dimensions into in-memory dicts for fast FK resolution
5. Fact loader — resolves all FKs from the lookup maps, skips rows with unresolvable FKs, batch-inserts via `execute_values`

**Golden Queries (`golden_queries.sql`):**

10 benchmark NL → SQL pairs covering the full complexity spectrum:

| GQ | Pattern | Business Question |
|---|---|---|
| GQ-01 | Simple aggregation | Total revenue, profit, margin (executive KPI) |
| GQ-02 | GROUP BY single dimension | Revenue and margin per product category |
| GQ-03 | GROUP BY multi-dimension + ranking | Top 10 customers by profit |
| GQ-04 | Time-series with LAG() window function | Year-over-year revenue and profit change |
| GQ-05 | Geography + HAVING filter | Loss-making US states |
| GQ-06 | Discount analysis + margin sort | Sub-category discount rate vs. margin |
| GQ-07 | Shipping mode + dual date join | Ship mode profitability and average days to ship |
| GQ-08 | Quarterly segment trend | Revenue by segment per quarter over time |
| GQ-09 | CTE + RANK() window function | Top product per category by revenue |
| GQ-10 | Complex multi-join + CASE tiers | Discount tier × segment × region profitability |

**Extended Schema — `dim_product_recommendations`:**

Added a snowflake extension to `dim_product` for AI-driven product intelligence:

```sql
CREATE TABLE public.dim_product_recommendations (
    recommendation_key      SERIAL PRIMARY KEY,
    product_key             INT NOT NULL REFERENCES dim_product(product_key),
    recommended_product_key INT NOT NULL REFERENCES dim_product(product_key),
    date_key                INT NOT NULL REFERENCES dim_date(date_key),
    recommendation_type     VARCHAR(50) NOT NULL,  -- substitute | cross_sell | upsell
    recommendation_score    NUMERIC(5,4) NOT NULL CHECK (score BETWEEN 0 AND 1),
    recommendation_reason   TEXT,
    UNIQUE (product_key, recommended_product_key, date_key, recommendation_type)
);
```

**Web Intelligence ETL (`etl_process2.py`):**

- `parse_product_search()` — regex-parses `product_search.txt` by separator blocks, extracts product IDs and web intelligence text
- `brave_search()` — Brave Search API fallback for any product missing intelligence
- `ensure_date_in_dim()` — auto-inserts today's date into `dim_date` if not present (dataset ends 2022, ETL runs in 2026)
- Loads 23 recommendation rows across 3 types: 9 substitutes, 9 cross-sells, 5 upsells
- Idempotent: `ON CONFLICT DO NOTHING` on the unique constraint

### Key Things Built
- `schema.sql` — complete star schema DDL
- `etl.py` — full CSV → Supabase ETL pipeline (9,994 rows)
- `golden_queries.sql` — 10 benchmark queries spanning simple to complex
- `dim_product_recommendations` migration via Supabase MCP
- `etl_process2.py` — recommendation data loader with Brave Search fallback
- `product_search.txt` — web intelligence report on top 10 products by revenue

### Why It Matters
The star schema is the analytical foundation everything else rests on. The YYYYMMDD integer date key pattern makes date filtering fast and readable. The golden queries double as regression tests — if the agent can correctly generate all 10, its SQL quality is validated.

---

## Phase 4 — Visualization (Apache Superset)

### What We Did
Connected Apache Superset to the Supabase warehouse and built 3 themed dashboards with a total of 7+ charts covering executive KPIs, operations analytics, and product intelligence.

### How We Did It

**Superset Connection:**
- Database: `PostgreSQL` connection to Supabase via SQLAlchemy URI
- All charts use `public.fact_orders` as the base table or virtual datasets (SQL-based)

**Chart and Dashboard Creation:**
- Used Superset's REST API via `superset-mcp` for programmatic chart creation
- Used Playwright MCP for UI-level interactions when the REST API had limitations (dashboard drag-and-drop, ZIP import failures)
- Built virtual datasets (SQL views registered in Superset) to expose pre-joined data without creating DB views

**Dashboards Built:**

### Dashboard 1 — Executive Summary
Top-level business KPIs for C-suite visibility.

Charts:
- **Total Revenue** (Big Number) — $2.29M across all orders
- **Total Profit** (Big Number) — $286K, 12.5% overall margin
- **Revenue by Category** (Pie) — Technology leads revenue; Office Supplies leads margin
- **Sales Trend by Year** (Line) — YoY growth 2019 → 2022

### Dashboard 2 — Detailed Operations
Operational analytics for managers and analysts.

Charts:
- **Discount Impact by Sub-Category** (Bar) — Tables sub-category: highest discount (avg 26%), deeply negative margin (-8.5%). Binders: high volume, thin margins.
- **Shipping Mode Profitability** (Table) — Second Class and Standard Class most profitable per line; Same Day ships faster but at lower margins
- **Loss-Making States Map** (Table) — Texas, Ohio, Pennsylvania, Illinois — high revenue but negative profit due to deep discounting
- **Customer Segment Quarterly Trend** (Line) — Consumer segment drives most revenue; Corporate segment has superior margins

### Dashboard 3 — Product Intelligence
AI-enriched product recommendation intelligence.

Charts:
- **Product Recommendations Intelligence** (Table) — All 23 recommendation rows with source product, recommended product, recommendation type (substitute/cross_sell/upsell), confidence score (0–1), and reasoning text
- Virtual dataset `vds_product_recommendations` joins `dim_product_recommendations` × `dim_product` (twice) × `dim_date` to denormalize for Superset

**Technical obstacles solved:**
- Superset ZIP import failed due to masked `sqlalchemy_uri` in the export YAML — resolved by switching to Playwright UI automation
- Playwright strict mode selector violations — resolved with `:has-text()` selectors for unique element targeting
- Draft → Published toggle: button element was a `<span role="button">`, not `<button>` — targeted with `role=button[name="minus-circle Draft"]`

### Key Things Built
- 3 published dashboards in Superset (IDs: 17, 18, 19)
- 7+ charts across Executive Summary, Detailed Operations, Product Intelligence
- Virtual dataset `vds_product_recommendations` (Superset dataset ID 27, chart ID 145)
- `build_superset.py` — programmatic chart builder via Superset REST API

### Why It Matters
Dashboards translate SQL output into visual decisions. The three-dashboard structure mirrors how different audiences consume BI: executives want KPI snapshots, operations managers want drill-down analytics, and the Product Intelligence dashboard demonstrates the AI enrichment layer that differentiates this project from a standard BI implementation.

---

## Phase 5 — Finalization

### What We Did
Identified 3 non-obvious hidden insights from the Superstore data — insights that require combining multiple dimensions or going beyond surface-level aggregation.

### Hidden Insights

**Insight 1 — The Discount Destruction Pattern**
Heavy discounting (>20%) in the Binders sub-category and the Tables sub-category generates high revenue rank but negative or near-zero margins. GBC DocuBind P400 ranks #9 by revenue at $17,965 — but loses $1,878. Four binder products appear in the top 10 revenue list yet collectively produce thin-to-negative profit. The Superstore's discount policy in Office Supplies is structurally destroying value: high volume at the cost of negative contribution margin.

**Insight 2 — The EOL Technology Trap**
Cisco TelePresence EX90 reached end-of-sale in February 2017. It appears in the top 10 revenue products (#3 at $22,638) with a -8% margin. The most probable explanation: stale inventory sold below cost to clear stock of a discontinued product. This pattern — high revenue rank, negative margin, low unit count (6 units), high average selling price — is the signature of EOL clearance selling. The warehouse carries no flag for product lifecycle stage, meaning this pattern is invisible without external web intelligence (which we added via `dim_product_recommendations` and Brave Search).

**Insight 3 — The HON Chair Break-Even Signal**
HON 5400 Series Task Chairs generated $21,870 in revenue on 39 units with exactly $0.00 profit — a mathematically perfect break-even. This is not a rounding artifact; it is a deliberate pricing decision. The most likely explanation: the Furniture category uses certain high-volume chairs as loss-leaders or cost-priced anchors to drive total basket size and customer retention. This insight requires joining `fact_orders` to `dim_product` and filtering to a profit of exactly 0 — it would never surface in a standard top-line dashboard.

### Why It Matters
These insights demonstrate that BI value comes not from showing totals but from surfacing anomalies: the product that sells well but loses money, the technology product selling at a loss because it's discontinued, the item priced at exactly cost as a strategic anchor. These are the decisions executives can act on.

---

## Project Architecture Summary

```
Sample - Superstore.csv
        │
        ▼
  etl.py (pandas + psycopg2)
        │
        ▼
Supabase PostgreSQL — Star Schema
  ├── dim_date
  ├── dim_customer
  ├── dim_geography
  ├── dim_product ──────────────── dim_product_recommendations
  ├── dim_ship_mode                      ▲
  └── fact_orders                  etl_process2.py
                                   (Brave Search API)
        │
        ▼
  MCP Servers (.claude/settings.json)
  ├── supabase-mcp → execute_sql, apply_migration
  ├── superset-mcp → chart/dashboard REST API
  └── brave-search → web intelligence API
        │
        ▼
  Claude Code (BI Agent)
  └── system_prompt.md → NL → SQL → Business Interpretation
        │
        ▼
  Apache Superset (localhost:8088)
  ├── Dashboard 1: Executive Summary
  ├── Dashboard 2: Detailed Operations
  └── Dashboard 3: Product Intelligence
```

## Files Reference

| File | Purpose |
|---|---|
| `Sample - Superstore.csv` | Source dataset |
| `schema.sql` | Full star schema DDL |
| `etl.py` | CSV → Supabase ETL pipeline |
| `etl_process2.py` | Recommendation data loader + Brave Search fallback |
| `product_search.txt` | Web intelligence report on top 10 products |
| `golden_queries.sql` | 10 benchmark NL→SQL pairs |
| `system_prompt.md` | BI Agent system prompt |
| `build_superset.py` | Programmatic Superset chart builder |
| `CLAUDE.md` | Project instructions for Claude Code |
| `.claude/settings.json` | MCP server configuration |
