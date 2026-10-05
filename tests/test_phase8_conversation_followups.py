from __future__ import annotations

import datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch
import uuid
import pytest

from app.database.schema import (
    ColumnInfo,
    DatabaseSchema,
    ForeignKeyInfo,
    TableInfo,
)
from app.database.sql_executor import (
    SQLQueryExecutionError,
    SQLQueryExecutor,
)
from app.database.query_service import (
    DatabaseQueryResult,
    DatabaseQueryService,
    DatabaseQueryServiceError,
)
from app.conversation.conversation_memory import (
    ConversationMemory,
    ConversationMemoryError,
)
from app.query.analyzer import QuestionAnalyzer
from app.query.answer_generator import AnswerGenerator
from app.query.result_validator import QueryResultValidator
from app.query.schema import (
    QueryColumn,
    QueryFilter,
    QueryJoin,
    QueryPlan,
)
from app.query.validator import QueryPlanValidator


# =============================================================================
# Helper schema builders
# =============================================================================

def _build_test_schema() -> DatabaseSchema:
    table_workspaces = TableInfo(
        schema_name="dbo",
        table_name="workspaces",
        columns=[
            ColumnInfo("workspace_id", "int", False, 1),
            ColumnInfo("workspace_name", "nvarchar", False, 2),
            ColumnInfo("is_active", "bit", True, 3),
        ],
        primary_key_columns=["workspace_id"],
    )

    table_members = TableInfo(
        schema_name="dbo",
        table_name="team_members",
        columns=[
            ColumnInfo("member_id", "int", False, 1),
            ColumnInfo("workspace_id", "int", False, 2),
            ColumnInfo("member_name", "nvarchar", False, 3),
            ColumnInfo("role", "nvarchar", True, 4),
            ColumnInfo("is_active", "bit", True, 5),
        ],
        primary_key_columns=["member_id"],
    )

    table_events = TableInfo(
        schema_name="dbo",
        table_name="site_events",
        columns=[
            ColumnInfo("event_id", "int", False, 1),
            ColumnInfo("event_name", "nvarchar", False, 2),
            ColumnInfo("event_status", "nvarchar", True, 3),
            ColumnInfo("event_date", "datetime2", True, 4),
        ],
        primary_key_columns=["event_id"],
    )

    return DatabaseSchema(
        tables=[table_workspaces, table_members, table_events],
        foreign_keys=[
            ForeignKeyInfo(
                constraint_name="FK_team_members_workspaces",
                schema_name="dbo",
                table_name="team_members",
                column_name="workspace_id",
                referenced_schema_name="dbo",
                referenced_table_name="workspaces",
                referenced_column_name="workspace_id",
            )
        ],
    )


def _make_mock_service(schema: DatabaseSchema | None = None) -> DatabaseQueryService:
    if schema is None:
        schema = _build_test_schema()
    service = DatabaseQueryService.__new__(DatabaseQueryService)
    service.database_schema = schema
    service.analyzer = QuestionAnalyzer()
    service.validator = QueryPlanValidator()
    service.executor = SQLQueryExecutor()
    service.result_validator = QueryResultValidator()
    service.entity_resolver = MagicMock()
    service.relationship_service = MagicMock()
    service.metadata_service = MagicMock()
    service.semantic_cache = MagicMock()
    service.semantic_cache.get.return_value = None
    service.database_server_name = "localhost"
    service.database_name = "testdb"
    service.schema_fingerprint = "fp_phase8_test"
    return service


# =============================================================================
# 1. conversation save/retrieve
# =============================================================================

