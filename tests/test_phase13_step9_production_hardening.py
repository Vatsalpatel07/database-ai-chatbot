"""
Phase 13 Step 9 — Production Hardening, Performance & Operational Reliability Test Suite

Validates:
1. Configuration and parameter safety (query_timeout, validation, password masking).
2. Engine lifecycle and connection pool management (pool sizing, pre-ping, disposal).
3. Statement timeout enforcement, query cancellation, and SQLQueryTimeoutError mapping.
4. Transaction safety, rollback on query failure, and read-only database invariance.
5. Result set memory safety cap (MAX_LOOKUP_ROWS = 5000).
6. Observability and credential sanitization in error logs.
7. Concurrent query execution safety across multiple worker threads.
"""

from __future__ import annotations

import concurrent.futures
import unittest.mock
import pytest
import psycopg

from app.core.config import (
    DatabaseConfig,
    DatabaseConfigurationError,
    get_database_config,
)
from app.database.connection import (
    _ENGINES,
    DatabaseConnectionError,
    dispose_all_engines,
    dispose_engine,
    get_connection,
    get_engine,
)
from app.database.sql_executor import (
    SQLQueryExecutionError,
    SQLQueryExecutor,
    SQLQueryTimeoutError,
)
from app.database.schema import ColumnInfo, TableInfo
from app.query.schema import QueryPlan


@pytest.fixture(scope="module")
def live_config() -> DatabaseConfig:
    cfg = get_database_config()
    assert cfg.engine == "postgresql"
    assert cfg.database == "mnghealthreportingdb"
    return cfg


# ==============================================================================
# 1. CONFIGURATION SAFETY & PARAMETER VALIDATION
# ==============================================================================

