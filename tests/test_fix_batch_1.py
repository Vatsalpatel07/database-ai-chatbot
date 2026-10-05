from unittest.mock import MagicMock, patch
import json
import pytest

from app.core.config import DatabaseConfig
from app.database.schema import (
    ColumnInfo,
    DatabaseSchema,
    ForeignKeyInfo,
    TableInfo,
    parse_column_reference,
)
from app.database.sql_executor import SQLQueryExecutor
from app.database.table_selector import select_tables
from app.database.query_service import DatabaseQueryService
from app.query.analyzer import QuestionAnalyzer
from app.query.schema import (
    QueryColumn,
    QueryFilter,
    QueryJoin,
    QueryPlan,
)
from app.query.validator import QueryPlanValidator


# =====================================================================
# FIX 1: COUNT VALIDATION TESTS
# =====================================================================

def test_count_validation_on_uuid_target_column():
    """COUNT aggregation should not require numeric column type."""
    schema = DatabaseSchema(
        tables=[
            TableInfo(
                schema_name="dbo",
                table_name="events",
                columns=[
                    ColumnInfo(name="id", data_type="uuid", nullable=False, ordinal_position=1),
                    ColumnInfo(name="name", data_type="varchar", nullable=False, ordinal_position=2),
                ],
                primary_key_columns=["id"],
            )
        ]
    )
    validator = QueryPlanValidator()
    plan = QueryPlan(
        intent="aggregation",
        target_columns=["id"],
        aggregation="count",
    )
    result = validator.validate(plan, schema)
    assert result.valid is True
    assert result.errors == []


def test_count_validation_on_varchar_target_column():
    """COUNT aggregation on VARCHAR/TEXT columns must pass validation."""
    schema = DatabaseSchema(
        tables=[
            TableInfo(
                schema_name="dbo",
                table_name="events",
                columns=[
                    ColumnInfo(name="status", data_type="varchar", nullable=True, ordinal_position=1),
                ],
            )
        ]
    )
    validator = QueryPlanValidator()
    plan = QueryPlan(
        intent="aggregation",
        target_columns=["status"],
        aggregation="count",
    )
    result = validator.validate(plan, schema)
    assert result.valid is True
    assert result.errors == []


def test_grouped_count_validation_on_uuid():
    """Grouped COUNT where target column is UUID must pass validation."""
    schema = DatabaseSchema(
        tables=[
            TableInfo(
                schema_name="dbo",
                table_name="events",
                columns=[
                    ColumnInfo(name="event_id", data_type="uuid", nullable=False, ordinal_position=1),
                    ColumnInfo(name="status", data_type="varchar", nullable=False, ordinal_position=2),
                ],
            )
        ]
    )
    validator = QueryPlanValidator()
    plan = QueryPlan(
        intent="aggregation",
        target_columns=["event_id"],
        group_by=["status"],
        aggregation="count",
    )
    result = validator.validate(plan, schema)
    assert result.valid is True
    assert result.errors == []


def test_grouped_count_validation_by_categorical_column():
    """Grouped COUNT by category with empty or UUID target columns must pass."""
    schema = DatabaseSchema(
        tables=[
            TableInfo(
                schema_name="dbo",
                table_name="events",
                columns=[
                    ColumnInfo(name="category", data_type="varchar", nullable=False, ordinal_position=1),
                    ColumnInfo(name="event_id", data_type="uuid", nullable=False, ordinal_position=2),
                ],
            )
        ]
    )
    validator = QueryPlanValidator()
    plan = QueryPlan(
        intent="aggregation",
        target_columns=[],
        group_by=["category"],
        aggregation="count",
    )
    result = validator.validate(plan, schema)
    assert result.valid is True