def test_conversation_save_and_retrieve():
    mem = ConversationMemory()
    session_id = f"test_save_{uuid.uuid4()}"

    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value = mock_cursor

    plan = QueryPlan(
        intent="lookup",
        target_columns=["workspace_name"],
        explanation="List workspaces",
    )
    tables = [{"schema": "dbo", "table": "workspaces"}]
    result_data = [{"workspace_name": "Finance"}, {"workspace_name": "HR"}]

    with patch("app.conversation.conversation_memory.get_connection", return_value=mock_conn):
        ref_id = mem.save(
            session_id=session_id,
            question="Show workspaces",
            result=result_data,
            plan=plan,
            tables=tables,
        )

        assert ref_id is not None
        assert mock_cursor.execute.called

        # Simulate fetch from database
        mock_row = MagicMock()
        mock_row.reference_id = ref_id
        mock_row.question = "Show workspaces"
        mock_row.result_columns = '["workspace_name"]'
        mock_row.result_data = '[{"workspace_name": "Finance"}, {"workspace_name": "HR"}]'
        mock_row.query_context = f'{{"plan": {{"intent": "lookup"}}, "tables": [{{"schema": "dbo", "table": "workspaces"}}], "is_scalar": false}}'
        mock_cursor.fetchall.return_value = [mock_row]

        context = mem.get_context(session_id)
        assert "history" in context
        assert len(context["history"]) == 1
        entry = context["history"][0]
        assert entry["reference_id"] == ref_id
        assert entry["question"] == "Show workspaces"
        assert entry["columns"] == ["workspace_name"]
        assert len(entry["data"]) == 2
        assert entry["tables"] == [{"schema": "dbo", "table": "workspaces"}]
        assert entry["plan"]["intent"] == "lookup"


# =============================================================================
# 2. session isolation
# =============================================================================

def test_session_isolation():
    mem = ConversationMemory()
    session_a = f"session_A_{uuid.uuid4()}"
    session_b = f"session_B_{uuid.uuid4()}"

    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value = mock_cursor

    with patch("app.conversation.conversation_memory.get_connection", return_value=mock_conn):
        # When querying session_A, return only session_A rows
        row_a = MagicMock()
        row_a.reference_id = "ref_a"
        row_a.question = "Question A"
        row_a.result_columns = '["col_a"]'
        row_a.result_data = '[{"col_a": 1}]'
        row_a.query_context = '{}'

        mock_cursor.fetchall.return_value = [row_a]
        ctx_a = mem.get_context(session_a)
        called_args = mock_cursor.execute.call_args[0]
        assert session_a in called_args
        assert ctx_a["history"][0]["reference_id"] == "ref_a"

        # When querying session_B, return only session_B rows
        row_b = MagicMock()
        row_b.reference_id = "ref_b"
        row_b.question = "Question B"
        row_b.result_columns = '["col_b"]'
        row_b.result_data = '[{"col_b": 2}]'
        row_b.query_context = '{}'

        mock_cursor.fetchall.return_value = [row_b]
        ctx_b = mem.get_context(session_b)
        called_args = mock_cursor.execute.call_args[0]
        assert session_b in called_args
        assert ctx_b["history"][0]["reference_id"] == "ref_b"
        assert ctx_b["history"][0]["reference_id"] != ctx_a["history"][0]["reference_id"]


# =============================================================================
# 3. valid reference resolution
# =============================================================================

def test_valid_reference_resolution():
    service = _make_mock_service()
    ref_id = str(uuid.uuid4())
    context = {
        "history": [
            {
                "reference_id": ref_id,
                "question": "Show event statuses",
                "columns": ["event_status"],
                "data": [{"event_status": "Active"}, {"event_status": "Cancelled"}],
            }
        ]
    }
    entry = service._get_referenced_conversation_entry(context, ref_id)
    assert entry is not None
    assert entry["reference_id"] == ref_id
    assert entry["data"] == [{"event_status": "Active"}, {"event_status": "Cancelled"}]


# =============================================================================
# 4. invalid reference
# =============================================================================

def test_invalid_reference_safety():
    service = _make_mock_service()
    context = {
        "history": [
            {
                "reference_id": "valid_ref",
                "question": "Show event statuses",
                "data": [{"event_status": "Active"}],
            }
        ]
    }
    entry = service._get_referenced_conversation_entry(context, "non_existent_ref")
    assert entry is None

    # When executing in-memory with invalid reference, fails safely
    plan = QueryPlan(
        intent="lookup",
        input_result_reference="non_existent_ref",
        target_columns=["event_status"],
    )
    with pytest.raises(DatabaseQueryServiceError, match="could not be found"):
        service._execute_conversation_result_plan(plan, context)


# =============================================================================
# 5. stale reference
# =============================================================================

