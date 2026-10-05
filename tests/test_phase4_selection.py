from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest

from app.database.entity_resolver import EntityResolver, EntityCandidate, EntityResolutionResult
from app.database.schema import (
    ColumnInfo,
    DatabaseSchema,
    ForeignKeyInfo,
    TableInfo,
)
from app.database.schema_intelligence import DatabaseSchemaIntelligence
from app.database.table_selector import (
    score_table,
    select_tables,
    expand_selected_tables_by_relationships,
)
from app.database.query_service import (
    DatabaseQueryService,
    DatabaseQueryServiceError,
)
from app.query.analyzer import QuestionAnalyzer
from app.query.schema import QueryColumn, QueryFilter, QueryPlan


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


def _build_ecommerce_schema() -> DatabaseSchema:
    """
    Build a generic multi-table schema representing an ecommerce domain:
    - customers
    - orders (has order_date, customer_id)
    - order_items (bridge table between orders and products)
    - products
    - audit_logs (wide table with 15 date/status/id columns)
    """
    customers = TableInfo(
        schema_name="sales",
        table_name="customers",
        columns=[
            _make_col("customer_id", "int", False, 1),
            _make_col("customer_name", "nvarchar", False, 2),
            _make_col("email", "nvarchar", True, 3),
            _make_col("status", "nvarchar", True, 4),
        ],
        primary_key_columns=["customer_id"],
    )

    orders = TableInfo(
        schema_name="sales",
        table_name="orders",
        columns=[
            _make_col("order_id", "int", False, 1),
            _make_col("order_date", "datetime", False, 2),
            _make_col("order_status", "nvarchar", True, 3),
            _make_col("customer_id", "int", False, 4),
            _make_col("total_amount", "decimal", False, 5),
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
            _make_col("unit_price", "decimal", False, 5),
        ],
        primary_key_columns=["order_item_id"],
    )

    products = TableInfo(
        schema_name="sales",
        table_name="products",
        columns=[
            _make_col("product_id", "int", False, 1),
            _make_col("product_name", "nvarchar", False, 2),
            _make_col("category", "nvarchar", True, 3),
            _make_col("price", "decimal", False, 4),
        ],
        primary_key_columns=["product_id"],
    )

    # Wide table with 12 date/status/audit columns designed to test column capping
    audit_columns = [_make_col("log_id", "int", False, 1)]
    for i in range(2, 14):
        audit_columns.append(_make_col(f"log_date_{i}", "datetime", True, i))
    audit_columns.append(_make_col("order_id", "int", True, 14))
    audit_columns.append(_make_col("audit_status", "nvarchar", True, 15))

    audit_logs = TableInfo(
        schema_name="sales",
        table_name="audit_logs",
        columns=audit_columns,
        primary_key_columns=["log_id"],
    )

    foreign_keys = [
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
            constraint_name="FK_order_items_orders",
            schema_name="sales",
            table_name="order_items",
            column_name="order_id",
            referenced_schema_name="sales",
            referenced_table_name="orders",
            referenced_column_name="order_id",
        ),
        ForeignKeyInfo(
            constraint_name="FK_order_items_products",
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
        foreign_keys=foreign_keys,
    )


# =============================================================================
# 1. EntityResolver useful capabilities: compound matching & column capping
# =============================================================================

def test_entity_resolver_compound_matching():
    schema = _build_ecommerce_schema()
    resolver = EntityResolver(schema)

    # "order date" should resolve to orders table with compound evidence
    result = resolver.resolve("order date", limit=3)
    assert len(result.candidates) > 0
    top = result.candidates[0]
    assert top.table_name == "orders"
    assert any("compound" in ev for ev in top.evidence)


def test_entity_resolver_column_capping_prevents_wide_table_takeover():
    schema = _build_ecommerce_schema()
    resolver = EntityResolver(schema)

    # Query with multiple date/log terms. The orders table should still outscore
    # or score properly against the wide audit_logs table.
    result = resolver.resolve("order date", limit=5)
    orders_cand = next((c for c in result.candidates if c.table_name == "orders"), None)
    audit_cand = next((c for c in result.candidates if c.table_name == "audit_logs"), None)

    assert orders_cand is not None
    if audit_cand is not None:
        assert orders_cand.score > audit_cand.score


# =============================================================================
# 2. score_table and DatabaseSchemaIntelligence column evidence capping
# =============================================================================

