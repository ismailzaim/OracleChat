# OracleChat — Architecture

## Overview

OracleChat is a natural language interface for Oracle Database 19c.
The user types a question in plain English. The system understands
the database schema automatically, generates correct Oracle SQL using
an LLM, executes it safely, and returns results with a chart and a
plain explanation.

The core design principle: **every component has exactly one
responsibility**. This makes each part independently testable,
replaceable, and explainable in an interview.

---

## System architecture
```
Browser (Chart.js UI)
        │
        │  POST /query  {"question": "...", "history": [...]}
        ▼
┌─────────────────────┐
│     routes.py       │  HTTP layer — input validation, orchestration
└────────┬────────────┘
         │
    ┌────┴────┐
    │         │
    ▼         ▼
rag.py      llm.py
    │         │
    │  schema │  prompt + context
    │  context│
    └────┬────┘
         │
         │  Oracle SQL string
         ▼
┌─────────────────────┐
│    executor.py      │  Safety layer — SELECT only, row limit, timeout
└────────┬────────────┘
         │
         │  query
         ▼
┌─────────────────────┐
│  Oracle 19c ORCLPDB │  oracledb connection pool
└────────┬────────────┘
         │
         │  raw rows + column names
         ▼
┌─────────────────────┐
│   formatter.py      │  Chart type detection, type coercion
└────────┬────────────┘
         │
         │  JSON response
         ▼
Browser renders Chart.js + table + explanation
```

---

## Component decisions

### `app/__init__.py` — Application factory

Uses the Flask factory pattern (`create_app()`) rather than a
module-level app object. This allows tests to instantiate the app
multiple times with different configurations without state leaking
between test cases.

An Oracle connection pool is created once at startup and attached
to the app object (`app.pool`). Schema discovery also runs at startup
and caches the result on `app.schema_cache`. Both are available
to all request handlers via `current_app`.

**Why a connection pool and not per-request connections?**
Opening an Oracle connection takes ~200ms. Under any concurrent load,
per-request connections would make the app unusably slow and would
exhaust Oracle's process limit. The pool keeps `POOL_MIN` connections
permanently open and expands to `POOL_MAX` under load.

---

### `app/rag.py` — Schema discovery and context builder

**The problem RAG solves:**
The LLM has no knowledge of your specific database. Without context,
it hallucinates table names, column names, and join conditions.
Injecting the schema into every prompt gives the LLM the knowledge
it needs to generate correct SQL.

**Why not fine-tune the model?**
Fine-tuning is expensive, slow, and requires retraining every time
the schema changes. RAG is dynamic — the context is rebuilt from
the live database on every startup. A schema change is reflected
immediately with no retraining.

**Auto-discovery from Oracle data dictionary:**
`discover_schema()` queries these Oracle system views at startup:

| View | Purpose |
|---|---|
| `all_tables` | Table names and row counts |
| `all_tab_columns` | Column names, types, nullability |
| `all_constraints` | Primary and foreign key definitions |
| `all_cons_columns` | Which columns belong to which constraint |

This means OracleChat works on **any Oracle schema** without
configuration. Connect, start, query.

**Column value sampling:**
For `VARCHAR2` columns whose names suggest categorical data
(`STATUS`, `TYPE`, `CATEGORY`, `METHOD`, etc.), the app runs
`SELECT DISTINCT` at startup and injects the real values into
the prompt context. This prevents Gemini from generating
`WHERE status = 'delivered'` when the correct value is `'DELIVERED'`.

**Table relevance scoring:**
Rather than injecting the full schema into every prompt (expensive,
token-wasteful), `_get_relevant_tables()` scores each table by:
- Direct table name mention in the question (+10)
- Column name mention in the question (+3)
- Presence of foreign keys (+1)
- Row count above 100 (+1)

The top 5 tables are injected. The largest table (central fact table)
is always included as a guarantee.

---

### `app/llm.py` — LLM interface

**Why isolate the LLM in its own module?**
Swapping Gemini for another model (GPT-4, Mistral, Claude) requires
changing only this file. Routes, RAG, and executor are untouched.

**Model:** `gemini-2.5-flash` — fast, free tier, sufficient for
SQL generation which requires precision not creativity.

