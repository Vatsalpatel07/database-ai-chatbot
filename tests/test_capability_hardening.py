from unittest.mock import MagicMock, patch
import json
import pytest

from app.core.config import DatabaseConfig
from app.database.schema import (
    ColumnInfo,
    DatabaseSchema,
    ForeignKeyInfo,
    TableInfo,
)
from app.database.sql_executor import SQLQueryExecutor, SQLQueryExecutionError
from app.query.analyzer import QuestionAnalyzer
from app.query.schema import (
    QueryColumn,
    QueryFilter,
    QueryJoin,
    QueryPlan,
)
from app.query.validator import QueryPlanValidator
from app.query.result_validator import QueryResultValidator


# =====================================================================
# 1. QUERYPLAN CONTRACT & BACKWARD COMPATIBILITY
# =====================================================================

def test_queryplan_inner_aggregation_field():
    """QueryPlan supports inner_aggregation field with default None."""
    plan = QueryPlan(intent="derived_aggregation")
    assert plan.inner_aggregation is None

    plan2 = QueryPlan(
        intent="derived_aggregation",
        aggregation="average",
        inner_aggregation="count",
    )
    assert plan2.inner_aggregation == "count"
    assert plan2.aggregation == "average"


def test_queryplan_backward_compatibility():
    """Existing plan construction without inner_aggregation is fully preserved."""
    plan = QueryPlan(
        intent="aggregation",
        aggregation="count",
        group_by=["event_sitecore_id"],
    )
    assert plan.inner_aggregation is None
    assert plan.intent == "aggregation"
    assert plan.aggregation == "count"


# =====================================================================
# 2. QUESTION ANALYZER NORMALIZATION
# =====================================================================

@pytest.fixture
def test_schema():
    return DatabaseSchema(
        tables=[
            TableInfo(
                schema_name="dbo",
                table_name="site_events",
                columns=[
                    ColumnInfo(name="event_sitecore_id", data_type="uuid", nullable=False, ordinal_position=1),
                    ColumnInfo(name="event_name", data_type="varchar", nullable=False, ordinal_position=2),
                ],
            ),
            TableInfo(
                schema_name="dbo",
                table_name="site_event_registrants",
                columns=[
                    ColumnInfo(name="registration_sitecore_id", data_type="uuid", nullable=False, ordinal_position=1),
                    ColumnInfo(name="event_sitecore_id", data_type="uuid", nullable=False, ordinal_position=2),
                    ColumnInfo(name="fee_paid", data_type="decimal", nullable=True, ordinal_position=3),
                ],
            ),
        ]
    )


def test_analyzer_detect_derived_aggregation_patterns():
    """Analyzer detects derived aggregation patterns."""
    cases = [
        ("What is the average number of registrations per event?", ("average", "count")),
        ("Show me the median count of attendees per session", ("median", "count")),
        ("Find the maximum number of registrations per event", ("max", "count")),
        ("What is the min count of orders per customer?", ("min", "count")),
        ("Calculate the total number of items per store", ("sum", "count")),
        ("What is the avg count of tickets per user?", ("average", "count")),
    ]
    for question, expected in cases:
        detected = QuestionAnalyzer._detect_derived_aggregation_request(question.casefold())
        assert detected == expected, f"Failed for question: {question}"


def test_analyzer_normalize_derived_aggregation_clears_sort_and_limit(test_schema):
    """Derived aggregation normalization clears sort and limit to ensure scalar result."""
    raw_plan = QueryPlan(
        intent="aggregation",
        aggregation="average",
        group_by=["event_sitecore_id"],
        target_columns=["registration_sitecore_id"],
        sort_column="count",
        sort_direction="desc",
        limit=1,
    )
    normalized = QuestionAnalyzer._normalize_plan(
        plan=raw_plan,
        question="What is the average number of registrations per event?",
        semantic_schema=test_schema,
    )
    assert normalized.intent == "derived_aggregation"
    assert normalized.aggregation == "average"
    assert normalized.inner_aggregation == "count"
    assert normalized.group_by == ["event_sitecore_id"]
    assert normalized.sort_column is None
    assert normalized.sort_direction is None
    assert normalized.limit is None