class TestConfigurationSafety:
    """Verifies timeout configuration, validation rules, and credential masking."""

    def test_default_query_timeout(self) -> None:
        cfg = DatabaseConfig(
            engine="postgresql",
            server="localhost",
            database="testdb",
            schema="dbo",
        )
        assert cfg.query_timeout == 30
        assert cfg.connection_timeout == 30

    def test_custom_query_timeout(self) -> None:
        cfg = DatabaseConfig(
            engine="postgresql",
            server="localhost",
            database="testdb",
            schema="dbo",
            query_timeout=45,
        )
        assert cfg.query_timeout == 45
        cfg.validate()

    def test_query_timeout_env_loading(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DB_QUERY_TIMEOUT", "15")
        cfg = get_database_config()
        assert cfg.query_timeout == 15

    def test_query_timeout_validation_invalid_negative(self) -> None:
        with pytest.raises(DatabaseConfigurationError, match="Must be a non-negative integer"):
            DatabaseConfig(
                engine="postgresql",
                server="localhost",
                database="testdb",
                schema="dbo",
                query_timeout=-5,
            )

    def test_query_timeout_validation_invalid_type(self) -> None:
        with pytest.raises(DatabaseConfigurationError, match="Must be a non-negative integer"):
            DatabaseConfig(
                engine="postgresql",
                server="localhost",
                database="testdb",
                schema="dbo",
                query_timeout="not_a_number",  # type: ignore[arg-type]
            )

    def test_credential_masking_in_repr(self) -> None:
        cfg = DatabaseConfig(
            engine="postgresql",
            server="localhost",
            database="testdb",
            schema="dbo",
            user="secret_admin",
            password="super_sensitive_password_123",
            query_timeout=25,
        )
        repr_str = repr(cfg)
        assert "super_sensitive_password_123" not in repr_str
        assert "***" in repr_str
        assert "secret_admin" in repr_str
        assert "query_timeout=25" in repr_str


# ==============================================================================
# 2. ENGINE LIFECYCLE & CONNECTION POOL MANAGEMENT
# ==============================================================================

class TestEngineAndPoolManagement:
    """Verifies connection pool configuration, engine caching, pre-ping, and disposal."""

    def test_engine_pool_settings(self, live_config: DatabaseConfig) -> None:
        engine = get_engine(live_config)
        assert engine.pool.size() == 5
        assert engine.pool._max_overflow == 10
        assert engine.pool._timeout == 30
        assert engine.pool._recycle == 3600
        assert engine.pool._pre_ping is True

    def test_engine_live_statement_timeout_setting(self, live_config: DatabaseConfig) -> None:
        """Verifies session statement_timeout is active on connections from the engine."""
        with get_connection(live_config) as conn:
            cur = conn.cursor()
            cur.execute("SHOW statement_timeout;")
            val = cur.fetchone()[0]
            assert "30" in val

    def test_engine_caching_and_dispose_engine(self, live_config: DatabaseConfig) -> None:
        engine1 = get_engine(live_config)
        engine2 = get_engine(live_config)
        assert engine1 is engine2

        # Dispose specific engine
        dispose_engine(live_config)
        cache_key = f"{live_config.engine}:{live_config.server}:{live_config.port}:{live_config.database}:{live_config.schema}"
        assert cache_key not in _ENGINES

        # Next call creates a new engine instance
        engine3 = get_engine(live_config)
        assert engine3 is not engine1

    def test_dispose_engine_idempotent(self) -> None:
        dummy_cfg = DatabaseConfig(
            engine="postgresql",
            server="dummy_host",
            database="dummy_db",
            schema="dbo",
        )
        # Should not raise exception
        dispose_engine(dummy_cfg)

    def test_dispose_all_engines(self, live_config: DatabaseConfig) -> None:
        get_engine(live_config)
        assert len(_ENGINES) > 0
        dispose_all_engines()
        assert len(_ENGINES) == 0

    def test_connection_checkout_and_checkin(self, live_config: DatabaseConfig) -> None:
        """Verifies clean connection checkout and release back to pool."""
        engine = get_engine(live_config)
        initial_checked_in = engine.pool.checkedin()
        with get_connection(live_config) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 AS alive")
            row = cursor.fetchone()
            assert row[0] == 1
        # After context manager exit, connection is checked back in
        assert engine.pool.checkedin() >= initial_checked_in


# ==============================================================================
# 3. QUERY TIMEOUT ENFORCEMENT & RUNAWAY QUERY PROTECTION
# ==============================================================================

class TestQueryTimeoutAndCancellation:
    """Verifies statement timeout cancellation and mapping to SQLQueryTimeoutError."""

    def test_sql_query_timeout_error_inheritance(self) -> None:
        assert issubclass(SQLQueryTimeoutError, SQLQueryExecutionError)

    def test_statement_timeout_maps_to_query_timeout_error(self) -> None:
        executor = SQLQueryExecutor(
            DatabaseConfig(
                engine="postgresql",
                server="localhost",
                database="testdb",
                schema="dbo",
                query_timeout=10,
            )
        )
        # Simulated PostgreSQL timeout message
        simulated_exc = psycopg.errors.QueryCanceled("canceling statement due to statement timeout")
        with pytest.raises(SQLQueryTimeoutError, match="timed out after 10s"):
            executor._handle_execution_exception(simulated_exc)

    def test_live_statement_timeout_cancellation_and_recovery(self, live_config: DatabaseConfig) -> None:
        """
        Executes a query with session-level statement_timeout of 1 second,
        attempting pg_sleep(2.5). Verifies cancellation occurs and pool recovers cleanly.
        """
        with get_connection(live_config) as conn:
            cur = conn.cursor()
            cur.execute("SET statement_timeout = 1000;")  # 1 second
            with pytest.raises(Exception) as exc_info:
                cur.execute("SELECT pg_sleep(2.5);")
            assert "statement timeout" in str(exc_info.value).lower() or "querycanceled" in str(exc_info.value).lower()

        # Verify pool connection is not poisoned — next query immediately succeeds
        with get_connection(live_config) as conn:
            cur = conn.cursor()
            cur.execute("SELECT 42 AS recovered;")
            row = cur.fetchone()
            assert row[0] == 42


# ==============================================================================
# 4. TRANSACTION SAFETY & READ-ONLY DATABASE INVARIANCE
# ==============================================================================

class TestTransactionSafety:
    """Verifies that query execution failures cleanly roll back and leave data untouched."""

    def test_query_failure_rolls_back_cleanly(self, live_config: DatabaseConfig) -> None:
        """A failed query in get_connection does not leave transaction in failed state."""
        with pytest.raises(Exception):
            with get_connection(live_config) as conn:
                cur = conn.cursor()
                cur.execute("SELECT * FROM non_existent_table_xyz_12345;")

        # Subsequent checkout must be clean
        with get_connection(live_config) as conn:
            cur = conn.cursor()
            cur.execute("SELECT 100 AS success;")
            assert cur.fetchone()[0] == 100

    def test_database_row_count_invariance(self, live_config: DatabaseConfig) -> None:
        """Verifies row count of dbo.site_events is unchanged before and after query operations."""
        table_name = "dbo.site_events"
        with get_connection(live_config) as conn:
            cur = conn.cursor()
            cur.execute(f"SELECT COUNT(*) FROM {table_name};")
            initial_count = cur.fetchone()[0]

        # Execute some failing operations
        executor = SQLQueryExecutor(live_config)
        dummy_table = TableInfo(
            schema_name="dbo",
            table_name="site_events",
            columns=[ColumnInfo(name="event_sitecore_id", data_type="uuid", nullable=False, ordinal_position=1)],
        )
        bad_plan = QueryPlan(
            intent="lookup",
            filters=[],
            sort_column="non_existent_column_for_testing",
        )
        with pytest.raises(SQLQueryExecutionError):
            executor.execute(bad_plan, dummy_table)

        # Check row count after
        with get_connection(live_config) as conn:
            cur = conn.cursor()
            cur.execute(f"SELECT COUNT(*) FROM {table_name};")
            final_count = cur.fetchone()[0]

        assert initial_count == final_count == 720


# ==============================================================================
# 5. RESULT SET & MEMORY SAFETY
# ==============================================================================

class TestMemoryAndResultSafety:
    """Verifies that unbounded lookups are capped at MAX_LOOKUP_ROWS to prevent OOM."""

    def test_max_lookup_rows_constant_value(self) -> None:
        assert SQLQueryExecutor.MAX_LOOKUP_ROWS == 5000

    def test_max_lookup_rows_enforced_in_lookup(self, live_config: DatabaseConfig) -> None:
        executor = SQLQueryExecutor(live_config)
        table = TableInfo(
            schema_name="dbo",
            table_name="site_events",
            columns=[
                ColumnInfo(name="id", data_type="int", nullable=False, ordinal_position=1),
                ColumnInfo(name="title", data_type="varchar", nullable=True, ordinal_position=2),
            ],
        )
        plan = QueryPlan(
            intent="lookup",
            target_columns=["id"],
            limit=None,  # Unbounded
        )

        # Mock cursor returning 6000 rows
        mock_cursor = unittest.mock.MagicMock()
        mock_cursor.description = [("id",)]
        mock_cursor.fetchall.return_value = [(i,) for i in range(6000)]

        mock_conn = unittest.mock.MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_conn.__enter__.return_value = mock_conn

        with unittest.mock.patch("app.database.sql_executor.get_connection", return_value=mock_conn):
            result = executor._execute_lookup(plan, table)
            assert len(result) == SQLQueryExecutor.MAX_LOOKUP_ROWS
            assert len(result) == 5000

    def test_explicit_limit_respected(self, live_config: DatabaseConfig) -> None:
        executor = SQLQueryExecutor(live_config)
        table = TableInfo(
            schema_name="dbo",
            table_name="site_events",
            columns=[
                ColumnInfo(name="event_sitecore_id", data_type="uuid", nullable=False, ordinal_position=1),
                ColumnInfo(name="event_status", data_type="varchar", nullable=True, ordinal_position=4),
            ],
        )
        plan = QueryPlan(
            intent="lookup",
            target_columns=["event_sitecore_id"],
            limit=5,
        )
        result = executor.execute(plan, table)
        assert len(result) == 5


# ==============================================================================
# 6. OBSERVABILITY & CREDENTIAL SANITIZATION
# ==============================================================================

class TestObservabilityAndSanitization:
    """Verifies that database credentials are never leaked in error messages or logs."""

    def test_engine_creation_error_masks_password(self) -> None:
        bad_cfg = DatabaseConfig(
            engine="postgresql",
            server="invalid_non_existent_host_99999",
            port=5432,
            database="testdb",
            schema="dbo",
            user="testuser",
            password="super_secret_test_password_xyz",
            connection_timeout=1,
            query_timeout=1,
        )
        # Attempting to connect will fail, error must mask password
        with pytest.raises(DatabaseConnectionError) as exc_info:
            get_engine(bad_cfg)
            with get_connection(bad_cfg) as conn:
                conn.cursor().execute("SELECT 1")
        err_msg = str(exc_info.value)
        assert "super_secret_test_password_xyz" not in err_msg


# ==============================================================================
# 7. CONCURRENCY SAFETY
# ==============================================================================

class TestConcurrencySafety:
    """Verifies thread-safe execution across concurrent worker threads."""

    def test_concurrent_pool_queries(self, live_config: DatabaseConfig) -> None:
        def worker_query(worker_id: int) -> int:
            with get_connection(live_config) as conn:
                cur = conn.cursor()
                cur.execute(f"SELECT {worker_id} * 10 AS res;")
                return int(cur.fetchone()[0])

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            futures = [pool.submit(worker_query, i) for i in range(16)]
            results = [f.result(timeout=10) for f in futures]

        assert results == [i * 10 for i in range(16)]
