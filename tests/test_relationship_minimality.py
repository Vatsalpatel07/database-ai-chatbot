from __future__ import annotations

from unittest.mock import MagicMock
import pytest

from app.database.schema import (
    ColumnInfo,
    DatabaseSchema,
    ForeignKeyInfo,
    TableInfo,
)
from app.query.result_validator import (
    QueryResultValidator,
)
from app.database.relationship_service import (
    RelationshipDiscoveryService,
    RelationshipGraph,
    RelationshipPath,
    RelationshipResult,
    RelationshipStep,
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


def _build_test_schema() -> DatabaseSchema:
    workspaces = TableInfo(
        schema_name="app",
        table_name="workspaces",
        columns=[
            _make_col("workspace_id", "int", False, 1),
            _make_col("workspace_title", "nvarchar", False, 2),
            _make_col("site_id", "int", True, 3),
        ],
        primary_key_columns=["workspace_id"],
    )

    resources = TableInfo(
        schema_name="app",
        table_name="resources",
        columns=[
            _make_col("resource_id", "int", False, 1),
            _make_col("resource_title", "nvarchar", False, 2),
            _make_col("workspace_id", "int", True, 3),
            _make_col("site_id", "int", True, 4),
        ],
        primary_key_columns=["resource_id"],
    )

    registrations = TableInfo(
        schema_name="app",
        table_name="registrations",
        columns=[
            _make_col("registration_id", "int", False, 1),
            _make_col("resource_id", "int", False, 2),
            _make_col("site_id", "int", True, 3),
            _make_col("registered_at", "datetime", False, 4),
        ],
        primary_key_columns=["registration_id"],
    )

    activities = TableInfo(
        schema_name="app",
        table_name="activities",
        columns=[
            _make_col("activity_id", "int", False, 1),
            _make_col("resource_id", "int", False, 2),
            _make_col("action_name", "nvarchar", False, 3),
            _make_col("action_time", "datetime", False, 4),
            _make_col("site_id", "int", True, 5),
        ],
        primary_key_columns=["activity_id"],
    )

    step_c = TableInfo(
        schema_name="app",
        table_name="step_c",
        columns=[
            _make_col("c_id", "int", False, 1),
            _make_col("workspace_id", "int", True, 2),
            _make_col("d_id", "int", True, 3),
        ],
        primary_key_columns=["c_id"],
    )

    step_d = TableInfo(
        schema_name="app",
        table_name="step_d",
        columns=[
            _make_col("d_id", "int", False, 1),
            _make_col("registration_id", "int", True, 2),
        ],
        primary_key_columns=["d_id"],
    )

    return DatabaseSchema(
        tables=[workspaces, resources, registrations, activities, step_c, step_d],
        foreign_keys=[],
    )


# ==========================================================
# Scenario A: Minimal direct join beats unnecessary 3-hop path
# ==========================================================

def test_scenario_a_minimal_direct_join_beats_3hop():
    schema = _build_test_schema()
    graph = RelationshipGraph()

    # Direct 1-hop path: resources -> registrations
    graph.add(
        RelationshipResult(
            relationship_type="semantic_name_match",
            status="validated",
            left_schema="app",
            left_table="resources",
            left_column="resource_id",
            right_schema="app",
            right_table="registrations",
            right_column="resource_id",
            confidence=0.85,
            reason="Direct semantic match",
        )
    )

    # 3-hop path: resources -> step_c -> step_d -> registrations
    graph.add(
        RelationshipResult(
            relationship_type="semantic_name_match",
            status="validated",
            left_schema="app",
            left_table="resources",
            left_column="resource_id",
            right_schema="app",
            right_table="step_c",
            right_column="c_id",
            confidence=0.88,
            reason="Hop 1",
        )
    )
    graph.add(
        RelationshipResult(
            relationship_type="semantic_name_match",
            status="validated",
            left_schema="app",
            left_table="step_c",
            left_column="d_id",
            right_schema="app",
            right_table="step_d",
            right_column="d_id",
            confidence=0.88,
            reason="Hop 2",
        )
    )
    graph.add(
        RelationshipResult(
            relationship_type="semantic_name_match",
            status="validated",
            left_schema="app",
            left_table="step_d",
            left_column="registration_id",
            right_schema="app",
            right_table="registrations",
            right_column="registration_id",
            confidence=0.88,
            reason="Hop 3",
        )
    )

    best_path = graph.find_best_path(
        start=("app", "resources"),
        target=("app", "registrations"),
    )

    assert best_path is not None
    assert len(best_path.steps) == 1
    assert best_path.steps[0].left_table == "resources"
    assert best_path.steps[0].right_table == "registrations"


# ==========================================================
# Scenario B: Stronger 2-hop path beats weak direct relationship when intermediate required
# ==========================================================

def test_scenario_b_strong_multihop_beats_weak_direct_when_intermediate_required():
    schema = _build_test_schema()
    graph = RelationshipGraph()

    # Weak direct path: workspaces -> registrations on site_id
    graph.add(
        RelationshipResult(
            relationship_type="column_name_match",
            status="validated",
            left_schema="app",
            left_table="workspaces",
            left_column="site_id",
            right_schema="app",
            right_table="registrations",
            right_column="site_id",
            confidence=0.40,
            reason="generic container site_id",
        )
    )

    # Strong 2-hop path: workspaces -> resources -> registrations
    graph.add(
        RelationshipResult(
            relationship_type="semantic_name_match",
            status="validated",
            left_schema="app",
            left_table="workspaces",
            left_column="workspace_id",
            right_schema="app",
            right_table="resources",
            right_column="workspace_id",
            confidence=0.85,
            reason="workspace to resource",
        )
    )
    graph.add(
        RelationshipResult(
            relationship_type="semantic_name_match",
            status="validated",
            left_schema="app",
            left_table="resources",
            left_column="resource_id",
            right_schema="app",
            right_table="registrations",
            right_column="resource_id",
            confidence=0.85,
            reason="resource to registration",
        )
    )

    # When resource intermediate is requested
    path_with_req = graph.find_best_path(
        start=("app", "workspaces"),
        target=("app", "registrations"),
        required_intermediates={("app", "resources")},
    )

    assert path_with_req is not None
    assert len(path_with_req.steps) == 2
    assert path_with_req.steps[0].right_table == "resources"
    assert path_with_req.steps[1].right_table == "registrations"


# ==========================================================
# Scenario C: Unnecessary bridge table rejected
# ==========================================================

def test_scenario_c_unnecessary_bridge_table_rejected():
    schema = _build_test_schema()
    rel_service = RelationshipDiscoveryService(schema)

    # Single-table registration query
    raw_plan = QueryPlan(
        intent="aggregation",
        aggregation="count",
        target_columns=["registration_id"],
        group_by=["resource_id"],
        joins=[
            QueryJoin(
                left_schema="app",
                left_table="registrations",
                left_column="site_id",
                right_schema="app",
                right_table="activities",
                right_column="site_id",
                join_type="inner",
            )
        ],
    )

    norm_plan = QuestionAnalyzer._normalize_plan(
        plan=raw_plan,
        question="Which resource has the most registrations?",
        semantic_schema=schema,
        relationship_service=rel_service,
    )

    # Question only asks about registrations and resources; unrequested activities table is pruned
    assert len(norm_plan.joins) == 0 or not any(j.right_table == "activities" for j in norm_plan.joins)


# ==========================================================
# Scenario D: Aggregation grain remains stable after optional relationship candidates exist
# ==========================================================

def test_scenario_d_aggregation_grain_remains_stable():
    schema = _build_test_schema()
    rel_service = RelationshipDiscoveryService(schema)

    raw_plan = QueryPlan(
        intent="aggregation",
        aggregation="count",
        target_columns=["registration_id"],
        group_by=["resource_id"],
    )

    norm_plan = QuestionAnalyzer._normalize_plan(
        plan=raw_plan,
        question="Which resource has the most registrations?",
        semantic_schema=schema,
        relationship_service=rel_service,
    )

    # The group_by must contain the resource identifier and at most resource title
    assert "resource_id" in norm_plan.group_by
    # Must NOT include activity or unrelated child table columns
    for col in norm_plan.group_by:
        assert not col.startswith("action_")
        assert not col.startswith("activity_")


# ==========================================================
# Scenario E: Activity table does not multiply registration counts
# ==========================================================

def test_scenario_e_activity_table_does_not_multiply_counts():
    schema = _build_test_schema()
    rel_service = RelationshipDiscoveryService(schema)

    raw_plan = QueryPlan(
        intent="count",
        target_columns=["registration_id"],
        joins=[],
    )

    norm_plan = QuestionAnalyzer._normalize_plan(
        plan=raw_plan,
        question="How many registrations are there?",
        semantic_schema=schema,
        relationship_service=rel_service,
    )

    # Join minimality: single table count query should have 0 joins
    assert len(norm_plan.joins) == 0


# ==========================================================
# Scenario F: Descriptive projection does not add activity columns to GROUP BY
# ==========================================================

def test_scenario_f_descriptive_projection_does_not_pollute_group_by():
    schema = _build_test_schema()
    rel_service = RelationshipDiscoveryService(schema)

    raw_plan = QueryPlan(
        intent="aggregation",
        aggregation="count",
        target_columns=["registration_id"],
        group_by=["resource_id"],
    )

    norm_plan = QuestionAnalyzer._normalize_plan(
        plan=raw_plan,
        question="Which resource has the most registrations?",
        semantic_schema=schema,
        relationship_service=rel_service,
    )

    # Descriptive projection adds resource_title from resources, but NOT activity columns
    for col in norm_plan.group_by:
        assert "activity" not in col.lower()
        assert "action" not in col.lower()


# ==========================================================
# Scenario G: Empty result from valid plan remains empty result
# ==========================================================

def test_scenario_g_empty_result_passes_validation():
    plan = QueryPlan(
        intent="lookup",
        target_columns=["resource_id", "resource_title"],
        filters=[
            QueryFilter(column="resource_title", operator="equals", value="NonExistentResource123"),
        ],
    )
    validator = QueryResultValidator()
    result = validator.validate(plan=plan, data=[])
    assert result.valid is True
    assert len(result.errors) == 0


# ==========================================================
# Scenario H: Ambiguous / over-constrained mixed grain fails closed
# ==========================================================

def test_scenario_h_mixed_grain_fails_closed():
    schema = _build_test_schema()
    rel_service = RelationshipDiscoveryService(schema)

    raw_plan = QueryPlan(
        intent="aggregation",
        aggregation="count",
        target_columns=["registration_id"],
        group_by=["resource_id"],
    )

    question = "Show the resource name, registration count, and account activity information for resources"
    norm_plan = QuestionAnalyzer._normalize_plan(
        plan=raw_plan,
        question=question,
        semantic_schema=schema,
        relationship_service=rel_service,
    )

    assert norm_plan.intent == "unsupported"
    assert "grain" in norm_plan.explanation.lower() or "unaggregated" in norm_plan.explanation.lower() or "activity" in norm_plan.explanation.lower()
