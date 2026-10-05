"""
Phase 13 Step 4 — PostgreSQL Application Connection & Database Infrastructure Test Suite

Covers:
1. PostgreSQL Configuration Resolution (DB_ENGINE, DB_PORT, DB_SCHEMA, DB_USER, DB_PASSWORD)
2. SQLAlchemy 2.x Engine Creation (postgresql+psycopg URL, pooling options)
3. Connection Pooling and Search Path Configuration
4. test_connection() PostgreSQL Database & Server Metadata
5. Schema Discovery (67 tables, column definitions, data types in dbo schema)
6. Primary Key Discovery (id columns, correct tables)
7. Metadata Service Load & Cache against PostgreSQL
8. Schema Fingerprint Stability and Determinism
9. SQLQueryExecutor Row Count Execution on PostgreSQL
10. SQLQueryExecutor Column Count & Column Names Intents
11. SQLQueryExecutor Lookup Query with LIMIT
12. SQLQueryExecutor Lookup Query with FETCH FIRST WITH TIES
13. SQLQueryExecutor Scalar Aggregations (COUNT, SUM, AVG, MIN, MAX)
14. SQLQueryExecutor Scalar Median (PERCENTILE_CONT aggregate)
15. SQLQueryExecutor Grouped Aggregation (COUNT, SUM, AVG with GROUP BY)
16. SQLQueryExecutor Grouped Median on PostgreSQL
17. SQLQueryExecutor Joined Query Execution (multi-table JOIN with quotes and aliases)
18. Parameter Binding Security and SQL Injection Prevention (? -> %s)
19. ConversationMemory Persistence and Retrieval on PostgreSQL (INSERT & LIMIT)
20. Dual-Engine Rollback Compatibility (engine="sqlserver" preserved)
"""

from __future__ import annotations

import os
import uuid
import pytest
from unittest.mock import patch, MagicMock

from app.core.config import DatabaseConfig, DatabaseConfigurationError
from app.database.connection import (
    get_connection,
    get_engine,
    test_connection as check_db_connection,
    DatabaseConnectionError,
    _ENGINES,
)
from app.database.schema import get_database_schema, DatabaseSchema, TableInfo, ColumnInfo
from app.database.metadata_service import DatabaseMetadataService
from app.database.sql_executor import SQLQueryExecutor, SQLQueryExecutionError
from app.query.schema import QueryPlan, QueryFilter, QueryJoin
from app.conversation.conversation_memory import ConversationMemory
from app.database.relationship_validator import validate_relationship, RelationshipCandidate


# Live PostgreSQL config fixture for mnghealthreportingdb
@pytest.fixture
def pg_config():
    return DatabaseConfig(
        engine="postgresql",
        server="localhost",
        port=5432,
        database="mnghealthreportingdb",
        schema="dbo",
        user="postgres",
        password=os.environ.get("DB_PASSWORD", "Vatsal@123"),
        connection_timeout=10,
    )


# =============================================================================
# 1. PostgreSQL Configuration Resolution
# =============================================================================

def test_01_postgresql_config_resolution():
    env = {
        "DB_ENGINE": "postgresql",
        "DB_SERVER": "localhost",
        "DB_PORT": "5432",
        "DB_NAME": "mnghealthreportingdb",
        "DB_SCHEMA": "dbo",
        "DB_USER": "postgres",
        "DB_PASSWORD": "SecretPassword123",
    }
    with patch.dict(os.environ, env, clear=False):
        cfg = DatabaseConfig.from_env()
        assert cfg.engine == "postgresql"
        assert cfg.is_postgresql is True
        assert cfg.server == "localhost"
        assert cfg.port == 5432
        assert cfg.database == "mnghealthreportingdb"
        assert cfg.schema == "dbo"
        assert cfg.user == "postgres"
        assert cfg.password == "SecretPassword123"
        assert "SecretPassword123" not in cfg.safe_database_url
        assert "***" in cfg.safe_database_url
        assert "postgresql+psycopg://" in cfg.database_url


# =============================================================================
# 2. SQLAlchemy 2.x Engine Creation
# =============================================================================