def test_count_validation_with_is_null_and_is_not_null():
    """COUNT query with IS NULL and IS NOT NULL filters."""
    schema = DatabaseSchema(
        tables=[
            TableInfo(
                schema_name="dbo",
                table_name="events",
                columns=[
                    ColumnInfo(name="id", data_type="uuid", nullable=False, ordinal_position=1),
                    ColumnInfo(name="end_date", data_type="timestamp", nullable=True, ordinal_position=2),
                ],
            )
        ]
    )
    validator = QueryPlanValidator()
    plan = QueryPlan(
        intent="count",
        target_columns=["id"],
        filters=[
            QueryFilter(column="end_date", operator="is_null", value=None),
        ],
    )
    res1 = validator.validate(plan, schema)
    assert res1.valid is True

    plan2 = QueryPlan(
        intent="count",
        target_columns=["id"],
        filters=[
            QueryFilter(column="end_date", operator="is_not_null", value=None),
        ],
    )
    res2 = validator.validate(plan2, schema)
    assert res2.valid is True


def test_count_validation_with_having_filter():
    """Grouped COUNT with a HAVING filter."""
    schema = DatabaseSchema(
        tables=[
            TableInfo(
                schema_name="dbo",
                table_name="events",
                columns=[
                    ColumnInfo(name="status", data_type="varchar", nullable=False, ordinal_position=1),
                    ColumnInfo(name="id", data_type="uuid", nullable=False, ordinal_position=2),
                ],
            )
        ]
    )
    validator = QueryPlanValidator()
    plan = QueryPlan(
        intent="aggregation",
        target_columns=["id"],
        group_by=["status"],
        aggregation="count",
        having_filters=[
            QueryFilter(column="count", operator="greater_than", value=5),
        ],
    )
    result = validator.validate(plan, schema)
    assert result.valid is True


def test_count_validation_with_order_by_aggregate():
    """Grouped COUNT with sorting on aggregate count."""
    schema = DatabaseSchema(
        tables=[
            TableInfo(
                schema_name="dbo",
                table_name="events",
                columns=[
                    ColumnInfo(name="status", data_type="varchar", nullable=False, ordinal_position=1),
                    ColumnInfo(name="id", data_type="uuid", nullable=False, ordinal_position=2),
                ],
            )
        ]
    )
    validator = QueryPlanValidator()
    plan = QueryPlan(
        intent="aggregation",
        target_columns=["id"],
        group_by=["status"],
        aggregation="count",
        sort_column="count",
        sort_direction="desc",
        limit=1,
    )
    result = validator.validate(plan, schema)
    assert result.valid is True


def test_non_count_aggregations_still_require_numeric_types():
    """Ensure sum, average, min, max, median continue to enforce numeric requirements."""
    schema = DatabaseSchema(
        tables=[
            TableInfo(
                schema_name="dbo",
                table_name="events",
                columns=[
                    ColumnInfo(name="name", data_type="varchar", nullable=False, ordinal_position=1),
                ],
            )
        ]
    )
    validator = QueryPlanValidator()
    for agg in ("sum", "average", "median"):
        plan = QueryPlan(
            intent="aggregation",
            target_columns=["name"],
            aggregation=agg,
        )
        res = validator.validate(plan, schema)
        assert res.valid is False
        assert any("requires a numeric column" in err for err in res.errors)


# =====================================================================
# FIX 2: RANKING DISPATCH TESTS
# =====================================================================

def test_ranking_dispatch_in_sql_executor_postgresql():
    """ranking intent routes to _execute_lookup and generates PostgreSQL LIMIT."""
    config = DatabaseConfig(
        server="localhost",
        database="testdb",
        engine="postgresql",
        user="test",
        password="pwd",
    )
    executor = SQLQueryExecutor(config=config)
    table = TableInfo(
        schema_name="dbo",
        table_name="events",
        columns=[
            ColumnInfo(name="id", data_type="integer", nullable=False, ordinal_position=1),
            ColumnInfo(name="capacity", data_type="integer", nullable=False, ordinal_position=2),
        ],
        primary_key_columns=["id"],
    )
    plan = QueryPlan(
        intent="ranking",
        target_columns=["id", "capacity"],
        sort_column="capacity",
        sort_direction="desc",
        limit=5,
    )

    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.description = [("id",), ("capacity",)]
    mock_cursor.fetchall.return_value = [(1, 100), (2, 90)]
    mock_conn.cursor.return_value = mock_cursor

    with patch("app.database.sql_executor.get_connection") as mock_get_conn:
        mock_get_conn.return_value.__enter__.return_value = mock_conn
        results = executor.execute(plan, table)
        assert len(results) == 2
        # Verify executed SQL contains LIMIT and ORDER BY
        call_args = mock_cursor.execute.call_args[0]
        sql = call_args[0]
        assert "ORDER BY \"capacity\" DESC" in sql
        assert "LIMIT 5" in sql


