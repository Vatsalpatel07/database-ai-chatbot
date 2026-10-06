from __future__ import annotations

from unittest.mock import MagicMock
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
from app.database.join_validator import (
    validate_query_plan_joins,
)
from app.database.relationship_service import (
    RelationshipDiscoveryService,
    RelationshipGraph,
    RelationshipResult,
    RelationshipStep,
    RelationshipPath,
)
from app.database.table_selector import (
    expand_selected_tables_by_relationships,
)
from app.database.query_service import (
    DatabaseQueryService,
)
from app.query.analyzer import QuestionAnalyzer
from app.query.schema import (
    QueryColumn,
    QueryFilter,
    QueryJoin,
    QueryPlan,
)


def _make_col(name: str, data_type: str = "nvarchar", nullable: bool = True, pos: int = 1) -> ColumnInfo:
    return ColumnInfo(
        name=name,
        data_type=data_type,
        nullable=nullable,
        ordinal_position=pos,
    )


def _build_synthetic_multihop_schema() -> DatabaseSchema:
    """
    Synthetic 3-tier schema:
    workspaces -> workspace_items -> items
    """
    workspaces = TableInfo(
        schema_name="app",
        table_name="workspaces",
        columns=[
            _make_col("workspace_id", "int", False, 1),
            _make_col("workspace_name", "nvarchar", False, 2),
            _make_col("owner_id", "int", True, 3),
        ],
        primary_key_columns=["workspace_id"],
    )

    workspace_items = TableInfo(
        schema_name="app",
        table_name="workspace_items",
        columns=[
            _make_col("bridge_id", "int", False, 1),
            _make_col("workspace_id", "int", False, 2),
            _make_col("item_id", "int", False, 3),
        ],
        primary_key_columns=["bridge_id"],
    )

    items = TableInfo(
        schema_name="app",
        table_name="items",
        columns=[
            _make_col("item_id", "int", False, 1),
            _make_col("item_title", "nvarchar", False, 2),
            _make_col("item_status", "nvarchar", True, 3),
            _make_col("item_count", "int", True, 4),
        ],
        primary_key_columns=["item_id"],
    )

    return DatabaseSchema(
        tables=[workspaces, workspace_items, items],
        foreign_keys=[
            ForeignKeyInfo(
                constraint_name="fk_wi_workspace",
                schema_name="app",
                table_name="workspace_items",
                column_name="workspace_id",
                referenced_schema_name="app",
                referenced_table_name="workspaces",
                referenced_column_name="workspace_id",
            ),
            ForeignKeyInfo(
                constraint_name="fk_wi_item",
                schema_name="app",
                table_name="workspace_items",
                column_name="item_id",
                referenced_schema_name="app",
                referenced_table_name="items",
                referenced_column_name="item_id",
            ),
        ],
    )


# =============================================================================
# TESTS
# =============================================================================

def test_direct_relationship_a_to_b():
    """Test direct relationship path and join validation."""
    schema = _build_synthetic_multihop_schema()
    rel_service = RelationshipDiscoveryService(schema)

    plan = QueryPlan(
        intent="lookup",
        target_columns=["workspace_name"],
        joins=[
            QueryJoin(
                left_schema="app",
                left_table="workspaces",
                left_column="workspace_id",
                right_schema="app",
                right_table="workspace_items",
                right_column="workspace_id",
                join_type="inner",
            )
        ],
    )
    res = validate_query_plan_joins(plan, schema, rel_service)
    assert res.valid is True
    assert len(res.errors) == 0


def test_multi_hop_relationship_a_to_b_to_c():
    """Test multi-hop relationship path finding and normalization."""
    schema = _build_synthetic_multihop_schema()
    rel_service = RelationshipDiscoveryService(schema)

    # find_best_path between workspaces and items
    path = rel_service.find_best_path(
        start=("app", "workspaces"),
        target=("app", "items"),
    )
    assert path is not None
    assert path.total_hops == 2
    assert len(path.steps) == 2
    assert (path.steps[0].left_table, path.steps[0].right_table) == ("workspaces", "workspace_items")
    assert (path.steps[1].left_table, path.steps[1].right_table) == ("workspace_items", "items")


