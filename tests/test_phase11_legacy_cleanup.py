from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from app.conversation.conversation_memory import ConversationMemory
from app.core.config import DatabaseConfig, settings
from app.database.connection import test_connection as run_test_connection
from app.database.metadata_cache import MetadataCache
from app.database.metadata_service import DatabaseMetadata, TableMetadata
from app.database.query_service import DatabaseQueryService
from app.database.relationship_cache import RelationshipCache
from app.database.relationship_service import RelationshipResult
from app.database.schema import ColumnInfo, DatabaseSchema, TableInfo
from app.database.schema_fingerprint import SchemaFingerprint
from app.database.semantic_query_cache import SemanticQueryCache
from app.database.sql_executor import SQLQueryExecutor
from app.orchestration.database_orchestrator import DatabaseOrchestrator
from app.query.analyzer import QuestionAnalyzer
from app.query.answer_generator import AnswerGenerator
from app.query.result_validator import QueryResultValidator
from app.query.schema import QueryPlan
from app.query.validator import QueryPlanValidator
from app.web import app


# =============================================================================
# 1. Active SQL Server Application Imports Successfully
# =============================================================================

def test_active_sql_server_application_imports_successfully():
    """All active SQL Server application modules import successfully without legacy residue."""
    assert app is not None
    assert DatabaseOrchestrator is not None
    assert DatabaseQueryService is not None
    assert SQLQueryExecutor is not None
    assert QuestionAnalyzer is not None
    assert QueryPlanValidator is not None
    assert QueryResultValidator is not None
    assert AnswerGenerator is not None
    assert ConversationMemory is not None
    assert DatabaseConfig is not None


# =============================================================================
# 2. FastAPI Application Starts
# =============================================================================

def test_fastapi_application_starts():
    """FastAPI application instantiates and creates a valid test client."""
    client = TestClient(app)
    assert client is not None
    assert app.title == "Database AI Chatbot"


# =============================================================================
# 3. Health Route Remains Functional
# =============================================================================

def test_health_route_remains_functional():
    """The /health endpoint returns HTTP 200 with status ok."""
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# =============================================================================
# 4. Database API Remains Registered (/ask/database)
# =============================================================================

def test_database_api_remains_registered():
    """The /ask/database endpoint is registered and responds to POST requests."""
    client = TestClient(app)
    # Sending an empty POST should produce validation error (422), proving route is active.
    response = client.post("/ask/database", json={})
    assert response.status_code == 422

    response_empty_q = client.post("/ask/database", json={"question": ""})
    assert response_empty_q.status_code == 400

    # Check openapi paths explicitly
    paths = list(app.openapi()["paths"].keys())
    assert "/ask/database" in paths


# =============================================================================
# 5. SQL Server Connection Remains Functional
# =============================================================================

def test_sql_server_connection_remains_functional():
    """The database connection test helper succeeds with a valid mock connection."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_row = MagicMock()
    mock_row.database_name = "mnghealthreportingdb"
    mock_cursor.fetchone.return_value = mock_row
    mock_conn.cursor.return_value = mock_cursor
    mock_conn.__enter__.return_value = mock_conn

    with patch("app.database.connection.pyodbc.connect", return_value=mock_conn):
        result = run_test_connection()
        assert result.get("database_name") == "mnghealthreportingdb"
        assert "server_name" in result


# =============================================================================
# 6. Metadata Loading Remains Functional
# =============================================================================

def test_metadata_loading_remains_functional(tmp_path: Path):
    """Metadata loading and caching function deterministically for SQL Server schema."""
    cache = MetadataCache(cache_dir=tmp_path / "metadata")
    fingerprint = "fp_sqlserver_test"
    test_schema = DatabaseSchema(
        tables=[
            TableInfo(schema_name="dbo", table_name="patients", columns=[ColumnInfo("id", "int", False, 1)]),
            TableInfo(schema_name="dbo", table_name="appointments", columns=[ColumnInfo("id", "int", False, 1)]),
        ]
    )
    meta = DatabaseMetadata(
        database_name="mnghealthreportingdb",
        server_name="localhost",
        schema=test_schema,
    )
    cache.save(meta, fingerprint=fingerprint)
    cached = cache.load(
        server_name="localhost",
        database_name="mnghealthreportingdb",
        fingerprint=fingerprint,
    )
    assert cached is not None
    assert cached.database_name == "mnghealthreportingdb"
    assert len(cached.tables) == 2


# =============================================================================
# 7. Normal Database Query Remains Functional
# =============================================================================

def test_normal_database_query_remains_functional():
    """SQLQueryExecutor compiles and executes queries returning native records."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.description = [("id",), ("name",)]
    mock_cursor.fetchall.return_value = [(1, "Alpha"), (2, "Beta")]
    mock_conn.cursor.return_value = mock_cursor
    mock_conn.__enter__.return_value = mock_conn

    executor = SQLQueryExecutor()
    table = TableInfo(
        schema_name="dbo",
        table_name="customers",
        columns=[
            ColumnInfo("id", "int", False, 1),
            ColumnInfo("name", "nvarchar", True, 2),
        ],
    )
    plan = QueryPlan(
        intent="lookup",
        target_columns=["id", "name"],
    )

    with patch("app.database.sql_executor.get_connection", return_value=mock_conn):
        result = executor.execute(plan, table)
        assert result == [{"id": 1, "name": "Alpha"}, {"id": 2, "name": "Beta"}]


