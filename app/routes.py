# app/routes.py
from flask import Blueprint, request, jsonify, render_template, current_app
from app.executor import run_query, validate_sql, ExecutorError
from app.formatter import format_result
from app.rag import build_context
from app.llm import (
    generate_sql_with_history,
    generate_sql_with_retry,
    generate_explanation,
    LLMError,
)
import oracledb

main = Blueprint("main", __name__)


@main.route("/")
def index():
    return render_template("index.html")


@main.route("/health")
def health():
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


@main.route("/schema")
def schema():
    """Returns the auto-discovered schema as JSON."""
    schema_cache = getattr(current_app, "schema_cache", {})
    summary = {}
    for table, meta in schema_cache.items():
        summary[table] = {
            "columns":   [c["name"] for c in meta["columns"]],
            "row_count": meta["row_count"],
            "fk_count":  len(meta["foreign_keys"]),
        }
    return jsonify({
        "tables_discovered": len(summary),
        "schema": summary,
    }), 200


@main.route("/query", methods=["POST"])
def query():
    # ── Parse request ──────────────────────────────────────────
    body = request.get_json(silent=True)
    if not body or "question" not in body:
        return jsonify({
            "error": "Request body must be JSON with a 'question' field."
        }), 400

    question = body["question"].strip()
    if not question:
        return jsonify({"error": "Question cannot be empty."}), 400

    history = body.get("history", [])

    # ── RAG + LLM pipeline ─────────────────────────────────────
    try:
        context = build_context(question)
        sql     = generate_sql_with_history(question, context, history)
    except LLMError as e:
        return jsonify({
            "error": f"Could not generate SQL: {str(e)}"
        }), 422
    except Exception as e:
        current_app.logger.error(f"LLM error: {e}")
        return jsonify({
            "error": "LLM service unavailable. Try again in a moment."
        }), 503

    # ── Validate SQL before execution ──────────────────────────
    is_valid, error_msg = validate_sql(sql)
    if not is_valid:
        current_app.logger.warning(
            f"Generated SQL failed validation: {error_msg}\nSQL: {sql}"
        )
        return jsonify({
            "error":  "The generated SQL has a syntax error. "
                      "Try rephrasing your question.",
            "sql":    sql,
            "detail": error_msg,
        }), 422

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
            "error": "The generated SQL caused a database error. "
                     "Try rephrasing your question.",
            "sql":   sql,
        }), 500

    # ── Retry if zero rows ─────────────────────────────────────
    if result["row_count"] == 0:
        sql, result["columns"], result["rows"] = generate_sql_with_retry(
            question, context,
            result["columns"], result["rows"],
        )
        result["row_count"] = len(result["rows"])

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
        "turn":        {"question": question, "sql": sql},
    }), 200