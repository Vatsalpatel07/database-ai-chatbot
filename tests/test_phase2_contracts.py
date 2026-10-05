import json
from unittest.mock import MagicMock, patch

import pytest

from app.database.join_validator import validate_query_plan_joins
from app.database.relationship_discovery import RelationshipCandidate
from app.database.relationship_service import (
    RelationshipDiscoveryService,
    RelationshipResult,
)
from app.database.relationship_validator import (
    RelationshipValidation,
    validate_relationship,
)
from app.database.schema import ColumnInfo, DatabaseSchema, ForeignKeyInfo, TableInfo
from app.database.semantic_query_cache import SemanticQueryCache
from app.orchestration.database_orchestrator import DatabaseOrchestrator
from app.query.schema import QueryFilter, QueryJoin, QueryPlan
from app.query.validator import QueryPlanValidator


# =============================================================================
# Helpers / Generic synthetic fixtures
# =============================================================================

def _build_generic_schema() -> DatabaseSchema:
    table_orders = TableInfo(
        schema_name="sales",
        table_name="orders",
        columns=[
            ColumnInfo("order_id", "int", False, 1),
            ColumnInfo("customer_id", "int", False, 2),
            ColumnInfo("amount", "decimal", False, 3),
            ColumnInfo("status", "varchar", True, 4),
        ],
        primary_key_columns=["order_id"],
    )
    table_customers = TableInfo(
        schema_name="sales",
        table_name="customers",
        columns=[
            ColumnInfo("customer_id", "int", False, 1),
            ColumnInfo("customer_name", "varchar", False, 2),
        ],
        primary_key_columns=["customer_id"],
    )
    return DatabaseSchema(
        tables=[table_orders, table_customers],
        foreign_keys=[],
        unique_constraints=[],
    )


# =============================================================================
# PART A1: Semantic Cache having_filters roundtrip & backward compatibility
# =============================================================================

def test_semantic_cache_roundtrip_with_having_filters(tmp_path):
    cache = SemanticQueryCache(cache_dir=tmp_path)

    plan = QueryPlan(
        intent="aggregation",
        target_columns=["amount"],
        group_by=["customer_id"],
        aggregation="sum",
        having_filters=[
            QueryFilter(column="sum", operator="greater_than", value=500),
            QueryFilter(column="amount", operator="less_than_or_equal", value=10000),
        ],
        confidence=0.95,
        explanation="Orders grouped by customer with sum > 500",
    )

    cache.set(
        question="Which customers have total orders over 500?",
        server_name="test_server",
        database_name="test_db",
        schema_fingerprint="fp123",
        plan=plan,
    )

    restored = cache.get(
        question="Which customers have total orders over 500?",
        server_name="test_server",
        database_name="test_db",
        schema_fingerprint="fp123",
    )

    assert restored is not None
    assert len(restored.having_filters) == 2
    assert restored.having_filters[0].column == "sum"
    assert restored.having_filters[0].operator == "greater_than"
    assert restored.having_filters[0].value == 500
    assert restored.having_filters[1].column == "amount"
    assert restored.having_filters[1].operator == "less_than_or_equal"
    assert restored.having_filters[1].value == 10000
    assert restored.aggregation == "sum"
    assert restored.group_by == ["customer_id"]


def test_semantic_cache_roundtrip_with_empty_having_filters(tmp_path):
    cache = SemanticQueryCache(cache_dir=tmp_path)

    plan = QueryPlan(
        intent="lookup",
        target_columns=["customer_name"],
        having_filters=[],
        confidence=0.9,
    )

    cache.set(
        question="show customer names",
        server_name="test_server",
        database_name="test_db",
        schema_fingerprint="fp123",
        plan=plan,
    )

    restored = cache.get(
        question="show customer names",
        server_name="test_server",
        database_name="test_db",
        schema_fingerprint="fp123",
    )

    assert restored is not None
    assert restored.having_filters == []


