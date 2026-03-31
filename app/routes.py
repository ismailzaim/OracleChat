# app/routes.py
#
# HTTP endpoints for OracleChat.
# All routes live in the 'main' Blueprint.
#
# Endpoints:
#   GET  /        — serves the chat UI
#   GET  /health  — confirms app and DB connection are alive
#   POST /query   — accepts a question, returns SQL results as JSON

from flask import Blueprint, request, jsonify, render_template, current_app
from app.executor import run_query, ExecutorError
from app.formatter import format_result
from app.rag import build_context
from app.llm import generate_sql, generate_explanation, LLMError
import oracledb

main = Blueprint("main", __name__)

@main.route("/schema")
def schema():
    """
    Returns the auto-discovered schema as JSON.
    Useful for debugging and for users to verify the app
    has correctly read their database structure.
    """
    schema_cache = getattr(current_app, "schema_cache", {})
    summary = {}
    for table, meta in schema_cache.items():
        summary[table] = {
            "columns":    [c["name"] for c in meta["columns"]],
            "row_count":  meta["row_count"],
            "fk_count":   len(meta["foreign_keys"]),
        }
    return jsonify({
        "tables_discovered": len(summary),
        "schema": summary,
    }), 200
@main.route("/")
def index():
    """Serve the chat UI."""
    return render_template("index.html")


@main.route("/health")
def health():
    """
    Health check endpoint.
    Used by Docker, Render.com, and CI/CD to verify the app is alive.
    Checks both Flask (process alive) and Oracle (pool can execute).
    """
    try:
        result = run_query("SELECT 1 AS status FROM dual")
        return jsonify({
            "status":   "ok",
            "database": "connected",
            "rows":     result["row_count"],
        }), 200
    except Exception as e:
        return jsonify({
            "status":   "error",
            "database": "unreachable",
            "detail":   str(e),
        }), 503


@main.route("/query", methods=["POST"])
def query():
    """
    Main endpoint — receives a natural language question,
    returns query results as JSON.

    Request body (JSON):
        { "question": "who are the top customers?" }

    Response (JSON):
        {
            "question":    "who are the top customers?",
            "sql":         "SELECT ...",
            "explanation": "This query returns...",
            "chart_type":  "bar",
            "chart_data":  { "labels": [...], "datasets": [...] },
            "table_data":  [ {...}, {...} ],
            "columns":     ["CUSTOMER_NAME", "CITY", ...],
            "row_count":   5
        }
    """
    # ── Parse request ──────────────────────────────────────────
    body = request.get_json(silent=True)
    if not body or "question" not in body:
        return jsonify({
            "error": "Request body must be JSON with a 'question' field."
        }), 400

    question = body["question"].strip()
    if not question:
        return jsonify({"error": "Question cannot be empty."}), 400

    # ── RAG + LLM pipeline ─────────────────────────────────────
    try:
        context = build_context(question)
        sql     = generate_sql(question, context)
    except LLMError as e:
        return jsonify({
            "error": f"Could not generate SQL: {str(e)}"
        }), 422
    except Exception as e:
        current_app.logger.error(f"LLM error: {e}")
        return jsonify({
            "error": "LLM service unavailable. Try again in a moment."
        }), 503

    # ── Execute ────────────────────────────────────────────────
    try:
        result = run_query(sql)
    except ExecutorError as e:
        return jsonify({"error": str(e)}), 400
    except oracledb.Error as e:
        current_app.logger.error(
            f"Oracle error on generated SQL: {e}\nSQL was: {sql}"
        )
        return jsonify({
            "error": "The generated SQL caused a database error. Try rephrasing your question.",
            "sql":   sql,
        }), 500

    # ── Format for frontend ────────────────────────────────────
    formatted   = format_result(result["columns"], result["rows"])
    explanation = generate_explanation(question, sql, formatted["row_count"])

    return jsonify({
        "question":    question,
        "sql":         sql,
        "explanation": explanation,
        "chart_type":  formatted["chart_type"],
        "chart_data":  formatted["chart_data"],
        "table_data":  formatted["table_data"],
        "columns":     formatted["columns"],
        "row_count":   formatted["row_count"],
    }), 200