def test_stale_reference_safety():
    service = _make_mock_service()
    plan = QueryPlan(
        intent="lookup",
        input_result_reference="stale_ref_123",
        target_columns=["event_status"],
    )
    # Empty context (or expired outside history window)
    context = {"history": []}
    with pytest.raises(DatabaseQueryServiceError, match="could not be found"):
        service._execute_conversation_result_plan(plan, context)


# =============================================================================
# 6. previous-result sorting (Mode 1 In-Memory)
# =============================================================================

def test_previous_result_sorting_in_memory():
    service = _make_mock_service()
    plan = QueryPlan(
        intent="ranking",
        input_result_reference="ref-sort",
        target_columns=["event_status"],
        sort_column="event_status",
        sort_direction="asc",
    )
    context = {
        "history": [
            {
                "reference_id": "ref-sort",
                "question": "Show event statuses",
                "columns": ["event_status"],
                "data": [
                    {"event_status": "Pending"},
                    {"event_status": "Active"},
                    {"event_status": "Completed"},
                    {"event_status": "Cancelled"},
                ],
            }
        ]
    }
    result = service._execute_conversation_result_plan(plan, context)
    statuses = [r["event_status"] for r in result]
    assert statuses == ["Active", "Cancelled", "Completed", "Pending"]


# =============================================================================
# 7. previous-result filtering (Mode 1 In-Memory)
# =============================================================================

def test_previous_result_filtering_in_memory():
    service = _make_mock_service()
    plan = QueryPlan(
        intent="filter",
        input_result_reference="ref-filter",
        target_columns=["event_status"],
        filters=[
            QueryFilter(column="event_status", operator="starts_with", value="C")
        ],
    )
    context = {
        "history": [
            {
                "reference_id": "ref-filter",
                "question": "Show event statuses",
                "columns": ["event_status"],
                "data": [
                    {"event_status": "Active"},
                    {"event_status": "Cancelled"},
                    {"event_status": "Completed"},
                    {"event_status": "Pending"},
                ],
            }
        ]
    }
    result = service._execute_conversation_result_plan(plan, context)
    statuses = [r["event_status"] for r in result]
    assert statuses == ["Cancelled", "Completed"]


# =============================================================================
# 8. previous-result limiting (Mode 1 In-Memory)
# =============================================================================

def test_previous_result_limiting_in_memory():
    service = _make_mock_service()
    plan = QueryPlan(
        intent="lookup",
        input_result_reference="ref-limit",
        target_columns=["event_status"],
        limit=2,
    )
    context = {
        "history": [
            {
                "reference_id": "ref-limit",
                "question": "Show event statuses",
                "columns": ["event_status"],
                "data": [
                    {"event_status": "Active"},
                    {"event_status": "Cancelled"},
                    {"event_status": "Completed"},
                    {"event_status": "Pending"},
                ],
            }
        ]
    }
    result = service._execute_conversation_result_plan(plan, context)
    assert len(result) == 2
    assert result == [{"event_status": "Active"}, {"event_status": "Cancelled"}]


# =============================================================================
# 9. previous-result projection (Mode 1 In-Memory)
# =============================================================================

def test_previous_result_projection_in_memory():
    service = _make_mock_service()
    plan = QueryPlan(
        intent="lookup",
        input_result_reference="ref-proj",
        target_columns=["member_name"],
    )
    context = {
        "history": [
            {
                "reference_id": "ref-proj",
                "question": "Show team members",
                "columns": ["member_id", "member_name", "role", "is_active"],
                "data": [
                    {"member_id": 1, "member_name": "Alice", "role": "Lead", "is_active": True},
                    {"member_id": 2, "member_name": "Bob", "role": "Engineer", "is_active": True},
                ],
            }
        ]
    }
    result = service._execute_conversation_result_plan(plan, context)
    assert result == [{"member_name": "Alice"}, {"member_name": "Bob"}]


# =============================================================================
# 10. aggregated-result follow-up (Mode 1 In-Memory)
# =============================================================================

