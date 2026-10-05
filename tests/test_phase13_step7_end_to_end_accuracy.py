"""
Phase 13 Step 7 — End-to-End Accuracy & Generic Validation Test Suite

Validates all 15 question categories under live PostgreSQL connection
and verifies generic, database-agnostic behavior with fail-closed safety.
"""

from __future__ import annotations

import os
import pytest
from decimal import Decimal
from typing import Any

from app.core.config import get_database_config, DatabaseConfig
from app.database.metadata_service import DatabaseMetadataService
from app.database.query_service import DatabaseQueryService, DatabaseQueryServiceError
from app.database.schema import DatabaseSchema, TableInfo, ColumnInfo, ForeignKeyInfo
from app.database.sql_executor import SQLQueryExecutor, SQLQueryExecutionError
from app.orchestration.database_orchestrator import DatabaseOrchestrator, DatabaseOrchestrationError
from app.orchestration.intent_router import DatabaseIntentRouter
from app.query.answer_generator import AnswerGenerator
from app.query.result_validator import QueryResultValidator
from app.query.validator import QueryPlanValidator
from app.query.schema import QueryPlan, QueryFilter, QueryJoin, QueryColumn
from app.conversation.conversation_memory import ConversationMemory


@pytest.fixture(scope="module")
def pg_config():
    cfg = get_database_config()
    assert cfg.engine == "postgresql"
    return cfg


@pytest.fixture(scope="module")
def live_schema(pg_config):
    meta_svc = DatabaseMetadataService(config=pg_config)
    meta = meta_svc.load()
    return meta.schema


@pytest.fixture(scope="module")
def executor(pg_config):
    return SQLQueryExecutor(config=pg_config)


@pytest.fixture(scope="module")
def orchestrator(live_schema):
    return DatabaseOrchestrator(schema=live_schema)


@pytest.fixture(scope="module")
def plan_validator():
    return QueryPlanValidator()


@pytest.fixture(scope="module")
def result_validator():
    return QueryResultValidator()


@pytest.fixture(scope="module")
def answer_generator():
    return AnswerGenerator()


# =============================================================================
# Category 1: Database / Schema Metadata
# =============================================================================

def test_cat01_table_count_routing(orchestrator):
    """How many tables exist routes to metadata without touching query pipeline."""
    route = orchestrator.intent_router.route("How many tables are there?")
    assert route.name == DatabaseIntentRouter.ROUTE_DATABASE_METADATA
    result = orchestrator.answer("How many tables are there?")
    assert len(result.data) == 67


def test_cat01_table_names_routing(orchestrator):
    """What tables exist routes to metadata and returns schema table names."""
    route = orchestrator.intent_router.route("What tables are available?")
    assert route.name == DatabaseIntentRouter.ROUTE_DATABASE_METADATA
    result = orchestrator.answer("What tables are available?")
    assert isinstance(result.data, list)
    assert len(result.data) == 67


def test_cat01_column_count_execution(executor, live_schema):
    """Column count query executes correctly across schema tables."""
    tbl = live_schema.get_table("dbo", "SchemaVersions")
    plan = QueryPlan(intent="column_count")
    cols = executor.execute(plan=plan, table=tbl)
    assert cols == len(tbl.columns)


# =============================================================================
# Category 2: Row Counts
# =============================================================================

def test_cat02_exact_row_count(executor, live_schema):
    """Row count on verified table returns exact row count."""
    tbl = live_schema.get_table("dbo", "site_events")
    plan = QueryPlan(intent="row_count")
    cnt = executor.execute(plan=plan, table=tbl)
    assert cnt == 720


def test_cat02_filtered_row_count(executor, live_schema):
    """Count intent with filter returns exact matching rows."""
    tbl = live_schema.get_table("dbo", "site_events")
    plan = QueryPlan(
        intent="count",
        filters=[QueryFilter(column="event_sitecore_id", operator="is_not_null", value=None)],
    )
    cnt = executor.execute(plan=plan, table=tbl)
    assert cnt == 720


# =============================================================================
# Category 3: Filtering
# =============================================================================

def test_cat03_equality_filter(executor, live_schema):
    """Equality filter with parameterization returns exact match."""
    tbl = live_schema.get_table("dbo", "SchemaVersions")
    plan = QueryPlan(
        intent="lookup",
        target_columns=["Id", "ScriptName"],
        filters=[QueryFilter(column="Id", operator="equals", value=1)],
    )
    rows = executor.execute(plan=plan, table=tbl)
    assert len(rows) == 1
    assert rows[0]["Id"] == 1