def test_semantic_cache_backward_compatibility_missing_having_filters(tmp_path):
    cache = SemanticQueryCache(cache_dir=tmp_path)
    key = cache.build_key(
        question="legacy query test",
        server_name="test_server",
        database_name="test_db",
        schema_fingerprint="fp123",
    )

    # Legacy cache payload without having_filters key in plan
    legacy_payload = {
        "cache_version": cache.CACHE_VERSION,
        "server_name": "test_server",
        "database_name": "test_db",
        "schema_fingerprint": "fp123",
        "normalized_question": cache.normalize_question("legacy query test"),
        "created_at": "2025-01-01T00:00:00+00:00",
        "plan": {
            "intent": "count",
            "target_columns": ["order_id"],
            "filters": [],
            "group_by": ["status"],
            "aggregation": "count",
            "sort_column": None,
            "sort_direction": None,
            "limit": None,
            "include_ties": False,
            "input_result_reference": None,
            "explanation": "Legacy cached plan",
            "confidence": 0.85,
            "joins": [],
            "target_column_refs": [],
            "group_by_refs": [],
            "group_by_granularity": None,
            "require_all_filter_values": False,
            # 'having_filters' is intentionally absent
        },
    }

    cache_file = tmp_path / f"{key}.json"
    cache_file.write_text(json.dumps(legacy_payload), encoding="utf-8")

    restored = cache.get(
        question="legacy query test",
        server_name="test_server",
        database_name="test_db",
        schema_fingerprint="fp123",
    )

    assert restored is not None
    assert restored.having_filters == []
    assert restored.intent == "count"
    assert restored.aggregation == "count"
    assert restored.group_by == ["status"]


# =============================================================================
# PART A2: QueryPlanValidator having_filters validation
# =============================================================================

def test_validator_valid_having_filters():
    schema = _build_generic_schema()
    validator = QueryPlanValidator()

    plan = QueryPlan(
        intent="aggregation",
        target_columns=["amount"],
        group_by=["status"],
        aggregation="sum",
        having_filters=[
            QueryFilter(column="sum", operator="greater_than", value=100),
            QueryFilter(column="amount", operator="less_than_or_equal", value=5000),
        ],
        confidence=0.9,
    )

    result = validator.validate(plan, schema)
    assert result.valid is True
    assert result.errors == []


def test_validator_having_filter_with_virtual_aggregate_columns():
    schema = _build_generic_schema()
    validator = QueryPlanValidator()

    for col in ["count", "sum", "average", "min", "max", "aggregation_value"]:
        plan = QueryPlan(
            intent="aggregation",
            target_columns=["amount"],
            group_by=["status"],
            aggregation="sum",
            having_filters=[
                QueryFilter(column=col, operator="greater_than", value=10),
            ],
            confidence=0.9,
        )
        result = validator.validate(plan, schema)
        assert result.valid is True, f"Failed for column {col}: {result.errors}"


def test_validator_having_filter_missing_aggregation():
    schema = _build_generic_schema()
    validator = QueryPlanValidator()

    plan = QueryPlan(
        intent="lookup",
        target_columns=["amount"],
        group_by=["customer_id"],
        aggregation=None,
        having_filters=[
            QueryFilter(column="amount", operator="greater_than", value=100),
        ],
        confidence=0.9,
    )

    result = validator.validate(plan, schema)
    assert result.valid is False
    assert any("HAVING filter requires an aggregation function" in e for e in result.errors)


def test_validator_having_filter_median_unsupported():
    schema = _build_generic_schema()
    validator = QueryPlanValidator()

    plan = QueryPlan(
        intent="aggregation",
        target_columns=["amount"],
        group_by=["customer_id"],
        aggregation="median",
        having_filters=[
            QueryFilter(column="median", operator="greater_than", value=100),
        ],
        confidence=0.9,
    )

    result = validator.validate(plan, schema)
    assert result.valid is False
    assert any("HAVING filters are not supported for median grouped aggregation" in e for e in result.errors)