def test_analyzer_normalize_explicit_derived_aggregation(test_schema):
    """Planner returning intent=derived_aggregation is preserved."""
    raw_plan = QueryPlan(
        intent="derived_aggregation",
        aggregation="median",
        inner_aggregation="count",
        group_by=["event_sitecore_id"],
        target_columns=["registration_sitecore_id"],
    )
    normalized = QuestionAnalyzer._normalize_plan(
        plan=raw_plan,
        question="What is the median number of registrations per event?",
        semantic_schema=test_schema,
    )
    assert normalized.intent == "derived_aggregation"
    assert normalized.aggregation == "median"
    assert normalized.inner_aggregation == "count"
    assert normalized.group_by == ["event_sitecore_id"]


def test_analyzer_ordinary_aggregation_not_converted(test_schema):
    """Ordinary grouped aggregation without per-entity count language is preserved."""
    raw_plan = QueryPlan(
        intent="aggregation",
        aggregation="sum",
        group_by=["event_sitecore_id"],
        target_columns=["fee_paid"],
    )
    normalized = QuestionAnalyzer._normalize_plan(
        plan=raw_plan,
        question="What is the total fee paid by event?",
        semantic_schema=test_schema,
    )
    assert normalized.intent == "aggregation"
    assert normalized.aggregation == "sum"
    assert normalized.inner_aggregation is None


# =====================================================================
# 3. QUERYPLAN VALIDATOR
# =====================================================================

def test_validator_derived_aggregation_count_exempt_from_numeric_check():
    """Inner COUNT in derived aggregation does NOT require numeric target columns."""
    schema = DatabaseSchema(
        tables=[
            TableInfo(
                schema_name="dbo",
                table_name="site_event_registrants",
                columns=[
                    ColumnInfo(name="registration_sitecore_id", data_type="uuid", nullable=False, ordinal_position=1),
                    ColumnInfo(name="event_sitecore_id", data_type="uuid", nullable=False, ordinal_position=2),
                ],
            ),
        ]
    )
    validator = QueryPlanValidator()
    plan = QueryPlan(
        intent="derived_aggregation",
        aggregation="average",
        inner_aggregation="count",
        group_by=["event_sitecore_id"],
        target_columns=["registration_sitecore_id"],  # uuid column
    )
    res = validator.validate(plan, schema)
    assert res.valid, f"Expected valid, got errors: {res.errors}"


def test_validator_derived_aggregation_sum_requires_numeric_target():
    """Inner SUM in derived aggregation still requires numeric target columns."""
    schema = DatabaseSchema(
        tables=[
            TableInfo(
                schema_name="dbo",
                table_name="site_event_registrants",
                columns=[
                    ColumnInfo(name="registration_sitecore_id", data_type="uuid", nullable=False, ordinal_position=1),
                    ColumnInfo(name="event_sitecore_id", data_type="uuid", nullable=False, ordinal_position=2),
                    ColumnInfo(name="fee_paid", data_type="decimal", nullable=True, ordinal_position=3),
                ],
            ),
        ]
    )
    validator = QueryPlanValidator()
    # Invalid: inner SUM on UUID column
    bad_plan = QueryPlan(
        intent="derived_aggregation",
        aggregation="average",
        inner_aggregation="sum",
        group_by=["event_sitecore_id"],
        target_columns=["registration_sitecore_id"],  # uuid
    )
    res_bad = validator.validate(bad_plan, schema)
    assert not res_bad.valid
    assert any("requires a numeric column" in err for err in res_bad.errors)

    # Valid: inner SUM on decimal column
    good_plan = QueryPlan(
        intent="derived_aggregation",
        aggregation="average",
        inner_aggregation="sum",
        group_by=["event_sitecore_id"],
        target_columns=["fee_paid"],  # decimal
    )
    res_good = validator.validate(good_plan, schema)
    assert res_good.valid, f"Expected valid, got errors: {res_good.errors}"


def test_validator_ordinary_aggregation_still_enforces_numeric_check(test_schema):
    """Ordinary aggregation still strictly enforces numeric column validation."""
    validator = QueryPlanValidator()
    plan = QueryPlan(
        intent="aggregation",
        aggregation="average",
        target_columns=["event_name"],  # varchar
    )
    res = validator.validate(plan, test_schema)
    assert not res.valid
    assert any("requires a numeric column" in err for err in res.errors)


def test_validator_derived_aggregation_requires_group_by(test_schema):
    """Derived aggregation requires at least one group-by column."""
    validator = QueryPlanValidator()
    plan = QueryPlan(
        intent="derived_aggregation",
        aggregation="average",
        inner_aggregation="count",
        group_by=[],
        target_columns=["registration_sitecore_id"],
    )
    res = validator.validate(plan, test_schema)
    assert not res.valid
    assert any("group-by" in err for err in res.errors)