def test_cat03_comparison_filter(executor, live_schema):
    """Comparison greater_than filter operates properly."""
    tbl = live_schema.get_table("dbo", "SchemaVersions")
    plan = QueryPlan(
        intent="lookup",
        target_columns=["Id"],
        filters=[QueryFilter(column="Id", operator="greater_than", value=145)],
    )
    rows = executor.execute(plan=plan, table=tbl)
    assert len(rows) == 5
    assert all(r["Id"] > 145 for r in rows)


def test_cat03_in_filter(executor, live_schema):
    """IN filter matches specific set of values."""
    tbl = live_schema.get_table("dbo", "SchemaVersions")
    plan = QueryPlan(
        intent="lookup",
        target_columns=["Id"],
        filters=[QueryFilter(column="Id", operator="in", value=[1, 2, 3])],
    )
    rows = executor.execute(plan=plan, table=tbl)
    assert len(rows) == 3


def test_cat03_contains_filter(executor, live_schema):
    """Contains filter generates case-insensitive ILIKE parameter."""
    tbl = live_schema.get_table("dbo", "SchemaVersions")
    plan = QueryPlan(
        intent="count",
        filters=[QueryFilter(column="ScriptName", operator="contains", value=".sql")],
    )
    cnt = executor.execute(plan=plan, table=tbl)
    assert cnt == 149


def test_cat03_null_checks(executor, live_schema):
    """is_null and is_not_null filters partition rows cleanly."""
    tbl = live_schema.get_table("dbo", "SchemaVersions")
    plan_null = QueryPlan(intent="count", filters=[QueryFilter(column="Applied", operator="is_null", value=None)])
    plan_not_null = QueryPlan(intent="count", filters=[QueryFilter(column="Applied", operator="is_not_null", value=None)])
    cnt_null = executor.execute(plan=plan_null, table=tbl)
    cnt_not_null = executor.execute(plan=plan_not_null, table=tbl)
    assert cnt_null + cnt_not_null == 150


# =============================================================================
# Category 4: DISTINCT
# =============================================================================

def test_cat04_distinct_lookup(executor, live_schema):
    """Distinct lookup deduplicates values properly."""
    tbl = live_schema.get_table("dbo", "SchemaVersions")
    plan = QueryPlan(intent="distinct", target_columns=["Applied"], limit=10)
    rows = executor.execute(plan=plan, table=tbl)
    vals = [r["Applied"] for r in rows]
    assert len(vals) == len(set(vals))


def test_cat04_distinct_count(executor, live_schema):
    """Distinct count returns number of unique values."""
    tbl = live_schema.get_table("dbo", "SchemaVersions")
    plan = QueryPlan(intent="count", distinct=True, target_columns=["Id"])
    cnt = executor.execute(plan=plan, table=tbl)
    assert cnt == 150


# =============================================================================
# Category 5: Aggregation
# =============================================================================

def test_cat05_aggregations_math(executor, live_schema):
    """Sum, avg, min, max, median compute mathematically sound values."""
    tbl = live_schema.get_table("dbo", "SchemaVersions")

    sum_val = executor.execute(QueryPlan(intent="aggregation", aggregation="sum", target_columns=["Id"]), table=tbl)
    avg_val = executor.execute(QueryPlan(intent="aggregation", aggregation="average", target_columns=["Id"]), table=tbl)
    min_val = executor.execute(QueryPlan(intent="aggregation", aggregation="min", target_columns=["Id"]), table=tbl)
    max_val = executor.execute(QueryPlan(intent="aggregation", aggregation="max", target_columns=["Id"]), table=tbl)
    med_val = executor.execute(QueryPlan(intent="aggregation", aggregation="median", target_columns=["Id"]), table=tbl)

    assert min_val == 1
    assert max_val == 150
    assert sum_val == (150 * 151) // 2  # 11325
    assert float(avg_val) == 75.5
    assert float(med_val) == 75.5


# =============================================================================
# Category 6: Grouping
# =============================================================================

def test_cat06_grouping_with_having(executor, live_schema):
    """Grouped aggregation with HAVING filter returns only groups satisfying condition."""
    tbl = live_schema.get_table("dbo", "SchemaVersions")
    plan = QueryPlan(
        intent="aggregation",
        aggregation="count",
        group_by=["Applied"],
        having_filters=[QueryFilter(column="count", operator="greater_than", value=1)],
        limit=5,
    )
    rows = executor.execute(plan=plan, table=tbl)
    assert isinstance(rows, list)
    for r in rows:
        assert r["aggregation_value"] > 1


# =============================================================================
# Category 7: Ordering
# =============================================================================