def test_aggregated_result_followup_in_memory():
    service = _make_mock_service()
    # "Show only statuses with more than 100"
    plan = QueryPlan(
        intent="filter",
        input_result_reference="ref-agg",
        target_columns=["event_status", "count"],
        filters=[
            QueryFilter(column="count", operator="greater_than", value=100)
        ],
    )
    context = {
        "history": [
            {
                "reference_id": "ref-agg",
                "question": "How many events are there by status?",
                "columns": ["event_status", "aggregation_value"],
                "data": [
                    {"event_status": "Active", "aggregation_value": 250},
                    {"event_status": "Cancelled", "aggregation_value": 45},
                    {"event_status": "Completed", "aggregation_value": 120},
                ],
            }
        ]
    }
    # Verify _can_execute_in_memory is True
    entry = context["history"][0]
    assert service._can_execute_in_memory(plan, entry) is True

    result = service._execute_conversation_result_plan(plan, context)
    assert len(result) == 2
    assert result == [
        {"event_status": "Active", "count": 250},
        {"event_status": "Completed", "count": 120},
    ]


# =============================================================================
# 11. HAVING-style follow-up (Mode 1 In-Memory)
# =============================================================================

def test_having_style_followup_in_memory():
    service = _make_mock_service()
    plan = QueryPlan(
        intent="filter",
        input_result_reference="ref-having",
        target_columns=["event_status", "aggregation_value"],
        having_filters=[
            QueryFilter(column="aggregation_value", operator="greater_than_or_equal", value=100)
        ],
    )
    context = {
        "history": [
            {
                "reference_id": "ref-having",
                "question": "How many events are there by status?",
                "columns": ["event_status", "aggregation_value"],
                "data": [
                    {"event_status": "Active", "aggregation_value": 250},
                    {"event_status": "Cancelled", "aggregation_value": 50},
                    {"event_status": "Completed", "aggregation_value": 100},
                ],
            }
        ]
    }
    assert service._can_execute_in_memory(plan, context["history"][0]) is True
    result = service._execute_conversation_result_plan(plan, context)
    assert len(result) == 2
    statuses = [r["event_status"] for r in result]
    assert "Active" in statuses
    assert "Completed" in statuses
    assert "Cancelled" not in statuses


# =============================================================================
# 12. entity follow-up requiring additional SQL context (Mode 2 SQL Re-Query)
# =============================================================================

def test_entity_followup_requiring_sql_requery():
    service = _make_mock_service()
    # Question 1 resulted in: workspace_name + count
    context = {
        "history": [
            {
                "reference_id": "ref-workspaces",
                "question": "How many workspaces have team members?",
                "columns": ["workspace_name", "aggregation_value"],
                "data": [
                    {"workspace_name": "Engineering", "aggregation_value": 5},
                ],
                "tables": [{"schema": "dbo", "table": "workspaces"}],
            }
        ]
    }
    # Question 2 asks for: "What are the names of those team members?"
    # Target column is member_name, which is NOT in the previous result!
    plan = QueryPlan(
        intent="lookup",
        input_result_reference="ref-workspaces",
        target_columns=["member_name"],
    )

    entry = context["history"][0]
    # In-memory execution must return False!
    assert service._can_execute_in_memory(plan, entry) is False


# =============================================================================
# 13. follow-up with additional filter requiring unprojected column (Mode 2)
# =============================================================================

def test_followup_with_additional_filter_requiring_sql_requery():
    service = _make_mock_service()
    # Question 1: "Show event staff" (projected only staff_name)
    context = {
        "history": [
            {
                "reference_id": "ref-staff",
                "question": "Show event staff",
                "columns": ["member_name"],
                "data": [{"member_name": "Alice"}, {"member_name": "Bob"}],
            }
        ]
    }
    # Question 2: "Only active ones." -> filter on is_active, which was not in previous result!
    plan = QueryPlan(
        intent="filter",
        input_result_reference="ref-staff",
        target_columns=["member_name"],
        filters=[QueryFilter(column="is_active", operator="equals", value=True)],
    )

    entry = context["history"][0]
    assert service._can_execute_in_memory(plan, entry) is False


# =============================================================================
# 14. pronoun/reference resolution
# =============================================================================