# =====================================================================
# 4. QUERY RESULT VALIDATOR
# =====================================================================

def test_result_validator_derived_aggregation_scalar():
    """QueryResultValidator validates scalar numeric result for derived_aggregation."""
    rv = QueryResultValidator()
    plan = QueryPlan(intent="derived_aggregation", aggregation="average", inner_aggregation="count")

    assert rv.validate(plan, 2.96).valid
    assert rv.validate(plan, 5).valid
    assert rv.validate(plan, None).valid  # allow_none=True
    assert not rv.validate(plan, "string").valid
    assert not rv.validate(plan, [{"val": 1}]).valid


def test_result_validator_ranking_tabular():
    """QueryResultValidator validates tabular list[dict] result for ranking."""
    rv = QueryResultValidator()
    plan = QueryPlan(intent="ranking", sort_column="count")

    assert rv.validate(plan, [{"id": 1, "count": 10}]).valid
    assert rv.validate(plan, []).valid
    assert not rv.validate(plan, 10).valid
    assert not rv.validate(plan, "top1").valid


# =====================================================================
# 5. SQL EXECUTOR (UNIT & DIALECT VERIFICATION)
# =====================================================================

def test_sql_executor_single_table_derived_aggregation_sql():
    """SQLQueryExecutor constructs correct derived aggregation SQL for single table."""
    config = DatabaseConfig(
        server="localhost",
        database="testdb",
        engine="postgresql",
        user="test",
        password="pwd",
    )
    executor = SQLQueryExecutor(config)

    table = TableInfo(
        schema_name="dbo",
        table_name="site_event_registrants",
        columns=[
            ColumnInfo(name="registration_sitecore_id", data_type="uuid", nullable=False, ordinal_position=1),
            ColumnInfo(name="event_sitecore_id", data_type="uuid", nullable=False, ordinal_position=2),
        ],
    )

    plan = QueryPlan(
        intent="derived_aggregation",
        aggregation="average",
        inner_aggregation="count",
        group_by=["event_sitecore_id"],
        target_columns=["registration_sitecore_id"],
    )

    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = MagicMock(aggregation_value=3.5)
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    mock_conn.__enter__.return_value = mock_conn

    with patch("app.database.sql_executor.get_connection", return_value=mock_conn):
        res = executor.execute(plan, table)

    assert res == 3.5
    executed_sql, params = mock_cursor.execute.call_args[0]
    assert "AVG(CAST(sub.\"__derived_metric\" AS FLOAT))" in executed_sql
    assert "GROUP BY \"event_sitecore_id\"" in executed_sql


def test_sql_executor_sqlserver_median_dialect():
    """SQL Server dialect generates TOP (1) ... OVER () for median derived aggregation."""
    config = DatabaseConfig(
        server="localhost",
        database="testdb",
        engine="sqlserver",
    )
    executor = SQLQueryExecutor(config)

    table = TableInfo(
        schema_name="dbo",
        table_name="registrations",
        columns=[
            ColumnInfo(name="id", data_type="int", nullable=False, ordinal_position=1),
            ColumnInfo(name="group_id", data_type="int", nullable=False, ordinal_position=2),
        ],
    )

    plan = QueryPlan(
        intent="derived_aggregation",
        aggregation="median",
        inner_aggregation="count",
        group_by=["group_id"],
    )

    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = MagicMock(aggregation_value=4.0)
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    mock_conn.__enter__.return_value = mock_conn

    with patch("app.database.sql_executor.get_connection", return_value=mock_conn):
        res = executor.execute(plan, table)

    assert res == 4.0
    executed_sql, params = mock_cursor.execute.call_args[0]
    assert "TOP (1)" in executed_sql
    assert "PERCENTILE_CONT(0.5) WITHIN GROUP" in executed_sql
    assert "OVER ()" in executed_sql


# =====================================================================
# 6. LIVE DATABASE INTEGRATION TESTS (POSTGRESQL)
# =====================================================================