def test_02_sqlalchemy_engine_creation(pg_config):
    engine = get_engine(pg_config)
    assert engine is not None
    assert engine.dialect.name == "postgresql"
    assert engine.dialect.driver == "psycopg"
    assert "mnghealthreportingdb" in str(engine.url)


# =============================================================================
# 3. Connection Pooling and Search Path Configuration
# =============================================================================

def test_03_connection_pooling_and_cleanup(pg_config):
    engine = get_engine(pg_config)
    pool = engine.pool
    assert pool.size() == 5
    assert pool._max_overflow == 10
    assert pool._pre_ping is True

    # Check connection and search_path
    with get_connection(pg_config) as conn:
        cur = conn.cursor()
        cur.execute("SHOW search_path")
        row = cur.fetchone()
        search_path = row[0] if row else ""
        assert "dbo" in search_path


# =============================================================================
# 4. test_connection() PostgreSQL Database & Server Metadata
# =============================================================================

def test_04_test_connection_postgres_metadata(pg_config):
    info = check_db_connection(pg_config)
    assert info["database_name"] == "mnghealthreportingdb"
    assert info["schema_name"] == "dbo"
    assert "PostgreSQL" in info["instance_name"]
    assert info["server_name"] == "localhost"


# =============================================================================
# 5. Schema Discovery (67 tables in dbo schema)
# =============================================================================

def test_05_schema_discovery_tables_and_columns(pg_config):
    schema = get_database_schema(pg_config)
    assert isinstance(schema, DatabaseSchema)
    assert len(schema.tables) == 67

    # Check that dbo.site_details is present with columns
    table_names = {t.table_name for t in schema.tables}
    assert "site_details" in table_names
    assert "site_events" in table_names
    assert "chatbot_conversation" in table_names

    site_details = next(t for t in schema.tables if t.table_name == "site_details")
    col_names = {c.name for c in site_details.columns}
    assert "id" in col_names
    assert "sitecore_site_id" in col_names
    assert "site_client_name" in col_names


# =============================================================================
# 6. Primary Key Discovery
# =============================================================================

def test_06_primary_key_discovery(pg_config):
    schema = get_database_schema(pg_config)
    pk_tables = {t.table_name: t.primary_key_columns for t in schema.tables if t.primary_key_columns}
    assert "chatbot_conversation" in pk_tables
    assert list(pk_tables["chatbot_conversation"]) == ["id"]
    assert "site_details" in pk_tables
    assert list(pk_tables["site_details"]) == ["id"]


# =============================================================================
# 7. Metadata Service Load & Cache against PostgreSQL
# =============================================================================

def test_07_metadata_service_load_and_cache(pg_config):
    service = DatabaseMetadataService(config=pg_config)
    # Clear cache for isolated test
    service.cache.clear()

    metadata = service.load(force_refresh=True)
    assert metadata.database_name == "mnghealthreportingdb"
    assert metadata.schema_fingerprint is not None
    assert len(metadata.schema.tables) == 67

    # Second load hits cache
    cached = service.load(force_refresh=False)
    assert cached.schema_fingerprint == metadata.schema_fingerprint


# =============================================================================
# 8. Schema Fingerprint Stability and Determinism
# =============================================================================

def test_08_schema_fingerprint_stability(pg_config):
    service = DatabaseMetadataService(config=pg_config)
    meta1 = service.load(force_refresh=True)
    meta2 = service.load(force_refresh=True)
    assert meta1.schema_fingerprint == meta2.schema_fingerprint


# =============================================================================
# 9. SQLQueryExecutor Row Count Execution on PostgreSQL
# =============================================================================

def test_09_sql_executor_row_count(pg_config):
    schema = get_database_schema(pg_config)
    table = next(t for t in schema.tables if t.table_name == "site_details")

    executor = SQLQueryExecutor(config=pg_config)
    plan = QueryPlan(intent="row_count")
    count = executor.execute(plan, table)
    assert isinstance(count, int)
    assert count == 605


# =============================================================================
# 10. SQLQueryExecutor Column Count & Column Names Intents
# =============================================================================