def test_ranking_dispatch_sql_server_compatibility_path():
    """ranking intent routes to _execute_lookup and generates SQL Server TOP (N)."""
    config = DatabaseConfig(
        server="localhost",
        database="testdb",
        engine="sqlserver",
        trusted_connection=True,
    )
    executor = SQLQueryExecutor(config=config)
    table = TableInfo(
        schema_name="dbo",
        table_name="events",
        columns=[
            ColumnInfo(name="id", data_type="integer", nullable=False, ordinal_position=1),
            ColumnInfo(name="capacity", data_type="integer", nullable=False, ordinal_position=2),
        ],
        primary_key_columns=["id"],
    )
    plan = QueryPlan(
        intent="ranking",
        target_columns=["id", "capacity"],
        sort_column="capacity",
        sort_direction="asc",
        limit=10,
    )

    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.description = [("id",), ("capacity",)]
    mock_cursor.fetchall.return_value = [(1, 10)]
    mock_conn.cursor.return_value = mock_cursor

    with patch("app.database.sql_executor.get_connection") as mock_get_conn:
        mock_get_conn.return_value.__enter__.return_value = mock_conn
        results = executor.execute(plan, table)
        assert len(results) == 1
        call_args = mock_cursor.execute.call_args[0]
        sql = call_args[0]
        assert "SELECT TOP (10)" in sql
        assert "ORDER BY [capacity] ASC" in sql


def test_ranking_with_include_ties_postgresql():
    """ranking with include_ties produces FETCH FIRST N ROWS WITH TIES in PostgreSQL."""
    config = DatabaseConfig(
        server="localhost",
        database="testdb",
        engine="postgresql",
        user="test",
        password="pwd",
    )
    executor = SQLQueryExecutor(config=config)
    table = TableInfo(
        schema_name="dbo",
        table_name="events",
        columns=[
            ColumnInfo(name="id", data_type="integer", nullable=False, ordinal_position=1),
            ColumnInfo(name="capacity", data_type="integer", nullable=False, ordinal_position=2),
        ],
    )
    plan = QueryPlan(
        intent="ranking",
        target_columns=["id", "capacity"],
        sort_column="capacity",
        sort_direction="desc",
        limit=3,
        include_ties=True,
    )

    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.description = [("id",), ("capacity",)]
    mock_cursor.fetchall.return_value = [(1, 100), (2, 100), (3, 100), (4, 100)]
    mock_conn.cursor.return_value = mock_cursor

    with patch("app.database.sql_executor.get_connection") as mock_get_conn:
        mock_get_conn.return_value.__enter__.return_value = mock_conn
        results = executor.execute(plan, table)
        assert len(results) == 4
        sql = mock_cursor.execute.call_args[0][0]
        assert "FETCH FIRST 3 ROWS WITH TIES" in sql


def test_ranking_with_filters():
    """ranking combined with WHERE filters."""
    config = DatabaseConfig(
        server="localhost",
        database="testdb",
        engine="postgresql",
        user="test",
        password="pwd",
    )
    executor = SQLQueryExecutor(config=config)
    table = TableInfo(
        schema_name="dbo",
        table_name="events",
        columns=[
            ColumnInfo(name="id", data_type="integer", nullable=False, ordinal_position=1),
            ColumnInfo(name="capacity", data_type="integer", nullable=False, ordinal_position=2),
            ColumnInfo(name="status", data_type="varchar", nullable=False, ordinal_position=3),
        ],
    )
    plan = QueryPlan(
        intent="ranking",
        target_columns=["id", "capacity"],
        filters=[QueryFilter(column="status", operator="equals", value="active")],
        sort_column="capacity",
        sort_direction="desc",
        limit=5,
    )

    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.description = [("id",), ("capacity",)]
    mock_cursor.fetchall.return_value = []
    mock_conn.cursor.return_value = mock_cursor

    with patch("app.database.sql_executor.get_connection") as mock_get_conn:
        mock_get_conn.return_value.__enter__.return_value = mock_conn
        executor.execute(plan, table)
        sql, params = mock_cursor.execute.call_args[0]
        assert 'WHERE "status" = ?' in sql
        assert params == ["active"]
        assert "LIMIT 5" in sql