def test_live_derived_aggregations_postgresql():
    """Live execution against canonical PostgreSQL database."""
    cfg = DatabaseConfig.from_env()
    executor = SQLQueryExecutor(cfg)

    table = TableInfo(
        schema_name="dbo",
        table_name="site_event_registrants",
        columns=[
            ColumnInfo(name="registration_sitecore_id", data_type="uuid", nullable=False, ordinal_position=1),
            ColumnInfo(name="event_sitecore_id", data_type="uuid", nullable=False, ordinal_position=2),
        ],
    )

    # Average registrations per event
    plan_avg = QueryPlan(
        intent="derived_aggregation",
        aggregation="average",
        inner_aggregation="count",
        group_by=["event_sitecore_id"],
        target_columns=["registration_sitecore_id"],
    )
    avg_val = executor.execute(plan_avg, table)
    assert avg_val is not None
    assert isinstance(avg_val, float)
    assert 2.0 < avg_val < 4.0

    # Median registrations per event
    plan_med = QueryPlan(
        intent="derived_aggregation",
        aggregation="median",
        inner_aggregation="count",
        group_by=["event_sitecore_id"],
        target_columns=["registration_sitecore_id"],
    )
    med_val = executor.execute(plan_med, table)
    assert med_val is not None
    assert float(med_val) == 3.0

    # Min registrations per event
    plan_min = QueryPlan(
        intent="derived_aggregation",
        aggregation="min",
        inner_aggregation="count",
        group_by=["event_sitecore_id"],
        target_columns=["registration_sitecore_id"],
    )
    min_val = executor.execute(plan_min, table)
    assert min_val is not None
    assert float(min_val) == 1.0

    # Max registrations per event
    plan_max = QueryPlan(
        intent="derived_aggregation",
        aggregation="max",
        inner_aggregation="count",
        group_by=["event_sitecore_id"],
        target_columns=["registration_sitecore_id"],
    )
    max_val = executor.execute(plan_max, table)
    assert max_val is not None
    assert float(max_val) == 5.0

    # Sum of counts
    plan_sum = QueryPlan(
        intent="derived_aggregation",
        aggregation="sum",
        inner_aggregation="count",
        group_by=["event_sitecore_id"],
        target_columns=["registration_sitecore_id"],
    )
    sum_val = executor.execute(plan_sum, table)
    assert sum_val is not None
    assert float(sum_val) == 800.0


def test_live_joined_derived_aggregation_postgresql():
    """Live execution of joined derived aggregation against PostgreSQL."""
    cfg = DatabaseConfig.from_env()
    executor = SQLQueryExecutor(cfg)

    events_table = TableInfo(
        schema_name="dbo",
        table_name="site_events",
        columns=[
            ColumnInfo(name="event_sitecore_id", data_type="uuid", nullable=False, ordinal_position=1),
            ColumnInfo(name="event_name", data_type="varchar", nullable=False, ordinal_position=2),
        ],
    )
    registrants_table = TableInfo(
        schema_name="dbo",
        table_name="site_event_registrants",
        columns=[
            ColumnInfo(name="registration_sitecore_id", data_type="uuid", nullable=False, ordinal_position=1),
            ColumnInfo(name="event_sitecore_id", data_type="uuid", nullable=False, ordinal_position=2),
        ],
    )

    plan = QueryPlan(
        intent="derived_aggregation",
        aggregation="average",
        inner_aggregation="count",
        group_by=["event_sitecore_id"],
        target_columns=["registration_sitecore_id"],
        joins=[
            QueryJoin(
                left_schema="dbo",
                left_table="site_events",
                left_column="event_sitecore_id",
                right_schema="dbo",
                right_table="site_event_registrants",
                right_column="event_sitecore_id",
                join_type="inner",
            )
        ],
    )
    res = executor.execute(plan, events_table, tables=[events_table, registrants_table])
    assert res is not None
    assert isinstance(res, float)
    assert 2.0 < res < 4.0


# =====================================================================
# 7. AGGREGATE RANKING & JOIN ENTITY PROJECTION TESTS
# =====================================================================