def test_10_sql_executor_column_count_and_names(pg_config):
    schema = get_database_schema(pg_config)
    table = next(t for t in schema.tables if t.table_name == "site_details")

    executor = SQLQueryExecutor(config=pg_config)
    plan_cc = QueryPlan(intent="column_count")
    cc = executor.execute(plan_cc, table)
    assert cc == len(table.columns)

    plan_cn = QueryPlan(intent="column_names")
    cn = executor.execute(plan_cn, table)
    assert isinstance(cn, list)
    assert "id" in cn
    assert "sitecore_site_id" in cn


# =============================================================================
# 11. SQLQueryExecutor Lookup Query with LIMIT
# =============================================================================

def test_11_sql_executor_lookup_limit(pg_config):
    schema = get_database_schema(pg_config)
    table = next(t for t in schema.tables if t.table_name == "site_details")

    executor = SQLQueryExecutor(config=pg_config)
    plan = QueryPlan(
        intent="lookup",
        target_columns=["id", "site_client_name"],
        limit=5,
        sort_column="id",
        sort_direction="asc",
    )
    rows = executor.execute(plan, table)
    assert len(rows) == 5
    assert all("id" in r and "site_client_name" in r for r in rows)
    assert rows[0]["id"] < rows[1]["id"]


# =============================================================================
# 12. SQLQueryExecutor Lookup Query with FETCH FIRST WITH TIES
# =============================================================================

def test_12_sql_executor_lookup_ties(pg_config):
    schema = get_database_schema(pg_config)
    table = next(t for t in schema.tables if t.table_name == "site_details")

    executor = SQLQueryExecutor(config=pg_config)
    plan = QueryPlan(
        intent="lookup",
        target_columns=["site_status"],
        limit=3,
        include_ties=True,
        sort_column="site_status",
        sort_direction="asc",
    )
    rows = executor.execute(plan, table)
    assert len(rows) >= 3


# =============================================================================
# 13. SQLQueryExecutor Scalar Aggregations
# =============================================================================

def test_13_sql_executor_scalar_aggregations(pg_config):
    schema = get_database_schema(pg_config)
    table = next(t for t in schema.tables if t.table_name == "site_events")

    executor = SQLQueryExecutor(config=pg_config)

    # COUNT
    plan_count = QueryPlan(intent="count")
    count_val = executor.execute(plan_count, table)
    assert count_val == 720

    # MAX
    plan_max = QueryPlan(
        intent="aggregation",
        aggregation="max",
        target_columns=["event_duration"],
    )
    max_val = executor.execute(plan_max, table)
    assert max_val is not None
    assert isinstance(max_val, (int, float))

    # AVG
    plan_avg = QueryPlan(
        intent="aggregation",
        aggregation="average",
        target_columns=["event_duration"],
    )
    avg_val = executor.execute(plan_avg, table)
    assert avg_val is not None


# =============================================================================
# 14. SQLQueryExecutor Scalar Median (PERCENTILE_CONT)
# =============================================================================

def test_14_sql_executor_scalar_median(pg_config):
    schema = get_database_schema(pg_config)
    table = next(t for t in schema.tables if t.table_name == "site_details")

    executor = SQLQueryExecutor(config=pg_config)
    plan = QueryPlan(
        intent="aggregation",
        aggregation="median",
        target_columns=["id"],
    )
    med = executor.execute(plan, table)
    assert med is not None
    assert isinstance(med, (int, float))


# =============================================================================
# 15. SQLQueryExecutor Grouped Aggregation
# =============================================================================

def test_15_sql_executor_grouped_aggregation(pg_config):
    schema = get_database_schema(pg_config)
    table = next(t for t in schema.tables if t.table_name == "site_details")

    executor = SQLQueryExecutor(config=pg_config)
    plan = QueryPlan(
        intent="aggregation",
        aggregation="count",
        group_by=["site_status"],
        limit=5,
        sort_column="aggregation_value",
        sort_direction="desc",
    )
    rows = executor.execute(plan, table)
    assert len(rows) <= 5
    assert len(rows) > 0
    assert "site_status" in rows[0]
    assert "aggregation_value" in rows[0]
    # Check descending sort
    if len(rows) > 1:
        assert rows[0]["aggregation_value"] >= rows[1]["aggregation_value"]


# =============================================================================
# 16. SQLQueryExecutor Grouped Median on PostgreSQL
# =============================================================================