def test_validator_having_filter_missing_group_by():
    schema = _build_generic_schema()
    validator = QueryPlanValidator()

    plan = QueryPlan(
        intent="aggregation",
        target_columns=["amount"],
        group_by=[],
        aggregation="sum",
        having_filters=[
            QueryFilter(column="sum", operator="greater_than", value=100),
        ],
        confidence=0.9,
    )

    result = validator.validate(plan, schema)
    assert result.valid is False
    assert any("HAVING filter requires at least one group-by column" in e for e in result.errors)


def test_validator_having_filter_nonexistent_column():
    schema = _build_generic_schema()
    validator = QueryPlanValidator()

    plan = QueryPlan(
        intent="aggregation",
        target_columns=["amount"],
        group_by=["customer_id"],
        aggregation="sum",
        having_filters=[
            QueryFilter(column="ghost_column", operator="greater_than", value=100),
        ],
        confidence=0.9,
    )

    result = validator.validate(plan, schema)
    assert result.valid is False
    assert any("HAVING filter column does not exist: ghost_column" in e for e in result.errors)


def test_validator_having_filter_unsupported_operators():
    schema = _build_generic_schema()
    validator = QueryPlanValidator()

    # Operator not in VALID_OPERATORS at all
    plan1 = QueryPlan(
        intent="aggregation",
        target_columns=["amount"],
        group_by=["customer_id"],
        aggregation="sum",
        having_filters=[
            QueryFilter(column="sum", operator="regex_match", value=100),
        ],
        confidence=0.9,
    )
    result1 = validator.validate(plan1, schema)
    assert result1.valid is False
    assert any("Unsupported filter operator: regex_match" in e for e in result1.errors)

    # Operator in VALID_OPERATORS (like contains) but not in VALID_HAVING_OPERATORS
    plan2 = QueryPlan(
        intent="aggregation",
        target_columns=["amount"],
        group_by=["customer_id"],
        aggregation="sum",
        having_filters=[
            QueryFilter(column="sum", operator="contains", value="abc"),
        ],
        confidence=0.9,
    )
    result2 = validator.validate(plan2, schema)
    assert result2.valid is False
    assert any("not supported for aggregate filtering" in e for e in result2.errors)


def test_validator_having_filter_invalid_value_shapes():
    schema = _build_generic_schema()
    validator = QueryPlanValidator()

    # None value
    plan_none = QueryPlan(
        intent="aggregation",
        target_columns=["amount"],
        group_by=["customer_id"],
        aggregation="sum",
        having_filters=[
            QueryFilter(column="sum", operator="greater_than", value=None),
        ],
        confidence=0.9,
    )
    res_none = validator.validate(plan_none, schema)
    assert res_none.valid is False
    assert any("requires a non-empty value" in e for e in res_none.errors)

    # Empty string value
    plan_empty = QueryPlan(
        intent="aggregation",
        target_columns=["amount"],
        group_by=["customer_id"],
        aggregation="sum",
        having_filters=[
            QueryFilter(column="sum", operator="greater_than", value="   "),
        ],
        confidence=0.9,
    )
    res_empty = validator.validate(plan_empty, schema)
    assert res_empty.valid is False
    assert any("requires a non-empty value" in e for e in res_empty.errors)

    # Non-scalar collection value
    plan_list = QueryPlan(
        intent="aggregation",
        target_columns=["amount"],
        group_by=["customer_id"],
        aggregation="sum",
        having_filters=[
            QueryFilter(column="sum", operator="greater_than", value=[10, 20]),
        ],
        confidence=0.9,
    )
    res_list = validator.validate(plan_list, schema)
    assert res_list.valid is False
    assert any("must be a scalar number or string" in e for e in res_list.errors)


# =============================================================================
# PART B: Canonical Relationship Status Lifecycle
# =============================================================================

