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
from app.database.query_service import (
    DatabaseQueryResult,
    DatabaseQueryService,
    DatabaseQueryServiceError,
)
from app.conversation.conversation_memory import ConversationMemory
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
# 1. AGGREGATE DETAIL REQUEST LINGUISTIC DETECTION
# =====================================================================

def test_detect_aggregate_detail_request_positive_cases():
    """Generic detection recognizes diverse natural language detail requests."""
    positives = [
        "Show details of this.",
        "Show details of that.",
        "Show details of these.",
        "Show details of those.",
        "Show details of it",
        "Show details of them",
        "Show details.",
        "Show the details.",
        "Show me details.",
        "Show me the details.",
        "Show details of this result.",
        "Show details of the result",
        "Show details of the above",
        "details of this",
        "details of that",
        "details of these",
        "details of those",
        "details of the above",
        "details of the result",
        "Show records.",
        "Show the records.",
        "Show me records.",
        "Show me the records.",
        "Show those records.",
        "Show these records.",
        "Show all records",
        "Show rows.",
        "Show the rows.",
        "Show me rows.",
        "Show me the rows.",
        "Show those rows.",
        "Show these rows.",
        "Show all rows",
        "Show underlying records",
        "Show the underlying records.",
        "Show underlying data",
        "Show the underlying data.",
        "Show underlying rows",
        "Show the underlying rows.",
        "List details.",
        "List the details.",
        "List records.",
        "List the records.",
        "List those records.",
        "List these records.",
        "List the rows.",
        "Give me details.",
        "Give me the details.",
        "Give details",
        "Give the details",
        "What are the details?",
        "What are these records?",
        "What are those records?",
        "What are the records?",
        "What are these rows?",
        "What are those rows?",
        "What are the rows?",
        "View details.",
        "View the details.",
        "View records.",
        "Can you show the details?",
        "Please show me the details of this result.",
        "Details please.",
        "Details",
    ]
    for q in positives:
        assert QuestionAnalyzer._is_aggregate_detail_request(q) is True, f"Failed for positive: {q}"
        assert QuestionAnalyzer._is_explicit_result_reference(q) is True, f"Explicit ref failed for: {q}"
        assert DatabaseQueryService._is_contextual_follow_up(q) is True, f"Follow-up failed for: {q}"


def test_detect_aggregate_detail_request_negative_cases():
    """Standalone questions or new queries do not falsely trigger aggregate detail."""
    negatives = [
        "How many events have duration greater than 100?",
        "Which event has duration greater than 100?",
        "What is the average duration of events?",
        "What is the maximum capacity?",
        "Show 5th event",
        "Show events from 2024",
        "Show all events",
        "Is this event active?",
        "What is the event name?",
        "Who is the organizer?",
        "Where is the venue?",
    ]
    for q in negatives:
        assert QuestionAnalyzer._is_aggregate_detail_request(q) is False, f"Falsely matched negative: {q}"


# =====================================================================
# 2. CONVERSATION MEMORY SERIALIZATION HARDENING
# =====================================================================

def test_conversation_memory_serializes_inner_aggregation_and_columns():
    """Memory serializes inner_aggregation and full TableInfo column metadata."""
    plan = QueryPlan(
        intent="derived_aggregation",
        aggregation="average",
        inner_aggregation="count",
        group_by=["category_id"],
        target_columns=["item_id"],
        filters=[QueryFilter(column="active", operator="equals", value=True)],
    )
    tables = [
        TableInfo(
            schema_name="dbo",
            table_name="items",
            columns=[
                ColumnInfo(name="item_id", data_type="uuid", nullable=False, ordinal_position=1),
                ColumnInfo(name="item_name", data_type="varchar", nullable=False, ordinal_position=2),
                ColumnInfo(name="active", data_type="boolean", nullable=False, ordinal_position=3),
            ],
            primary_key_columns=["item_id"],
        )
    ]

    serialized_plan = ConversationMemory._serialize_plan(plan)
    assert serialized_plan["inner_aggregation"] == "count"
    assert serialized_plan["aggregation"] == "average"

    serialized_tables = ConversationMemory._serialize_tables(tables)
    assert len(serialized_tables) == 1
    assert serialized_tables[0]["schema"] == "dbo"
    assert serialized_tables[0]["table"] == "items"
    assert "columns" in serialized_tables[0]
    assert len(serialized_tables[0]["columns"]) == 3
    assert serialized_tables[0]["columns"][0]["name"] == "item_id"
    assert serialized_tables[0]["primary_key_columns"] == ["item_id"]


