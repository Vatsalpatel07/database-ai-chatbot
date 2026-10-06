"""
Focused regression tests for HAVING filter preservation, parsing, normalization,
SQL execution, and conversation follow-up inheritance.
"""

import json
import pytest
from unittest.mock import MagicMock

from app.query.analyzer import QuestionAnalyzer
from app.query.schema import QueryPlan, QueryFilter, QueryJoin, QueryColumn
from app.query.validator import QueryPlanValidator
from app.database.query_service import DatabaseQueryService
from app.core.config import DatabaseConfig
from app.database.metadata_service import DatabaseMetadataService


import os

@pytest.fixture
def pg_config():
    return DatabaseConfig(
        engine="postgresql",
        server="localhost",
        port=5432,
        database="mnghealthreportingdb",
        schema="dbo",
        driver="",
        user="postgres",
        password=os.environ.get("DB_PASSWORD", "Vatsal@123"),
    )


@pytest.fixture
def live_schema(pg_config):
    svc = DatabaseMetadataService(config=pg_config)
    meta = svc.load()
    return meta.schema


# =============================================================================
# 1. PARSING & OPERATOR NORMALIZATION
# =============================================================================

def test_parse_response_having_filters_from_json():
    """Verify _parse_response parses having_filters from JSON."""
    raw = json.dumps({
        "intent": "aggregation",
        "having_filters": [
            {"column": "count", "operator": "greater_than", "value": 5}
        ],
        "group_by": ["event_sitecore_id"],
        "aggregation": "count",
    })
    plan = QuestionAnalyzer._parse_response(raw)
    assert len(plan.having_filters) == 1
    assert plan.having_filters[0].column == "count"
    assert plan.having_filters[0].operator == "greater_than"
    assert plan.having_filters[0].value == 5


def test_parse_response_having_filters_symbol_operators():
    """Verify _parse_response normalizes symbolic operators like >, >=, <, <=, ==, !="""
    for sym_op, norm_op in [
        (">", "greater_than"),
        (">=", "greater_than_or_equal"),
        ("<", "less_than"),
        ("<=", "less_than_or_equal"),
        ("==", "equals"),
        ("!=", "not_equals"),
    ]:
        raw = json.dumps({
            "intent": "aggregation",
            "having_filters": [
                {"column": "count", "operator": sym_op, "value": "10"}
            ],
            "group_by": ["event_sitecore_id"],
            "aggregation": "count",
        })
        plan = QuestionAnalyzer._parse_response(raw)
        assert len(plan.having_filters) == 1
        assert plan.having_filters[0].operator == norm_op
        assert plan.having_filters[0].value == 10


# =============================================================================
# 2. PLAN NORMALIZATION & PRESERVATION
# =============================================================================

def test_normalize_plan_preserves_having_filters():
    """Verify _normalize_plan does not discard valid having_filters."""
    mock_schema = MagicMock()
    mock_schema.tables = []

    plan = QueryPlan(
        intent="aggregation",
        group_by=["event_sitecore_id"],
        aggregation="count",
        having_filters=[QueryFilter(column="count", operator="greater_than", value=5)],
    )

    normalized = QuestionAnalyzer._normalize_plan(
        plan=plan,
        question="Which events have more than 5 registrations?",
        semantic_schema=mock_schema,
    )

    assert len(normalized.having_filters) == 1
    assert normalized.having_filters[0].column == "count"
    assert normalized.having_filters[0].operator == "greater_than"
    assert normalized.having_filters[0].value == 5
    assert normalized.limit is None  # Must NOT be limited to 1


def test_normalize_plan_moves_aggregate_filter_from_filters_to_having():
    """Verify that an aggregate filter in filters[] is properly moved to having_filters[]."""
    mock_schema = MagicMock()
    mock_schema.tables = []

    plan = QueryPlan(
        intent="aggregation",
        group_by=["event_sitecore_id"],
        aggregation="count",
        filters=[QueryFilter(column="count", operator="greater_than", value=5)],
    )

    normalized = QuestionAnalyzer._normalize_plan(
        plan=plan,
        question="Which events have more than 5 registrations?",
        semantic_schema=mock_schema,
    )

    assert len(normalized.having_filters) == 1
    assert normalized.having_filters[0].column == "count"
    assert normalized.having_filters[0].operator == "greater_than"
    assert normalized.having_filters[0].value == 5
    assert len(normalized.filters) == 0


