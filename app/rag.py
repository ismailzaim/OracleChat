# app/rag.py
#
# RAG — schema discovery and context builder.
# discover_schema() queries Oracle data dictionary at startup.
# build_context()   assembles the Gemini prompt context.

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from flask import current_app
from oracle.schema_metadata import ORACLE_RULES, SAMPLE_QUERIES


def discover_schema() -> dict:
    """
    Query Oracle data dictionary to build a complete schema description.
    Supports multi-schema via ORACLE_SCHEMA env variable.
    Samples distinct values for low-cardinality VARCHAR2 columns.
    """
    conn   = None
    cursor = None

    target_schema = os.environ.get(
        "ORACLE_SCHEMA",
        os.environ.get("ORACLE_USER", "")
    ).upper()

    try:
        conn   = current_app.pool.acquire()
        cursor = conn.cursor()

        # ── Step 1: all tables ─────────────────────────────────
        cursor.execute("""
            SELECT table_name, num_rows
            FROM   all_tables
            WHERE  owner = :schema
            ORDER  BY table_name
        """, schema=target_schema)
        tables_raw = cursor.fetchall()

        if not tables_raw:
            current_app.logger.warning(
                f"discover_schema: no tables found for schema '{target_schema}'."
            )
            return {}

        schema = {}
        for table_name, num_rows in tables_raw:
            schema[table_name] = {
                "columns":      [],
                "foreign_keys": [],
                "row_count":    num_rows or 0,
            }

        # ── Step 2: all columns ────────────────────────────────
        cursor.execute("""
            SELECT c.table_name,
                   c.column_name,
                   c.data_type,
                   c.data_length,
                   c.data_precision,
                   c.data_scale,
                   c.nullable,
                   c.column_id
            FROM   all_tab_columns c
            WHERE  c.owner = :schema
            ORDER  BY c.table_name, c.column_id
        """, schema=target_schema)
        columns_raw = cursor.fetchall()

        for (table_name, col_name, data_type, data_length,
             data_precision, data_scale, nullable, col_id) in columns_raw:

            if table_name not in schema:
                continue

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
                "name":            col_name,
                "type":            type_str,
                "nullable":        nullable == "Y",
                "is_pk":           False,
                "distinct_values": [],
            })

        # ── Step 3: primary keys ───────────────────────────────
        cursor.execute("""
            SELECT cc.table_name, cc.column_name
            FROM   all_constraints  c
            JOIN   all_cons_columns cc
                   ON  cc.constraint_name = c.constraint_name
                   AND cc.owner           = c.owner
            WHERE  c.constraint_type = 'P'
            AND    c.owner           = :schema
            ORDER  BY cc.table_name, cc.position
        """, schema=target_schema)

        for table_name, col_name in cursor.fetchall():
            if table_name not in schema:
                continue
            for col in schema[table_name]["columns"]:
                if col["name"] == col_name:
                    col["is_pk"] = True

        # ── Step 4: foreign keys ───────────────────────────────
        cursor.execute("""
            SELECT uc.table_name,
                   ucc.column_name,
                   uc2.table_name   AS ref_table,
                   ucc2.column_name AS ref_column
            FROM   all_constraints  uc
            JOIN   all_cons_columns ucc
                   ON  ucc.constraint_name = uc.constraint_name
                   AND ucc.owner           = uc.owner
            JOIN   all_constraints  uc2
                   ON  uc2.constraint_name = uc.r_constraint_name
            JOIN   all_cons_columns ucc2
                   ON  ucc2.constraint_name = uc2.constraint_name
                   AND ucc2.owner           = uc2.owner
            WHERE  uc.constraint_type = 'R'
            AND    uc.owner           = :schema
            ORDER  BY uc.table_name
        """, schema=target_schema)

        for table_name, col_name, ref_table, ref_col in cursor.fetchall():
            if table_name not in schema:
                continue
            schema[table_name]["foreign_keys"].append(
                f"{table_name}.{col_name} references {ref_table}.{ref_col}"
            )

        # ── Step 5: sample distinct values ────────────────────
        CATEGORICAL_HINTS = [
            "STATUS", "TYPE", "CATEGORY", "METHOD", "MODE",
            "GENDER", "ROLE", "STATE", "FLAG", "CODE", "LEVEL",
            "PRIORITY", "CLASS", "KIND", "GROUP",
        ]

        for table_name, meta in schema.items():
            for col in meta["columns"]:
                if col["is_pk"]:
                    continue
                if "VARCHAR2" not in col["type"]:
                    continue
                col_upper = col["name"].upper()
                is_categorical = any(
                    hint in col_upper for hint in CATEGORICAL_HINTS
                )
                if not is_categorical:
                    continue

                try:
                    cursor.execute(f"""
                        SELECT DISTINCT {col['name']}
                        FROM   {target_schema}.{table_name}
                        WHERE  {col['name']} IS NOT NULL
                        FETCH  FIRST 20 ROWS ONLY
                    """)
                    values = [
                        str(row[0]) for row in cursor.fetchall()
                        if row[0] is not None
                    ]
                    col["distinct_values"] = sorted(values)
                except Exception as e:
                    current_app.logger.warning(
                        f"Value sampling failed for "
                        f"{table_name}.{col['name']}: {e}"
                    )

        current_app.logger.info(
            f"discover_schema: {len(schema)} tables, "
            f"schema='{target_schema}'"
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
    """
    schema = getattr(current_app, "schema_cache", None)
    if not schema:
        current_app.logger.warning(
            "build_context: schema_cache missing, re-running discovery."
        )
        schema = discover_schema()
        current_app.schema_cache = schema

    relevant_tables = _get_relevant_tables(question, schema)

    parts = []

    parts.append("=== ORACLE 19c SQL RULES — FOLLOW EXACTLY ===")
    for rule in ORACLE_RULES:
        parts.append(f"- {rule}")
    parts.append("")

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
            pk_marker   = " [PK]"     if col["is_pk"]       else ""
            null_marker = " NOT NULL" if not col["nullable"] else ""
            line = (
                f"  {col['name']}: "
                f"{col['type']}{pk_marker}{null_marker}"
            )
            if col["distinct_values"]:
                vals = ", ".join(f"'{v}'" for v in col["distinct_values"])
                line += f"  -- valid values: {vals}"
            parts.append(line)

        if meta["foreign_keys"]:
            parts.append("Foreign keys:")
            for fk in meta["foreign_keys"]:
                parts.append(f"  {fk}")

        parts.append("")

    parts.append("=== JOIN CONDITIONS ===")
    join_count = 0
    for table_name in relevant_tables:
        if table_name not in schema:
            continue
        for fk in schema[table_name]["foreign_keys"]:
            parts.append(f"- {fk}")
            join_count += 1
    if join_count == 0:
        parts.append(
            "No foreign keys detected — infer joins from column names."
        )
    parts.append("")

    parts.append("=== EXAMPLE QUERIES (style reference) ===")
    for ex in SAMPLE_QUERIES:
        parts.append(f"Question: {ex['question']}")
        parts.append(f"SQL:\n{ex['sql']}")
        parts.append("")

    return "\n".join(parts)


def _get_relevant_tables(question: str, schema: dict) -> list:
    """Score and rank tables by relevance to the question."""
    question_upper = question.upper()
    scores = {table: 0 for table in schema}

    for table_name, meta in schema.items():
        if table_name in question_upper:
            scores[table_name] += 10
        for col in meta["columns"]:
            if col["name"] in question_upper:
                scores[table_name] += 3
        if meta["foreign_keys"]:
            scores[table_name] += 1
        if meta["row_count"] and meta["row_count"] > 100:
            scores[table_name] += 1

    ranked   = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    selected = [t for t, s in ranked[:5]]

    if schema:
        largest = max(
            schema.items(),
            key=lambda x: x[1].get("row_count") or 0
        )
        if largest[0] not in selected:
            selected[-1] = largest[0]

    return selected