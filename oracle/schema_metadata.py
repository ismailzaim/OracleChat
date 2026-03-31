# oracle/schema_metadata.py
#
# Static configuration for OracleChat — reusable across ANY Oracle schema.
# Table and column definitions are no longer hardcoded here.
# They are discovered at runtime by rag.discover_schema().

ORACLE_RULES = [
    "Use Oracle 19c SQL syntax only. Do NOT use MySQL or PostgreSQL syntax.",
    "To limit rows, use FETCH FIRST N ROWS ONLY — not LIMIT N.",
    "To get the current date, use SYSDATE — not NOW() or CURRENT_DATE.",
    "For string concatenation, use || — not + or CONCAT().",
    "For date formatting, use TO_CHAR(date_column, 'YYYY-MM') — not DATE_FORMAT().",
    "Column and table names are uppercase in Oracle.",
    "Do not use backticks. Use double quotes for identifiers only if necessary.",
    "For top-N queries, use FETCH FIRST N ROWS ONLY after ORDER BY.",
    "Do not use ROWNUM for pagination — use FETCH FIRST / OFFSET instead.",
    "All joins must use explicit JOIN ... ON syntax, never implicit comma joins.",
]

SAMPLE_QUERIES = [
    {
        "question": "How many rows are in each table?",
        "sql": "SELECT table_name, num_rows FROM user_tables ORDER BY num_rows DESC",
    },
    {
        "question": "Show me the top 10 rows from a table called ORDERS.",
        "sql": """SELECT *
FROM   orders
FETCH  FIRST 10 ROWS ONLY""",
    },
    {
        "question": "What is the monthly trend of a date column?",
        "sql": """SELECT TO_CHAR(order_date, 'YYYY-MM') AS month,
       COUNT(*)                        AS total
FROM   orders
GROUP  BY TO_CHAR(order_date, 'YYYY-MM')
ORDER  BY month""",
    },
    {
        "question": "Who are the top 5 records by a numeric column?",
        "sql": """SELECT *
FROM   some_table
ORDER  BY numeric_column DESC
FETCH  FIRST 5 ROWS ONLY""",
    },
]