# =====================================================================
# FIX 3 & 4: FILTER QUALIFICATION & ANTI-JOIN TESTS
# =====================================================================

def test_filter_qualification_preserved_in_parse_response():
    """When LLM returns table in filter, parse_response must qualify the column name."""
    raw_response = {
        "intent": "filter",
        "target_columns": ["id"],
        "filters": [
            {
                "schema": "dbo",
                "table": "site_events",
                "column": "actual_end_time",
                "operator": "is_null",
                "value": None,
            }
        ],
    }
    analyzer = QuestionAnalyzer()
    plan = analyzer._parse_response(json.dumps(raw_response))
    assert len(plan.filters) == 1
    assert plan.filters[0].column == "dbo.site_events.actual_end_time"
    assert plan.filters[0].operator == "is_null"
    assert plan.filters[0].value is None


def test_anti_join_not_in_normalized_to_is_null_with_qualification():
    """operator not_in with empty value maps to is_null with qualified table."""
    raw_response = {
        "intent": "filter",
        "target_columns": ["event_id"],
        "filters": [
            {
                "table": "site_event_registrants",
                "column": "event_id",
                "operator": "not_in",
                "value": None,
            }
        ],
        "joins": [
            {
                "left_schema": "dbo",
                "left_table": "site_events",
                "left_column": "event_id",
                "right_schema": "dbo",
                "right_table": "site_event_registrants",
                "right_column": "event_id",
                "join_type": "left",
            }
        ],
    }
    analyzer = QuestionAnalyzer()
    plan = analyzer._parse_response(json.dumps(raw_response))
    assert len(plan.filters) == 1
    assert plan.filters[0].column == "site_event_registrants.event_id"
    assert plan.filters[0].operator == "is_null"
    assert plan.filters[0].value is None


def test_qualified_filter_resolves_without_ambiguity_across_tables():
    """Qualified filter prevents ambiguity when column exists in multiple tables."""
    table1 = TableInfo(
        schema_name="dbo",
        table_name="table_a",
        columns=[ColumnInfo(name="id", data_type="integer", nullable=False, ordinal_position=1)],
    )
    table2 = TableInfo(
        schema_name="dbo",
        table_name="table_b",
        columns=[ColumnInfo(name="id", data_type="integer", nullable=False, ordinal_position=1)],
    )
    schema = DatabaseSchema(tables=[table1, table2])
    validator = QueryPlanValidator()

    # Unqualified filter is ambiguous
    unqual_plan = QueryPlan(
        intent="filter",
        target_columns=["id"],
        filters=[QueryFilter(column="id", operator="equals", value=1)],
    )
    unqual_res = validator.validate(unqual_plan, schema)
    assert unqual_res.valid is False
    assert any("ambiguous" in err for err in unqual_res.errors)

    # Qualified filter resolves unambiguously
    qual_plan = QueryPlan(
        intent="filter",
        target_columns=["id"],
        filters=[QueryFilter(column="table_a.id", operator="equals", value=1)],
        target_column_refs=[QueryColumn(schema="dbo", table="table_a", column="id")],
    )
    qual_res = validator.validate(qual_plan, schema)
    assert qual_res.valid is True
    assert qual_res.errors == []


# =====================================================================
# FIX 5: POST-PLANNING SCHEMA PRUNING TESTS
# =====================================================================

