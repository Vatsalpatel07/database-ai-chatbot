from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from app.database.schema import (
    ColumnInfo,
    DatabaseSchema,
    ForeignKeyInfo,
    TableInfo,
)
from app.database.relationship_cache import RelationshipCache, _canonical_key
from app.database.relationship_discovery import (
    RelationshipCandidate,
    discover_relationships,
    discover_bounded_candidates,
    find_candidate_bridge_tables,
)
from app.database.relationship_validator import (
    RelationshipValidation,
)
from app.database.relationship_service import (
    RelationshipResult,
    RelationshipGraph,
    RelationshipDiscoveryService,
    RelationshipService,
)
from app.database.table_selector import (
    select_tables,
    expand_selected_tables_by_relationships,
)
from app.database.join_validator import (
    validate_query_plan_joins,
)
from app.database.query_service import (
    DatabaseQueryService,
)
from app.query.schema import QueryJoin, QueryPlan


# =============================================================================
# Helper Fixtures
# =============================================================================

def _make_col(
    name: str,
    data_type: str = "nvarchar",
    nullable: bool = True,
    pos: int = 1,
) -> ColumnInfo:
    return ColumnInfo(
        name=name,
        data_type=data_type,
        nullable=nullable,
        ordinal_position=pos,
    )


def _build_synthetic_ecommerce_schema(with_fks: bool = True) -> DatabaseSchema:
    customers = TableInfo(
        schema_name="sales",
        table_name="customers",
        columns=[
            _make_col("customer_id", "int", False, 1),
            _make_col("customer_name", "nvarchar", False, 2),
            _make_col("email", "nvarchar", True, 3),
        ],
        primary_key_columns=["customer_id"],
    )

    orders = TableInfo(
        schema_name="sales",
        table_name="orders",
        columns=[
            _make_col("order_id", "int", False, 1),
            _make_col("customer_id", "int", False, 2),
            _make_col("order_date", "datetime", False, 3),
            _make_col("total_amount", "decimal", True, 4),
        ],
        primary_key_columns=["order_id"],
    )

    order_items = TableInfo(
        schema_name="sales",
        table_name="order_items",
        columns=[
            _make_col("order_item_id", "int", False, 1),
            _make_col("order_id", "int", False, 2),
            _make_col("product_id", "int", False, 3),
            _make_col("quantity", "int", False, 4),
        ],
        primary_key_columns=["order_item_id"],
    )

    products = TableInfo(
        schema_name="sales",
        table_name="products",
        columns=[
            _make_col("product_id", "int", False, 1),
            _make_col("product_name", "nvarchar", False, 2),
            _make_col("price", "decimal", False, 3),
        ],
        primary_key_columns=["product_id"],
    )

    audit_logs = TableInfo(
        schema_name="sales",
        table_name="audit_logs",
        columns=[
            _make_col("log_id", "int", False, 1),
            _make_col("action", "nvarchar", True, 2),
        ],
        primary_key_columns=["log_id"],
    )

    fks = []
    if with_fks:
        fks = [
            ForeignKeyInfo(
                constraint_name="FK_orders_customers",
                schema_name="sales",
                table_name="orders",
                column_name="customer_id",
                referenced_schema_name="sales",
                referenced_table_name="customers",
                referenced_column_name="customer_id",
            ),
            ForeignKeyInfo(
                constraint_name="FK_items_orders",
                schema_name="sales",
                table_name="order_items",
                column_name="order_id",
                referenced_schema_name="sales",
                referenced_table_name="orders",
                referenced_column_name="order_id",
            ),
            ForeignKeyInfo(
                constraint_name="FK_items_products",
                schema_name="sales",
                table_name="order_items",
                column_name="product_id",
                referenced_schema_name="sales",
                referenced_table_name="products",
                referenced_column_name="product_id",
            ),
        ]

    return DatabaseSchema(
        tables=[customers, orders, order_items, products, audit_logs],
        foreign_keys=fks,
    )


# =============================================================================
# 1. Declared FK relationship representation
# =============================================================================

def test_declared_fk_relationship_representation():
    schema = _build_synthetic_ecommerce_schema(with_fks=True)
    service = RelationshipService(schema)

    results = service.discover([("sales", "orders"), ("sales", "customers")])
    assert len(results) == 1
    rel = results[0]
    assert rel.relationship_type == "declared_foreign_key"
    assert rel.status == "confirmed"
    assert rel.confidence == 1.0
    assert rel.origin == "declared"
    assert rel.left_table == "orders"
    assert rel.right_table == "customers"


# =============================================================================
# 2. Inferred candidate generic discovery
# =============================================================================