def test_live_joined_entity_projection_and_ranking_postgresql():
    """Generic JOIN entity projection returns both ID and descriptor alongside aggregate."""
    cfg = DatabaseConfig.from_env()
    executor = SQLQueryExecutor(cfg)

    events_table = TableInfo(
        schema_name="dbo",
        table_name="site_events",
        columns=[
            ColumnInfo(name="event_sitecore_id", data_type="uuid", nullable=False, ordinal_position=1),
            ColumnInfo(name="event_topic_title", data_type="varchar", nullable=False, ordinal_position=2),
        ],
    )
    registrants_table = TableInfo(
        schema_name="dbo",
        table_name="site_event_registrants",
        columns=[
            ColumnInfo(name="registration_sitecore_id", data_type="uuid", nullable=False, ordinal_position=1),
            ColumnInfo(name="event_sitecore_id", data_type="uuid", nullable=False, ordinal_position=2),
        ],
    )

    plan = QueryPlan(
        intent="aggregation",
        aggregation="count",
        group_by=["event_sitecore_id", "event_topic_title"],
        group_by_refs=[
            QueryColumn(schema="dbo", table="site_events", column="event_sitecore_id"),
            QueryColumn(schema="dbo", table="site_events", column="event_topic_title"),
        ],
        sort_column="count",
        sort_direction="desc",
        limit=1,
        joins=[
            QueryJoin(
                left_schema="dbo",
                left_table="site_events",
                left_column="event_sitecore_id",
                right_schema="dbo",
                right_table="site_event_registrants",
                right_column="event_sitecore_id",
                join_type="inner",
            )
        ],
    )

    rows = executor.execute(plan, events_table, tables=[events_table, registrants_table])
    assert rows is not None
    assert len(rows) == 1
    row = rows[0]
    assert "event_sitecore_id" in row
    assert "event_topic_title" in row
    assert "aggregation_value" in row
    assert row["aggregation_value"] >= 1


def test_aggregate_ranking_with_ties_sql_generation():
    """Dialect-aware WITH TIES generation for aggregate ranking."""
    # PostgreSQL dialect
    pg_config = DatabaseConfig(
        server="localhost",
        database="testdb",
        engine="postgresql",
        user="test",
        password="pwd",
    )
    pg_executor = SQLQueryExecutor(pg_config)

    table = TableInfo(
        schema_name="dbo",
        table_name="events",
        columns=[
            ColumnInfo(name="event_id", data_type="uuid", nullable=False, ordinal_position=1),
        ],
    )

    plan = QueryPlan(
        intent="aggregation",
        aggregation="count",
        group_by=["event_id"],
        sort_column="count",
        sort_direction="desc",
        limit=1,
        include_ties=True,
    )

    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = []
    mock_cursor.description = [("event_id",), ("aggregation_value",)]
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    mock_conn.__enter__.return_value = mock_conn

    with patch("app.database.sql_executor.get_connection", return_value=mock_conn):
        pg_executor.execute(plan, table)

    pg_sql = mock_cursor.execute.call_args[0][0]
    assert "FETCH FIRST 1 ROWS WITH TIES" in pg_sql

    # SQL Server dialect
    ms_config = DatabaseConfig(
        server="localhost",
        database="testdb",
        engine="sqlserver",
    )
    ms_executor = SQLQueryExecutor(ms_config)

    with patch("app.database.sql_executor.get_connection", return_value=mock_conn):
        ms_executor.execute(plan, table)

    ms_sql = mock_cursor.execute.call_args[0][0]
    assert "TOP (1) WITH TIES" in ms_sql


# =====================================================================
# 6. CAPABILITY-HARDENING BATCH 2:
#    FILTER PRESERVATION, NULL-SAFE RANKING, FOLLOW-UP HARDENING
# =====================================================================

def test_batch2_year_equals_filter_survives_normalization():
    """LLM filter with operator 'year_equals' is preserved and converted to date range."""
    raw_response = {
        "intent": "count",
        "target_columns": ["event_sitecore_id"],
        "filters": [
            {
                "column": "event_start_datetime",
                "operator": "year_equals",
                "value": 2024,
            }
        ],
    }
    plan = QuestionAnalyzer._parse_response(json.dumps(raw_response))
    assert len(plan.filters) == 2
    f1 = plan.filters[0]
    f2 = plan.filters[1]
    assert f1.column == "event_start_datetime"
    assert f1.operator == "greater_than_or_equal"
    assert f1.value == "2024-01-01"
    assert f2.column == "event_start_datetime"
    assert f2.operator == "less_than"
    assert f2.value == "2025-01-01"