def test_normalize_plan_fallback_detects_all_six_having_operators():
    """Verify fallback detection handles all 6 generic comparison operators."""
    mock_schema = MagicMock()
    mock_schema.tables = []

    test_cases = [
        ("Which events have more than 5 registrations?", "greater_than", 5),
        ("Which events have at least 10 registrations?", "greater_than_or_equal", 10),
        ("Which events have fewer than 3 registrations?", "less_than", 3),
        ("Which events have 5 or less registrations?", "less_than_or_equal", 5),
        ("Which events have exactly 5 registrations?", "equals", 5),
        ("Which events do not have 5 registrations?", "not_equals", 5),
    ]

    for question, expected_op, expected_val in test_cases:
        plan = QueryPlan(
            intent="aggregation",
            group_by=["event_sitecore_id"],
            aggregation="count",
        )
        normalized = QuestionAnalyzer._normalize_plan(
            plan=plan,
            question=question,
            semantic_schema=mock_schema,
        )
        assert len(normalized.having_filters) == 1, f"Failed for {question}"
        assert normalized.having_filters[0].operator == expected_op, f"Failed for {question}"
        assert normalized.having_filters[0].value == expected_val, f"Failed for {question}"
        assert normalized.limit is None


# =============================================================================
# 3. CONVERSATION FOLLOW-UP INHERITANCE
# =============================================================================

def test_followup_inherits_having_filters_from_prior_result():
    """Verify follow-up asking for entity attribute & count inherits having_filters."""
    mock_schema = MagicMock()
    mock_schema.tables = []

    context = {
        "history": [
            {
                "reference_id": "ref_turn1",
                "question": "Which events have more than 4 registrations?",
                "plan": {
                    "intent": "aggregation",
                    "group_by": ["event_sitecore_id"],
                    "aggregation": "count",
                    "having_filters": [
                        {"column": "count", "operator": "greater_than", "value": 4}
                    ],
                },
                "data": [
                    {"event_sitecore_id": "2feae74c-7368-45e4-9f28-9b06ff096fac", "count": 5}
                ],
            }
        ]
    }

    followup_plan = QueryPlan(
        intent="aggregation",
        group_by=["event_sitecore_id", "site_name"],
        aggregation="count",
        input_result_reference="ref_turn1",
    )

    normalized = QuestionAnalyzer._normalize_plan(
        plan=followup_plan,
        question="Show the event title and registration count for those events.",
        semantic_schema=mock_schema,
        conversation_context=context,
    )

    assert len(normalized.having_filters) == 1
    assert normalized.having_filters[0].column == "count"
    assert normalized.having_filters[0].operator == "greater_than"
    assert normalized.having_filters[0].value == 4
    assert normalized.limit is None


# =============================================================================
# 4. END-TO-END EXECUTION ON CANONICAL POSTGRESQL DATABASE
# =============================================================================

def test_e2e_single_table_having_greater_than_5(pg_config, live_schema):
    """
    Q1: "Which events have more than 5 registrations?"
    In controlled test data, max registration count is 5, so > 5 returns 0 rows.
    """
    service = DatabaseQueryService(database_schema=live_schema)

    plan = QueryPlan(
        intent="aggregation",
        group_by=["event_sitecore_id"],
        aggregation="count",
        having_filters=[QueryFilter(column="count", operator="greater_than", value=5)],
    )

    table = live_schema.get_table("dbo", "site_event_registrants")
    result = service.executor.execute(plan, table)
    assert isinstance(result, list)
    assert len(result) == 0


def test_e2e_single_table_having_greater_than_4(pg_config, live_schema):
    """
    Q1: "Which events have more than 4 registrations?"
    In controlled test data, event '2feae74c-7368-45e4-9f28-9b06ff096fac' has 5 registrations.
    Must return only qualifying event(s) with count > 4.
    """
    service = DatabaseQueryService(database_schema=live_schema)

    plan = QueryPlan(
        intent="aggregation",
        group_by=["event_sitecore_id"],
        aggregation="count",
        having_filters=[QueryFilter(column="count", operator="greater_than", value=4)],
    )

    table = live_schema.get_table("dbo", "site_event_registrants")
    result = service.executor.execute(plan, table)
    assert isinstance(result, list)
    assert len(result) >= 1
    for row in result:
        val = row.get("aggregation_value") or row.get("count")
        assert val > 4


