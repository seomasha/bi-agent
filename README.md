# IT 501 — AI-Powered Business Intelligence Pipeline

A full end-to-end BI pipeline built on the **Sample Superstore** dataset. Raw CSV data flows through a Python ETL pipeline into a Supabase PostgreSQL star schema, where a Claude-powered AI agent translates natural-language business questions into precise SQL queries and returns plain-English business interpretations. Apache Superset provides the visualization layer.

## Pipeline

```
Sample - Superstore.csv
        ↓  etl.py (pandas + psycopg2)
Supabase PostgreSQL — Star Schema
        ↓  Supabase MCP Server
Claude BI Agent (NL → SQL)
        ↓
Apache Superset — Dashboards
```

## Tech Stack

| Layer | Tool |
|---|---|
| Dataset | Sample Superstore (Kaggle, 9,994 rows) |
| Database | Supabase PostgreSQL |
| ETL | Python 3 — pandas + psycopg2 |
| AI Agent | Claude Code (claude-sonnet-4-6) |
| Schema exposure | Supabase MCP Server |
| Web enrichment | Brave Search MCP |
| Dashboards | Apache Superset |

## Schema

Star schema with 1 fact table and 5 dimension tables, plus a snowflake extension for AI-enriched product recommendations.

| Table | Role |
|---|---|
| `fact_orders` | One row per order line item |
| `dim_date` | Shared calendar dimension (order + ship dates) |
| `dim_customer` | Customer name and segment |
| `dim_geography` | City / State / Region |
| `dim_product` | Product + Category → Sub-Category |
| `dim_ship_mode` | 4 shipping modes |
| `dim_product_recommendations` | AI-enriched product intelligence (Brave Search) |

Full DDL: [`schema.sql`](schema.sql)

## Setup

### Prerequisites

- Python 3.10+
- Supabase project with PostgreSQL
- Apache Superset running locally
- Claude Code with Supabase MCP configured

### Environment Variables

Create a `.env` file in the project root:

```env
POSTGRES_HOST=aws-0-eu-west-1.pooler.supabase.com
POSTGRES_PORT=6543
POSTGRES_USER=postgres.<your-project-ref>
POSTGRES_PASSWORD=<your-password>
POSTGRES_DATABASE=postgres
BRAVE_API_KEY=<your-brave-api-key>
```

### Run the ETL

```bash
python3 -m venv venv && source venv/bin/activate
pip install pandas psycopg2-binary python-dotenv requests

# Load the star schema
python3 etl.py

# Load AI-enriched product recommendations
python3 etl_process2.py
```

### MCP Configuration

The `.claude/settings.json` file registers three MCP servers:

- **supabase-mcp** — executes SQL queries and schema migrations against the warehouse
- **superset-mcp** — manages Superset charts and dashboards via REST API
- **brave-search** — real-time web intelligence for product enrichment

Set `BRAVE_API_KEY` in the env block of `.claude/settings.json` before use.

### Activate the BI Agent

Paste the contents of [`system_prompt.md`](system_prompt.md) as the system prompt in Claude Code. The agent will:

1. Parse your natural-language question
2. Identify the relevant tables and columns from the embedded schema reference
3. Generate a valid PostgreSQL query
4. Execute it via the Supabase MCP server
5. Return the result with a plain-English business interpretation

## Key Files

| File | Purpose |
|---|---|
| `schema.sql` | Full star schema DDL |
| `etl.py` | CSV → Supabase ETL pipeline |
| `etl_process2.py` | Product recommendation loader + Brave Search fallback |
| `golden_queries.sql` | 10 benchmark NL→SQL pairs (simple to complex) |
| `system_prompt.md` | BI Agent system prompt |
| `build_superset.py` | Programmatic Superset chart builder via REST API |
| `product_search.txt` | Web intelligence report on top 10 products by revenue |

## Dashboards

Four published dashboards in Apache Superset:

| Dashboard | Audience | Key Charts |
|---|---|---|
| Executive Overview | C-suite | Revenue KPI, profit, annual trend, revenue by region |
| Detailed Operations | Operations managers | Top customers, segment trends, shipping performance, discount analysis |
| Anomaly Alerts | Analysts | Loss-making states, sub-category margin ranking, heavy discount damage |
| Product Intelligence | Product / marketing | AI recommendation table with confidence scores and reasoning |

## Hidden Insights

Three non-obvious insights discovered through the agent:

1. **Discount Destruction** — Tables sub-category: 26% avg discount → -8.5% margin. The discount policy in Office Supplies is destroying value at scale.
2. **EOL Technology Trap** — Cisco TelePresence EX90 (end-of-sale 2017) ranks #3 by revenue at $22,638 but runs at -8% margin — a signature of EOL clearance selling, invisible without external web intelligence.
3. **Break-Even Signal** — HON 5400 Task Chairs: $21,870 revenue, 39 units, exactly $0.00 profit — deliberate cost-pricing as a loss-leader, never surfaces in a standard dashboard.

## Dataset

[Sample Superstore — Kaggle](https://www.kaggle.com/datasets/vivek468/superstore-dataset-final?resource=download)