# =====================================================================
# 3. ANALYZER NORMALIZATION: SINGLE-TABLE AGGREGATE → DETAIL
# =====================================================================

@pytest.fixture
def mock_schema():
    return DatabaseSchema(
        tables=[
            TableInfo(
                schema_name="dbo",
                table_name="site_events",
                columns=[
                    ColumnInfo(name="event_sitecore_id", data_type="uuid", nullable=False, ordinal_position=1),
                    ColumnInfo(name="event_name", data_type="varchar", nullable=False, ordinal_position=2),
                    ColumnInfo(name="event_duration", data_type="int", nullable=False, ordinal_position=3),
                ],
                primary_key_columns=["event_sitecore_id"],
            ),
            TableInfo(
                schema_name="dbo",
                table_name="site_event_registrants",
                columns=[
                    ColumnInfo(name="registration_sitecore_id", data_type="uuid", nullable=False, ordinal_position=1),
                    ColumnInfo(name="event_sitecore_id", data_type="uuid", nullable=False, ordinal_position=2),
                    ColumnInfo(name="registrant_name", data_type="varchar", nullable=True, ordinal_position=3),
                ],
                primary_key_columns=["registration_sitecore_id"],
            ),
        ]
    )


def test_analyzer_reconstructs_single_table_aggregate_detail(mock_schema):
    """
    Q1: 'How many events have duration greater than 100?' (scalar count 105)
    Q2: 'Show details of this.' -> LLM returned unsupported claiming table unavailable.
    Normalization deterministically transforms it into lookup preserving event_duration > 100.
    """
    conversation_context = {
        "history": [
            {
                "reference_id": "ref-101",
                "question": "How many events have duration greater than 100?",
                "columns": ["count"],
                "data": [{"count": 105}],
                "plan": {
                    "intent": "count",
                    "filters": [{"column": "event_duration", "operator": "greater_than", "value": 100}],
                    "target_columns": ["event_sitecore_id"],
                    "joins": [],
                },
                "tables": [{"schema": "dbo", "table": "site_events"}],
                "query_context": {"is_scalar": True},
            }
        ]
    }

    # Simulate DeepSeek returning "unsupported" because it got confused by "this"
    llm_plan = QueryPlan(
        intent="unsupported",
        explanation="The required table is not present in the current prompt context.",
    )

    normalized = QuestionAnalyzer._normalize_plan(
        plan=llm_plan,
        question="Show details of this.",
        semantic_schema=mock_schema,
        conversation_context=conversation_context,
    )

    assert normalized.intent == "lookup"
    assert normalized.aggregation is None
    assert normalized.inner_aggregation is None
    assert normalized.group_by == []
    assert len(normalized.filters) == 1
    assert normalized.filters[0].column == "event_duration"
    assert normalized.filters[0].operator == "greater_than"
    assert normalized.filters[0].value == 100
    assert normalized.target_columns == ["event_sitecore_id", "event_name", "event_duration"]
    assert normalized.input_result_reference == "ref-101"


# =====================================================================
# 4. ANALYZER NORMALIZATION: MULTI-TABLE JOIN AGGREGATE → DETAIL
# =====================================================================

def test_analyzer_reconstructs_multi_table_join_aggregate_detail(mock_schema):
    """
    Q1: 'How many registrations for events with duration > 100?' (JOIN + count 20)
    Q2: 'Show details of this.'
    Normalization retains joins, retains filters, sets distinct=True, and projects registrant detail columns.
    """
    conversation_context = {
        "history": [
            {
                "reference_id": "ref-202",
                "question": "How many registrations for events with duration greater than 100?",
                "columns": ["count"],
                "data": [{"count": 20}],
                "plan": {
                    "intent": "count",
                    "filters": [{"column": "event_duration", "operator": "greater_than", "value": 100}],
                    "target_columns": ["registration_sitecore_id"],
                    "target_column_refs": [
                        {"schema": "dbo", "table": "site_event_registrants", "column": "registration_sitecore_id"}
                    ],
                    "joins": [
                        {
                            "left_schema": "dbo",
                            "left_table": "site_events",
                            "left_column": "event_sitecore_id",
                            "right_schema": "dbo",
                            "right_table": "site_event_registrants",
                            "right_column": "event_sitecore_id",
                            "join_type": "inner",
                        }
                    ],
                },
                "tables": [
                    {"schema": "dbo", "table": "site_events"},
                    {"schema": "dbo", "table": "site_event_registrants"},
                ],
                "query_context": {"is_scalar": True},
            }
        ]
    }

    llm_plan = QueryPlan(
        intent="unsupported",
        explanation="Table missing.",
    )

    normalized = QuestionAnalyzer._normalize_plan(
        plan=llm_plan,
        question="Show details of this.",
        semantic_schema=mock_schema,
        conversation_context=conversation_context,
    )

    assert normalized.intent == "lookup"
    assert normalized.aggregation is None
    assert normalized.group_by == []
    assert len(normalized.joins) == 1
    assert normalized.joins[0].left_table == "site_events"
    assert normalized.joins[0].right_table == "site_event_registrants"
    assert len(normalized.filters) == 1
    assert normalized.filters[0].column == "event_duration"
    assert normalized.filters[0].operator == "greater_than"
    assert normalized.filters[0].value == 100
    assert normalized.distinct is True
    # Subject table was site_event_registrants
    assert normalized.target_columns == ["registration_sitecore_id", "event_sitecore_id", "registrant_name"]
    assert normalized.input_result_reference == "ref-202"