def test_score_table_column_evidence_capped():
    schema = _build_ecommerce_schema()
    audit_logs = schema.get_table("sales", "audit_logs")
    assert audit_logs is not None

    # Even though question tokens match all 12 date columns in audit_logs,
    # column evidence must be capped at MAX_COLUMN_EVIDENCE = 12.
    question = "date date log date"
    score = score_table(question, audit_logs)
    # table_name tokens match "log" (10 + ratio), and columns match "date" and "log"
    # Column contribution cannot exceed 12.
    assert score <= 32


def test_schema_intelligence_score_table_capped():
    schema = _build_ecommerce_schema()
    intel = DatabaseSchemaIntelligence(schema)
    audit_logs = schema.get_table("sales", "audit_logs")

    score = intel.score_table("date log", audit_logs)
    # Verifies capped score does not blow up uncontrollably
    assert score < 50


# =============================================================================
# 3. TableSelector with integrated EntityResolver
# =============================================================================

def test_select_tables_integrates_entity_resolver():
    schema = _build_ecommerce_schema()
    resolver = EntityResolver(schema)

    # "customer email" compound phrase should strongly pick customers
    selected = select_tables(
        question="customer email",
        schema=schema.tables,
        max_tables=3,
        entity_resolver=resolver,
    )
    assert len(selected) > 0
    assert selected[0]["table"] == "customers"
    assert selected[0]["score"] >= 20


def test_select_tables_auto_instantiates_entity_resolver():
    schema = _build_ecommerce_schema()

    # Even without passing entity_resolver explicitly, select_tables should
    # auto-instantiate it and accurately resolve compound phrases.
    selected = select_tables(
        question="order date",
        schema=schema.tables,
        max_tables=3,
    )
    assert len(selected) > 0
    assert selected[0]["table"] == "orders"


def test_select_tables_wide_table_does_not_beat_entity_table():
    schema = _build_ecommerce_schema()

    # "Show me orders by date"
    selected = select_tables(
        question="Show me orders by date",
        schema=schema.tables,
        max_tables=5,
    )
    table_names = [item["table"] for item in selected]
    assert "orders" in table_names
    orders_rank = table_names.index("orders")
    if "audit_logs" in table_names:
        audit_rank = table_names.index("audit_logs")
        assert orders_rank < audit_rank, "orders should rank higher than audit_logs"


# =============================================================================
# 4. TableSelector relationship expansion (bridge tables)
# =============================================================================

def test_select_tables_relationship_expansion_adds_bridge_table():
    schema = _build_ecommerce_schema()

    # Query mentions customers and products, but NOT orders or order_items.
    # Relationship path: customers <-> orders <-> order_items <-> products
    selected = select_tables(
        question="customers and products",
        schema=schema.tables,
        max_tables=2,
        relationships=schema.foreign_keys,
    )

    names = {item["table"] for item in selected}
    assert "customers" in names
    assert "products" in names
    # Bridge tables orders and order_items should be added
    assert "orders" in names
    assert "order_items" in names

    # Intermediate tables must have relationship_required = True and score = 0
    bridge_item = next(item for item in selected if item["table"] == "order_items")
    assert bridge_item["relationship_required"] is True
    assert bridge_item["score"] == 0


# =============================================================================
# 5. QuestionAnalyzer avoids duplicate table selection & preserves bridge tables
# =============================================================================

def test_question_analyzer_preserves_bridge_tables_without_duplicate_selection():
    schema = _build_ecommerce_schema()

    # Prepare an execution schema that contains bridge table order_items with score: 0
    execution_tables = [
        schema.get_table("sales", "customers"),
        schema.get_table("sales", "orders"),
        schema.get_table("sales", "order_items"),
        schema.get_table("sales", "products"),
    ]
    execution_schema = DatabaseSchema(
        tables=execution_tables,
        foreign_keys=schema.foreign_keys,
    )
    execution_schema.is_execution_schema = True

    analyzer = QuestionAnalyzer(client=MagicMock())

    # Mock the LLM client to return valid QueryPlan JSON
    mock_json = """
    {
        "intent": "lookup",
        "target_columns": ["customers.customer_name", "products.product_name"],
        "confidence": 0.95
    }
    """
    analyzer.client.generate_json.return_value = mock_json

    # Mock _select_database_tables to detect if it gets incorrectly called
    with patch.object(analyzer, "_select_database_tables") as mock_select:
        plan = analyzer.analyze(
            question="customers and products",
            semantic_schema=execution_schema,
        )

        # _select_database_tables MUST NOT be called because execution_schema is already scoped!
        mock_select.assert_not_called()
        assert plan.intent == "lookup"


