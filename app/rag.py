# app/rag.py
#
# RAG — schema discovery and context builder.
#
# discover_schema()  — queries Oracle data dictionary at startup,
#                      builds a complete schema description automatically.
#                      Works on ANY Oracle schema, not just e-commerce.
#
# build_context()    — assembles the Gemini prompt context from the
#                      discovered schema + static Oracle rules + examples.

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from flask import current_app
from oracle.schema_metadata import ORACLE_RULES, SAMPLE_QUERIES


def discover_schema() -> dict:
    """
    Query Oracle's data dictionary to build a complete schema description.

    Reads from:
        user_tables     — all tables owned by the current user
        user_tab_columns — all columns with data types and nullability
        user_constraints — primary and foreign keys
        user_cons_columns — which columns are in which constraints

    Returns a dict structured as:
        {
            "CUSTOMERS": {
                "columns": [
                    {
                        "name":      "CUSTOMER_ID",
                        "type":      "NUMBER",
                        "nullable":  False,
                        "is_pk":     True,
                    },
                    ...
                ],
                "foreign_keys": [
                    "CUSTOMER_ID references ORDERS.CUSTOMER_ID"
                ],
                "row_count": 200,
            },
            ...
        }

    Why query user_tables and not all_tables?
    user_tables contains only tables owned by the connected schema user.
    all_tables includes system tables and tables from other schemas —
    injecting those into the prompt would confuse the LLM with irrelevant
    Oracle internals like SYS.OBJ$ and SYSTEM.HELP.
    """
    conn   = None
    cursor = None

    try:
        conn   = current_app.pool.acquire()
        cursor = conn.cursor()

        # ── Step 1: get all user tables with row counts ────────
        cursor.execute("""
            SELECT table_name, num_rows
            FROM   user_tables
            ORDER  BY table_name
        """)
        tables_raw = cursor.fetchall()

        if not tables_raw:
            current_app.logger.warning(
                "discover_schema: no tables found for current user. "
                "Check that schema objects exist in this PDB."
            )
            return {}

        schema = {}
        table_names = [row[0] for row in tables_raw]

        for table_name, num_rows in tables_raw:
            schema[table_name] = {
                "columns":      [],
                "foreign_keys": [],
                "row_count":    num_rows or 0,
            }

        # ── Step 2: get all columns for all user tables ────────
        # Single query for all tables — much faster than N queries.
        # We filter by table_name IN (...) using a bind variable
        # workaround: Oracle doesn't support IN with a bind list,
        # so we use a subquery against user_tables instead.
        cursor.execute("""
            SELECT c.table_name,
                   c.column_name,
                   c.data_type,
                   c.data_length,
                   c.data_precision,
                   c.data_scale,
                   c.nullable,
                   c.column_id
            FROM   user_tab_columns c
            WHERE  c.table_name IN (
                       SELECT table_name FROM user_tables
                   )
            ORDER  BY c.table_name, c.column_id
        """)
        columns_raw = cursor.fetchall()

        for (table_name, col_name, data_type, data_length,
             data_precision, data_scale, nullable, col_id) in columns_raw:

            if table_name not in schema:
                continue

            # Format the type string cleanly
            # e.g. VARCHAR2(100), NUMBER(10,2), DATE
            if data_type == "VARCHAR2" and data_length:
                type_str = f"VARCHAR2({data_length})"
            elif data_type == "NUMBER" and data_precision:
                if data_scale and data_scale > 0:
                    type_str = f"NUMBER({data_precision},{data_scale})"
                else:
                    type_str = f"NUMBER({data_precision})"
            else:
                type_str = data_type

            schema[table_name]["columns"].append({
                "name":     col_name,
                "type":     type_str,
                "nullable": nullable == "Y",
                "is_pk":    False,  # filled in Step 3
            })

        # ── Step 3: identify primary keys ─────────────────────
        cursor.execute("""
            SELECT cc.table_name, cc.column_name
            FROM   user_constraints  c
            JOIN   user_cons_columns cc
                   ON cc.constraint_name = c.constraint_name
            WHERE  c.constraint_type = 'P'
            AND    c.table_name IN (SELECT table_name FROM user_tables)
            ORDER  BY cc.table_name, cc.position
        """)
        pk_raw = cursor.fetchall()

        for table_name, col_name in pk_raw:
            if table_name not in schema:
                continue
            for col in schema[table_name]["columns"]:
                if col["name"] == col_name:
                    col["is_pk"] = True

        # ── Step 4: discover foreign key relationships ─────────
        # This is the join path information the LLM needs most.
        cursor.execute("""
            SELECT uc.table_name,
                   ucc.column_name,
                   uc2.table_name  AS ref_table,
                   ucc2.column_name AS ref_column
            FROM   user_constraints  uc
            JOIN   user_cons_columns ucc
                   ON ucc.constraint_name = uc.constraint_name
            JOIN   user_constraints  uc2
                   ON uc2.constraint_name = uc.r_constraint_name
            JOIN   user_cons_columns ucc2
                   ON ucc2.constraint_name = uc2.constraint_name
            WHERE  uc.constraint_type = 'R'
            AND    uc.table_name IN (SELECT table_name FROM user_tables)
            ORDER  BY uc.table_name
        """)
        fk_raw = cursor.fetchall()

        for table_name, col_name, ref_table, ref_col in fk_raw:
            if table_name not in schema:
                continue
            fk_desc = (
                f"{table_name}.{col_name} "
                f"references {ref_table}.{ref_col}"
            )
            schema[table_name]["foreign_keys"].append(fk_desc)

        current_app.logger.info(
            f"discover_schema: discovered {len(schema)} tables — "
            f"{', '.join(schema.keys())}"
        )
        return schema

    finally:
        if cursor:
            cursor.close()
        if conn:
            current_app.pool.release(conn)