def test_schema_pruning_single_table_with_companion_tables():
    """Unreferenced companion tables are pruned post-planning."""
    base_table = TableInfo(
        schema_name="dbo",
        table_name="events",
        columns=[
            ColumnInfo(name="id", data_type="integer", nullable=False, ordinal_position=1),
            ColumnInfo(name="end_time", data_type="timestamp", nullable=True, ordinal_position=2),
        ],
    )
    companion_table = TableInfo(
        schema_name="dbo",
        table_name="events_activity",
        columns=[
            ColumnInfo(name="id", data_type="integer", nullable=False, ordinal_position=1),
            ColumnInfo(name="end_time", data_type="timestamp", nullable=True, ordinal_position=2),
        ],
    )
    unrelated_table = TableInfo(
        schema_name="dbo",
        table_name="audit_log",
        columns=[ColumnInfo(name="id", data_type="integer", nullable=False, ordinal_position=1)],
    )
    tables = [base_table, companion_table, unrelated_table]
    full_schema = DatabaseSchema(tables=tables)

    qs = DatabaseQueryService(full_schema)
    plan = QueryPlan(
        intent="count",
        target_columns=["id"],
        filters=[QueryFilter(column="end_time", operator="is_null", value=None)],
        target_column_refs=[QueryColumn(schema="dbo", table="events", column="id")],
    )

    pruned = qs._prune_execution_tables(plan, tables)
    assert len(pruned) == 1
    assert pruned[0].table_name == "events"


def test_schema_pruning_multi_table_join():
    """Pruning retains all tables required by joins and drops companion tables."""
    t1 = TableInfo(schema_name="dbo", table_name="events", columns=[ColumnInfo(name="id", data_type="int", nullable=False, ordinal_position=1)])
    t2 = TableInfo(schema_name="dbo", table_name="registrants", columns=[ColumnInfo(name="id", data_type="int", nullable=False, ordinal_position=1), ColumnInfo(name="event_id", data_type="int", nullable=False, ordinal_position=2)])
    companion = TableInfo(schema_name="dbo", table_name="registrants_report", columns=[ColumnInfo(name="id", data_type="int", nullable=False, ordinal_position=1)])
    tables = [t1, t2, companion]
    schema = DatabaseSchema(tables=tables)

    qs = DatabaseQueryService(schema)
    plan = QueryPlan(
        intent="filter",
        target_columns=["id"],
        joins=[
            QueryJoin(
                left_schema="dbo", left_table="events", left_column="id",
                right_schema="dbo", right_table="registrants", right_column="event_id",
                join_type="left",
            )
        ],
        target_column_refs=[QueryColumn(schema="dbo", table="events", column="id")],
    )

    pruned = qs._prune_execution_tables(plan, tables)
    assert len(pruned) == 2
    pruned_names = {t.table_name for t in pruned}
    assert pruned_names == {"events", "registrants"}


# =====================================================================
# FIX 6: VECTOR RETRIEVAL CALIBRATION TESTS
# =====================================================================

def test_vector_retrieval_threshold_rejects_noise():
    """Tables with only low-score vector noise are rejected in favor of lexical match."""
    table_lexical = TableInfo(
        schema_name="dbo",
        table_name="site_events",
        columns=[
            ColumnInfo(name="event_capacity_limit", data_type="integer", nullable=False, ordinal_position=1),
        ],
    )
    table_noise = TableInfo(
        schema_name="dbo",
        table_name="user_session_log",
        columns=[
            ColumnInfo(name="session_id", data_type="integer", nullable=False, ordinal_position=1),
        ],
    )

    schema = [table_lexical, table_noise]

    # Mock vector service returning 0.14 similarity for table_noise and 0.0 for table_lexical
    mock_vc = MagicMock()
    mock_vc.schema_name = "dbo"
    mock_vc.table_name = "user_session_log"
    mock_vc.similarity = 0.14  # converts to v_score = 14.0

    mock_vector = MagicMock()
    mock_vector.search_tables.return_value = [mock_vc]

    selected = select_tables(
        question="What is the median capacity limit?",
        schema=schema,
        max_tables=5,
        vector_service=mock_vector,
        schema_fingerprint="test_fp",
    )

    selected_names = [t["table"] for t in selected]
    # table_lexical should be selected because capacity matches event_capacity_limit
    assert "site_events" in selected_names
    # table_noise should be rejected because v_score 14 < 25.0
    assert "user_session_log" not in selected_names


