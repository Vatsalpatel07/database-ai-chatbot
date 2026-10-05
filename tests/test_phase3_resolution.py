from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest

from app.database.schema import (
    ColumnInfo,
    ColumnResolution,
    DatabaseSchema,
    ResolvedColumn,
    TableInfo,
    parse_column_reference,
)
from app.database.sql_executor import (
    SQLQueryExecutionError,
    SQLQueryExecutor,
)
from app.database.query_service import (
    DatabaseQueryService,
    DatabaseQueryServiceError,
)
from app.query.schema import (
    QueryColumn,
    QueryFilter,
    QueryJoin,
    QueryPlan,
)
from app.query.validator import QueryPlanValidator


# =============================================================================
# Generic synthetic fixtures
# =============================================================================

def _build_test_schema() -> DatabaseSchema:
    table_orders = TableInfo(
        schema_name="sales",
        table_name="orders",
        columns=[
            ColumnInfo("order_id", "int", False, 1),
            ColumnInfo("customer_id", "int", False, 2),
            ColumnInfo("amount", "decimal", False, 3),
            ColumnInfo("order_date", "datetime", False, 4),
            ColumnInfo("status", "varchar", True, 5),
        ],
        primary_key_columns=["order_id"],
    )
    table_customers = TableInfo(
        schema_name="sales",
        table_name="customers",
        columns=[
            ColumnInfo("customer_id", "int", False, 1),
            ColumnInfo("customer_name", "varchar", False, 2),
            ColumnInfo("status", "varchar", True, 3),
        ],
        primary_key_columns=["customer_id"],
    )
    table_items = TableInfo(
        schema_name="inventory",
        table_name="items",
        columns=[
            ColumnInfo("item_id", "int", False, 1),
            ColumnInfo("item_name", "varchar", False, 2),
            ColumnInfo("price", "decimal", False, 3),
        ],
        primary_key_columns=["item_id"],
    )
    return DatabaseSchema(
        tables=[table_orders, table_customers, table_items],
        foreign_keys=[],
    )


# =============================================================================
# 1. Unique unqualified column resolves correctly
# =============================================================================

def test_unique_unqualified_column_resolution():
    schema = _build_test_schema()

    # order_id exists only in sales.orders
    res1 = schema.resolve_column("order_id")
    assert res1.resolved is not None
    assert res1.resolved.table_name == "orders"
    assert res1.resolved.schema_name == "sales"
    assert res1.resolved.column_name == "order_id"
    assert res1.is_ambiguous is False
    assert res1.error is None

    # customer_name exists only in sales.customers
    res2 = schema.resolve_column("customer_name")
    assert res2.resolved is not None
    assert res2.resolved.table_name == "customers"
    assert res2.resolved.column_name == "customer_name"
    assert res2.is_ambiguous is False

    # item_name exists only in inventory.items
    res3 = schema.resolve_column("item_name")
    assert res3.resolved is not None
    assert res3.resolved.schema_name == "inventory"
    assert res3.resolved.table_name == "items"
    assert res3.resolved.column_name == "item_name"


# =============================================================================
# 2. Duplicate unqualified column across multiple tables raises ambiguity
# =============================================================================

def test_duplicate_unqualified_column_ambiguity():
    schema = _build_test_schema()

    # customer_id is present in both sales.orders and sales.customers
    res = schema.resolve_column("customer_id")
    assert res.resolved is None
    assert res.is_ambiguous is True
    assert len(res.matching_tables) == 2
    assert ("sales", "orders") in res.matching_tables
    assert ("sales", "customers") in res.matching_tables
    assert "ambiguous across multiple selected tables" in res.error

    # Validator must reject a plan using ambiguous unqualified column
    validator = QueryPlanValidator()
    plan = QueryPlan(
        intent="lookup",
        target_columns=["customer_id"],
        confidence=0.9,
    )
    result = validator.validate(plan, schema)
    assert result.valid is False
    assert any("ambiguous across multiple selected tables" in err for err in result.errors)


# =============================================================================
# 3. Table-qualified column resolves unambiguously
# =============================================================================

def test_table_qualified_column_resolution():
    schema = _build_test_schema()

    # orders.customer_id
    res_orders = schema.resolve_column("orders.customer_id")
    assert res_orders.resolved is not None
    assert res_orders.resolved.table_name == "orders"
    assert res_orders.resolved.column_name == "customer_id"
    assert res_orders.is_ambiguous is False

    # customers.customer_id
    res_cust = schema.resolve_column("customers.customer_id")
    assert res_cust.resolved is not None
    assert res_cust.resolved.table_name == "customers"
    assert res_cust.resolved.column_name == "customer_id"
    assert res_cust.is_ambiguous is False

    # Bracket-quoted identifiers
    res_bracket = schema.resolve_column("[orders].[customer_id]")
    assert res_bracket.resolved is not None
    assert res_bracket.resolved.table_name == "orders"

    # Validator accepts table-qualified columns
    validator = QueryPlanValidator()
    plan = QueryPlan(
        intent="lookup",
        target_columns=["orders.customer_id", "customers.customer_id"],
        confidence=0.9,
    )
    result = validator.validate(plan, schema)
    assert result.valid is True
    assert result.errors == []


