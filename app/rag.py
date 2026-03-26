# app/rag.py
#
# Retrieval-Augmented Generation — context builder.
# Reads schema_metadata.py and assembles the prompt context
# that gets injected into every Gemini call.
#
# Why not just dump the entire schema into every prompt?
# Two reasons:
#   1. Gemini free tier has input token limits. A huge context
#      wastes tokens and can hit the limit on complex questions.
#   2. Less context = less confusion. If the question is about
#      payments, injecting full ORDER_ITEMS details adds noise.
#
# The trade-off: keyword matching is imperfect. If a question
# uses unusual phrasing it might miss a relevant table.
# The fix: always include ORDERS as the central table, and
# include all sample queries regardless of question topic.

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from oracle.schema_metadata import (
    TABLES,
    JOIN_PATHS,
    ORACLE_RULES,
    SAMPLE_QUERIES,
    get_tables_for_question,
)


def build_context(question: str) -> str:
    """
    Build a focused schema context string for the given question.

    This string becomes the system knowledge injected into the
    Gemini prompt. Quality here directly determines SQL quality.

    Structure of the output:
        1. Oracle rules (always included — prevent syntax mistakes)
        2. Relevant table definitions (filtered by keyword match)
        3. Join paths between relevant tables
        4. Few-shot example queries (always included)
    """
    relevant_tables = get_tables_for_question(question)

    parts = []

    # ── Section 1: Oracle-specific rules ──────────────────────
    # Always injected first. These prevent the most common
    # LLM mistakes: using LIMIT instead of FETCH FIRST,
    # using NOW() instead of SYSDATE, etc.
    parts.append("=== ORACLE 19c SQL RULES — FOLLOW EXACTLY ===")
    for rule in ORACLE_RULES:
        parts.append(f"- {rule}")
    parts.append("")

    # ── Section 2: Relevant table definitions ─────────────────
    parts.append("=== SCHEMA TABLES ===")
    for table_name in relevant_tables:
        if table_name not in TABLES:
            continue
        meta = TABLES[table_name]
        parts.append(f"TABLE: {table_name}")
        parts.append(f"Purpose: {meta['description']}")
        parts.append("Columns:")
        for col, desc in meta["columns"].items():
            parts.append(f"  {col}: {desc}")
        parts.append("")

    # ── Section 3: Relevant join paths ────────────────────────
    # Only include join paths that connect the relevant tables.
    # No point showing CUSTOMERS↔PAYMENTS join if the question
    # is only about products.
    relevant_set = set(relevant_tables)
    parts.append("=== JOIN CONDITIONS ===")
    for jp in JOIN_PATHS:
        jp_tables = set(jp["tables"])
        # Include if at least 2 of the join's tables are relevant
        if len(jp_tables & relevant_set) >= 2:
            parts.append(
                f"{' + '.join(jp['tables'])}: "
                f"{jp['condition']}"
                f"  -- {jp['note']}"
            )
    parts.append("")

    # ── Section 4: Few-shot examples ──────────────────────────
    # Always included. These are the single most powerful signal
    # for getting correct Oracle syntax from the LLM.
    # Each example shows: correct JOIN style, correct FETCH FIRST,
    # correct TO_CHAR for dates, correct column naming.
    parts.append("=== EXAMPLE QUERIES (use these as style reference) ===")
    for ex in SAMPLE_QUERIES:
        parts.append(f"Question: {ex['question']}")
        parts.append(f"SQL:\n{ex['sql']}")
        parts.append("")

    return "\n".join(parts)


def get_relevant_tables(question: str) -> list:
    """Expose table selection for logging and debugging."""
    return get_tables_for_question(question)