def test_inferred_candidate_generic_discovery():
    schema = _build_synthetic_ecommerce_schema(with_fks=False)
    candidates = discover_relationships(
        schema,
        [("sales", "orders"), ("sales", "customers")],
    )

    assert len(candidates) >= 1
    top = candidates[0]
    assert top.left_column == "customer_id"
    assert top.right_column == "customer_id"
    assert top.confidence >= 0.60
    assert "same column name" in top.reason


# =============================================================================
# 3. Validated inferred relationship becomes part of canonical graph
# =============================================================================

def test_validated_inferred_becomes_canonical_graph_edge():
    graph = RelationshipGraph()
    rel = RelationshipResult(
        relationship_type="inferred",
        status="validated",
        left_schema="sales",
        left_table="orders",
        left_column="customer_id",
        right_schema="sales",
        right_table="customers",
        right_column="customer_id",
        reason="42 distinct values overlap",
        confidence=0.85,
        matching_value_count=42,
    )

    graph.add(rel)
    assert graph.is_connected({("sales", "orders"), ("sales", "customers")})
    neighbors = graph.get_neighbors(("sales", "orders"))
    assert ("sales", "customers") in neighbors


# =============================================================================
# 4. Rejected relationship does not become an accepted graph edge
# =============================================================================

def test_rejected_relationship_not_accepted_graph_edge():
    graph = RelationshipGraph()
    rejected_rel = RelationshipResult(
        relationship_type="inferred",
        status="rejected",
        left_schema="sales",
        left_table="orders",
        left_column="customer_id",
        right_schema="sales",
        right_table="audit_logs",
        right_column="log_id",
        reason="No matching values found",
        confidence=0.0,
    )

    graph.add(rejected_rel)
    # Must NOT form a traversable edge
    assert not graph.is_connected({("sales", "orders"), ("sales", "audit_logs")})
    assert len(graph.get_neighbors(("sales", "orders"))) == 0


# =============================================================================
# 5. Insufficient-data relationship representation
# =============================================================================

def test_insufficient_data_relationship_representation():
    rel = RelationshipResult(
        relationship_type="inferred",
        status="insufficient_data",
        left_schema="sales",
        left_table="orders",
        left_column="customer_id",
        right_schema="sales",
        right_table="customers",
        right_column="customer_id",
        reason="One or both tables contain no rows.",
        confidence=0.0,
    )

    assert rel.status == "insufficient_data"
    assert rel.origin == "inferred"

    graph = RelationshipGraph()
    graph.add(rel)
    # Must NOT form a traversable edge
    assert graph.find_shortest_path(("sales", "orders"), ("sales", "customers")) is None


# =============================================================================
# 6. Direct A -> B path
# =============================================================================

def test_direct_a_to_b_path():
    schema = _build_synthetic_ecommerce_schema(with_fks=True)
    service = RelationshipService(schema)

    path = service.find_path(("sales", "orders"), ("sales", "customers"))
    assert path == [("sales", "orders"), ("sales", "customers")]


# =============================================================================
# 7. Bridge A -> Bridge -> B path
# =============================================================================

def test_bridge_a_to_bridge_to_b_path():
    schema = _build_synthetic_ecommerce_schema(with_fks=True)
    service = RelationshipService(schema)

    # Path from orders to products must go through order_items: orders -> order_items -> products
    path = service.find_path(("sales", "orders"), ("sales", "products"))
    assert path == [("sales", "orders"), ("sales", "order_items"), ("sales", "products")]


# =============================================================================
# 8. Disconnected tables detected
# =============================================================================

def test_disconnected_tables_detected():
    schema = _build_synthetic_ecommerce_schema(with_fks=True)
    service = RelationshipService(schema)

    # audit_logs has no relationships with customers
    path = service.find_path(("sales", "customers"), ("sales", "audit_logs"))
    assert path is None
    assert not service.is_connected([("sales", "customers"), ("sales", "audit_logs")])


# =============================================================================
# 9. Multiple possible paths are detected rather than silently guessed
# =============================================================================

def test_multiple_possible_paths_detected():
    graph = RelationshipGraph()

    # Create diamond graph:
    # A -> X -> B
    # A -> Y -> B
    def _make_edge(t1, t2):
        return RelationshipResult(
            relationship_type="inferred",
            status="validated",
            left_schema="dbo",
            left_table=t1,
            left_column="id",
            right_schema="dbo",
            right_table=t2,
            right_column="id",
            reason="test",
            confidence=0.9,
        )

    graph.add(_make_edge("tbl_a", "tbl_x"))
    graph.add(_make_edge("tbl_x", "tbl_b"))
    graph.add(_make_edge("tbl_a", "tbl_y"))
    graph.add(_make_edge("tbl_y", "tbl_b"))

    paths = graph.find_all_paths(("dbo", "tbl_a"), ("dbo", "tbl_b"), max_depth=2)
    assert len(paths) == 2
    path_tables = [[t[1] for t in p] for p in paths]
    assert ["tbl_a", "tbl_x", "tbl_b"] in path_tables
    assert ["tbl_a", "tbl_y", "tbl_b"] in path_tables