def test_batch2_year_filter_aliases():
    """All operator variations for year are canonicalized into date range."""
    for op in ["year", "year_is", "in_year", "year equal", "year_equals"]:
        raw_response = {
            "intent": "count",
            "target_columns": ["id"],
            "filters": [
                {
                    "column": "start_date",
                    "operator": op,
                    "value": "2025",
                }
            ],
        }
        plan = QuestionAnalyzer._parse_response(json.dumps(raw_response))
        assert len(plan.filters) == 2, f"Failed for operator {op}"
        assert plan.filters[0].operator == "greater_than_or_equal"
        assert plan.filters[0].value == "2025-01-01"
        assert plan.filters[1].operator == "less_than"
        assert plan.filters[1].value == "2026-01-01"


def test_batch2_temporal_equality_normalized_to_range(test_schema):
    """Equality filter on temporal column with 4-digit year converts to range in _normalize_plan."""
    plan = QueryPlan(
        intent="count",
        target_columns=["event_sitecore_id"],
        filters=[
            QueryFilter(
                column="event_start_datetime",
                operator="equals",
                value=2024,
            )
        ],
    )
    normalized = QuestionAnalyzer._normalize_plan(
        plan=plan,
        question="How many events started in 2024?",
        semantic_schema=test_schema,
    )
    assert len(normalized.filters) == 2
    assert normalized.filters[0].operator == "greater_than_or_equal"
    assert normalized.filters[0].value == "2024-01-01"
    assert normalized.filters[1].operator == "less_than"
    assert normalized.filters[1].value == "2025-01-01"


def _get_live_site_events_table():
    return TableInfo(
        schema_name="dbo",
        table_name="site_events",
        columns=[
            ColumnInfo(name="event_sitecore_id", data_type="uuid", nullable=False, ordinal_position=1),
            ColumnInfo(name="event_start_datetime", data_type="timestamp", nullable=False, ordinal_position=2),
            ColumnInfo(name="event_duration", data_type="integer", nullable=True, ordinal_position=3),
            ColumnInfo(name="event_capacity_limit", data_type="integer", nullable=True, ordinal_position=4),
        ],
    )


def test_batch2_live_postgresql_yearly_event_counts():
    """Live query on PostgreSQL dbo.site_events verifies exact yearly counts."""
    cfg = DatabaseConfig.from_env()
    events_table = _get_live_site_events_table()
    executor = SQLQueryExecutor(cfg)

    # 2024 -> 211
    plan_2024 = QueryPlan(
        intent="count",
        target_columns=["event_sitecore_id"],
        filters=[
            QueryFilter(column="event_start_datetime", operator="greater_than_or_equal", value="2024-01-01"),
            QueryFilter(column="event_start_datetime", operator="less_than", value="2025-01-01"),
        ],
    )
    count_2024 = executor.execute(plan_2024, events_table)
    assert count_2024 == 211

    # 2025 -> 313
    plan_2025 = QueryPlan(
        intent="count",
        target_columns=["event_sitecore_id"],
        filters=[
            QueryFilter(column="event_start_datetime", operator="greater_than_or_equal", value="2025-01-01"),
            QueryFilter(column="event_start_datetime", operator="less_than", value="2026-01-01"),
        ],
    )
    count_2025 = executor.execute(plan_2025, events_table)
    assert count_2025 == 313

    # 2026 -> 196
    plan_2026 = QueryPlan(
        intent="count",
        target_columns=["event_sitecore_id"],
        filters=[
            QueryFilter(column="event_start_datetime", operator="greater_than_or_equal", value="2026-01-01"),
            QueryFilter(column="event_start_datetime", operator="less_than", value="2027-01-01"),
        ],
    )
    count_2026 = executor.execute(plan_2026, events_table)
    assert count_2026 == 196

    assert count_2024 + count_2025 + count_2026 == 720


def test_batch2_null_safe_ranking_highest_duration_postgresql():
    """Highest duration ranking excludes NULLs and returns winning record (180)."""
    cfg = DatabaseConfig.from_env()
    events_table = _get_live_site_events_table()
    executor = SQLQueryExecutor(cfg)

    plan = QueryPlan(
        intent="ranking",
        target_columns=["event_sitecore_id", "event_duration"],
        sort_column="event_duration",
        sort_direction="desc",
        limit=1,
    )
    result = executor.execute(plan, events_table)
    assert len(result) == 1
    winner = result[0]
    assert winner["event_duration"] is not None
    assert winner["event_duration"] == 180