# =====================================================================
# FIX 7: CONVERSATION REFERENCE TESTS
# =====================================================================

def test_independent_query_does_not_inherit_stale_reference():
    """Independent query starting with Sort users does not inherit recent_ref."""
    analyzer = QuestionAnalyzer()
    conversation_context = {
        "history": [
            {
                "question": "Show me 5 events",
                "reference_id": "ref-uuid-1234",
                "data": [{"id": 1, "title": "A"}],
            }
        ]
    }

    schema = DatabaseSchema(
        tables=[
            TableInfo(
                schema_name="dbo",
                table_name="users",
                columns=[
                    ColumnInfo(name="id", data_type="integer", nullable=False, ordinal_position=1),
                    ColumnInfo(name="last_login", data_type="timestamp", nullable=False, ordinal_position=2),
                ],
            )
        ]
    )

    # Mock LLM returning null for input_result_reference
    with patch.object(
        analyzer.client,
        "generate_json",
        return_value=json.dumps({
            "intent": "ranking",
            "target_columns": ["id", "last_login"],
            "sort_column": "last_login",
            "sort_direction": "desc",
            "input_result_reference": None,
        }),
    ):
        plan = analyzer.analyze(
            question="Sort users by last login",
            semantic_schema=schema,
            conversation_context=conversation_context,
        )
        assert plan.input_result_reference is None


def test_legitimate_follow_up_preserves_reference():
    """Legitimate follow-up with demonstrative preserves recent_ref."""
    analyzer = QuestionAnalyzer()
    conversation_context = {
        "history": [
            {
                "question": "Show me 5 events",
                "reference_id": "ref-uuid-1234",
                "data": [{"id": 1, "start_date": "2025-01-01"}],
            }
        ]
    }

    schema = DatabaseSchema(
        tables=[
            TableInfo(
                schema_name="dbo",
                table_name="events",
                columns=[
                    ColumnInfo(name="id", data_type="integer", nullable=False, ordinal_position=1),
                    ColumnInfo(name="start_date", data_type="timestamp", nullable=False, ordinal_position=2),
                ],
            )
        ]
    )

    with patch.object(
        analyzer.client,
        "generate_json",
        return_value=json.dumps({
            "intent": "ranking",
            "target_columns": ["id", "start_date"],
            "sort_column": "start_date",
            "sort_direction": "asc",
            "input_result_reference": None,  # even if LLM omitted, demonstrative rule sets it
        }),
    ):
        plan = analyzer.analyze(
            question="Sort those by date",
            semantic_schema=schema,
            conversation_context=conversation_context,
        )
        assert plan.input_result_reference == "ref-uuid-1234"


def test_qualified_not_null_filter_preserved_and_validated():
    """Qualified IS NOT NULL filter is parsed and resolves unambiguously."""
    raw_response = {
        "intent": "filter",
        "target_columns": ["id"],
        "filters": [
            {
                "schema": "dbo",
                "table": "events",
                "column": "completion_date",
                "operator": "is_not_null",
                "value": None,
            }
        ],
    }
    analyzer = QuestionAnalyzer()
    plan = analyzer._parse_response(json.dumps(raw_response))
    assert len(plan.filters) == 1
    assert plan.filters[0].column == "dbo.events.completion_date"
    assert plan.filters[0].operator == "is_not_null"

    schema = DatabaseSchema(
        tables=[
            TableInfo(
                schema_name="dbo",
                table_name="events",
                columns=[
                    ColumnInfo(name="id", data_type="integer", nullable=False, ordinal_position=1),
                    ColumnInfo(name="completion_date", data_type="timestamp", nullable=True, ordinal_position=2),
                ],
            )
        ]
    )
    validator = QueryPlanValidator()
    res = validator.validate(plan, schema)
    assert res.valid is True