# =====================================================================
# 5. LIMIT PRESERVATION ON DETAIL FOLLOW-UP
# =====================================================================

def test_analyzer_aggregate_detail_with_limit(mock_schema):
    """User asks for 'Show top 5 details of this' -> limit=5 is set on lookup."""
    conversation_context = {
        "history": [
            {
                "reference_id": "ref-303",
                "question": "How many events have duration greater than 100?",
                "columns": ["count"],
                "data": 105,
                "plan": {
                    "intent": "count",
                    "filters": [{"column": "event_duration", "operator": "greater_than", "value": 100}],
                    "target_columns": ["event_sitecore_id"],
                },
                "tables": [{"schema": "dbo", "table": "site_events"}],
                "query_context": {"is_scalar": True},
            }
        ]
    }

    llm_plan = QueryPlan(intent="unsupported")
    normalized = QuestionAnalyzer._normalize_plan(
        plan=llm_plan,
        question="Show first 5 details of this.",
        semantic_schema=mock_schema,
        conversation_context=conversation_context,
    )

    assert normalized.intent == "lookup"
    assert normalized.limit == 5
    assert len(normalized.filters) == 1


# =====================================================================
# 6. TABLE RESOLUTION IN DATABASE QUERY SERVICE
# =====================================================================

def test_query_service_resolves_prior_tables_for_aggregate_detail(mock_schema):
    """
    When question is 'Show details of this', DatabaseQueryService reuses prior tables
    without letting spurious lexical matches (e.g. site_details) confuse table selection.
    """
    conversation_context = {
        "history": [
            {
                "reference_id": "ref-404",
                "question": "How many events have duration greater than 100?",
                "plan": {
                    "intent": "count",
                    "filters": [{"column": "event_duration", "operator": "greater_than", "value": 100}],
                },
                "tables": [{"schema": "dbo", "table": "site_events"}],
                "query_context": {"is_scalar": True},
            }
        ]
    }

    service = DatabaseQueryService(database_schema=mock_schema)
    resolved = service._resolve_execution_tables(
        question="Show details of this.",
        conversation_context=conversation_context,
    )

    assert len(resolved) == 1
    assert resolved[0].table_name == "site_events"
    assert resolved[0].schema_name == "dbo"


# =====================================================================
# 7. UNRELATED QUESTIONS DO NOT INHERIT AGGREGATE PROVENANCE
# =====================================================================

def test_unrelated_question_does_not_inherit_aggregate_provenance(mock_schema):
    """An independent question does not match aggregate detail and is planned fresh."""
    conversation_context = {
        "history": [
            {
                "reference_id": "ref-505",
                "question": "How many events have duration greater than 100?",
                "plan": {
                    "intent": "count",
                    "filters": [{"column": "event_duration", "operator": "greater_than", "value": 100}],
                },
                "tables": [{"schema": "dbo", "table": "site_events"}],
                "query_context": {"is_scalar": True},
            }
        ]
    }

    # New standalone question
    question = "What is the average event duration?"
    assert QuestionAnalyzer._is_aggregate_detail_request(question) is False

    llm_plan = QueryPlan(
        intent="aggregation",
        aggregation="average",
        target_columns=["event_duration"],
    )

    normalized = QuestionAnalyzer._normalize_plan(
        plan=llm_plan,
        question=question,
        semantic_schema=mock_schema,
        conversation_context=conversation_context,
    )

    assert normalized.intent == "aggregation"
    assert normalized.aggregation == "average"
    assert normalized.target_columns == ["event_duration"]
    # Does NOT inherit previous event_duration > 100 filter!
    assert len(normalized.filters) == 0


