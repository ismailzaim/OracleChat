# app/llm.py
import os
import re
from google import genai
from google.genai import types
from flask import current_app

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY", ""))
    return _client


MODEL = "gemini-2.5-flash"

_PROMPT_TEMPLATE = """
You are an expert Oracle Database 19c SQL generator.
You are given a schema description and a natural language question.
Your task is to write a single, correct Oracle 19c SQL SELECT statement.

{context}

=== YOUR TASK ===
Write a single Oracle 19c SQL SELECT query that answers this question:
"{question}"

=== STRICT OUTPUT RULES ===
- Output ONLY the raw SQL statement. Nothing else.
- Do NOT include any explanation, commentary, or markdown.
- Do NOT wrap the SQL in ```sql``` code blocks.
- Do NOT add a semicolon at the end.
- The query MUST start with SELECT.
- Use only the tables and columns defined in the schema above.
- Follow all Oracle SQL rules listed above exactly.
""".strip()


class LLMError(Exception):
    pass


def _extract_sql(raw: str) -> str:
    text = raw.strip()
    text = re.sub(r'```(?:sql)?\s*', '', text, flags=re.IGNORECASE)
    text = text.replace('```', '')

    match = re.search(r'\bSELECT\b', text, re.IGNORECASE)
    if not match:
        raise LLMError(f"No SELECT found in response: {text[:200]}")
    text = text[match.start():]
    text = text.rstrip().rstrip(';').rstrip()

    lines = text.split('\n')
    sql_lines = []
    for line in lines:
        if line.strip() == '' and sql_lines:
            break
        sql_lines.append(line)

    result = '\n'.join(sql_lines).strip()
    if not result:
        raise LLMError("Extracted SQL is empty after cleaning.")
    return result


def generate_sql(question: str, context: str) -> str:
    """Call Gemini and return a clean Oracle SQL SELECT string."""
    client = _get_client()
    prompt = _PROMPT_TEMPLATE.format(context=context, question=question)

    current_app.logger.info(f"Calling Gemini for: '{question}'")

    response = client.models.generate_content(
        model=MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.1,
            max_output_tokens=1024,
        ),
    )

    raw = response.text
    current_app.logger.info(f"Gemini raw: {raw[:300]}")

    sql = _extract_sql(raw)
    current_app.logger.info(f"Extracted SQL: {sql[:200]}")
    return sql


def generate_sql_with_history(
    question: str,
    context: str,
    history: list,
) -> str:
    """
    Generate SQL taking previous questions into account.
    history = [{"question": "...", "sql": "..."}, ...]
    """
    client = _get_client()

    history_text = ""
    if history:
        recent = history[-3:]
        history_text = "\n=== CONVERSATION HISTORY ===\n"
        for i, turn in enumerate(recent, 1):
            history_text += (
                f"Turn {i}:\n"
                f"  Question: {turn['question']}\n"
                f"  SQL: {turn['sql']}\n\n"
            )
        history_text += (
            "Use this history to understand references like "
            "'their', 'those', 'same', 'also', 'and'. "
            "Build on previous queries when the new question refers to them.\n"
        )

    prompt = _PROMPT_TEMPLATE.format(
        context=context + history_text,
        question=question,
    )

    response = client.models.generate_content(
        model=MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.1,
            max_output_tokens=1024,
        ),
    )

    return _extract_sql(response.text)


def generate_sql_with_retry(
    question: str,
    context: str,
    columns: list,
    rows: list,
) -> tuple:
    """
    If the first SQL attempt returned zero rows, retry with a
    corrected prompt that emphasises valid column values.
    Returns (sql, columns, rows).
    """
    from app.executor import run_query, ExecutorError
    import oracledb

    if rows:
        return context, columns, rows

    current_app.logger.info(
        "Zero rows returned — attempting retry with corrected context."
    )

    retry_addition = """
=== IMPORTANT: PREVIOUS ATTEMPT RETURNED ZERO ROWS ===
Your previous SQL returned zero rows.
This usually means a filter value was wrong (wrong case, wrong spelling).
Check the valid values listed for each column above and use EXACTLY
those values in your WHERE clause — including correct uppercase.
Try a different approach.
""".strip()

    retry_context = context + "\n\n" + retry_addition

    try:
        retry_sql    = generate_sql(question, retry_context)
        retry_result = run_query(retry_sql)
        return (
            retry_sql,
            retry_result["columns"],
            retry_result["rows"],
        )
    except (ExecutorError, oracledb.Error, LLMError) as e:
        current_app.logger.warning(f"Retry also failed: {e}")
        return context, columns, rows


def generate_explanation(question: str, sql: str, row_count: int) -> str:
    """Generate a plain English explanation of the query result."""
    client = _get_client()
    prompt = f"""
In one or two sentences, explain what this Oracle SQL query does
and summarise the result in plain English for a non-technical user.

Question asked: "{question}"
SQL executed: {sql}
Number of rows returned: {row_count}

Output only the explanation. No SQL, no formatting, no markdown.
""".strip()

    try:
        response = client.models.generate_content(
            model=MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.3,
                max_output_tokens=150,
            ),
        )
        return response.text.strip()
    except Exception:
        return f"Query returned {row_count} row(s)."