def test_multi_table_join_with_duplicate_column_names_both_sides():
    """Multi-table join where both tables share column name resolves via qualified filter."""
    t1 = TableInfo(
        schema_name="dbo",
        table_name="events",
        columns=[
            ColumnInfo(name="id", data_type="integer", nullable=False, ordinal_position=1),
            ColumnInfo(name="status", data_type="varchar", nullable=False, ordinal_position=2),
        ],
    )
    t2 = TableInfo(
        schema_name="dbo",
        table_name="registrations",
        columns=[
            ColumnInfo(name="id", data_type="integer", nullable=False, ordinal_position=1),
            ColumnInfo(name="event_id", data_type="integer", nullable=False, ordinal_position=2),
            ColumnInfo(name="status", data_type="varchar", nullable=False, ordinal_position=3),
        ],
    )
    schema = DatabaseSchema(tables=[t1, t2])
    validator = QueryPlanValidator()

    plan = QueryPlan(
        intent="filter",
        target_columns=["id"],
        target_column_refs=[QueryColumn(schema="dbo", table="events", column="id")],
        joins=[
            QueryJoin(
                left_schema="dbo", left_table="events", left_column="id",
                right_schema="dbo", right_table="registrations", right_column="event_id",
                join_type="inner",
            )
        ],
        filters=[
            QueryFilter(column="dbo.events.status", operator="equals", value="published"),
            QueryFilter(column="dbo.registrations.status", operator="equals", value="confirmed"),
        ],
    )
    res = validator.validate(plan, schema)
    assert res.valid is True
    assert res.errors == []


def test_schema_pruning_single_table_with_five_candidate_tables():
    """Single-table query with five candidate tables is pruned to exactly the target table."""
    tables = [
        TableInfo(schema_name="dbo", table_name="events", columns=[ColumnInfo(name="id", data_type="int", nullable=False, ordinal_position=1), ColumnInfo(name="title", data_type="varchar", nullable=False, ordinal_position=2)]),
        TableInfo(schema_name="dbo", table_name="events_archive", columns=[ColumnInfo(name="id", data_type="int", nullable=False, ordinal_position=1)]),
        TableInfo(schema_name="dbo", table_name="events_summary", columns=[ColumnInfo(name="id", data_type="int", nullable=False, ordinal_position=1)]),
        TableInfo(schema_name="dbo", table_name="event_logs", columns=[ColumnInfo(name="id", data_type="int", nullable=False, ordinal_position=1)]),
        TableInfo(schema_name="dbo", table_name="event_types", columns=[ColumnInfo(name="id", data_type="int", nullable=False, ordinal_position=1)]),
    ]
    schema = DatabaseSchema(tables=tables)
    qs = DatabaseQueryService(schema)
    plan = QueryPlan(
        intent="lookup",
        target_columns=["title"],
        target_column_refs=[QueryColumn(schema="dbo", table="events", column="title")],
    )

    pruned = qs._prune_execution_tables(plan, tables)
    assert len(pruned) == 1
    assert pruned[0].table_name == "events"


def test_schema_pruning_three_table_join():
    """Pruning retains exactly the 3 tables in a 3-table join out of 5 candidates."""
    t1 = TableInfo(schema_name="dbo", table_name="orders", columns=[ColumnInfo(name="order_id", data_type="int", nullable=False, ordinal_position=1)])
    t2 = TableInfo(schema_name="dbo", table_name="order_items", columns=[ColumnInfo(name="item_id", data_type="int", nullable=False, ordinal_position=1), ColumnInfo(name="order_id", data_type="int", nullable=False, ordinal_position=2), ColumnInfo(name="product_id", data_type="int", nullable=False, ordinal_position=3)])
    t3 = TableInfo(schema_name="dbo", table_name="products", columns=[ColumnInfo(name="product_id", data_type="int", nullable=False, ordinal_position=1), ColumnInfo(name="name", data_type="varchar", nullable=False, ordinal_position=2)])
    c1 = TableInfo(schema_name="dbo", table_name="orders_archive", columns=[ColumnInfo(name="order_id", data_type="int", nullable=False, ordinal_position=1)])
    c2 = TableInfo(schema_name="dbo", table_name="product_reviews", columns=[ColumnInfo(name="review_id", data_type="int", nullable=False, ordinal_position=1)])

    tables = [t1, t2, t3, c1, c2]
    schema = DatabaseSchema(tables=tables)
    qs = DatabaseQueryService(schema)
    plan = QueryPlan(
        intent="lookup",
        target_columns=["name"],
        target_column_refs=[QueryColumn(schema="dbo", table="products", column="name")],
        joins=[
            QueryJoin(left_schema="dbo", left_table="orders", left_column="order_id", right_schema="dbo", right_table="order_items", right_column="order_id", join_type="inner"),
            QueryJoin(left_schema="dbo", left_table="order_items", left_column="product_id", right_schema="dbo", right_table="products", right_column="product_id", join_type="inner"),
        ],
    )

    pruned = qs._prune_execution_tables(plan, tables)
    assert len(pruned) == 3
    names = {t.table_name for t in pruned}
    assert names == {"orders", "order_items", "products"}