# =============================================================================
# 4. Schema-qualified column resolves unambiguously
# =============================================================================

def test_schema_qualified_column_resolution():
    schema = _build_test_schema()

    # sales.orders.customer_id
    res = schema.resolve_column("sales.orders.customer_id")
    assert res.resolved is not None
    assert res.resolved.schema_name == "sales"
    assert res.resolved.table_name == "orders"
    assert res.resolved.column_name == "customer_id"

    # [sales].[orders].[customer_id]
    res_b = schema.resolve_column("[sales].[orders].[customer_id]")
    assert res_b.resolved is not None
    assert res_b.resolved.table_name == "orders"

    # inventory.items.price
    res_item = schema.resolve_column("inventory.items.price")
    assert res_item.resolved is not None
    assert res_item.resolved.schema_name == "inventory"
    assert res_item.resolved.table_name == "items"
    assert res_item.resolved.column_name == "price"

    validator = QueryPlanValidator()
    plan = QueryPlan(
        intent="lookup",
        target_columns=["sales.orders.order_id", "inventory.items.price"],
        confidence=0.9,
    )
    result = validator.validate(plan, schema)
    assert result.valid is True


# =============================================================================
# 5. Explicit target_column_refs resolves duplicate column names
# =============================================================================

def test_explicit_target_column_refs_resolution():
    schema = _build_test_schema()

    refs = [
        QueryColumn(schema="sales", table="orders", column="customer_id"),
    ]
    res = schema.resolve_column("customer_id", explicit_refs=refs)
    assert res.resolved is not None
    assert res.resolved.table_name == "orders"
    assert res.resolved.column_name == "customer_id"
    assert res.is_ambiguous is False

    # Validator accepts ambiguous column name when target_column_refs provides resolution
    validator = QueryPlanValidator()
    plan = QueryPlan(
        intent="lookup",
        target_columns=["customer_id"],
        target_column_refs=[
            QueryColumn(schema="sales", table="customers", column="customer_id")
        ],
        confidence=0.9,
    )
    result = validator.validate(plan, schema)
    assert result.valid is True
    assert result.errors == []


# =============================================================================
# 6. Explicit group_by_refs resolves duplicate column names
# =============================================================================

def test_explicit_group_by_refs_resolution():
    schema = _build_test_schema()

    # status is in orders and customers
    refs = [
        QueryColumn(schema="sales", table="orders", column="status"),
    ]
    res = schema.resolve_column("status", explicit_refs=refs)
    assert res.resolved is not None
    assert res.resolved.table_name == "orders"

    validator = QueryPlanValidator()
    plan = QueryPlan(
        intent="aggregation",
        target_columns=["amount"],
        group_by=["status"],
        group_by_refs=[
            QueryColumn(schema="sales", table="orders", column="status")
        ],
        aggregation="sum",
        confidence=0.9,
    )
    result = validator.validate(plan, schema)
    assert result.valid is True
    assert result.errors == []


# =============================================================================
# 7. JOIN column identity preserved across JOIN graph
# =============================================================================

def test_join_column_identity_preserved():
    schema = _build_test_schema()
    validator = QueryPlanValidator()

    plan = QueryPlan(
        intent="lookup",
        target_columns=["orders.order_id", "customers.customer_name"],
        target_column_refs=[
            QueryColumn(schema="sales", table="orders", column="order_id"),
            QueryColumn(schema="sales", table="customers", column="customer_name"),
        ],
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
        confidence=0.9,
    )
    result = validator.validate(plan, schema)
    assert result.valid is True


# =============================================================================
# 8. Non-existent column on valid table raises clear error
# =============================================================================

def test_nonexistent_column_on_valid_table_error():
    schema = _build_test_schema()

    res = schema.resolve_column("orders.nonexistent_field")
    assert res.resolved is None
    assert res.is_ambiguous is False
    assert "does not exist on table 'orders'" in res.error

    validator = QueryPlanValidator()
    plan = QueryPlan(
        intent="lookup",
        target_columns=["orders.nonexistent_field"],
        confidence=0.9,
    )
    result = validator.validate(plan, schema)
    assert result.valid is False
    assert any("does not exist" in err for err in result.errors)


# =============================================================================
# 9. Non-existent table in qualified reference raises clear error
# =============================================================================

def test_nonexistent_table_error():
    schema = _build_test_schema()

    res = schema.resolve_column("nonexistent_table.order_id")
    assert res.resolved is None
    assert "Table 'nonexistent_table' does not exist" in res.error

    validator = QueryPlanValidator()
    plan = QueryPlan(
        intent="lookup",
        target_columns=["nonexistent_table.order_id"],
        confidence=0.9,
    )
    result = validator.validate(plan, schema)
    assert result.valid is False
    assert any("Table 'nonexistent_table' does not exist" in err for err in result.errors)