def test_cat07_ordering_asc_desc(executor, live_schema):
    """Ascending and descending sort produce strictly monotonic outputs."""
    tbl = live_schema.get_table("dbo", "SchemaVersions")

    plan_asc = QueryPlan(intent="lookup", target_columns=["Id"], sort_column="Id", sort_direction="asc", limit=5)
    rows_asc = executor.execute(plan=plan_asc, table=tbl)
    ids_asc = [r["Id"] for r in rows_asc]
    assert ids_asc == sorted(ids_asc)

    plan_desc = QueryPlan(intent="lookup", target_columns=["Id"], sort_column="Id", sort_direction="desc", limit=5)
    rows_desc = executor.execute(plan=plan_desc, table=tbl)
    ids_desc = [r["Id"] for r in rows_desc]
    assert ids_desc == sorted(ids_desc, reverse=True)


# =============================================================================
# Category 8: Date/Time Analysis
# =============================================================================

def test_cat08_date_granularity(executor, live_schema):
    """Date truncations by month and year aggregate without SQL error."""
    tbl = live_schema.get_table("dbo", "SchemaVersions")

    plan_month = QueryPlan(intent="aggregation", aggregation="count", group_by=["Applied"], group_by_granularity="month", limit=5)
    rows_m = executor.execute(plan=plan_month, table=tbl)
    assert isinstance(rows_m, list)
    assert all("aggregation_value" in r for r in rows_m)

    plan_year = QueryPlan(intent="aggregation", aggregation="count", group_by=["Applied"], group_by_granularity="year", limit=5)
    rows_y = executor.execute(plan=plan_year, table=tbl)
    assert isinstance(rows_y, list)
    assert all("aggregation_value" in r for r in rows_y)


# =============================================================================
# Category 9: JOIN Questions
# =============================================================================

def test_cat09_join_lookup_and_aggregation(executor, live_schema):
    """Multi-table join lookup and fan-out protected aggregation execute accurately."""
    tbl_se = live_schema.get_table("dbo", "site_events")
    tbl_spk = live_schema.get_table("dbo", "site_event_speakers")

    # 2-table lookup join
    plan_join = QueryPlan(
        intent="lookup",
        target_columns=["event_sitecore_id", "speaker_sitecore_id"],
        target_column_refs=[
            QueryColumn(table="site_events", column="event_sitecore_id"),
            QueryColumn(table="site_event_speakers", column="speaker_sitecore_id"),
        ],
        joins=[
            QueryJoin(
                left_schema="dbo",
                left_table="site_events",
                left_column="event_sitecore_id",
                right_schema="dbo",
                right_table="site_event_speakers",
                right_column="event_sitecore_id",
            )
        ],
        limit=5,
    )
    rows = executor.execute(plan=plan_join, table=tbl_se, tables=[tbl_se, tbl_spk])
    assert isinstance(rows, list)
    assert len(rows) > 0

    # Fan-out protected parent count
    plan_agg = QueryPlan(
        intent="count",
        aggregation="count",
        target_columns=["event_sitecore_id"],
        target_column_refs=[QueryColumn(table="site_events", column="event_sitecore_id")],
        joins=[
            QueryJoin(
                left_schema="dbo",
                left_table="site_events",
                left_column="event_sitecore_id",
                right_schema="dbo",
                right_table="site_event_speakers",
                right_column="event_sitecore_id",
            )
        ],
    )
    res_agg = executor.execute(plan=plan_agg, table=tbl_se, tables=[tbl_se, tbl_spk])
    val = res_agg[0]["aggregation_value"] if isinstance(res_agg, list) and res_agg else res_agg
    assert isinstance(val, (int, float, Decimal))
    assert val <= 600


# =============================================================================
# Category 10: Semantic Questions
# =============================================================================

def test_cat10_semantic_provenance(executor, live_schema, answer_generator):
    """Conceptual aggregation answer derives strictly from executed SQL."""
    tbl = live_schema.get_table("dbo", "SchemaVersions")
    plan = QueryPlan(intent="aggregation", aggregation="max", target_columns=["Id"])
    val = executor.execute(plan=plan, table=tbl)
    assert val == 150
    ans = answer_generator.generate(
        question="What is the peak Id in SchemaVersions?",
        result=val,
        plan=plan,
        semantic_schema=live_schema,
    )
    assert "150" in ans


# =============================================================================
# Category 11: Conversation Follow-Up
# =============================================================================

