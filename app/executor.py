# app/executor.py
import re
import oracledb
from flask import current_app

MAX_ROWS    = 500
TIMEOUT_SEC = 10

FORBIDDEN_KEYWORDS = [
    "INSERT", "UPDATE", "DELETE", "DROP", "CREATE",
    "ALTER", "TRUNCATE", "MERGE", "GRANT", "REVOKE",
    "COMMIT", "ROLLBACK", "EXECUTE", "EXEC",
]


class ExecutorError(Exception):
    pass


def _is_safe(sql: str) -> tuple:
    clean = re.sub(r'--[^\n]*', '', sql)
    clean = re.sub(r'/\*.*?\*/', '', clean, flags=re.DOTALL)
    clean = clean.strip().upper()

    if not clean:
        return False, "Empty query after stripping comments."

    if not clean.startswith("SELECT"):
        return False, f"Only SELECT statements are allowed. Got: {clean[:30]}"

    for keyword in FORBIDDEN_KEYWORDS:
        pattern = rf'\b{keyword}\b'
        if re.search(pattern, clean):
            return False, f"Forbidden keyword detected: {keyword}"

    return True, ""


def validate_sql(sql: str) -> tuple:
    """
    Validate SQL syntax using Oracle EXPLAIN PLAN before execution.
    Returns (True, "") if valid, (False, error_message) if not.
    """
    conn   = None
    cursor = None
    try:
        conn   = current_app.pool.acquire()
        cursor = conn.cursor()
        cursor.execute(f"EXPLAIN PLAN FOR {sql}")
        return True, ""
    except oracledb.Error as e:
        error_msg = str(e).split("\n")[0]
        return False, error_msg
    finally:
        if cursor:
            cursor.close()
        if conn:
            current_app.pool.release(conn)


def run_query(sql: str) -> dict:
    """
    Execute a validated SELECT statement against Oracle.
    Returns dict with columns, rows, row_count.
    """
    safe, reason = _is_safe(sql)
    if not safe:
        raise ExecutorError(f"Query rejected: {reason}")

    limited_sql = (
        f"SELECT * FROM ({sql}) "
        f"FETCH FIRST {MAX_ROWS} ROWS ONLY"
    )

    conn   = None
    cursor = None
    try:
        conn   = current_app.pool.acquire()
        cursor = conn.cursor()
        cursor.callTimeout = TIMEOUT_SEC * 1000
        cursor.execute(limited_sql)

        columns = [col[0] for col in cursor.description]
        rows    = cursor.fetchall()

        return {
            "columns":   columns,
            "rows":      rows,
            "row_count": len(rows),
        }

    finally:
        if cursor:
            cursor.close()
        if conn:
            current_app.pool.release(conn)