def test_batch2_null_safe_ranking_lowest_duration_postgresql():
    """Lowest duration ranking excludes NULLs and returns winning record (0)."""
    cfg = DatabaseConfig.from_env()
    events_table = _get_live_site_events_table()
    executor = SQLQueryExecutor(cfg)

    plan = QueryPlan(
        intent="ranking",
        target_columns=["event_sitecore_id", "event_duration"],
        sort_column="event_duration",
        sort_direction="asc",
        limit=1,
    )
    result = executor.execute(plan, events_table)
    assert len(result) == 1
    winner = result[0]
    assert winner["event_duration"] is not None
    assert winner["event_duration"] == 0
    assert len(result) == 1
    winner = result[0]
    assert winner["event_duration"] is not None
    assert winner["event_duration"] == 0


def test_batch2_all_null_ranking_returns_empty_result():
    """Ranking on a column where all candidates are NULL returns empty list."""
    config = DatabaseConfig(
        server="localhost",
        database="testdb",
        engine="postgresql",
        user="test",
        password="pwd",
    )
    executor = SQLQueryExecutor(config)
    table = TableInfo(
        schema_name="dbo",
        table_name="events",
        columns=[
            ColumnInfo(name="id", data_type="int", nullable=False, ordinal_position=1),
            ColumnInfo(name="duration", data_type="int", nullable=True, ordinal_position=2),
        ],
    )
    plan = QueryPlan(
        intent="ranking",
        target_columns=["id", "duration"],
        sort_column="duration",
        sort_direction="desc",
        limit=1,
    )

    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = []
    mock_cursor.description = [("id",), ("duration",)]
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    mock_conn.__enter__.return_value = mock_conn

    with patch("app.database.sql_executor.get_connection", return_value=mock_conn):
        res = executor.execute(plan, table)

    assert res == []
    sql_executed = mock_cursor.execute.call_args[0][0]
    assert '"duration" IS NOT NULL' in sql_executed


def test_batch2_explicit_is_null_filter_preserved():
    """Explicit 'is_null' filter on sort column is NOT overwritten by IS NOT NULL."""
    config = DatabaseConfig(
        server="localhost",
        database="testdb",
        engine="postgresql",
        user="test",
        password="pwd",
    )
    executor = SQLQueryExecutor(config)
    table = TableInfo(
        schema_name="dbo",
        table_name="events",
        columns=[
            ColumnInfo(name="id", data_type="int", nullable=False, ordinal_position=1),
            ColumnInfo(name="duration", data_type="int", nullable=True, ordinal_position=2),
        ],
    )
    plan = QueryPlan(
        intent="lookup",
        target_columns=["id", "duration"],
        filters=[QueryFilter(column="duration", operator="is_null", value=None)],
        sort_column="id",
        sort_direction="asc",
    )

    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = [{"id": 1, "duration": None}]
    mock_cursor.description = [("id",), ("duration",)]
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    mock_conn.__enter__.return_value = mock_conn

    with patch("app.database.sql_executor.get_connection", return_value=mock_conn):
        res = executor.execute(plan, table)

    sql_executed = mock_cursor.execute.call_args[0][0]
    assert '"duration" IS NULL' in sql_executed
    assert '"duration" IS NOT NULL' not in sql_executed


def test_batch2_followup_reference_cleared_for_standalone_queries(test_schema):
    """Standalone questions do not inherit input_result_reference even if LLM provided one."""
    analyzer = QuestionAnalyzer()
    context = {
        "history": [
            {
                "question": "How many events started in 2024?",
                "reference_id": "result_count_turn1",
                "data": [{"row_count": 211}],
            }
        ]
    }

    # "Show 5th event"
    with patch.object(
        analyzer.client,
        "generate_json",
        return_value=json.dumps({
            "intent": "lookup",
            "target_columns": ["event_sitecore_id"],
            "input_result_reference": "result_count_turn1",  # LLM over-inherited
        }),
    ):
        plan = analyzer.analyze(
            question="Show 5th event",
            semantic_schema=test_schema,
            conversation_context=context,
        )
        assert plan.input_result_reference is None
        assert plan.limit == 5

    # "Which event has the highest capacity?"
    with patch.object(
        analyzer.client,
        "generate_json",
        return_value=json.dumps({
            "intent": "ranking",
            "target_columns": ["event_sitecore_id"],
            "sort_column": "event_capacity_limit",
            "sort_direction": "desc",
            "limit": 1,
            "input_result_reference": "result_count_turn1",  # LLM over-inherited
        }),
    ):
        plan = analyzer.analyze(
            question="Which event has the highest capacity?",
            semantic_schema=test_schema,
            conversation_context=context,
        )
        assert plan.input_result_reference is None


