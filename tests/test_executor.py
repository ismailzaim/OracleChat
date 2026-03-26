# tests/test_executor.py
#
# Unit tests for the SQL safety layer.
# These tests do NOT need a real Oracle connection —
# they test the validation logic in isolation.
# The one integration test that hits Oracle is marked separately.

import pytest
from unittest.mock import MagicMock, patch


# ── Tests for _is_safe() ───────────────────────────────────────
# We import the private function directly because it is the core
# of our security model and deserves explicit coverage.

from app.executor import _is_safe, ExecutorError


class TestIsSafe:

    def test_valid_select_passes(self):
        ok, reason = _is_safe("SELECT * FROM customers")
        assert ok is True
        assert reason == ""

    def test_select_with_join_passes(self):
        sql = """
            SELECT c.first_name, SUM(o.total_amount)
            FROM customers c
            JOIN orders o ON o.customer_id = c.customer_id
            GROUP BY c.first_name
        """
        ok, reason = _is_safe(sql)
        assert ok is True

    def test_select_with_fetch_first_passes(self):
        sql = "SELECT * FROM products FETCH FIRST 10 ROWS ONLY"
        ok, reason = _is_safe(sql)
        assert ok is True

    def test_delete_is_rejected(self):
        ok, reason = _is_safe("DELETE FROM customers")
        assert ok is False
        assert "DELETE" in reason or "Only SELECT" in reason

    def test_drop_is_rejected(self):
        ok, reason = _is_safe("DROP TABLE customers")
        assert ok is False

    def test_insert_is_rejected(self):
        ok, reason = _is_safe("INSERT INTO customers VALUES (1, 'test')")
        assert ok is False

    def test_update_is_rejected(self):
        ok, reason = _is_safe("UPDATE customers SET status = 'BANNED'")
        assert ok is False

    def test_truncate_is_rejected(self):
        ok, reason = _is_safe("TRUNCATE TABLE customers")
        assert ok is False

    def test_select_with_embedded_delete_is_rejected(self):
        # The LLM could theoretically generate this
        sql = "SELECT * FROM customers; DELETE FROM customers"
        ok, reason = _is_safe(sql)
        assert ok is False

    def test_comment_before_delete_is_rejected(self):
        # Adversarial input: hide DELETE behind a comment
        sql = "-- get customers\nDELETE FROM customers"
        ok, reason = _is_safe(sql)
        assert ok is False

    def test_empty_query_is_rejected(self):
        ok, reason = _is_safe("")
        assert ok is False

    def test_comment_only_is_rejected(self):
        ok, reason = _is_safe("-- just a comment")
        assert ok is False

    def test_case_insensitive_detection(self):
        # Forbidden keywords must be caught regardless of case
        ok, _ = _is_safe("select * from customers; drop table orders")
        assert ok is False

    def test_alter_is_rejected(self):
        ok, _ = _is_safe("ALTER TABLE customers ADD COLUMN age NUMBER")
        assert ok is False

    def test_grant_is_rejected(self):
        ok, _ = _is_safe("GRANT ALL ON customers TO public")
        assert ok is False


# ── Tests for run_query() ─────────────────────────────────────
# These mock the Oracle pool so they run without a real database.

class TestRunQuery:

    def _make_mock_app(self, columns, rows):
        """Helper: build a mock Flask app with a fake Oracle pool."""
        mock_cursor = MagicMock()
        mock_cursor.description = [(col, None, None, None, None, None, None)
                                    for col in columns]
        mock_cursor.fetchall.return_value = rows

        mock_conn = MagicMock()
        mock_pool  = MagicMock()
        mock_pool.acquire.return_value = mock_conn
        mock_conn.cursor.return_value  = mock_cursor

        mock_app        = MagicMock()
        mock_app.pool   = mock_pool
        mock_app.logger = MagicMock()
        return mock_app, mock_cursor, mock_conn, mock_pool

    def test_valid_query_returns_columns_and_rows(self):
        mock_app, _, _, _ = self._make_mock_app(
            columns=["CITY", "TOTAL_ORDERS"],
            rows=[("Casablanca", 120), ("Rabat", 85)],
        )
        with patch("app.executor.current_app", mock_app):
            from app.executor import run_query
            result = run_query("SELECT city, COUNT(*) FROM orders GROUP BY city")

        assert result["columns"]   == ["CITY", "TOTAL_ORDERS"]
        assert result["row_count"] == 2
        assert result["rows"][0]   == ("Casablanca", 120)

    def test_unsafe_query_raises_executor_error(self):
        from app.executor import run_query
        with pytest.raises(ExecutorError):
            # No mock needed — _is_safe() fires before any DB call
            with patch("app.executor.current_app", MagicMock()):
                run_query("DELETE FROM customers")

    def test_connection_always_released(self):
        """Pool connection must be released even if fetchall raises."""
        mock_app, mock_cursor, mock_conn, mock_pool = self._make_mock_app(
            columns=["ID"], rows=[]
        )
        mock_cursor.fetchall.side_effect = Exception("DB exploded")

        with patch("app.executor.current_app", mock_app):
            from app.executor import run_query
            with pytest.raises(Exception):
                run_query("SELECT 1 FROM dual")

        # The critical assertion: release() was called despite the error
        mock_pool.release.assert_called_once_with(mock_conn)