def test_relationship_validator_status_lifecycle():
    candidate = RelationshipCandidate(
        left_schema="sales",
        left_table="orders",
        left_column="customer_id",
        right_schema="sales",
        right_table="customers",
        right_column="customer_id",
        confidence=0.85,
        reason="Matching column name and data type",
    )

    # Case 1: Sufficient overlap -> status="validated"
    mock_cursor = MagicMock()
    # Query order:
    # 1. COUNT_BIG(*) left -> 100
    # 2. COUNT_BIG(*) right -> 50
    # 3. COUNT(DISTINCT) left -> 40
    # 4. COUNT(DISTINCT) right -> 50
    # 5. COUNT(*) overlap -> 35
    mock_cursor.fetchone.side_effect = [(100,), (50,), (40,), (50,), (35,)]
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor

    with patch("app.database.relationship_validator.get_connection", return_value=mock_conn):
        val = validate_relationship(candidate)
        assert val.status == "validated"
        assert val.matching_value_count == 35

    # Case 2: Zero rows in table -> status="insufficient_data"
    mock_cursor2 = MagicMock()
    mock_cursor2.fetchone.side_effect = [(0,), (50,), (0,), (50,), (0,)]
    mock_conn2 = MagicMock()
    mock_conn2.cursor.return_value = mock_cursor2

    with patch("app.database.relationship_validator.get_connection", return_value=mock_conn2):
        val2 = validate_relationship(candidate)
        assert val2.status == "insufficient_data"

    # Case 3: Zero matching rows -> status="rejected"
    mock_cursor3 = MagicMock()
    mock_cursor3.fetchone.side_effect = [(100,), (50,), (40,), (50,), (0,)]
    mock_conn3 = MagicMock()
    mock_conn3.cursor.return_value = mock_cursor3

    with patch("app.database.relationship_validator.get_connection", return_value=mock_conn3):
        val3 = validate_relationship(candidate)
        assert val3.status == "rejected"

    # Case 4: Weak match (< 2 distinct overlapping) -> status="rejected"
    mock_cursor4 = MagicMock()
    mock_cursor4.fetchone.side_effect = [(100,), (50,), (40,), (50,), (1,)]
    mock_conn4 = MagicMock()
    mock_conn4.cursor.return_value = mock_cursor4

    with patch("app.database.relationship_validator.get_connection", return_value=mock_conn4):
        val4 = validate_relationship(candidate)
        assert val4.status == "rejected"


def test_relationship_service_full_normalization():
    schema = _build_generic_schema()
    schema.foreign_keys = [
        ForeignKeyInfo(
            constraint_name="FK_orders_customers",
            schema_name="sales",
            table_name="orders",
            column_name="customer_id",
            referenced_schema_name="sales",
            referenced_table_name="customers",
            referenced_column_name="customer_id",
        )
    ]

    service = RelationshipDiscoveryService(schema)

    # Declared FK should normalize to status="confirmed"
    results = service.discover([("sales", "orders"), ("sales", "customers")])
    assert len(results) == 1
    assert results[0].relationship_type == "declared_foreign_key"
    assert results[0].status == "confirmed"

    # When no FK exists, inferred candidate validated with status="validated"
    schema_no_fk = _build_generic_schema()
    service_inferred = RelationshipDiscoveryService(schema_no_fk)

    mock_val = RelationshipValidation(
        candidate=RelationshipCandidate(
            left_schema="sales",
            left_table="orders",
            left_column="customer_id",
            right_schema="sales",
            right_table="customers",
            right_column="customer_id",
            reason="name match",
            confidence=0.8,
        ),
        left_row_count=100,
        right_row_count=50,
        left_distinct_count=40,
        right_distinct_count=50,
        matching_value_count=35,
        status="validated",
        reason="35 distinct values overlap",
    )

    with patch("app.database.relationship_service.discover_relationships", return_value=[mock_val.candidate]):
        with patch("app.database.relationship_service.validate_relationship", return_value=mock_val):
            inferred_results = service_inferred.discover([("sales", "orders"), ("sales", "customers")])
            assert len(inferred_results) == 1
            assert inferred_results[0].relationship_type == "inferred"
            assert inferred_results[0].status == "validated"