def test_batch2_followup_reference_preserved_for_legitimate_followups(test_schema):
    """Legitimate follow-up patterns preserve the input_result_reference."""
    analyzer = QuestionAnalyzer()
    context = {
        "history": [
            {
                "question": "Which events have the highest capacity?",
                "reference_id": "result_top_capacity",
                "data": [{"event_sitecore_id": "uuid-1", "event_capacity_limit": 500}],
            }
        ]
    }

    legitimate_questions = [
        "Now show only the top 5",
        "Sort those by capacity",
        "What about the lowest one?",
        "Which one has the highest duration among them?",
        "Filter those where status is active",
    ]

    for q in legitimate_questions:
        with patch.object(
            analyzer.client,
            "generate_json",
            return_value=json.dumps({
                "intent": "ranking",
                "target_columns": ["event_sitecore_id"],
                "input_result_reference": None,  # Even if LLM omitted, rule restores it
            }),
        ):
            plan = analyzer.analyze(
                question=q,
                semantic_schema=test_schema,
                conversation_context=context,
            )
            assert plan.input_result_reference == "result_top_capacity", f"Failed for follow-up: {q}"


def test_batch2_ordinal_standalone_limit_not_arbitrary_one(test_schema):
    """Standalone ordinal questions set limit to N to fetch up to the N-th record."""
    analyzer = QuestionAnalyzer()

    # "Show 5th event" -> limit 5
    with patch.object(
        analyzer.client,
        "generate_json",
        return_value=json.dumps({
            "intent": "lookup",
            "target_columns": [],
        }),
    ):
        plan = analyzer.analyze(
            question="Show 5th event",
            semantic_schema=test_schema,
        )
        assert plan.limit == 5
        assert plan.input_result_reference is None

    # "Show the third event" -> limit 3
    with patch.object(
        analyzer.client,
        "generate_json",
        return_value=json.dumps({
            "intent": "lookup",
            "target_columns": [],
        }),
    ):
        plan = analyzer.analyze(
            question="Show the third event",
            semantic_schema=test_schema,
        )
        assert plan.limit == 3
        assert plan.input_result_reference is None


def test_batch2_filter_plus_ranking_interaction_postgresql():
    """Live query combining date range filter and ranking executes cleanly."""
    cfg = DatabaseConfig.from_env()
    events_table = _get_live_site_events_table()
    executor = SQLQueryExecutor(cfg)

    # Which event in 2025 has the highest capacity limit?
    plan = QueryPlan(
        intent="ranking",
        target_columns=["event_sitecore_id", "event_start_datetime", "event_capacity_limit"],
        filters=[
            QueryFilter(column="event_start_datetime", operator="greater_than_or_equal", value="2025-01-01"),
            QueryFilter(column="event_start_datetime", operator="less_than", value="2026-01-01"),
        ],
        sort_column="event_capacity_limit",
        sort_direction="desc",
        limit=1,
    )
    result = executor.execute(plan, events_table)
    assert len(result) == 1
    winner = result[0]
    assert winner["event_capacity_limit"] == 500
    assert str(winner["event_start_datetime"]).startswith("2025")


def test_batch2_dialect_null_safe_sql_server_compatibility():
    """SQL Server dialect uses IS NOT NULL and omits NULLS LAST."""
    config = DatabaseConfig(
        server="localhost",
        database="testdb",
        engine="sqlserver",
    )
    executor = SQLQueryExecutor(config)
    table = TableInfo(
        schema_name="dbo",
        table_name="events",
        columns=[
            ColumnInfo(name="id", data_type="int", nullable=False, ordinal_position=1),
            ColumnInfo(name="duration", data_type="int", nullable=True, ordinal_position=2),
        ],
    )
    plan = QueryPlan(
        intent="ranking",
        target_columns=["id", "duration"],
        sort_column="duration",
        sort_direction="desc",
        limit=1,
    )

    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = [{"id": 1, "duration": 180}]
    mock_cursor.description = [("id",), ("duration",)]
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    mock_conn.__enter__.return_value = mock_conn

    with patch("app.database.sql_executor.get_connection", return_value=mock_conn):
        executor.execute(plan, table)

    sql_executed = mock_cursor.execute.call_args[0][0]
    assert "[duration] IS NOT NULL" in sql_executed
    assert "NULLS LAST" not in sql_executed