**Temperature: 0.1** — deliberately low. SQL generation benefits
from deterministic output. High temperature produces creative SQL
that is often syntactically wrong.

**`_extract_sql()`** strips markdown fences, preamble text, and
trailing semicolons from Gemini responses. LLMs frequently wrap
output in formatting the caller did not ask for. This function
is the defensive layer between raw LLM output and the executor.

**Conversation memory:**
`generate_sql_with_history()` injects the last 3 question/SQL pairs
into the prompt. This allows follow-up questions like
"show me their orders" to reference the previous result.

The history is carried by the **frontend**, not the backend.
The backend remains stateless — each request is independent.
This is a deliberate architectural decision:
- No server-side session management needed
- Scales horizontally without sticky sessions
- History is transparent — the client controls what is sent

**Retry on zero rows:**
If the first SQL attempt returns zero rows, `generate_sql_with_retry()`
re-prompts Gemini with a message explaining that zero rows were
returned and emphasising that exact column values must be used.
One retry maximum — two LLM calls per question is the ceiling
acceptable on a free tier.

---

### `app/executor.py` — Safety layer

This is the most security-critical component. Every SQL statement
generated by the LLM passes through this module before touching
the database.

**`_is_safe()` — two-pass validation:**
1. Strip all SQL comments (`--` line comments and `/* */` block
   comments). An adversarial prompt could hide a `DELETE` behind
   a comment before a `SELECT`.
2. Verify the statement starts with `SELECT`.
3. Scan the entire statement for forbidden keywords using word
   boundary regex (`\bDELETE\b`) to avoid false positives
   (e.g. `ALTERNATE` containing `ALTER`).

**`validate_sql()` — syntax validation:**
Uses Oracle's `EXPLAIN PLAN FOR` to parse and validate the SQL
without executing it. A syntactically broken statement from the LLM
returns a clean error message rather than an Oracle exception stack.

**Row limit:** All queries are wrapped in a subquery with
`FETCH FIRST 500 ROWS ONLY`. This prevents runaway queries from
returning millions of rows to the frontend.

**Query timeout:** `cursor.callTimeout = 10000` (10 seconds).
Any query running longer than 10 seconds is killed. This protects
Oracle from expensive accidental full-table scans.

**Connection release guarantee:**
The `finally` block in `run_query()` always releases the connection
back to the pool — even if an exception is raised mid-execution.
Without this, the pool leaks connections until Oracle refuses new ones.

---

### `app/formatter.py` — Result shaping

**Chart type detection logic:**

| Condition | Chart type |
|---|---|
| First column name contains MONTH, DATE, YEAR, WEEK | Line |
| First column values match `YYYY-MM` pattern | Line |
| Exactly 2 columns and ≤ 8 rows | Pie |
| All other cases | Bar |

**Type coercion:**
Oracle returns `Decimal` for `NUMBER` columns and `datetime` for
`DATE` columns. Both fail JSON serialisation. `_to_python()` converts
these to `float` and `str` respectively before the response is built.

Numbers are preserved as numeric types — not stringified. This
ensures Chart.js receives `43772.07` not `"43772.07"`, which
affects tooltip formatting and axis scaling.

---

### `app/templates/index.html` — Frontend

Single-page application. No framework — vanilla JavaScript.

**Conversation history** is stored in a JavaScript array
(`conversationHistory`) and sent with every request. It is capped
at 6 turns to prevent prompt bloat.

**Chart switching** — the user can toggle between Bar, Line, and
Pie at any time. The chart data does not change — only the
Chart.js `type` property is updated and the chart is re-rendered.

**SQL panel** — collapsed by default. Expanding it shows the
exact Oracle SQL that was generated and executed. This is
important for trust and debuggability — the user can always
verify what the system did.

---

### `oracle/schema_metadata.py` — Static configuration

Contains only two things:
- `ORACLE_RULES` — Oracle-specific syntax rules injected into
  every prompt to prevent MySQL/PostgreSQL syntax contamination
- `SAMPLE_QUERIES` — few-shot examples that demonstrate correct
  Oracle style (FETCH FIRST, TO_CHAR, explicit JOINs)