def test_pronoun_reference_resolution():
    assert DatabaseQueryService._is_contextual_follow_up("What are the names of those team members?") is True
    assert DatabaseQueryService._is_contextual_follow_up("Sort those statuses alphabetically.") is True
    assert DatabaseQueryService._is_contextual_follow_up("Only active ones.") is True
    assert DatabaseQueryService._is_contextual_follow_up("Show only the statuses that start with C.") is True
    assert DatabaseQueryService._is_contextual_follow_up("Show the first 3.") is True
    assert DatabaseQueryService._is_contextual_follow_up("Which of them are managers?") is True
    assert DatabaseQueryService._is_contextual_follow_up("How many users are in the system?") is False


# =============================================================================
# 15. missing structured context backward compatibility
# =============================================================================

def test_missing_structured_context_backward_compatibility():
    service = _make_mock_service()
    # Historical record with NULL query_context, plan=None, tables=[]
    context = {
        "history": [
            {
                "reference_id": "old_ref",
                "question": "Show event statuses",
                "columns": ["event_status"],
                "data": [{"event_status": "Active"}, {"event_status": "Cancelled"}],
                "query_context": None,
                "plan": None,
                "tables": [],
            }
        ]
    }
    # In-memory operations on existing columns still work perfectly!
    plan = QueryPlan(
        intent="ranking",
        input_result_reference="old_ref",
        target_columns=["event_status"],
        sort_column="event_status",
        sort_direction="asc",
    )
    assert service._can_execute_in_memory(plan, context["history"][0]) is True
    result = service._execute_conversation_result_plan(plan, context)
    assert result == [{"event_status": "Active"}, {"event_status": "Cancelled"}]


# =============================================================================
# 16. malicious previous-result content cannot alter SQL
# =============================================================================

def test_malicious_previous_result_content_cannot_alter_sql():
    service = _make_mock_service()
    malicious_context = {
        "history": [
            {
                "reference_id": "ref-sqli",
                "question": "Search users",
                "columns": ["user_input"],
                "data": [
                    {"user_input": "'; DROP TABLE [dbo].[site_events]; --"},
                    {"user_input": "normal_val"},
                ],
            }
        ]
    }
    plan = QueryPlan(
        intent="filter",
        input_result_reference="ref-sqli",
        target_columns=["user_input"],
        filters=[
            QueryFilter(column="user_input", operator="contains", value="DROP TABLE")
        ],
    )
    # Mode 1 runs entirely in Python memory, zero SQL execution!
    result = service._execute_conversation_result_plan(plan, malicious_context)
    assert len(result) == 1
    assert "DROP TABLE" in result[0]["user_input"]


# =============================================================================
# 17. existing Phase 10 conversation behavior
# =============================================================================

def test_existing_phase10_conversation_behavior():
    service = _make_mock_service()
    plan = QueryPlan(
        intent="lookup",
        input_result_reference="ref-p10",
        target_columns=["product_name", "price"],
        filters=[QueryFilter(column="price", operator="greater_than", value=50)],
        sort_column="price",
        sort_direction="desc",
    )
    context = {
        "history": [
            {
                "reference_id": "ref-p10",
                "question": "show products",
                "columns": ["product_name", "price", "category"],
                "data": [
                    {"product_name": "Item A", "price": 25, "category": "Books"},
                    {"product_name": "Item B", "price": 80, "category": "Gadgets"},
                    {"product_name": "Item C", "price": 120, "category": "Gadgets"},
                ],
            }
        ]
    }
    result = service._execute_conversation_result_plan(plan, context)
    assert result == [
        {"product_name": "Item C", "price": 120},
        {"product_name": "Item B", "price": 80},
    ]


# =============================================================================
# 18. Phase 7 result-contract regression
# =============================================================================

def test_phase7_result_contract_regression():
    service = _make_mock_service()
    validator = QueryResultValidator()

    # In-memory execution produces valid row-list contract
    plan = QueryPlan(
        intent="lookup",
        input_result_reference="ref-contract",
        target_columns=["event_status"],
    )
    context = {
        "history": [
            {
                "reference_id": "ref-contract",
                "question": "Show event statuses",
                "columns": ["event_status"],
                "data": [{"event_status": "Active"}, {"event_status": "Cancelled"}],
            }
        ]
    }
    data = service._execute_conversation_result_plan(plan, context)
    val = validator.validate(plan=plan, data=data)
    assert val.valid is True
    assert len(val.errors) == 0


# =============================================================================
# 19. full API / session flow
# =============================================================================