def test_question_analyzer_falls_back_to_select_tables_on_large_schema():
    # Create a schema with > 5 tables without is_execution_schema
    tables = [
        TableInfo(schema_name="dbo", table_name=f"t_{i}", columns=[_make_col("id", "int", False)])
        for i in range(8)
    ]
    large_schema = DatabaseSchema(tables=tables)

    analyzer = QuestionAnalyzer(client=MagicMock())
    analyzer.client.generate_json.return_value = '{"intent": "lookup", "confidence": 0.8}'

    with patch.object(
        analyzer,
        "_select_database_tables",
        return_value=[tables[0]],
    ) as mock_select:
        analyzer.analyze(
            question="show t_0",
            semantic_schema=large_schema,
        )
        mock_select.assert_called_once()


# =============================================================================
# 6. DatabaseQueryService table resolution and wiring
# =============================================================================

def test_query_service_initializes_entity_resolver():
    schema = _build_ecommerce_schema()
    with patch("app.database.metadata_service.DatabaseMetadataService.load") as mock_load:
        mock_meta = MagicMock()
        mock_meta.server_name = "test_server"
        mock_meta.database_name = "test_db"
        mock_meta.schema_fingerprint = "fp123"
        mock_load.return_value = mock_meta

        service = DatabaseQueryService(database_schema=schema)
        assert hasattr(service, "entity_resolver")
        assert isinstance(service.entity_resolver, EntityResolver)


def test_query_service_build_execution_schema_marks_is_execution_schema():
    schema = _build_ecommerce_schema()
    with patch("app.database.metadata_service.DatabaseMetadataService.load") as mock_load:
        mock_meta = MagicMock()
        mock_meta.server_name = "test_server"
        mock_meta.database_name = "test_db"
        mock_meta.schema_fingerprint = "fp123"
        mock_load.return_value = mock_meta

        service = DatabaseQueryService(database_schema=schema)
        exec_schema = service._build_execution_schema([schema.get_table("sales", "orders")])
        assert getattr(exec_schema, "is_execution_schema", False) is True


def test_query_service_resolve_execution_tables():
    schema = _build_ecommerce_schema()
    with patch("app.database.metadata_service.DatabaseMetadataService.load") as mock_load:
        mock_meta = MagicMock()
        mock_meta.server_name = "test_server"
        mock_meta.database_name = "test_db"
        mock_meta.schema_fingerprint = "fp123"
        mock_load.return_value = mock_meta

        service = DatabaseQueryService(database_schema=schema)
        resolved_tables = service._resolve_execution_tables("order date")
        assert len(resolved_tables) > 0
        assert any(t.table_name == "orders" for t in resolved_tables)


# =============================================================================
# 7. Ambiguous semantic candidate handling
# =============================================================================

def test_ambiguous_candidate_tables_retained_in_selection():
    # Two tables with identically matching columns and names
    t1 = TableInfo(
        schema_name="dbo",
        table_name="active_orders",
        columns=[_make_col("order_id", "int", False), _make_col("amount", "decimal", False)],
    )
    t2 = TableInfo(
        schema_name="dbo",
        table_name="archived_orders",
        columns=[_make_col("order_id", "int", False), _make_col("amount", "decimal", False)],
    )
    schema = DatabaseSchema(tables=[t1, t2])

    selected = select_tables(
        question="orders amount",
        schema=schema.tables,
        max_tables=2,
    )
    # Both tables should be selected and ranked deterministically
    assert len(selected) == 2
    table_names = [item["table"] for item in selected]
    assert "active_orders" in table_names
    assert "archived_orders" in table_names


# =============================================================================
# 8. Phase 4 Correction Regression Tests
# =============================================================================

def test_generic_compound_entity_selection_event_topics_synthetic():
    """
    Synthetic schema with:
    - dbo.app_event_topics (event_id, topic_id)
    - dbo.app_events (event_id, officer_name, paste_all_chat_messages)
    - dbo.app_topics (topic_id, topic_title)
    
    Verifies dbo.app_event_topics is ranked #1 and app_events does not beat it.
    """
    t_event_topics = TableInfo(
        schema_name="dbo",
        table_name="app_event_topics",
        columns=[
            _make_col("event_id", "int", False, 1),
            _make_col("topic_id", "int", False, 2),
        ],
        primary_key_columns=["event_id", "topic_id"],
    )
    t_events = TableInfo(
        schema_name="dbo",
        table_name="app_events",
        columns=[
            _make_col("event_id", "int", False, 1),
            _make_col("event_title", "nvarchar", False, 2),
            _make_col("officer_name", "nvarchar", True, 3),
            _make_col("paste_all_chat_messages", "nvarchar", True, 4),
        ],
        primary_key_columns=["event_id"],
    )
    t_topics = TableInfo(
        schema_name="dbo",
        table_name="app_topics",
        columns=[
            _make_col("topic_id", "int", False, 1),
            _make_col("topic_title", "nvarchar", False, 2),
        ],
        primary_key_columns=["topic_id"],
    )

    schema = DatabaseSchema(tables=[t_events, t_event_topics, t_topics])

    selected = select_tables(
        question="List column names of event topics",
        schema=schema.tables,
        max_tables=5,
    )

    assert len(selected) > 0
    assert selected[0]["table"] == "app_event_topics"
    assert selected[0]["score"] >= 25