# =============================================================================
# 10. SQL generation with duplicate column names in multi-table queries
# =============================================================================

def test_sql_generation_duplicate_column_names_joined_query():
    schema = _build_test_schema()
    executor = SQLQueryExecutor()

    # Plan targets customer_id from both orders and customers
    plan = QueryPlan(
        intent="lookup",
        target_columns=["orders.customer_id", "customers.customer_id"],
        target_column_refs=[
            QueryColumn(schema="sales", table="orders", column="customer_id"),
            QueryColumn(schema="sales", table="customers", column="customer_id"),
        ],
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
        confidence=0.9,
    )

    captured_sql = {}
    with patch("app.database.sql_executor.get_connection") as mock_conn:
        mock_cursor = MagicMock()
        mock_cursor.description = [("orders.customer_id",), ("customers.customer_id",)]
        mock_cursor.fetchall.return_value = [(101, 101)]
        mock_conn.return_value.__enter__.return_value.cursor.return_value = mock_cursor

        def fake_execute(sql, params):
            captured_sql["sql"] = sql
            captured_sql["params"] = params

        mock_cursor.execute.side_effect = fake_execute

        results = executor.execute(
            plan=plan,
            table=schema.tables[0],
            tables=schema.tables,
        )

        sql = captured_sql["sql"]
        # Verify aliases t1 and t2 are used appropriately and customer_id is selected from both
        assert "t1.[customer_id] AS [orders.customer_id]" in sql
        assert "t2.[customer_id] AS [customers.customer_id]" in sql
        assert "INNER JOIN [sales].[customers] AS t2 ON t1.[customer_id] = t2.[customer_id]" in sql


# =============================================================================
# 11. Single-table resolution with qualified and unqualified names
# =============================================================================

def test_single_table_resolution_in_query_service():
    schema = _build_test_schema()
    tables = [schema.get_table("sales", "orders"), schema.get_table("sales", "customers")]

    # 1. Table-qualified column in target_columns resolves to that table
    plan1 = QueryPlan(
        intent="lookup",
        target_columns=["orders.customer_id"],
        confidence=0.9,
    )
    resolved_tbl1 = DatabaseQueryService._resolve_single_execution_table_for_plan(plan1, tables)
    assert resolved_tbl1.table_name == "orders"

    # 2. Explicit target_column_refs resolves to that table
    plan2 = QueryPlan(
        intent="lookup",
        target_columns=["customer_id"],
        target_column_refs=[
            QueryColumn(schema="sales", table="customers", column="customer_id")
        ],
        confidence=0.9,
    )
    resolved_tbl2 = DatabaseQueryService._resolve_single_execution_table_for_plan(plan2, tables)
    assert resolved_tbl2.table_name == "customers"

    # 3. Unqualified ambiguous column raises error
    plan3 = QueryPlan(
        intent="lookup",
        target_columns=["customer_id"],
        confidence=0.9,
    )
    with pytest.raises(DatabaseQueryServiceError, match="ambiguous across multiple selected tables"):
        DatabaseQueryService._resolve_single_execution_table_for_plan(plan3, tables)

    # 4. Unqualified unique column resolves unambiguously
    plan4 = QueryPlan(
        intent="lookup",
        target_columns=["amount"],
        confidence=0.9,
    )
    resolved_tbl4 = DatabaseQueryService._resolve_single_execution_table_for_plan(plan4, tables)
    assert resolved_tbl4.table_name == "orders"


# =============================================================================
# 12. Single-table executor translates qualified columns safely
# =============================================================================

def test_single_table_executor_translates_qualified_columns():
    schema = _build_test_schema()
    orders_table = schema.get_table("sales", "orders")
    executor = SQLQueryExecutor()

    plan = QueryPlan(
        intent="lookup",
        target_columns=["orders.amount"],
        filters=[
            QueryFilter(column="orders.order_id", operator="equals", value=42),
        ],
        sort_column="orders.order_date",
        sort_direction="desc",
        confidence=0.9,
    )

    captured_sql = {}
    with patch("app.database.sql_executor.get_connection") as mock_conn:
        mock_cursor = MagicMock()
        mock_cursor.description = [("orders.amount",)]
        mock_cursor.fetchall.return_value = [(99.95,)]
        mock_conn.return_value.__enter__.return_value.cursor.return_value = mock_cursor

        def fake_execute(sql, params):
            captured_sql["sql"] = sql
            captured_sql["params"] = params

        mock_cursor.execute.side_effect = fake_execute

        executor.execute(plan=plan, table=orders_table)

        sql = captured_sql["sql"]
        # Must strip table prefix from column access: [amount] AS [orders.amount] and WHERE [order_id] = ?
        assert "[amount] AS [orders.amount]" in sql
        assert "WHERE [order_id] = ?" in sql
        assert "ORDER BY [order_date] DESC" in sql
        assert "[orders.amount]" not in sql.split(" AS ")[0]