def test_e2e_joined_having_followup_preserves_constraint(pg_config, live_schema):
    """
    Follow-up: "Show the event title and registration count for those events."
    Joined query must execute with HAVING COUNT(*) > 4, returning only qualifying event(s).
    Events with counts 1, 2, 3 must NOT be returned.
    """
    service = DatabaseQueryService(database_schema=live_schema)

    context = {
        "history": [
            {
                "reference_id": "ref_prev",
                "question": "Which events have more than 4 registrations?",
                "plan": {
                    "intent": "aggregation",
                    "group_by": ["event_sitecore_id"],
                    "aggregation": "count",
                    "having_filters": [
                        {"column": "count", "operator": "greater_than", "value": 4}
                    ],
                },
                "data": [
                    {"event_sitecore_id": "2feae74c-7368-45e4-9f28-9b06ff096fac", "aggregation_value": 5}
                ],
            }
        ]
    }

    # Follow-up plan joining site_events and site_event_registrants
    followup_plan = QueryPlan(
        intent="aggregation",
        group_by=["event_topic_title"],
        group_by_refs=[
            QueryColumn(schema="dbo", table="site_events", column="event_topic_title")
        ],
        aggregation="count",
        input_result_reference="ref_prev",
        having_filters=[QueryFilter(column="count", operator="greater_than", value=4)],
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

    table1 = live_schema.get_table("dbo", "site_events")
    table2 = live_schema.get_table("dbo", "site_event_registrants")
    result = service.executor.execute(followup_plan, table=table1, tables=[table1, table2])
    assert isinstance(result, list)
    assert len(result) >= 1
    for row in result:
        val = row.get("aggregation_value") or row.get("count")
        assert val > 4, f"Row has count <= 4: {row}"


def test_database_query_service_mode2_inherits_having_filters():
    """
    Verify DatabaseQueryService Mode 2 inherits having_filters from referenced conversation entry
    when in-memory execution cannot satisfy the query and falls back to database query.
    """
    mock_schema = MagicMock()
    mock_table = MagicMock()
    mock_table.schema_name = "dbo"
    mock_table.table_name = "site_event_registrants"
    col = MagicMock()
    col.name = "event_sitecore_id"
    mock_table.columns = [col]
    mock_schema.tables = [mock_table]
    mock_schema.get_table.return_value = mock_table

    mock_analyzer = MagicMock()
    followup_plan = QueryPlan(
        intent="aggregation",
        group_by=["event_sitecore_id"],
        aggregation="count",
        input_result_reference="ref_1",
    )
    mock_analyzer.analyze.return_value = followup_plan

    mock_validator = MagicMock()
    mock_validator.validate.return_value.valid = True
    mock_validator.validate.return_value.errors = []
    mock_validator.validate.return_value.warnings = []

    mock_executor = MagicMock()
    mock_executor.execute.return_value = [{"event_sitecore_id": "abc", "aggregation_value": 5}]

    mock_result_validator = MagicMock()
    mock_result_validator.validate.return_value.valid = True
    mock_result_validator.validate.return_value.errors = []

    service = DatabaseQueryService(
        database_schema=mock_schema,
        analyzer=mock_analyzer,
        validator=mock_validator,
        executor=mock_executor,
        result_validator=mock_result_validator,
        vector_service=MagicMock(),
        relationship_service=MagicMock(),
    )
    service._resolve_execution_tables = MagicMock(return_value=[mock_table])
    service._prune_execution_tables = MagicMock(return_value=[mock_table])
    service._build_execution_schema = MagicMock(return_value=mock_schema)
    service._can_execute_in_memory = MagicMock(return_value=False)

    context = {
        "history": [
            {
                "reference_id": "ref_1",
                "question": "Which events have more than 4 registrations?",
                "plan": {
                    "intent": "aggregation",
                    "group_by": ["event_sitecore_id"],
                    "aggregation": "count",
                    "having_filters": [
                        {"column": "count", "operator": "greater_than", "value": 4}
                    ],
                },
                "data": [{"event_sitecore_id": "abc", "count": 5}],
            }
        ]
    }

    res = service.answer("Show the count for those", conversation_context=context)
    assert len(res.plan.having_filters) == 1
    assert res.plan.having_filters[0].column == "count"
    assert res.plan.having_filters[0].operator == "greater_than"
    assert res.plan.having_filters[0].value == 4
    assert mock_executor.execute.called
    executed_plan = mock_executor.execute.call_args[1]["plan"]
    assert len(executed_plan.having_filters) == 1
    assert executed_plan.having_filters[0].value == 4

