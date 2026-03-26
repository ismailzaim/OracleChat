# app/executor.py
#
# Safe SQL execution layer.
# All database queries in OracleChat go through this module.
# Nothing bypasses it — not routes, not tests, nothing.

import re
import oracledb
from flask import current_app

# ── Safety constants ───────────────────────────────────────────
MAX_ROWS    = 500   # Never return more than this many rows
TIMEOUT_SEC = 10    # Kill any query running longer than 10 seconds

# SQL statements that are never allowed, ever.
# Even if someone crafts a prompt that tricks the LLM into
# generating one of these, executor.py blocks it.
FORBIDDEN_KEYWORDS = [
    "INSERT", "UPDATE", "DELETE", "DROP", "CREATE",
    "ALTER", "TRUNCATE", "MERGE", "GRANT", "REVOKE",
    "COMMIT", "ROLLBACK", "EXECUTE", "EXEC",
]


class ExecutorError(Exception):
    """
    Raised when a query is rejected by the safety layer.
    Distinct from oracledb exceptions so the caller can
    distinguish 'blocked by us' from 'Oracle said no'.
    """
    pass


def _is_safe(sql: str) -> tuple[bool, str]:
    """
    Validate that sql is a safe read-only SELECT statement.

    Returns (True, "") if safe.
    Returns (False, reason) if rejected.

    Why not just check sql.startswith('SELECT')?
    Because a clever prompt could produce:
        -- harmless comment
        DELETE FROM customers;
    which starts with '--' not 'SELECT'. We normalise and check
    the first real keyword, then scan the whole statement.
    """
    # Strip comments and normalise whitespace
    clean = re.sub(r'--[^\n]*', '', sql)       # remove -- line comments
    clean = re.sub(r'/\*.*?\*/', '', clean,     # remove /* block comments */
                   flags=re.DOTALL)
    clean = clean.strip().upper()

    if not clean:
        return False, "Empty query after stripping comments."

    # Must start with SELECT
    if not clean.startswith("SELECT"):
        return False, f"Only SELECT statements are allowed. Got: {clean[:30]}"

    # Scan for any forbidden keyword anywhere in the statement.
    # Use word boundaries (\b) so ALTER inside 'ALTERNATE' doesn't fire.
    for keyword in FORBIDDEN_KEYWORDS:
        pattern = rf'\b{keyword}\b'
        if re.search(pattern, clean):
            return False, f"Forbidden keyword detected: {keyword}"

    return True, ""


def run_query(sql: str) -> dict:
    """
    Execute a validated SELECT statement against Oracle.

    Returns a dict with keys:
        columns : list of column name strings
        rows    : list of row tuples
        row_count: int

    Raises ExecutorError if the query is rejected.
    Raises oracledb.Error if Oracle returns a database error.

    Why return columns separately from rows?
    Because formatter.py needs to know column names to build
    the chart labels and JSON keys. Row tuples alone aren't enough.
    """
    # ── Step 1: safety check ───────────────────────────────────
    safe, reason = _is_safe(sql)
    if not safe:
        raise ExecutorError(f"Query rejected: {reason}")

    # ── Step 2: enforce row limit ──────────────────────────────
    # Wrap the original query in a subquery with FETCH FIRST.
    # Why wrap instead of appending? Because the original query
    # might already have an ORDER BY, and appending FETCH FIRST
    # after a subquery ORDER BY causes Oracle syntax errors.
    limited_sql = (
        f"SELECT * FROM ({sql}) "
        f"FETCH FIRST {MAX_ROWS} ROWS ONLY"
    )

    # ── Step 3: execute with timeout ──────────────────────────
    conn   = None
    cursor = None
    try:
        # Borrow a connection from the pool
        conn   = current_app.pool.acquire()
        cursor = conn.cursor()

        # callTimeout is in milliseconds
        cursor.callTimeout = TIMEOUT_SEC * 1000

        cursor.execute(limited_sql)

        # Extract column names from cursor description
        # cursor.description is a list of 7-tuples;
        # index 0 of each tuple is the column name
        columns = [col[0] for col in cursor.description]
        rows    = cursor.fetchall()

        return {
            "columns":   columns,
            "rows":      rows,
            "row_count": len(rows),
        }

    finally:
        # Always release cursor and connection back to the pool,
        # even if an exception was raised. Without this, the pool
        # leaks connections until Oracle refuses new ones.
        if cursor:
            cursor.close()
        if conn:
            current_app.pool.release(conn)