def test_weak_direct_vs_strong_two_hop_path_selection():
    """
    Test that when an invalid or weak direct join is proposed between endpoints,
    _normalize_plan replaces it with the validated multi-hop path.
    """
    schema = _build_synthetic_multihop_schema()
    rel_service = RelationshipDiscoveryService(schema)

    # Proposed direct join between workspaces and items that has no direct edge
    raw_plan = QueryPlan(
        intent="aggregation",
        target_columns=["item_id"],
        group_by=["workspace_id"],
        aggregation="count",
        joins=[
            QueryJoin(
                left_schema="app",
                left_table="workspaces",
                left_column="workspace_id",
                right_schema="app",
                right_table="items",
                right_column="item_id",  # Invalid direct edge
                join_type="inner",
            )
        ],
    )

    norm_plan = QuestionAnalyzer._normalize_plan(
        plan=raw_plan,
        question="Which workspace has the most items?",
        semantic_schema=schema,
        relationship_service=rel_service,
    )

    # Must be expanded into the 2-hop validated path
    assert len(norm_plan.joins) == 2
    assert norm_plan.joins[0].left_table == "workspaces"
    assert norm_plan.joins[0].right_table == "workspace_items"
    assert norm_plan.joins[1].left_table == "workspace_items"
    assert norm_plan.joins[1].right_table == "items"


def test_multi_table_entity_projection():
    """
    Test that descriptive entity attributes (workspace_name) are retained in group_by
    so they are projected alongside the aggregate count.
    """
    schema = _build_synthetic_multihop_schema()
    rel_service = RelationshipDiscoveryService(schema)

    raw_plan = QueryPlan(
        intent="aggregation",
        target_columns=["workspace_name"],
        group_by=["workspace_id"],
        aggregation="count",
        sort_column="count",
        sort_direction="desc",
        limit=1,
        joins=[
            QueryJoin(
                left_schema="app",
                left_table="workspaces",
                left_column="workspace_id",
                right_schema="app",
                right_table="workspace_items",
                right_column="workspace_id",
                join_type="inner",
            )
        ],
    )

    norm_plan = QuestionAnalyzer._normalize_plan(
        plan=raw_plan,
        question="Which workspace name has the most items?",
        semantic_schema=schema,
        relationship_service=rel_service,
    )

    # workspace_name should be included in group_by
    assert "workspace_name" in norm_plan.group_by
    assert "workspace_id" in norm_plan.group_by


def test_multi_table_filter_qualification():
    """
    Test that unqualified filters across joined tables are qualified with their respective tables.
    """
    schema = _build_synthetic_multihop_schema()
    rel_service = RelationshipDiscoveryService(schema)

    raw_plan = QueryPlan(
        intent="lookup",
        target_columns=["workspace_name"],
        filters=[
            QueryFilter(column="workspace_id", operator="equals", value=123),
        ],
        joins=[
            QueryJoin(
                left_schema="app",
                left_table="workspaces",
                left_column="workspace_id",
                right_schema="app",
                right_table="workspace_items",
                right_column="workspace_id",
                join_type="inner",
            ),
            QueryJoin(
                left_schema="app",
                left_table="workspace_items",
                left_column="item_id",
                right_schema="app",
                right_table="items",
                right_column="item_id",
                join_type="inner",
            ),
        ],
    )

    norm_plan = QuestionAnalyzer._normalize_plan(
        plan=raw_plan,
        question="Show workspaces with active items",
        semantic_schema=schema,
        relationship_service=rel_service,
    )

    # Ambiguous filter column should be qualified with primary table
    assert norm_plan.filters[0].column == "app.workspaces.workspace_id"


def test_left_join_anti_join_detection():
    """
    Test that negative questions ('without items', 'no items') normalize to LEFT JOIN.
    """
    schema = _build_synthetic_multihop_schema()
    rel_service = RelationshipDiscoveryService(schema)

    raw_plan = QueryPlan(
        intent="lookup",
        target_columns=["workspace_id"],
        joins=[
            QueryJoin(
                left_schema="app",
                left_table="workspaces",
                left_column="workspace_id",
                right_schema="app",
                right_table="workspace_items",
                right_column="workspace_id",
                join_type="inner",
            )
        ],
    )

    norm_plan = QuestionAnalyzer._normalize_plan(
        plan=raw_plan,
        question="Which workspaces have no items?",
        semantic_schema=schema,
        relationship_service=rel_service,
    )

    assert norm_plan.joins[0].join_type == "left"