def build_context(question: str) -> str:
    """
    Assemble the Gemini prompt context for a given question.

    Uses the schema cached on current_app.schema_cache (populated
    at startup by __init__.py). Falls back to re-discovery if the
    cache is missing.

    Context structure:
        1. Oracle rules (always — prevent syntax mistakes)
        2. Relevant table definitions (filtered by keyword match)
        3. Foreign key join paths
        4. Few-shot example queries
    """
    # Use cached schema — avoid hitting Oracle on every request
    schema = getattr(current_app, "schema_cache", None)
    if not schema:
        current_app.logger.warning(
            "build_context: schema_cache missing, running discovery now."
        )
        schema = discover_schema()
        current_app.schema_cache = schema

    relevant_tables = _get_relevant_tables(question, schema)

    parts = []

    # ── Section 1: Oracle rules ────────────────────────────────
    parts.append("=== ORACLE 19c SQL RULES — FOLLOW EXACTLY ===")
    for rule in ORACLE_RULES:
        parts.append(f"- {rule}")
    parts.append("")

    # ── Section 2: Relevant table definitions ─────────────────
    parts.append("=== SCHEMA TABLES ===")
    for table_name in relevant_tables:
        if table_name not in schema:
            continue
        meta = schema[table_name]

        row_info = (f"{meta['row_count']:,} rows"
                    if meta["row_count"] else "row count unknown")
        parts.append(f"TABLE: {table_name}  ({row_info})")
        parts.append("Columns:")

        for col in meta["columns"]:
            pk_marker  = " [PK]" if col["is_pk"]    else ""
            null_marker = " NOT NULL" if not col["nullable"] else ""
            parts.append(
                f"  {col['name']}: {col['type']}"
                f"{pk_marker}{null_marker}"
            )

        if meta["foreign_keys"]:
            parts.append("Foreign keys:")
            for fk in meta["foreign_keys"]:
                parts.append(f"  {fk}")

        parts.append("")

    # ── Section 3: All foreign key join paths ─────────────────
    parts.append("=== JOIN CONDITIONS (use these for JOINs) ===")
    join_count = 0
    for table_name in relevant_tables:
        if table_name not in schema:
            continue
        for fk in schema[table_name]["foreign_keys"]:
            parts.append(f"- {fk}")
            join_count += 1
    if join_count == 0:
        parts.append("No foreign keys found — use column names to infer joins.")
    parts.append("")

    # ── Section 4: Few-shot examples ──────────────────────────
    parts.append("=== EXAMPLE QUERIES (style reference) ===")
    for ex in SAMPLE_QUERIES:
        parts.append(f"Question: {ex['question']}")
        parts.append(f"SQL:\n{ex['sql']}")
        parts.append("")

    return "\n".join(parts)


def _get_relevant_tables(question: str, schema: dict) -> list:
    """
    Select which tables to inject into the prompt.

    Strategy:
        1. Check if any table name appears in the question
        2. Check if any column name appears in the question
        3. Always include the largest table (most likely central fact table)
        4. Cap at 5 tables to keep the prompt lean

    Why cap at 5?
    A schema with 50 tables would produce a prompt too large for
    the free tier context window. We inject the most relevant tables
    and trust the LLM to work within them.
    """
    question_upper = question.upper()
    scores = {table: 0 for table in schema}

    for table_name, meta in schema.items():
        # Direct table name mention — strong signal
        if table_name in question_upper:
            scores[table_name] += 10

        # Column name mention — medium signal
        for col in meta["columns"]:
            if col["name"] in question_upper:
                scores[table_name] += 3

        # Tables with foreign keys are likely join targets — small boost
        if meta["foreign_keys"]:
            scores[table_name] += 1

        # Larger tables are more likely to be relevant
        if meta["row_count"] and meta["row_count"] > 100:
            scores[table_name] += 1

    # Sort by score descending
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)

    # Always include at least the top 3 tables
    selected = [t for t, s in ranked[:5] if s >= 0]

    # Guarantee the highest-row-count table is always included
    # (it's almost always the central fact table)
    if schema:
        largest = max(schema.items(),
                      key=lambda x: x[1].get("row_count") or 0)
        if largest[0] not in selected:
            selected[-1] = largest[0]

    return selected