# =============================================================================
# 10. TableSelector consumes the canonical relationship graph
# =============================================================================

def test_table_selector_consumes_canonical_relationship_graph():
    schema = _build_synthetic_ecommerce_schema(with_fks=True)
    service = RelationshipService(schema)

    initial_selected = [
        {"schema": "sales", "table": "orders", "score": 50},
        {"schema": "sales", "table": "products", "score": 40},
    ]

    # Directly pass RelationshipGraph to expand_selected_tables_by_relationships
    expanded = expand_selected_tables_by_relationships(
        initial_selected,
        service.get_graph(),
    )

    expanded_tables = [item["table"] for item in expanded]
    assert "orders" in expanded_tables
    assert "products" in expanded_tables
    assert "order_items" in expanded_tables  # Bridge table successfully added!


# =============================================================================
# 11. TableSelector does not independently rediscover relationships
# =============================================================================

def test_table_selector_reuses_provided_relationship_service():
    schema = _build_synthetic_ecommerce_schema(with_fks=True)
    mock_service = MagicMock(spec=RelationshipDiscoveryService)
    mock_graph = RelationshipGraph()
    # Add FKs to graph
    for fk in schema.foreign_keys:
        mock_graph.add(RelationshipResult(
            relationship_type="declared_foreign_key",
            status="confirmed",
            left_schema=fk.schema_name,
            left_table=fk.table_name,
            left_column=fk.column_name,
            right_schema=fk.referenced_schema_name,
            right_table=fk.referenced_table_name,
            right_column=fk.referenced_column_name,
            reason="FK",
            confidence=1.0,
        ))
    mock_service.get_graph.return_value = mock_graph
    mock_service.is_connected.return_value = True

    selected = select_tables(
        question="orders and products",
        schema=schema.tables,
        max_tables=5,
        relationship_service=mock_service,
    )

    mock_service.get_graph.assert_called()


# =============================================================================
# 12. JoinValidator consumes canonical relationship knowledge
# =============================================================================

def test_join_validator_consumes_canonical_relationship_knowledge():
    schema = _build_synthetic_ecommerce_schema(with_fks=True)
    service = RelationshipService(schema)

    # Valid join: orders -> customers on customer_id
    valid_plan = QueryPlan(
        intent="lookup",
        target_columns=["customer_name", "total_amount"],
        joins=[
            QueryJoin(
                left_schema="sales",
                left_table="orders",
                left_column="customer_id",
                right_schema="sales",
                right_table="customers",
                right_column="customer_id",
                join_type="inner",
            )
        ],
    )

    res = validate_query_plan_joins(valid_plan, schema, relationship_service=service)
    assert res.valid is True
    assert not res.errors

    # Invalid join: orders -> audit_logs
    invalid_plan = QueryPlan(
        intent="lookup",
        target_columns=["action"],
        joins=[
            QueryJoin(
                left_schema="sales",
                left_table="orders",
                left_column="order_id",
                right_schema="sales",
                right_table="audit_logs",
                right_column="log_id",
                join_type="inner",
            )
        ],
    )

    res_invalid = validate_query_plan_joins(invalid_plan, schema, relationship_service=service)
    assert res_invalid.valid is False
    assert any("not validated" in err for err in res_invalid.errors)


# =============================================================================
# 13. Relationship knowledge is reused on repeated queries
# =============================================================================

def test_relationship_knowledge_reused_on_repeated_queries():
    schema = _build_synthetic_ecommerce_schema(with_fks=False)

    with tempfile.TemporaryDirectory() as tmp_dir:
        cache = RelationshipCache(
            cache_dir=tmp_dir,
            server_name="test_srv",
            database_name="test_db",
            schema_fingerprint="fp123",
        )

        service = RelationshipService(schema, cache=cache)

        mock_val = RelationshipValidation(
            candidate=RelationshipCandidate(
                left_schema="sales",
                left_table="orders",
                left_column="customer_id",
                right_schema="sales",
                right_table="customers",
                right_column="customer_id",
                reason="matching id",
                confidence=0.85,
            ),
            left_row_count=100,
            right_row_count=50,
            left_distinct_count=40,
            right_distinct_count=50,
            matching_value_count=35,
            status="validated",
            reason="35 distinct values overlap",
        )

        with patch("app.database.relationship_service.validate_relationship", return_value=mock_val) as mock_validate:
            # First query: validates and caches
            res1 = service.discover([("sales", "orders"), ("sales", "customers")])
            assert len(res1) == 1
            assert mock_validate.call_count == 1

            # Second query: must hit cache, 0 SQL validation calls!
            res2 = service.discover([("sales", "orders"), ("sales", "customers")])
            assert len(res2) == 1
            assert mock_validate.call_count == 1  # Not incremented!