def test_ambiguous_or_unconnected_relationship_fails_closed():
    """
    Test that joining completely disconnected tables fails closed during validation.
    """
    schema = _build_synthetic_multihop_schema()
    unconnected_table = TableInfo(
        schema_name="audit",
        table_name="logs",
        columns=[
            _make_col("log_id", "int", False, 1),
            _make_col("message", "nvarchar", True, 2),
        ],
        primary_key_columns=["log_id"],
    )
    full_schema = DatabaseSchema(
        tables=[*schema.tables, unconnected_table],
        foreign_keys=schema.foreign_keys,
    )
    rel_service = RelationshipDiscoveryService(full_schema)

    plan = QueryPlan(
        intent="lookup",
        target_columns=["workspace_id"],
        joins=[
            QueryJoin(
                left_schema="app",
                left_table="workspaces",
                left_column="workspace_id",
                right_schema="audit",
                right_table="logs",
                right_column="log_id",
                join_type="inner",
            )
        ],
    )

    res = validate_query_plan_joins(plan, full_schema, rel_service)
    assert res.valid is False
    assert any("not validated" in err for err in res.errors)


def test_conversation_followup_preserves_joins():
    """
    Test that a contextual follow-up query inherits prior multi-table joins.
    """
    schema = _build_synthetic_multihop_schema()
    rel_service = RelationshipDiscoveryService(schema)

    prior_joins = [
        QueryJoin(
            left_schema="app",
            left_table="workspaces",
            left_column="workspace_id",
            right_schema="app",
            right_table="workspace_items",
            right_column="workspace_id",
            join_type="inner",
        ),
        QueryJoin(
            left_schema="app",
            left_table="workspace_items",
            left_column="item_id",
            right_schema="app",
            right_table="items",
            right_column="item_id",
            join_type="inner",
        ),
    ]

    conversation_context = {
        "history": [
            {
                "reference_id": "ref-123",
                "question": "Which workspaces have more than 5 items?",
                "plan": {
                    "intent": "aggregation",
                    "group_by": ["workspace_id"],
                    "aggregation": "count",
                    "joins": [j.__dict__ for j in prior_joins],
                    "having_filters": [{"column": "count", "operator": "greater_than", "value": 5}],
                },
                "data": [{"workspace_id": 1, "aggregation_value": 8}],
            }
        ]
    }

    raw_followup_plan = QueryPlan(
        intent="aggregation",
        target_columns=["workspace_name"],
        group_by=["workspace_id"],
        aggregation="count",
        input_result_reference="ref-123",
        joins=[],
    )

    norm_plan = QuestionAnalyzer._normalize_plan(
        plan=raw_followup_plan,
        question="Show the workspace name and count for those workspaces.",
        semantic_schema=schema,
        conversation_context=conversation_context,
        relationship_service=rel_service,
    )

    # Joins must be preserved from prior query
    assert len(norm_plan.joins) == 2
    assert norm_plan.joins[0].left_table == "workspaces"
    assert norm_plan.joins[1].right_table == "items"
    # Having filter must be preserved
    assert len(norm_plan.having_filters) == 1
    assert norm_plan.having_filters[0].value == 5


def test_table_pruner_retains_bridge_tables():
    """
    Test that _prune_execution_tables retains intermediate bridge tables in multi-hop joins.
    """
    schema = _build_synthetic_multihop_schema()
    query_service = DatabaseQueryService(
        database_schema=schema,
        metadata_service=MagicMock(),
        executor=MagicMock(),
    )

    plan = QueryPlan(
        intent="aggregation",
        group_by=["workspace_id"],
        aggregation="count",
        joins=[
            QueryJoin(
                left_schema="app",
                left_table="workspaces",
                left_column="workspace_id",
                right_schema="app",
                right_table="workspace_items",
                right_column="workspace_id",
                join_type="inner",
            ),
            QueryJoin(
                left_schema="app",
                left_table="workspace_items",
                left_column="item_id",
                right_schema="app",
                right_table="items",
                right_column="item_id",
                join_type="inner",
            ),
        ],
    )

    # Candidate tables originally only contained endpoints
    candidate_tables = [
        schema.get_table("app", "workspaces"),
        schema.get_table("app", "items"),
    ]

    pruned = query_service._prune_execution_tables(plan, candidate_tables)
    pruned_names = {t.table_name for t in pruned}

    # Bridge table workspace_items must be retained
    assert "workspaces" in pruned_names
    assert "workspace_items" in pruned_names
    assert "items" in pruned_names


