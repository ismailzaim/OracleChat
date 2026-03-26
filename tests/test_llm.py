# tests/test_llm.py
#
# Unit tests for the LLM SQL extraction logic.
# These tests never call the real Gemini API —
# they test _extract_sql() which is pure Python string processing.

import pytest
from app.llm import _extract_sql, LLMError


class TestExtractSQL:

    def test_clean_select_passes_through(self):
        sql = "SELECT * FROM customers"
        assert _extract_sql(sql) == "SELECT * FROM customers"

    def test_strips_markdown_code_fence(self):
        raw = "```sql\nSELECT * FROM customers\n```"
        result = _extract_sql(raw)
        assert result == "SELECT * FROM customers"

    def test_strips_code_fence_without_language(self):
        raw = "```\nSELECT * FROM orders\n```"
        result = _extract_sql(raw)
        assert result == "SELECT * FROM orders"

    def test_strips_trailing_semicolon(self):
        raw = "SELECT * FROM customers;"
        result = _extract_sql(raw)
        assert ";" not in result

    def test_strips_preamble_text(self):
        raw = "Here is the SQL query:\nSELECT * FROM customers"
        result = _extract_sql(raw)
        assert result.startswith("SELECT")

    def test_strips_trailing_explanation(self):
        raw = "SELECT * FROM customers\n\nThis query returns all customers."
        result = _extract_sql(raw)
        assert "This query" not in result

    def test_raises_llm_error_when_no_select(self):
        with pytest.raises(LLMError):
            _extract_sql("I cannot generate SQL for that request.")

    def test_raises_llm_error_on_empty_string(self):
        with pytest.raises(LLMError):
            _extract_sql("")

    def test_multiline_sql_preserved(self):
        raw = """
SELECT c.first_name,
       SUM(o.total_amount) AS revenue
FROM   customers c
JOIN   orders o ON o.customer_id = c.customer_id
GROUP  BY c.first_name
ORDER  BY revenue DESC
FETCH  FIRST 5 ROWS ONLY
        """.strip()
        result = _extract_sql(raw)
        assert "FETCH  FIRST 5 ROWS ONLY" in result
        assert result.startswith("SELECT")

    def test_case_insensitive_select_detection(self):
        raw = "select * from customers"
        result = _extract_sql(raw)
        assert result == "select * from customers"