def test_database_orchestrator_accepts_canonical_statuses():
    schema = _build_generic_schema()
    orchestrator = DatabaseOrchestrator(
        schema=schema,
        query_service=MagicMock(),
    )

    mock_results = [
        RelationshipResult(
            relationship_type="declared_foreign_key",
            status="confirmed",
            left_schema="sales",
            left_table="orders",
            left_column="customer_id",
            right_schema="sales",
            right_table="customers",
            right_column="customer_id",
            reason="FK declared",
            confidence=1.0,
        ),
        RelationshipResult(
            relationship_type="inferred",
            status="validated",
            left_schema="sales",
            left_table="orders",
            left_column="status",
            right_schema="sales",
            right_table="customers",
            right_column="customer_name",
            reason="Inferred data overlap",
            confidence=0.75,
        ),
        RelationshipResult(
            relationship_type="inferred",
            status="rejected",
            left_schema="sales",
            left_table="orders",
            left_column="amount",
            right_schema="sales",
            right_table="customers",
            right_column="customer_id",
            reason="Zero overlap",
            confidence=0.2,
        ),
    ]

    with patch.object(RelationshipDiscoveryService, "discover", return_value=mock_results):
        response = orchestrator._handle_relationship_metadata_request()
        data = response.data

        assert len(data) == 2
        statuses = {item["status"] for item in data}
        assert statuses == {"confirmed", "validated"}
        assert "rejected" not in statuses


def test_join_validator_accepts_canonical_statuses():
    schema = _build_generic_schema()

    joins = [
        QueryJoin(
            left_schema="sales",
            left_table="orders",
            left_column="customer_id",
            right_schema="sales",
            right_table="customers",
            right_column="customer_id",
        )
    ]

    plan = QueryPlan(
        intent="lookup",
        target_columns=["customer_name"],
        joins=joins,
    )

    mock_relationship = RelationshipResult(
        relationship_type="inferred",
        status="validated",
        left_schema="sales",
        left_table="orders",
        left_column="customer_id",
        right_schema="sales",
        right_table="customers",
        right_column="customer_id",
        reason="Inferred data overlap",
        confidence=0.85,
    )

    with patch.object(RelationshipDiscoveryService, "discover", return_value=[mock_relationship]):
        res = validate_query_plan_joins(plan, schema)
        assert res.valid is True
        assert res.errors == []


def test_no_stage_relies_on_obsolete_status_string():
    """
    Ensure that no component in the pipeline silently rejects 'validated'
    in favor of 'candidate_validated', while maintaining backward compatibility.
    """
    schema = _build_generic_schema()

    # 1. Orchestrator accepts 'validated'
    orchestrator = DatabaseOrchestrator(
        schema=schema,
        query_service=MagicMock(),
    )
    validated_rel = RelationshipResult(
        relationship_type="inferred",
        status="validated",
        left_schema="sales",
        left_table="orders",
        left_column="customer_id",
        right_schema="sales",
        right_table="customers",
        right_column="customer_id",
        reason="Data overlap confirmed",
        confidence=0.8,
    )

    with patch.object(RelationshipDiscoveryService, "discover", return_value=[validated_rel]):
        response = orchestrator._handle_relationship_metadata_request()
        assert len(response.data) == 1
        assert response.data[0]["status"] == "validated"

    # 2. Join validator accepts 'validated'
    plan = QueryPlan(
        intent="lookup",
        target_columns=["customer_name"],
        joins=[
            QueryJoin(
                left_schema="sales",
                left_table="orders",
                left_column="customer_id",
                right_schema="sales",
                right_table="customers",
                right_column="customer_id",
            )
        ],
    )
    with patch.object(RelationshipDiscoveryService, "discover", return_value=[validated_rel]):
        res = validate_query_plan_joins(plan, schema)
        assert res.valid is True
        assert res.errors == []