def test_full_api_session_flow():
    schema = _build_test_schema()
    service = _make_mock_service(schema)

    # Simulate Turn 1: SQL execution returning row list
    plan_t1 = QueryPlan(
        intent="lookup",
        target_columns=["event_status"],
        explanation="List event statuses",
    )
    mock_data_t1 = [{"event_status": "Active"}, {"event_status": "Cancelled"}]

    with patch.object(service.analyzer, "analyze", return_value=plan_t1), \
         patch.object(service.executor, "execute", return_value=mock_data_t1):

        res_t1 = service.answer("Show the event statuses.")
        assert res_t1.data == mock_data_t1
        assert len(res_t1.tables) > 0

    # Simulate Turn 2: In-memory follow-up
    ref_id = "turn1_ref"
    context = {
        "history": [
            {
                "reference_id": ref_id,
                "question": "Show the event statuses.",
                "columns": ["event_status"],
                "data": mock_data_t1,
                "tables": [{"schema": "dbo", "table": "site_events"}],
            }
        ]
    }
    plan_t2 = QueryPlan(
        intent="ranking",
        input_result_reference=ref_id,
        target_columns=["event_status"],
        sort_column="event_status",
        sort_direction="asc",
    )

    with patch.object(service.analyzer, "analyze", return_value=plan_t2):
        res_t2 = service.answer(
            question="Sort those statuses alphabetically.",
            conversation_context=context,
        )
        assert res_t2.data == [{"event_status": "Active"}, {"event_status": "Cancelled"}]
        assert any("referenced conversation result" in w for w in res_t2.warnings)


# =============================================================================
# 20. multiple conversation turns
# =============================================================================

def test_multiple_conversation_turns():
    schema = _build_test_schema()
    service = _make_mock_service(schema)

    # Turn 1: Scalar count
    context = {
        "history": [
            {
                "reference_id": "turn1",
                "question": "How many events are there?",
                "columns": ["value_count"],
                "data": 600,
                "tables": [{"schema": "dbo", "table": "site_events"}],
            }
        ]
    }

    # Turn 2: Question requires SQL Server because Turn 1 was scalar!
    plan_t2 = QueryPlan(
        intent="lookup",
        target_columns=["event_status"],
        input_result_reference="turn1",
    )
    # Check that service._can_execute_in_memory returns False
    assert service._can_execute_in_memory(plan_t2, context["history"][0]) is False

    # After Turn 2 executes on SQL Server, data is row-based
    context["history"].append(
        {
            "reference_id": "turn2",
            "question": "Show me the event statuses.",
            "columns": ["event_status"],
            "data": [{"event_status": "Pending"}, {"event_status": "Active"}],
            "tables": [{"schema": "dbo", "table": "site_events"}],
        }
    )

    # Turn 3: "Sort those statuses alphabetically."
    plan_t3 = QueryPlan(
        intent="ranking",
        input_result_reference="turn2",
        target_columns=["event_status"],
        sort_column="event_status",
        sort_direction="asc",
    )
    assert service._can_execute_in_memory(plan_t3, context["history"][1]) is True
    res_t3 = service._execute_conversation_result_plan(plan_t3, context)
    assert res_t3 == [{"event_status": "Active"}, {"event_status": "Pending"}]


# =============================================================================
# REGRESSION CASE 1
# First: "How many events are there?" -> 600
# Second: "Show me the event statuses." -> valid status result
# Third: "Sort those statuses alphabetically." -> sort the referenced result
# =============================================================================