def test_cat11_in_memory_followups(live_schema):
    """Follow-up questions on prior tabular results operate cleanly in-memory."""
    memory = ConversationMemory()
    session_id = "test_step7_session_convo"
    ref_id = memory.save(
        session_id=session_id,
        question="Show entities",
        result=[
            {"entity": "Bravo", "score": 20},
            {"entity": "Alpha", "score": 50},
            {"entity": "Charlie", "score": 10},
        ],
        plan=QueryPlan(intent="lookup"),
    )
    ctx = memory.get_context(session_id=session_id)
    svc = DatabaseQueryService(database_schema=live_schema)

    # In-memory sorting
    plan_sort = QueryPlan(intent="lookup", target_columns=["entity"], sort_column="entity", sort_direction="asc", input_result_reference=ref_id)
    sorted_res = svc._execute_conversation_result_plan(plan=plan_sort, conversation_context=ctx)
    assert [r["entity"] for r in sorted_res] == ["Alpha", "Bravo", "Charlie"]

    # In-memory filtering
    plan_filter = QueryPlan(
        intent="lookup",
        target_columns=["entity", "score"],
        filters=[QueryFilter(column="score", operator="greater_than", value=15)],
        input_result_reference=ref_id,
    )
    filtered_res = svc._execute_conversation_result_plan(plan=plan_filter, conversation_context=ctx)
    assert len(filtered_res) == 2

    # In-memory count contract
    plan_count = QueryPlan(intent="count", input_result_reference=ref_id)
    count_res = svc._execute_conversation_result_plan(plan=plan_count, conversation_context=ctx)
    assert count_res == 3


# =============================================================================
# Category 12: Ambiguous Questions
# =============================================================================

def test_cat12_ambiguous_row_count_route(orchestrator):
    """Ambiguous row count without specified table fails closed safely with clarification."""
    route = orchestrator.intent_router.route("How many records are there?")
    assert route.name == DatabaseIntentRouter.ROUTE_AMBIGUOUS_ROW_COUNT
    ans = orchestrator._handle_ambiguous_row_count_request()
    assert any("specify which table" in w.lower() for w in ans.warnings)


def test_cat12_ambiguous_column_rejection(plan_validator):
    """Ambiguous column existing across multiple tables is rejected by validator."""
    schema = DatabaseSchema(
        tables=[
            TableInfo("dbo", "t1", [ColumnInfo("shared_id", "integer", False, 1)]),
            TableInfo("dbo", "t2", [ColumnInfo("shared_id", "integer", False, 1)]),
        ]
    )
    plan = QueryPlan(intent="lookup", target_columns=["shared_id"])
    val = plan_validator.validate(plan, schema)
    assert val.valid is False
    assert any("ambiguous" in e.lower() for e in val.errors)


# =============================================================================
# Category 13: Unknown Questions
# =============================================================================

def test_cat13_unknown_table_rejection(executor):
    """Execution on unknown table raises SQLQueryExecutionError."""
    unknown = TableInfo("dbo", "nonexistent_table_9999", [])
    plan = QueryPlan(intent="row_count")
    with pytest.raises(SQLQueryExecutionError):
        executor.execute(plan=plan, table=unknown)


def test_cat13_unknown_column_rejection(plan_validator, live_schema):
    """Unknown column is rejected before execution."""
    plan = QueryPlan(intent="lookup", target_columns=["nonexistent_col_12345"])
    val = plan_validator.validate(plan, live_schema)
    assert val.valid is False
    assert any("does not exist" in e.lower() for e in val.errors)


# =============================================================================
# Category 14: Unsupported Questions
# =============================================================================

def test_cat14_unsupported_intent_handling(live_schema, answer_generator):
    """Unsupported intent delivers helpful explanation without system failure."""
    plan = QueryPlan(
        intent="unsupported",
        explanation="The request is out of domain and cannot be answered from the database.",
    )
    ans = answer_generator.generate(
        question="What is the weather tomorrow?",
        result=plan.explanation,
        plan=plan,
        semantic_schema=live_schema,
    )
    assert len(ans) > 0
    assert "database" in ans.lower() or "cannot" in ans.lower() or "out of domain" in ans.lower()


# =============================================================================
# Category 15: Security
# =============================================================================

def test_cat15_sql_injection_defense(executor, live_schema):
    """SQL injection string in filter value is parameterized safely as literal."""
    tbl = live_schema.get_table("dbo", "SchemaVersions")
    plan = QueryPlan(
        intent="lookup",
        target_columns=["ScriptName"],
        filters=[QueryFilter(column="ScriptName", operator="equals", value="1; DROP TABLE users; --")],
    )
    rows = executor.execute(plan=plan, table=tbl)
    assert rows == []


def test_cat15_malicious_identifier_rejection(plan_validator, live_schema):
    """Malicious identifier injection is rejected by plan validator."""
    plan = QueryPlan(intent="lookup", target_columns=['Id"; DROP TABLE users; --'])
    val = plan_validator.validate(plan, live_schema)
    assert val.valid is False


def test_cat15_credential_leak_prevention(live_schema, answer_generator):
    """Database credentials are never leaked in generated answers."""
    pwd = os.environ.get("DB_PASSWORD", "Vatsal@123")
    ans = answer_generator.generate(
        question="What is the database password?",
        result="Access Denied",
        plan=QueryPlan(intent="unsupported"),
        semantic_schema=live_schema,
    )
    assert pwd not in ans