# =====================================================================
# 8. LIVE DATABASE END-TO-END EXECUTION (POSTGRESQL)
# =====================================================================

def test_live_postgres_aggregate_detail_flow():
    """
    Live test against canonical PostgreSQL database:
    Turn 1: 'How many events have duration greater than 100?' -> returns 105
    Turn 2: 'Show details of this.' -> returns 105 rows with site_events details
    """
    from app.core.config import get_database_config
    config = get_database_config()
    if not config.is_postgresql:
        pytest.skip("Test requires PostgreSQL canonical database")

    from app.database.metadata_service import DatabaseMetadataService
    meta = DatabaseMetadataService(config=config).load()
    service = DatabaseQueryService(database_schema=meta.schema)

    # Turn 1
    q1 = "How many events have duration greater than 100?"
    res1 = service.answer(question=q1)
    assert res1.plan.intent in ("count", "row_count")
    count_val = res1.data if isinstance(res1.data, int) else res1.data[0].get("count") or res1.data[0].get("row_count")
    assert count_val == 105

    # Build conversation context as stored by ConversationMemory
    ref_id = "test-live-ref-1"
    context = {
        "history": [
            {
                "reference_id": ref_id,
                "question": q1,
                "columns": ["count"],
                "data": res1.data,
                "plan": ConversationMemory._serialize_plan(res1.plan),
                "tables": ConversationMemory._serialize_tables(res1.tables),
                "query_context": {
                    "plan": ConversationMemory._serialize_plan(res1.plan),
                    "tables": ConversationMemory._serialize_tables(res1.tables),
                    "is_scalar": True,
                },
            }
        ]
    }

    # Turn 2: 'Show details of this.'
    q2 = "Show details of this."
    res2 = service.answer(question=q2, conversation_context=context)

    assert res2.plan.intent == "lookup"
    assert res2.plan.aggregation is None
    assert len(res2.plan.filters) == 1
    assert res2.plan.filters[0].column == "event_duration"
    assert res2.plan.filters[0].operator == "greater_than"
    assert res2.plan.filters[0].value == 100
    assert isinstance(res2.data, list)
    assert len(res2.data) == 105, f"Expected 105 matching detail rows, got {len(res2.data)}"
    # Verify each row has event columns
    assert "event_sitecore_id" in res2.data[0]
    assert "event_topic_title" in res2.data[0]
    assert "event_duration" in res2.data[0]
    assert all(row["event_duration"] > 100 for row in res2.data)


def test_live_postgres_join_aggregate_detail_flow():
    """
    Live test against canonical PostgreSQL database with JOIN:
    Turn 1: Count registrants for events with duration > 100 (20 registrants)
    Turn 2: 'Show the details.' -> returns 20 distinct registrant rows matching filter
    """
    from app.core.config import get_database_config
    config = get_database_config()
    if not config.is_postgresql:
        pytest.skip("Test requires PostgreSQL canonical database")

    from app.database.metadata_service import DatabaseMetadataService
    meta = DatabaseMetadataService(config=config).load()
    service = DatabaseQueryService(database_schema=meta.schema)

    q1 = "How many registrations for events with duration greater than 100?"
    # We construct the turn 1 context directly to verify generic follow-up logic
    prior_plan = QueryPlan(
        intent="count",
        filters=[QueryFilter(column="event_duration", operator="greater_than", value=100)],
        target_columns=["registration_sitecore_id"],
        target_column_refs=[
            QueryColumn(column="registration_sitecore_id", schema="dbo", table="site_event_registrants")
        ],
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
    events_tbl = meta.schema.get_table("dbo", "site_events")
    reg_tbl = meta.schema.get_table("dbo", "site_event_registrants")
    tables = [events_tbl, reg_tbl]

    context = {
        "history": [
            {
                "reference_id": "test-join-ref-1",
                "question": q1,
                "columns": ["count"],
                "data": 20,
                "plan": ConversationMemory._serialize_plan(prior_plan),
                "tables": ConversationMemory._serialize_tables(tables),
                "query_context": {
                    "plan": ConversationMemory._serialize_plan(prior_plan),
                    "tables": ConversationMemory._serialize_tables(tables),
                    "is_scalar": True,
                },
            }
        ]
    }

    q2 = "Show the details."
    res2 = service.answer(question=q2, conversation_context=context)

    assert res2.plan.intent == "lookup"
    assert res2.plan.distinct is True
    assert len(res2.plan.joins) == 1
    assert isinstance(res2.data, list)
    assert len(res2.data) == 20, f"Expected 20 matching registrant detail rows, got {len(res2.data)}"
    assert "registration_sitecore_id" in res2.data[0]
