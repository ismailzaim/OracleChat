# tests/test_routes.py
#
# Integration tests for the HTTP layer.
# These mock the LLM and executor so they run without
# Oracle or Gemini — testing only the route logic itself.

import pytest
import json
from unittest.mock import patch, MagicMock


@pytest.fixture
def client():
    """
    Create a Flask test client with a mocked Oracle pool.
    The pool mock prevents create_app() from trying to connect
    to a real Oracle database during tests.
    """
    with patch("app.oracledb.create_pool") as mock_pool:
        mock_pool.return_value = MagicMock()
        from app import create_app
        app = create_app()
        app.config["TESTING"] = True
        with app.test_client() as c:
            yield c


class TestHealthEndpoint:

    def test_health_returns_200_when_db_ok(self, client):
        mock_result = {"row_count": 1, "columns": ["STATUS"], "rows": [(1,)]}
        with patch("app.routes.run_query", return_value=mock_result):
            res = client.get("/health")
        assert res.status_code == 200
        data = json.loads(res.data)
        assert data["status"]   == "ok"
        assert data["database"] == "connected"

    def test_health_returns_503_when_db_down(self, client):
        with patch("app.routes.run_query", side_effect=Exception("no connection")):
            res = client.get("/health")
        assert res.status_code == 503
        data = json.loads(res.data)
        assert data["status"] == "error"


class TestQueryEndpoint:

    def _mock_pipeline(self, sql="SELECT 1 FROM dual"):
        """Return a set of patches that simulate a successful pipeline."""
        mock_result = {
            "columns":   ["CITY", "TOTAL_ORDERS"],
            "rows":      [("Casablanca", 120), ("Rabat", 85)],
            "row_count": 2,
        }
        return {
            "build_context":      MagicMock(return_value="schema context"),
            "generate_sql":       MagicMock(return_value=sql),
            "run_query":          MagicMock(return_value=mock_result),
            "generate_explanation": MagicMock(return_value="Returns orders by city."),
        }

    def test_missing_question_returns_400(self, client):
        res = client.post("/query",
                          data=json.dumps({}),
                          content_type="application/json")
        assert res.status_code == 400

    def test_empty_question_returns_400(self, client):
        res = client.post("/query",
                          data=json.dumps({"question": "   "}),
                          content_type="application/json")
        assert res.status_code == 400

    def test_non_json_body_returns_400(self, client):
        res = client.post("/query",
                          data="not json",
                          content_type="text/plain")
        assert res.status_code == 400

    def test_successful_query_returns_200(self, client):
        mocks = self._mock_pipeline()
        with patch("app.routes.build_context",       mocks["build_context"]), \
             patch("app.routes.generate_sql",         mocks["generate_sql"]), \
             patch("app.routes.run_query",            mocks["run_query"]), \
             patch("app.routes.generate_explanation", mocks["generate_explanation"]):
            res = client.post("/query",
                              data=json.dumps({"question": "orders by city"}),
                              content_type="application/json")

        assert res.status_code == 200
        data = json.loads(res.data)
        assert "sql"         in data
        assert "chart_data"  in data
        assert "table_data"  in data
        assert "explanation" in data
        assert data["row_count"] == 2

    def test_llm_error_returns_422(self, client):
        from app.llm import LLMError
        with patch("app.routes.build_context", return_value="ctx"), \
             patch("app.routes.generate_sql",
                   side_effect=LLMError("no SELECT found")):
            res = client.post("/query",
                              data=json.dumps({"question": "test"}),
                              content_type="application/json")
        assert res.status_code == 422

    def test_llm_unavailable_returns_503(self, client):
        with patch("app.routes.build_context", return_value="ctx"), \
             patch("app.routes.generate_sql",
                   side_effect=Exception("connection timeout")):
            res = client.post("/query",
                              data=json.dumps({"question": "test"}),
                              content_type="application/json")
        assert res.status_code == 503

    def test_executor_error_returns_400(self, client):
        from app.executor import ExecutorError
        with patch("app.routes.build_context",  return_value="ctx"), \
             patch("app.routes.generate_sql",   return_value="SELECT 1 FROM dual"), \
             patch("app.routes.run_query",
                   side_effect=ExecutorError("forbidden keyword")):
            res = client.post("/query",
                              data=json.dumps({"question": "test"}),
                              content_type="application/json")
        assert res.status_code == 400