def test_regression_case_1_events_statuses_sort():
    schema = _build_test_schema()
    service = _make_mock_service(schema)

    # Turn 1: scalar count 600
    ref_1 = "turn1_scalar"
    context = {
        "history": [
            {
                "reference_id": ref_1,
                "question": "How many events are there?",
                "columns": ["value_count"],
                "data": 600,
                "tables": [{"schema": "dbo", "table": "site_events"}],
            }
        ]
    }

    # Turn 2: "Show me the event statuses."
    # Even if DeepSeek attached input_result_reference=ref_1,
    # Mode 1 is rejected because 600 is scalar! Mode 2 executes on SQL Server.
    plan_turn2 = QueryPlan(
        intent="lookup",
        input_result_reference=ref_1,
        target_columns=["event_status"],
    )
    assert service._can_execute_in_memory(plan_turn2, context["history"][0]) is False

    mock_statuses = [
        {"event_status": "Scheduled"},
        {"event_status": "Active"},
        {"event_status": "Completed"},
    ]
    ref_2 = "turn2_statuses"
    context["history"].append(
        {
            "reference_id": ref_2,
            "question": "Show me the event statuses.",
            "columns": ["event_status"],
            "data": mock_statuses,
            "tables": [{"schema": "dbo", "table": "site_events"}],
        }
    )

    # Turn 3: "Sort those statuses alphabetically."
    plan_turn3 = QueryPlan(
        intent="ranking",
        input_result_reference=ref_2,
        target_columns=["event_status"],
        sort_column="event_status",
        sort_direction="asc",
    )
    assert service._can_execute_in_memory(plan_turn3, context["history"][1]) is True
    res_turn3 = service._execute_conversation_result_plan(plan_turn3, context)
    assert [r["event_status"] for r in res_turn3] == ["Active", "Completed", "Scheduled"]


# =============================================================================
# REGRESSION CASE 2
# First: "Show me the event statuses."
# Second: "Show only the statuses that start with C."
# Expected: only matching statuses
# =============================================================================

def test_regression_case_2_statuses_start_with_c():
    schema = _build_test_schema()
    service = _make_mock_service(schema)

    ref_1 = "statuses_turn1"
    context = {
        "history": [
            {
                "reference_id": ref_1,
                "question": "Show me the event statuses.",
                "columns": ["event_status"],
                "data": [
                    {"event_status": "Active"},
                    {"event_status": "Cancelled"},
                    {"event_status": "Completed"},
                    {"event_status": "Closed"},
                    {"event_status": "Draft"},
                ],
                "tables": [{"schema": "dbo", "table": "site_events"}],
            }
        ]
    }

    # Turn 2: "Show only the statuses that start with C."
    plan_turn2 = QueryPlan(
        intent="filter",
        input_result_reference=ref_1,
        target_columns=["event_status"],
        filters=[
            QueryFilter(column="event_status", operator="starts_with", value="C")
        ],
    )
    assert service._can_execute_in_memory(plan_turn2, context["history"][0]) is True
    result = service._execute_conversation_result_plan(plan_turn2, context)
    statuses = [r["event_status"] for r in result]
    assert statuses == ["Cancelled", "Completed", "Closed"]


# =============================================================================
# REGRESSION CASE 3
# First: "How many workspaces have team members?"
# Second: "What are the names of those team members?"
# Expected: second query uses semantic context of first query and
# identifies appropriate underlying entity/table relationship generically.
# =============================================================================

def test_regression_case_3_workspaces_team_members():
    schema = _build_test_schema()
    service = _make_mock_service(schema)

    # Turn 1: Grouped workspaces count
    ref_1 = "workspaces_turn1"
    context = {
        "history": [
            {
                "reference_id": ref_1,
                "question": "How many workspaces have team members?",
                "columns": ["workspace_name", "aggregation_value"],
                "data": [
                    {"workspace_name": "Alpha", "aggregation_value": 3},
                    {"workspace_name": "Beta", "aggregation_value": 7},
                ],
                "tables": [{"schema": "dbo", "table": "workspaces"}],
            }
        ]
    }

    # Turn 2: "What are the names of those team members?"
    # 1. In-memory check must be False because member_name is not in previous result!
    plan_turn2 = QueryPlan(
        intent="lookup",
        input_result_reference=ref_1,
        target_columns=["member_name"],
    )
    assert service._can_execute_in_memory(plan_turn2, context["history"][0]) is False

    # 2. Table resolution must combine team_members with prior workspaces!
    with patch("app.database.query_service.select_tables") as mock_select:
        mock_select.return_value = [{"schema": "dbo", "table": "team_members"}]
        resolved_tables = service._resolve_execution_tables(
            question="What are the names of those team members?",
            conversation_context=context,
        )
        resolved_table_names = [t.table_name for t in resolved_tables]
        assert "team_members" in resolved_table_names
        assert "workspaces" in resolved_table_names