def test_executor_grouped_count_grain_preservation():
    """
    Test that SQLQueryExecutor projects all joined table keys in the subquery
    when grouping, so detail rows are not collapsed.
    """
    from unittest.mock import patch
    schema = _build_synthetic_multihop_schema()
    executor = SQLQueryExecutor()

    plan = QueryPlan(
        intent="aggregation",
        group_by=["workspace_id"],
        aggregation="count",
        joins=[
            QueryJoin(
                left_schema="app",
                left_table="workspaces",
                left_column="workspace_id",
                right_schema="app",
                right_table="workspace_items",
                right_column="workspace_id",
                join_type="inner",
            )
        ],
    )

    with patch("app.database.sql_executor.get_connection") as mock_conn:
        cur = MagicMock()
        cur.description = [("workspace_id",), ("aggregation_value",)]
        cur.fetchall.return_value = [(1, 5)]
        mock_conn.return_value.__enter__.return_value.cursor.return_value = cur

        res = executor.execute(
            plan=plan,
            table=schema.tables[0],
            tables=schema.tables[:2],
        )

        sql = cur.execute.call_args[0][0]
        # Both workspace and workspace_items identifying columns must be projected in subquery
        assert ("t1.[workspace_id]" in sql or "t1.\"workspace_id\"" in sql)
        assert ("t2.[bridge_id]" in sql or "t2.\"bridge_id\"" in sql)
        assert "COUNT(*)" in sql
        assert res == [{"workspace_id": 1, "aggregation_value": 5}]


def test_executor_left_join_count_zero():
    """
    Test that SQLQueryExecutor projects __sub_right_id on LEFT JOIN queries
    so that 0 related records produce COUNT 0 instead of COUNT(*) = 1.
    """
    from unittest.mock import patch
    schema = _build_synthetic_multihop_schema()
    executor = SQLQueryExecutor()

    plan = QueryPlan(
        intent="aggregation",
        group_by=["workspace_id"],
        aggregation="count",
        joins=[
            QueryJoin(
                left_schema="app",
                left_table="workspaces",
                left_column="workspace_id",
                right_schema="app",
                right_table="workspace_items",
                right_column="workspace_id",
                join_type="left",
            )
        ],
    )

    with patch("app.database.sql_executor.get_connection") as mock_conn:
        cur = MagicMock()
        cur.description = [("workspace_id",), ("aggregation_value",)]
        cur.fetchall.return_value = [(1, 0)]
        mock_conn.return_value.__enter__.return_value.cursor.return_value = cur

        res = executor.execute(
            plan=plan,
            table=schema.tables[0],
            tables=schema.tables[:2],
        )

        sql = cur.execute.call_args[0][0]
        # Subquery must project right table identifier for null-safe counting
        assert "__sub_right_id" in sql
        assert "COUNT(sub.[__sub_right_id])" in sql or "COUNT(sub.\"__sub_right_id\")" in sql


def test_executor_distinct_count():
    """
    Test that SQLQueryExecutor respects distinct=True on count aggregations.
    """
    from unittest.mock import patch
    schema = _build_synthetic_multihop_schema()
    executor = SQLQueryExecutor()

    plan = QueryPlan(
        intent="aggregation",
        group_by=["workspace_id"],
        aggregation="count",
        target_columns=["workspace_items.item_id"],
        distinct=True,
        joins=[
            QueryJoin(
                left_schema="app",
                left_table="workspaces",
                left_column="workspace_id",
                right_schema="app",
                right_table="workspace_items",
                right_column="workspace_id",
                join_type="inner",
            )
        ],
    )

    with patch("app.database.sql_executor.get_connection") as mock_conn:
        cur = MagicMock()
        cur.description = [("workspace_id",), ("aggregation_value",)]
        cur.fetchall.return_value = [(1, 3)]
        mock_conn.return_value.__enter__.return_value.cursor.return_value = cur

        res = executor.execute(
            plan=plan,
            table=schema.tables[0],
            tables=schema.tables[:2],
        )

        sql = cur.execute.call_args[0][0]
        assert "COUNT(DISTINCT sub.[__sub_target])" in sql or "COUNT(DISTINCT sub.\"__sub_target\")" in sql