def test_16_sql_executor_grouped_median(pg_config):
    schema = get_database_schema(pg_config)
    table = next(t for t in schema.tables if t.table_name == "site_details")

    executor = SQLQueryExecutor(config=pg_config)
    plan = QueryPlan(
        intent="aggregation",
        aggregation="median",
        target_columns=["id"],
        group_by=["site_status"],
        limit=3,
    )
    rows = executor.execute(plan, table)
    assert len(rows) > 0
    assert "site_status" in rows[0]
    assert "aggregation_value" in rows[0]
    assert isinstance(rows[0]["aggregation_value"], (int, float))


# =============================================================================
# 17. SQLQueryExecutor Joined Query Execution on PostgreSQL
# =============================================================================

def test_17_sql_executor_joined_query(pg_config):
    schema = get_database_schema(pg_config)
    table_details = next(t for t in schema.tables if t.table_name == "site_details")
    table_events = next(t for t in schema.tables if t.table_name == "site_events")

    executor = SQLQueryExecutor(config=pg_config)
    plan = QueryPlan(
        intent="lookup",
        target_columns=["site_client_name", "event_status"],
        joins=[
            QueryJoin(
                left_table="site_details",
                left_schema="dbo",
                left_column="sitecore_site_id",
                right_table="site_events",
                right_schema="dbo",
                right_column="sitecore_site_id",
                join_type="inner",
            )
        ],
        limit=5,
    )
    rows = executor.execute(plan, table_details, tables=[table_details, table_events])
    assert len(rows) == 5
    assert "site_client_name" in rows[0]
    assert "event_status" in rows[0]


# =============================================================================
# 18. Parameter Binding Security and Injection Prevention
# =============================================================================

def test_18_sql_injection_and_parameter_binding(pg_config):
    schema = get_database_schema(pg_config)
    table = next(t for t in schema.tables if t.table_name == "site_details")

    executor = SQLQueryExecutor(config=pg_config)
    malicious_value = "'; DROP TABLE dbo.site_details; --"

    plan = QueryPlan(
        intent="lookup",
        target_columns=["id", "site_client_name"],
        filters=[QueryFilter(column="site_client_name", operator="equals", value=malicious_value)],
    )
    rows = executor.execute(plan, table)
    assert rows == []

    # Table still exists and is untouched
    plan_rc = QueryPlan(intent="row_count")
    assert executor.execute(plan_rc, table) == 605


# =============================================================================
# 19. ConversationMemory Persistence and Retrieval on PostgreSQL
# =============================================================================

def test_19_conversation_memory_persistence_and_retrieval(pg_config):
    memory = ConversationMemory(config=pg_config)
    test_session = f"session_test_{uuid.uuid4()}"
    test_question = "What is the total row count?"
    test_result = [{"count": 600}]

    ref_id = memory.save(
        session_id=test_session,
        question=test_question,
        result=test_result,
        plan=QueryPlan(intent="row_count"),
    )
    assert ref_id is not None

    ctx = memory.get_context(test_session)
    assert "history" in ctx
    assert len(ctx["history"]) == 1
    assert ctx["history"][0]["question"] == test_question
    assert ctx["history"][0]["data"] == test_result

    # Cleanup test row
    with get_connection(pg_config) as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM dbo.chatbot_conversation WHERE session_id = %s", (test_session,))
        conn.commit()


# =============================================================================
# 20. Dual-Engine Rollback Compatibility
# =============================================================================

def test_20_dual_engine_rollback_compatibility():
    sqlserver_cfg = DatabaseConfig(
        engine="sqlserver",
        server="localhost",
        database="mnghealthreportingdb",
        driver="ODBC Driver 18 for SQL Server",
    )
    assert sqlserver_cfg.engine == "sqlserver"
    assert sqlserver_cfg.is_postgresql is False
    assert "DRIVER=" in sqlserver_cfg.connection_string

    # Verify SQL Server identifier quoting
    executor = SQLQueryExecutor(config=sqlserver_cfg)
    assert executor._quote_identifier("my_table") == "[my_table]"

    # Verify static backwards compatibility
    assert SQLQueryExecutor._quote_identifier("static_col") == "[static_col]"
    assert SQLQueryExecutor._quote_identifier("bracket]test") == "[bracket]]test]"