Table and column definitions were intentionally removed from this
file. They are now discovered dynamically from the live database.
This file is reusable across any Oracle schema without modification.

---

## Data flow — complete request lifecycle
```
1. User types: "who are the top customers by revenue?"

2. Browser sends:
   POST /query
   {"question": "who are the top customers?", "history": []}

3. routes.py validates input, calls build_context()

4. rag.py reads app.schema_cache (discovered at startup):
   - Scores tables: CUSTOMERS (+3 for "customers"), ORDERS (+1)
   - Selects top 5 relevant tables
   - Builds context string with column definitions,
     valid STATUS values ('ACTIVE','INACTIVE','BANNED'),
     FK join paths, Oracle rules, example queries

5. llm.py sends prompt to Gemini 2.5 Flash:
   - Temperature 0.1
   - Context + question + history
   - Gemini returns raw response

6. _extract_sql() strips markdown, extracts SELECT statement

7. executor.validate_sql() runs EXPLAIN PLAN — syntax check

8. executor.run_query() executes:
   SELECT * FROM (
     SELECT c.first_name || ' ' || c.last_name AS customer_name,
            SUM(o.total_amount) AS total_revenue
     FROM   customers c
     JOIN   orders o ON o.customer_id = c.customer_id
     WHERE  o.status = 'DELIVERED'
     GROUP  BY c.customer_id, c.first_name, c.last_name
     ORDER  BY total_revenue DESC
     FETCH  FIRST 5 ROWS ONLY
   ) FETCH FIRST 500 ROWS ONLY

9. If row_count == 0: retry with corrected prompt

10. formatter.py:
    - Detects chart type: BAR (2 columns, >8 rows)
    - Coerces Decimal to float
    - Builds Chart.js labels + datasets

11. llm.generate_explanation() — second Gemini call:
    "This query identifies the top 5 customers by their total
     spend on delivered orders, ranked from highest to lowest."

12. routes.py returns JSON:
    {question, sql, explanation, chart_type,
     chart_data, table_data, columns, row_count, turn}

13. Browser renders Bar chart + data table + explanation
    Appends turn to conversationHistory
```

---

## Known limitations

**Column value blindness for non-categorical columns:**
Free-text columns like `NAME`, `EMAIL`, `ADDRESS` are not sampled.
If a user asks "show me orders for customer John Smith", Gemini
must guess the exact spelling. Fuzzy matching is not implemented.

**No vector embeddings:**
Table relevance is determined by keyword matching, not semantic
similarity. A question using unusual phrasing may score the wrong
tables. A production system would use vector embeddings of table
and column descriptions for semantic retrieval.

**Single schema per instance:**
The app discovers one schema (configured via `ORACLE_SCHEMA` env var).
Multi-tenant support would require per-request schema switching.

**Conversation history is frontend state:**
Refreshing the browser clears history. A production system would
persist conversation sessions server-side or in a cookie.

---

## What v2 would add

- **Vector embeddings** for semantic table selection
- **Column annotation UI** — let users add business descriptions
  to columns that the auto-discovery cannot infer
- **Query feedback loop** — thumbs up/down on results, used to
  improve future prompt construction
- **Rate limiting** — per-IP request throttling on `/query`
- **Oracle Autonomous Database** — cloud deployment with a real
  cloud Oracle instance
- **Query history** — persist past questions and results per session

---

## Tech stack summary

| Component | Technology | Why |
|---|---|---|
| Database | Oracle 19c (CDB/PDB) | Enterprise standard, LTS release |
| DB driver | oracledb 2.x | Official Oracle Python driver |
| Connection management | oracledb pool | Thread safety, performance |
| Backend | Python 3.11 + Flask | Lightweight, well-understood |
| LLM | Google Gemini 2.5 Flash | Free tier, fast, accurate for SQL |
| RAG | Custom keyword + data dictionary | No vector DB needed at this scale |
| Frontend | Vanilla JS + Chart.js | No framework overhead |
| Tests | pytest + unittest.mock | Industry standard |
| CI | GitHub Actions | Free, integrated with GitHub |
| Containerisation | Docker + gunicorn | Production-ready packaging |