# =============================================================================
# 14. Schema fingerprint change invalidates incompatible cache
# =============================================================================

def test_schema_fingerprint_change_invalidates_cache():
    schema = _build_synthetic_ecommerce_schema(with_fks=False)

    with tempfile.TemporaryDirectory() as tmp_dir:
        # Cache saved under fp_v1
        cache_v1 = RelationshipCache(
            cache_dir=tmp_dir,
            server_name="srv",
            database_name="db",
            schema_fingerprint="fp_v1",
        )
        rel = RelationshipResult(
            relationship_type="inferred",
            status="validated",
            left_schema="sales",
            left_table="orders",
            left_column="customer_id",
            right_schema="sales",
            right_table="customers",
            right_column="customer_id",
            reason="overlap",
            confidence=0.8,
        )
        cache_v1.set(rel)
        cache_v1.save()

        # Load with new fingerprint fp_v2
        cache_v2 = RelationshipCache(
            cache_dir=tmp_dir,
            server_name="srv",
            database_name="db",
            schema_fingerprint="fp_v2",
        )

        assert cache_v2.get("sales", "orders", "customer_id", "sales", "customers", "customer_id") is None


# =============================================================================
# 15. Semantic cache hit does not cause redundant discovery
# =============================================================================

def test_semantic_cache_hit_does_not_cause_redundant_discovery():
    schema = _build_synthetic_ecommerce_schema(with_fks=True)
    mock_service = MagicMock(spec=RelationshipDiscoveryService)
    mock_graph = RelationshipGraph()
    mock_service.get_graph.return_value = mock_graph
    mock_service.discover.return_value = []

    mock_cache = MagicMock()
    cached_plan = QueryPlan(
        intent="lookup",
        target_columns=["customer_name"],
        confidence=1.0,
    )
    mock_cache.get.return_value = cached_plan

    mock_executor = MagicMock()
    mock_executor.execute.return_value = [{"customer_name": "Alice"}]

    with patch("app.database.metadata_service.DatabaseMetadataService.load") as mock_load:
        mock_meta = MagicMock()
        mock_meta.server_name = "srv"
        mock_meta.database_name = "db"
        mock_meta.schema_fingerprint = "fp"
        mock_load.return_value = mock_meta

        service = DatabaseQueryService(
            database_schema=schema,
            semantic_cache=mock_cache,
            executor=mock_executor,
            relationship_service=mock_service,
        )

        result = service.answer("customers")
        assert result.data == [{"customer_name": "Alice"}]
        # Service discover was NOT called because plan has no joins
        mock_service.discover.assert_not_called()


# =============================================================================
# 16. Bounded candidate discovery prevents O(N^2) evaluation on large schemas
# =============================================================================

def test_no_exhaustive_all_table_pair_discovery_on_large_schema():
    # Build schema with 67 tables
    tables = []
    # 2 tables that share an identifier column 'site_id'
    t1 = TableInfo(
        schema_name="dbo",
        table_name="sites",
        columns=[_make_col("site_id", "int", False, 1), _make_col("site_name", "nvarchar", False, 2)],
        primary_key_columns=["site_id"],
    )
    t2 = TableInfo(
        schema_name="dbo",
        table_name="site_analytics",
        columns=[_make_col("site_id", "int", False, 1), _make_col("visits", "int", False, 2)],
        primary_key_columns=["site_id"],
    )
    tables.extend([t1, t2])

    # 65 other tables with unique unrelated identifiers
    for i in range(3, 68):
        tables.append(
            TableInfo(
                schema_name="dbo",
                table_name=f"unrelated_table_{i}",
                columns=[_make_col(f"unique_col_{i}_id", "int", False, 1), _make_col("val", "nvarchar", True, 2)],
                primary_key_columns=[f"unique_col_{i}_id"],
            )
        )

    large_schema = DatabaseSchema(tables=tables)
    all_table_keys = [(t.schema_name, t.table_name) for t in tables]

    # Bounded candidate discovery
    candidates = discover_bounded_candidates(
        large_schema,
        selected_tables=all_table_keys,
    )

    # Instead of evaluating 67*66/2 = 2211 pairs, only the pair sharing 'site_id' matches!
    assert len(candidates) == 1
    assert candidates[0].left_table in {"sites", "site_analytics"}
    assert candidates[0].right_table in {"sites", "site_analytics"}
