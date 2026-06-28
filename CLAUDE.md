# IT 501 — Business Intelligence Final Project

## Project Overview

Full end-to-end BI pipeline for the IT 501 course final exam, built on the **Sample Superstore** dataset using a **vibe coding** approach — the user has predefined prompts that drive each phase.

**Pipeline:**
```
Sample - Superstore.csv → ETL → Supabase PostgreSQL (star/snowflake schema)
                                      ↓
                           MCP Server (exposes schema to LLM)
                                      ↓
                           BI Agent (NL → SQL via Claude)
                                      ↓
                           Apache Superset (dashboards)
```

## Tech Stack

| Layer | Tool |
|---|---|
| Dataset | Sample - Superstore.csv |
| Database | Supabase PostgreSQL |
| AI Agent | Claude Code (migrated from Gemini CLI) |
| Schema exposure | MCP Server (supabase-mcp or custom) |
| Web research | Brave Search MCP |
| Dashboards | Apache Superset (localhost:8088) |
| ETL | Python (pandas + psycopg2) |

## Phases

1. **Data** — Superstore CSV selected as dataset
2. **Agent Engineering** — MCP server + Claude as the BI agent
3. **Foundation** — Star/snowflake schema in Supabase + ETL pipeline + 5–10 Golden Queries
4. **Visualization** — Superset connection + 3 themed dashboards
5. **Finalization** — 3 hidden insights + video demo + presentation

## Vibe Coding Approach

The user drives implementation with **predefined prompts** per phase. When the user says they are using a predefined prompt, treat it as the authoritative spec for that phase — do not improvise beyond it.

## Migration from Gemini CLI

This project was previously set up for Gemini CLI. Key migration notes:

- MCP config moved from `.gemini/settings.json` → `.claude/settings.json`
- All Python ETL scripts (pandas/psycopg2) have zero Gemini dependencies — reuse as-is
- The BI agent layer (NL → SQL) was handled by Gemini CLI interactively; Claude Code now takes that role

## Environment Variables

All in `.env` (gitignored):

```
POSTGRES_HOST=aws-0-eu-west-1.pooler.supabase.com
POSTGRES_PORT=6543
POSTGRES_USER=postgres.<project-ref>
POSTGRES_PASSWORD=<password>
POSTGRES_DATABASE=postgres
BRAVE_API_KEY=<your-brave-api-key>
```

## MCP Servers

Configured in `.claude/settings.json`:

- **superset-mcp** — manages Superset charts/dashboards programmatically (localhost:8088)
- **brave-search** — Brave Search API for product/domain research

## Reference: bi-agent Repo

The original boilerplate at `/Users/smasetic/bi-agent/` used OnlineRetail.csv. Its ETL patterns (`etl_process.py`, `etl_process2.py`) and star schema design are the reference implementation for this project's Superstore adaptation.

## Agent System Prompt

The BI Agent's full system prompt lives at:

```
/Users/smasetic/it-501-bi-ai-project/system_prompt.md
```

It covers: role definition, embedded star schema reference, SQL generation rules (PostgreSQL/Supabase conventions), structured response format, ambiguity handling, read-only guardrails, and 3 inline golden query examples.

To activate the agent: paste the contents of `system_prompt.md` as the system turn in Claude, or reference this file when configuring the MCP-connected agent session.

## Grading Weights

| Component | Weight |
|---|---|
| Technical Setup & Data Architecture | 20% |
| AI Agent Implementation (MCP, prompt engineering, GitHub) | 30% |
| BI Dashboarding in Apache Superset | 25% |
| Final Presentation & Video Demo | 25% |