def test_independent_query_show_only_does_not_inherit_stale_reference():
    """Independent query starting with 'Show only active users' does not inherit stale ref."""
    analyzer = QuestionAnalyzer()
    conversation_context = {
        "history": [
            {
                "question": "Show me 5 products",
                "reference_id": "ref-prod-5555",
                "data": [{"id": 1, "sku": "A1"}],
            }
        ]
    }
    schema = DatabaseSchema(
        tables=[
            TableInfo(
                schema_name="dbo",
                table_name="users",
                columns=[
                    ColumnInfo(name="id", data_type="int", nullable=False, ordinal_position=1),
                    ColumnInfo(name="status", data_type="varchar", nullable=False, ordinal_position=2),
                ],
            )
        ]
    )
    with patch.object(
        analyzer.client,
        "generate_json",
        return_value=json.dumps({
            "intent": "filter",
            "target_columns": ["id"],
            "filters": [{"column": "status", "operator": "equals", "value": "active"}],
            "input_result_reference": None,
        }),
    ):
        plan = analyzer.analyze(
            question="Show only active users",
            semantic_schema=schema,
            conversation_context=conversation_context,
        )
        assert plan.input_result_reference is None


def test_legitimate_follow_up_show_only_those_preserves_reference():
    """Follow up starting with 'Show only those...' preserves recent_ref."""
    analyzer = QuestionAnalyzer()
    conversation_context = {
        "history": [
            {
                "question": "Show me 5 users",
                "reference_id": "ref-users-8888",
                "data": [{"id": 1, "status": "active"}, {"id": 2, "status": "pending"}],
            }
        ]
    }
    schema = DatabaseSchema(
        tables=[
            TableInfo(
                schema_name="dbo",
                table_name="users",
                columns=[
                    ColumnInfo(name="id", data_type="int", nullable=False, ordinal_position=1),
                    ColumnInfo(name="status", data_type="varchar", nullable=False, ordinal_position=2),
                ],
            )
        ]
    )
    with patch.object(
        analyzer.client,
        "generate_json",
        return_value=json.dumps({
            "intent": "filter",
            "target_columns": ["id"],
            "filters": [{"column": "status", "operator": "equals", "value": "active"}],
            "input_result_reference": None,
        }),
    ):
        plan = analyzer.analyze(
            question="Show only those with status active",
            semantic_schema=schema,
            conversation_context=conversation_context,
        )
        assert plan.input_result_reference == "ref-users-8888"


def test_session_isolation_with_empty_or_different_context():
    """Independent session with empty history never receives an inherited reference."""
    analyzer = QuestionAnalyzer()
    schema = DatabaseSchema(
        tables=[
            TableInfo(
                schema_name="dbo",
                table_name="users",
                columns=[ColumnInfo(name="id", data_type="int", nullable=False, ordinal_position=1)],
            )
        ]
    )
    with patch.object(
        analyzer.client,
        "generate_json",
        return_value=json.dumps({
            "intent": "lookup",
            "target_columns": ["id"],
            "input_result_reference": None,
        }),
    ):
        plan = analyzer.analyze(
            question="Sort those by date",  # Even with demonstrative, if history is empty, cannot inherit
            semantic_schema=schema,
            conversation_context={"history": []},
        )
        assert plan.input_result_reference is None

