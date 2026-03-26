# OracleChat 🔶

> AI-powered natural language interface for Oracle Database 19c.  
> Ask questions in plain English — get SQL, chart visualisations, and plain explanations.



---

## What it does

OracleChat lets you query an Oracle 19c database using plain English.  
Type "who are the top customers by revenue?" and the system:

1. Retrieves the relevant schema context via **RAG**
2. Generates correct Oracle 19c SQL using **Google Gemini**
3. Executes the query safely (SELECT only, 500 row cap, 10s timeout)
4. Returns a **Chart.js visualisation** + plain English explanation

---

## Architecture
```
Browser (Chart.js UI)
    ↓ POST /query
Flask routes.py
    ↓
rag.py          →  schema_metadata.py (table/column descriptions)
    ↓
llm.py          →  Google Gemini 2.5 Flash (SQL generation)
    ↓
executor.py     →  Oracle 19c ORCLPDB (safe execution)
    ↓
formatter.py    →  chart type detection + JSON shaping
    ↓
Browser renders chart + table + explanation
```

---

## Tech stack

| Layer | Technology |
|---|---|
| Database | Oracle Database 19c (CDB/PDB architecture) |
| Backend | Python 3.11, Flask 3.0 |
| ORM / DB driver | python-oracledb |
| LLM | Google Gemini 2.5 Flash (free tier) |
| Context injection | RAG — keyword-based schema retrieval |
| Frontend | HTML/CSS/JS, Chart.js 4.4 |
| Testing | pytest, unittest.mock |
| CI/CD | GitHub Actions |
| Deployment | Docker, Render.com |

---

## Demo questions

Try these in the UI:

- Who are the top 5 customers by revenue?
- What is the monthly revenue trend?
- Which product category generates the most revenue?
- What is the most popular payment method?
- How many orders were placed per city?
- Top 10 best selling products

---

## Local setup

### Prerequisites

- Oracle Database 19c installed locally (CDB + ORCLPDB)
- Python 3.11+
- Google Gemini API key (free at https://aistudio.google.com)

### Steps
```bash
# 1. Clone the repository
git clone https://github.com/ismailzaim/OracleChat.git
cd OracleChat

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env
# Edit .env with your Oracle credentials and Gemini API key

# 4. Set up the database (connect as oraclechat in ORCLPDB)
# Run oracle/schema.sql then oracle/seed_data.sql in SQL*Plus

# 5. Start the server
python run.py

# 6. Open the UI
# http://localhost:5000
```

### Run tests
```bash
python -m pytest tests/ -v
```

---

## Project structure
```
OracleChat/
├── app/
│   ├── __init__.py          # Flask factory + Oracle connection pool
│   ├── routes.py            # HTTP endpoints (GET /, POST /query, GET /health)
│   ├── rag.py               # Schema context retrieval
│   ├── llm.py               # Gemini API integration
│   ├── executor.py          # Safe SQL execution (SELECT only)
│   ├── formatter.py         # Chart type detection + JSON shaping
│   └── templates/
│       └── index.html       # Chart.js UI
├── oracle/
│   ├── schema.sql           # CREATE TABLE, sequences, constraints, indexes
│   ├── seed_data.sql        # 200 customers, 60 products, 500 orders
│   ├── generate_seed.py     # Faker-based seed data generator
│   └── schema_metadata.py   # RAG knowledge base
├── tests/
│   ├── test_executor.py     # Safety layer unit tests
│   ├── test_llm.py          # SQL extraction unit tests
│   └── test_routes.py       # HTTP integration tests
├── .github/
│   └── workflows/
│       └── ci_cd.yml        # GitHub Actions CI pipeline
├── Dockerfile               # Container definition
├── requirements.txt         # Pinned dependencies
├── .env.example             # Environment variable template
└── run.py                   # Application entry point
```

---

## Security design

- **SELECT only** — executor rejects INSERT, UPDATE, DELETE, DROP and all DDL
- **Row cap** — maximum 500 rows returned per query
- **Query timeout** — 10 second hard limit on all Oracle queries
- **Dedicated DB user** — app connects as `oraclechat`, not SYSTEM
- **No secrets in code** — all credentials via environment variables

---

## Certifications

Built by an EMSI engineering student holding:

- Oracle Database 19c Administrator Certified Professional (1Z0-082 and 1Z0-083)
- Oracle Cloud Infrastructure Data Science Professional
- Oracle Cloud Infrastructure DevOps Professional