def test_generic_compound_entity_selection_event_staff_synthetic():
    """
    Synthetic schema with:
    - dbo.app_event_staff (event_id, staff_id, staff_role)
    - dbo.app_events (event_id, first_name, last_name)
    """
    t_event_staff = TableInfo(
        schema_name="dbo",
        table_name="app_event_staff",
        columns=[
            _make_col("event_id", "int", False, 1),
            _make_col("staff_id", "int", False, 2),
            _make_col("staff_role", "nvarchar", True, 3),
        ],
        primary_key_columns=["event_id", "staff_id"],
    )
    t_events = TableInfo(
        schema_name="dbo",
        table_name="app_events",
        columns=[
            _make_col("event_id", "int", False, 1),
            _make_col("first_name", "nvarchar", True, 2),
            _make_col("last_name", "nvarchar", True, 3),
        ],
        primary_key_columns=["event_id"],
    )

    schema = DatabaseSchema(tables=[t_events, t_event_staff])

    selected = select_tables(
        question="Show column names of event staff.",
        schema=schema.tables,
        max_tables=5,
    )

    assert len(selected) > 0
    assert selected[0]["table"] == "app_event_staff"


def test_metadata_column_names_request_selects_single_relevant_table():
    """
    When the user requests column names of a specific entity, verify that
    only the single relevant table is selected instead of needlessly pulling
    in unrelated tables.
    """
    schema = _build_ecommerce_schema()

    selected = select_tables(
        question="Show columns of customer orders",
        schema=schema.tables,
        max_tables=5,
    )

    # Must select only orders (1 table), not 5 tables
    assert len(selected) == 1
    assert selected[0]["table"] == "orders"


def test_unsupported_analyzer_result_preserved_and_never_converted_to_column_names():
    """
    When the analyzer returns intent = 'unsupported', verify that _normalize_plan
    preserves 'unsupported' and does NOT convert it into 'column_names' with
    target_columns = [].
    """
    schema = _build_ecommerce_schema()
    analyzer = QuestionAnalyzer(client=MagicMock())

    # DeepSeek returns unsupported with explanation that entity is missing
    raw_response = """
    {
        "intent": "unsupported",
        "explanation": "The table 'flying_unicorns' was not found in the database schema.",
        "confidence": 0.0
    }
    """
    analyzer.client.generate_json.return_value = raw_response

    with patch.object(analyzer, "_get_relationship_context", return_value=[]):
        plan = analyzer.analyze(
            question="List column names of flying unicorns",
            semantic_schema=schema,
        )

    assert plan.intent == "unsupported"
    assert "flying_unicorns" in plan.explanation


def test_query_service_unsupported_plan_returns_explanation_without_sql_execution():
    """
    Verify that DatabaseQueryService.answer returns the unsupported explanation
    without attempting SQL execution against an arbitrary table.
    """
    schema = _build_ecommerce_schema()

    mock_analyzer = MagicMock()
    unsupported_plan = QueryPlan(
        intent="unsupported",
        explanation="The requested entity does not exist in the database.",
        confidence=0.0,
    )
    mock_analyzer.analyze.return_value = unsupported_plan

    mock_executor = MagicMock()

    with patch("app.database.metadata_service.DatabaseMetadataService.load") as mock_load:
        mock_meta = MagicMock()
        mock_meta.server_name = "test_server"
        mock_meta.database_name = "test_db"
        mock_meta.schema_fingerprint = "fp123"
        mock_load.return_value = mock_meta

        service = DatabaseQueryService(
            database_schema=schema,
            analyzer=mock_analyzer,
            executor=mock_executor,
        )

        result = service.answer("List column names of flying unicorns")

        # Unsupported result returned cleanly
        assert result.plan.intent == "unsupported"
        assert "does not exist" in result.data
        # SQL executor MUST NOT be called!
        mock_executor.execute.assert_not_called()