# =============================================================================
# 8. Conversation Memory Remains Functional
# =============================================================================

def test_conversation_memory_remains_functional():
    """ConversationMemory stores context, generates reference IDs, and retrieves context."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    mock_conn.__enter__.return_value = mock_conn

    memory = ConversationMemory()
    with patch("app.conversation.conversation_memory.get_connection", return_value=mock_conn):
        ref_id = memory.save(
            session_id="session_sql_1",
            question="How many patients?",
            result=142,
            plan=QueryPlan(intent="count"),
        )
        assert ref_id is not None
        assert isinstance(ref_id, str)
        assert mock_cursor.execute.called

        # Mock retrieval
        mock_row = MagicMock()
        mock_row.reference_id = ref_id
        mock_row.question = "How many patients?"
        mock_row.result_columns = '["count"]'
        mock_row.result_data = "142"
        mock_row.query_context = '{"plan": {"intent": "count"}}'
        mock_cursor.fetchall.return_value = [mock_row]

        context = memory.get_context("session_sql_1")
        assert context is not None
        assert len(context.get("history", [])) == 1
        assert context["history"][0]["reference_id"] == ref_id

        # Empty session check
        empty_context = memory.get_context("")
        assert empty_context == {}


# =============================================================================
# 9. Semantic Cache Remains Functional
# =============================================================================

def test_semantic_cache_remains_functional(tmp_path: Path):
    """SemanticQueryCache caches and retrieves verified query plans by schema fingerprint."""
    cache = SemanticQueryCache(cache_dir=tmp_path / "query_cache")
    fingerprint = "fp_semantic_test"
    plan = QueryPlan(
        intent="count",
        target_columns=[],
    )

    cache.set(
        question="how many patients are there?",
        server_name="localhost",
        database_name="mnghealthreportingdb",
        schema_fingerprint=fingerprint,
        plan=plan,
    )
    cached = cache.get(
        question="how many patients are there?",
        server_name="localhost",
        database_name="mnghealthreportingdb",
        schema_fingerprint=fingerprint,
    )
    assert cached is not None
    assert cached.intent == "count"


# =============================================================================
# 10. Relationship Cache Remains Functional
# =============================================================================

def test_relationship_cache_remains_functional(tmp_path: Path):
    """RelationshipCache caches and retrieves relationship knowledge by schema fingerprint."""
    cache = RelationshipCache(
        cache_dir=tmp_path / "relationship_cache",
        server_name="localhost",
        database_name="mnghealthreportingdb",
        schema_fingerprint="fp_rel_test",
    )
    rel = RelationshipResult(
        relationship_type="FK",
        status="validated",
        left_schema="dbo",
        left_table="orders",
        left_column="customer_id",
        right_schema="dbo",
        right_table="customers",
        right_column="id",
        reason="Verified FK",
        confidence=1.0,
    )
    cache.set(rel)
    cached = cache.get("dbo", "orders", "customer_id", "dbo", "customers", "id")
    assert cached is not None
    assert cached.status == "validated"


# =============================================================================
# 11. No Active Import References Deleted Legacy Modules
# =============================================================================

def test_no_active_import_references_deleted_legacy_modules():
    """No Python module in app/ imports pandas, openpyxl, xlrd, or non-existent legacy modules."""
    forbidden_modules = {
        "pandas",
        "openpyxl",
        "xlrd",
        "xlsxwriter",
        "pyxlsb",
        "app.excel",
        "app.dataset",
    }

    app_root = Path("app")
    py_files = list(app_root.rglob("*.py"))
    assert len(py_files) > 0

    for py_file in py_files:
        content = py_file.read_text(encoding="utf-8-sig")
        tree = ast.parse(content, filename=str(py_file))

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    module_base = alias.name.split(".")[0]
                    assert alias.name not in forbidden_modules, (
                        f"Forbidden import '{alias.name}' in {py_file}"
                    )
                    assert module_base not in forbidden_modules, (
                        f"Forbidden base import '{module_base}' in {py_file}"
                    )

            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    module_base = node.module.split(".")[0]
                    assert node.module not in forbidden_modules, (
                        f"Forbidden from-import '{node.module}' in {py_file}"
                    )
                    assert module_base not in forbidden_modules, (
                        f"Forbidden base from-import '{module_base}' in {py_file}"
                    )


# =============================================================================
# 12. No Active Route References Deleted Excel Endpoints
# =============================================================================

def test_no_active_route_references_deleted_excel_endpoints():
    """FastAPI route paths contain no references to excel, upload, or sheet endpoints."""
    forbidden_route_tokens = {"excel", "upload", "sheet", "workbook"}
    paths = list(app.openapi()["paths"].keys())

    for path in paths:
        path_lower = path.lower()
        for token in forbidden_route_tokens:
            assert token not in path_lower, f"Forbidden route token '{token}' in path '{path}'"


# =============================================================================
# 13. No Active Runtime Code Requires Deleted Excel Dependencies
# =============================================================================

def test_no_active_runtime_code_requires_deleted_excel_dependencies():
    """requirements.txt contains no pandas or Excel dependencies, and AnswerGenerator runs without pandas."""
    req_file = Path("requirements.txt")
    req_content = req_file.read_text(encoding="utf-8").lower()
    for dep in ["pandas", "openpyxl", "xlrd", "xlsxwriter"]:
        assert dep not in req_content, f"Legacy dependency '{dep}' found in requirements.txt"

    # AnswerGenerator._serialize_result handles various data types without pandas
    assert AnswerGenerator._serialize_result(None) == "null"
    assert AnswerGenerator._serialize_result(True) == "true"
    assert AnswerGenerator._serialize_result(False) == "false"
    assert AnswerGenerator._serialize_result(42) == "42"
    assert AnswerGenerator._serialize_result(3.14) == "3.14"
    assert AnswerGenerator._serialize_result("hello") == '"hello"'
    assert AnswerGenerator._serialize_result([{"id": 1, "val": "x"}]) == '[{"id":1,"val":"x"}]'

    # Duck-typed object with to_dict("records")
    class DuckRecordSet:
        empty = False
        def to_dict(self, orient=None):
            return [{"col": "a"}]

    assert AnswerGenerator._serialize_result(DuckRecordSet()) == '[{"col":"a"}]'


# =============================================================================
# 14. Frontend Static Routes Load Without Error
# =============================================================================

def test_frontend_static_routes_load_without_error():
    """The frontend root index, stylesheet, and javascript file load with HTTP 200."""
    client = TestClient(app)

    res_index = client.get("/")
    assert res_index.status_code == 200
    assert "text/html" in res_index.headers.get("content-type", "")
    assert "Database AI" in res_index.text

    res_css = client.get("/styles.css")
    assert res_css.status_code == 200
    assert "text/css" in res_css.headers.get("content-type", "")

    res_js = client.get("/app.js")
    assert res_js.status_code == 200
    assert "application/javascript" in res_js.headers.get("content-type", "") or "text/javascript" in res_js.headers.get("content-type", "")
