from __future__ import annotations

import datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch
import uuid
import pytest

from app.conversation.conversation_memory import ConversationMemory
from app.database.join_validator import validate_query_plan_joins
from app.database.metadata_cache import MetadataCache
from app.database.metadata_service import DatabaseMetadata
from app.database.query_service import DatabaseQueryService
from app.database.relationship_cache import RelationshipCache
from app.database.relationship_service import RelationshipResult
from app.database.schema import (
    ColumnInfo,
    ColumnResolution,
    DatabaseSchema,
    ForeignKeyInfo,
    TableInfo,
)
from app.database.semantic_query_cache import SemanticQueryCache
from app.database.sql_executor import (
    SQLQueryExecutionError,
    SQLQueryExecutor,
)
from app.database.table_selector import select_tables
from app.query.analyzer import QuestionAnalyzer
from app.query.answer_generator import AnswerGenerator
from app.query.result_validator import QueryResultValidator
from app.query.schema import (
    QueryColumn,
    QueryFilter,
    QueryJoin,
    QueryPlan,
)
from app.query.validator import (
    QueryPlanValidator,
    ValidationResult,
)


# =============================================================================
# Synthetic Schema Builders
# =============================================================================

def _build_synthetic_sales_schema() -> DatabaseSchema:
    customers = TableInfo(
        schema_name="dbo",
        table_name="customers",
        columns=[
            ColumnInfo("customer_id", "int", False, 1),
            ColumnInfo("name", "nvarchar", True, 2),
            ColumnInfo("balance", "decimal", True, 3),
            ColumnInfo("status", "nvarchar", True, 4),
            ColumnInfo("created_at", "datetime2", True, 5),
            ColumnInfo("guid", "uniqueidentifier", True, 6),
        ],
        primary_key_columns=["customer_id"],
    )
    orders = TableInfo(
        schema_name="dbo",
        table_name="orders",
        columns=[
            ColumnInfo("order_id", "int", False, 1),
            ColumnInfo("customer_id", "int", False, 2),
            ColumnInfo("amount", "decimal", True, 3),
            ColumnInfo("status", "nvarchar", True, 4),
            ColumnInfo("order_date", "datetime2", True, 5),
        ],
        primary_key_columns=["order_id"],
    )
    order_items = TableInfo(
        schema_name="dbo",
        table_name="order_items",
        columns=[
            ColumnInfo("item_id", "int", False, 1),
            ColumnInfo("order_id", "int", False, 2),
            ColumnInfo("product_id", "int", False, 3),
            ColumnInfo("quantity", "int", True, 4),
            ColumnInfo("unit_price", "decimal", True, 5),
        ],
        primary_key_columns=["item_id"],
    )
    products = TableInfo(
        schema_name="dbo",
        table_name="products",
        columns=[
            ColumnInfo("product_id", "int", False, 1),
            ColumnInfo("product_name", "nvarchar", True, 2),
            ColumnInfo("category", "nvarchar", True, 3),
        ],
        primary_key_columns=["product_id"],
    )
    fks = [
        ForeignKeyInfo(
            constraint_name="FK_orders_customers",
            schema_name="dbo",
            table_name="orders",
            column_name="customer_id",
            referenced_schema_name="dbo",
            referenced_table_name="customers",
            referenced_column_name="customer_id",
        ),
        ForeignKeyInfo(
            constraint_name="FK_order_items_orders",
            schema_name="dbo",
            table_name="order_items",
            column_name="order_id",
            referenced_schema_name="dbo",
            referenced_table_name="orders",
            referenced_column_name="order_id",
        ),
        ForeignKeyInfo(
            constraint_name="FK_order_items_products",
            schema_name="dbo",
            table_name="order_items",
            column_name="product_id",
            referenced_schema_name="dbo",
            referenced_table_name="products",
            referenced_column_name="product_id",
        ),
    ]
    return DatabaseSchema(
        tables=[customers, orders, order_items, products],
        foreign_keys=fks,
        unique_constraints=[],
    )


# =============================================================================
# Category A — Basic Database Questions
# =============================================================================

def test_cat_a_01_row_count():
    executor = SQLQueryExecutor()
    schema = _build_synthetic_sales_schema()
    table = schema.get_table("dbo", "customers")
    plan = QueryPlan(intent="row_count")

    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = (142,)
    mock_conn.cursor.return_value = mock_cursor
    mock_conn.__enter__.return_value = mock_conn

    with patch("app.database.sql_executor.get_connection", return_value=mock_conn):
        result = executor.execute(plan, table)
        assert result == 142
        mock_cursor.execute.assert_called_once()
        sql = mock_cursor.execute.call_args[0][0]
        assert "COUNT(*)" in sql
        assert "[dbo].[customers]" in sql


def test_cat_a_02_column_count():
    executor = SQLQueryExecutor()
    schema = _build_synthetic_sales_schema()
    table = schema.get_table("dbo", "customers")
    plan = QueryPlan(intent="column_count")

    result = executor.execute(plan, table)
    assert result == 6


def test_cat_a_03_column_names():
    executor = SQLQueryExecutor()
    schema = _build_synthetic_sales_schema()
    table = schema.get_table("dbo", "customers")
    plan = QueryPlan(intent="column_names")

    result = executor.execute(plan, table)
    assert result == ["customer_id", "name", "balance", "status", "created_at", "guid"]


def test_cat_a_04_show_records():
    executor = SQLQueryExecutor()
    schema = _build_synthetic_sales_schema()
    table = schema.get_table("dbo", "customers")
    plan = QueryPlan(intent="lookup", limit=10)

    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.description = [("customer_id",), ("name",)]
    mock_cursor.fetchall.return_value = [(1, "Alpha"), (2, "Beta")]
    mock_conn.cursor.return_value = mock_cursor
    mock_conn.__enter__.return_value = mock_conn

    with patch("app.database.sql_executor.get_connection", return_value=mock_conn):
        result = executor.execute(plan, table)
        assert len(result) == 2
        assert result[0] == {"customer_id": 1, "name": "Alpha"}
        sql = mock_cursor.execute.call_args[0][0]
        assert "TOP (10)" in sql


def test_cat_a_05_show_specific_column():
    executor = SQLQueryExecutor()
    schema = _build_synthetic_sales_schema()
    table = schema.get_table("dbo", "customers")
    plan = QueryPlan(intent="lookup", target_columns=["name"])

    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.description = [("name",)]
    mock_cursor.fetchall.return_value = [("Alpha",), ("Beta",)]
    mock_conn.cursor.return_value = mock_cursor
    mock_conn.__enter__.return_value = mock_conn

    with patch("app.database.sql_executor.get_connection", return_value=mock_conn):
        result = executor.execute(plan, table)
        assert result == [{"name": "Alpha"}, {"name": "Beta"}]
        sql = mock_cursor.execute.call_args[0][0]
        assert "SELECT [name] FROM [dbo].[customers]" in sql


def test_cat_a_06_show_multiple_columns():
    executor = SQLQueryExecutor()
    schema = _build_synthetic_sales_schema()
    table = schema.get_table("dbo", "customers")
    plan = QueryPlan(intent="lookup", target_columns=["customer_id", "name", "status"])

    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.description = [("customer_id",), ("name",), ("status",)]
    mock_cursor.fetchall.return_value = [(1, "Alpha", "Active")]
    mock_conn.cursor.return_value = mock_cursor
    mock_conn.__enter__.return_value = mock_conn

    with patch("app.database.sql_executor.get_connection", return_value=mock_conn):
        result = executor.execute(plan, table)
        assert result == [{"customer_id": 1, "name": "Alpha", "status": "Active"}]
        sql = mock_cursor.execute.call_args[0][0]
        assert "[customer_id], [name], [status]" in sql


def test_cat_a_07_show_distinct_values():
    executor = SQLQueryExecutor()
    schema = _build_synthetic_sales_schema()
    table = schema.get_table("dbo", "customers")
    plan = QueryPlan(intent="lookup", target_columns=["status"], group_by=["status"])

    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.description = [("status",)]
    mock_cursor.fetchall.return_value = [("Active",), ("Inactive",)]
    mock_conn.cursor.return_value = mock_cursor
    mock_conn.__enter__.return_value = mock_conn

    with patch("app.database.sql_executor.get_connection", return_value=mock_conn):
        result = executor.execute(plan, table)
        assert result == [{"status": "Active"}, {"status": "Inactive"}]


def test_cat_a_08_empty_result():
    executor = SQLQueryExecutor()
    schema = _build_synthetic_sales_schema()
    table = schema.get_table("dbo", "customers")
    plan = QueryPlan(intent="lookup", target_columns=["name"])

    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.description = [("name",)]
    mock_cursor.fetchall.return_value = []
    mock_conn.cursor.return_value = mock_cursor
    mock_conn.__enter__.return_value = mock_conn

    with patch("app.database.sql_executor.get_connection", return_value=mock_conn):
        result = executor.execute(plan, table)
        assert result == []
        assert isinstance(result, list)


# =============================================================================
# Category B — Filtering
# =============================================================================

def test_cat_b_01_comparison_operators():
    executor = SQLQueryExecutor()
    schema = _build_synthetic_sales_schema()
    table = schema.get_table("dbo", "customers")

    operators = [
        ("equals", "=", 10),
        ("not_equals", "<>", 10),
        ("greater_than", ">", 10),
        ("less_than", "<", 10),
        ("greater_than_or_equal", ">=", 10),
        ("less_than_or_equal", "<=", 10),
    ]

    for op, sql_op, val in operators:
        filters = [QueryFilter(column="balance", operator=op, value=val)]
        where_sql, params = executor._build_where_clause(filters, table)
        assert f"[balance] {sql_op} ?" in where_sql
        assert params == [val]


def test_cat_b_02_text_matching_operators():
    executor = SQLQueryExecutor()
    schema = _build_synthetic_sales_schema()
    table = schema.get_table("dbo", "customers")

    # contains
    w1, p1 = executor._build_where_clause([QueryFilter(column="name", operator="contains", value="health")], table)
    assert "[name] LIKE ?" in w1
    assert p1 == ["%health%"]

    # starts_with
    w2, p2 = executor._build_where_clause([QueryFilter(column="name", operator="starts_with", value="Dr.")], table)
    assert "[name] LIKE ?" in w2
    assert p2 == ["Dr.%"]

    # ends_with
    w3, p3 = executor._build_where_clause([QueryFilter(column="name", operator="ends_with", value="Inc.")], table)
    assert "[name] LIKE ?" in w3
    assert p3 == ["%Inc."]


def test_cat_b_03_multiple_filters():
    executor = SQLQueryExecutor()
    schema = _build_synthetic_sales_schema()
    table = schema.get_table("dbo", "customers")

    filters = [
        QueryFilter(column="status", operator="equals", value="Active"),
        QueryFilter(column="balance", operator="greater_than", value=100),
    ]
    where_sql, params = executor._build_where_clause(filters, table)
    assert "WHERE [status] = ? AND [balance] > ?" in where_sql
    assert params == ["Active", 100]


def test_cat_b_04_in_filter():
    executor = SQLQueryExecutor()
    schema = _build_synthetic_sales_schema()
    table = schema.get_table("dbo", "customers")

    filters = [QueryFilter(column="status", operator="in", value=["Active", "Pending"])]
    where_sql, params = executor._build_where_clause(filters, table)
    assert "WHERE [status] IN (?, ?)" in where_sql
    assert params == ["Active", "Pending"]


def test_cat_b_05_parameterization_safety():
    executor = SQLQueryExecutor()
    schema = _build_synthetic_sales_schema()
    table = schema.get_table("dbo", "customers")

    malicious_input = "' OR '1'='1"
    filters = [QueryFilter(column="name", operator="equals", value=malicious_input)]
    where_sql, params = executor._build_where_clause(filters, table)
    assert where_sql == " WHERE [name] = ?"
    assert params == [malicious_input]
    assert "' OR '1'='1" not in where_sql


# =============================================================================
# Category C — Aggregation
# =============================================================================

def test_cat_c_01_scalar_aggregations():
    executor = SQLQueryExecutor()
    schema = _build_synthetic_sales_schema()
    table = schema.get_table("dbo", "orders")

    aggs = [
        ("count", "COUNT(*)"),
        ("sum", "SUM([amount])"),
        ("average", "AVG([amount])"),
        ("min", "MIN([amount])"),
        ("max", "MAX([amount])"),
    ]

    for agg_name, expected_sql_agg in aggs:
        plan = QueryPlan(intent="aggregation", aggregation=agg_name, target_columns=["amount"])
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (500,)
        mock_conn.cursor.return_value = mock_cursor
        mock_conn.__enter__.return_value = mock_conn

        with patch("app.database.sql_executor.get_connection", return_value=mock_conn):
            result = executor.execute(plan, table)
            assert result == 500
            sql = mock_cursor.execute.call_args[0][0]
            assert expected_sql_agg in sql


def test_cat_c_02_grouped_aggregation():
    executor = SQLQueryExecutor()
    schema = _build_synthetic_sales_schema()
    table = schema.get_table("dbo", "orders")
    plan = QueryPlan(
        intent="aggregation",
        aggregation="sum",
        target_columns=["amount"],
        group_by=["status"],
    )

    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.description = [("status",), ("sum",)]
    mock_cursor.fetchall.return_value = [("Active", 1250), ("Completed", 4500)]
    mock_conn.cursor.return_value = mock_cursor
    mock_conn.__enter__.return_value = mock_conn

    with patch("app.database.sql_executor.get_connection", return_value=mock_conn):
        result = executor.execute(plan, table)
        assert result == [{"status": "Active", "sum": 1250}, {"status": "Completed", "sum": 4500}]
        sql = mock_cursor.execute.call_args[0][0]
        assert "GROUP BY [status]" in sql
        assert "SUM([amount])" in sql


def test_cat_c_03_multiple_group_columns():
    executor = SQLQueryExecutor()
    schema = _build_synthetic_sales_schema()
    table = schema.get_table("dbo", "customers")
    plan = QueryPlan(
        intent="aggregation",
        aggregation="count",
        group_by=["status", "name"],
    )

    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.description = [("status",), ("name",), ("count",)]
    mock_cursor.fetchall.return_value = [("Active", "Alpha", 1)]
    mock_conn.cursor.return_value = mock_cursor
    mock_conn.__enter__.return_value = mock_conn

    with patch("app.database.sql_executor.get_connection", return_value=mock_conn):
        result = executor.execute(plan, table)
        assert len(result) == 1
        sql = mock_cursor.execute.call_args[0][0]
        assert "GROUP BY [status], [name]" in sql


def test_cat_c_04_aggregation_with_having_filter():
    executor = SQLQueryExecutor()
    schema = _build_synthetic_sales_schema()
    table = schema.get_table("dbo", "orders")
    plan = QueryPlan(
        intent="aggregation",
        aggregation="count",
        group_by=["status"],
        having_filters=[QueryFilter(column="count", operator="greater_than", value=5)],
    )

    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.description = [("status",), ("count",)]
    mock_cursor.fetchall.return_value = [("Active", 12)]
    mock_conn.cursor.return_value = mock_cursor
    mock_conn.__enter__.return_value = mock_conn

    with patch("app.database.sql_executor.get_connection", return_value=mock_conn):
        result = executor.execute(plan, table)
        assert result == [{"status": "Active", "count": 12}]
        sql = mock_cursor.execute.call_args[0][0]
        assert "HAVING COUNT(*) > ?" in sql


def test_cat_c_05_empty_table_aggregation():
    executor = SQLQueryExecutor()
    schema = _build_synthetic_sales_schema()
    table = schema.get_table("dbo", "orders")
    plan = QueryPlan(intent="aggregation", aggregation="sum", target_columns=["amount"])

    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = (None,)
    mock_conn.cursor.return_value = mock_cursor
    mock_conn.__enter__.return_value = mock_conn

    with patch("app.database.sql_executor.get_connection", return_value=mock_conn):
        result = executor.execute(plan, table)
        assert result is None


# =============================================================================
# Category D — Sorting and Limiting
# =============================================================================

def test_cat_d_01_sorting_asc_desc():
    executor = SQLQueryExecutor()
    schema = _build_synthetic_sales_schema()
    table = schema.get_table("dbo", "customers")

    p1 = QueryPlan(intent="lookup", target_columns=["name"], sort_column="name", sort_direction="asc")
    sql1 = executor._build_order_by_clause(p1, table)
    assert sql1 == " ORDER BY [name] ASC"

    p2 = QueryPlan(intent="lookup", target_columns=["name"], sort_column="name", sort_direction="desc")
    sql2 = executor._build_order_by_clause(p2, table)
    assert sql2 == " ORDER BY [name] DESC"


def test_cat_d_02_sorting_grouped_results():
    executor = SQLQueryExecutor()
    schema = _build_synthetic_sales_schema()
    table = schema.get_table("dbo", "orders")
    plan = QueryPlan(
        intent="aggregation",
        aggregation="sum",
        target_columns=["amount"],
        group_by=["status"],
        sort_column="sum",
        sort_direction="desc",
    )

    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.description = [("status",), ("aggregation_value",)]
    mock_cursor.fetchall.return_value = [("Completed", 5000), ("Active", 1000)]
    mock_conn.cursor.return_value = mock_cursor
    mock_conn.__enter__.return_value = mock_conn

    with patch("app.database.sql_executor.get_connection", return_value=mock_conn):
        executor.execute(plan, table)
        sql = mock_cursor.execute.call_args[0][0]
        assert "ORDER BY [aggregation_value] DESC" in sql


def test_cat_d_03_limit_and_ties():
    executor = SQLQueryExecutor()
    schema = _build_synthetic_sales_schema()
    table = schema.get_table("dbo", "customers")

    p1 = QueryPlan(intent="lookup", target_columns=["name"], limit=5)
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.description = [("name",)]
    mock_cursor.fetchall.return_value = [("A",)]
    mock_conn.cursor.return_value = mock_cursor
    mock_conn.__enter__.return_value = mock_conn

    with patch("app.database.sql_executor.get_connection", return_value=mock_conn):
        executor.execute(p1, table)
        assert "TOP (5)" in mock_cursor.execute.call_args[0][0]

    p2 = QueryPlan(intent="lookup", target_columns=["name"], limit=5, include_ties=True, sort_column="name", sort_direction="desc")
    with patch("app.database.sql_executor.get_connection", return_value=mock_conn):
        executor.execute(p2, table)
        assert "TOP (5) WITH TIES" in mock_cursor.execute.call_args[0][0]


# =============================================================================
# Category E — Column Resolution
# =============================================================================

def test_cat_e_01_unqualified_and_qualified_columns():
    schema = _build_synthetic_sales_schema()

    res1 = schema.resolve_column("product_name")
    assert res1.resolved is not None
    assert res1.resolved.table_name == "products"

    res2 = schema.resolve_column("customers.name")
    assert res2.resolved is not None
    assert res2.resolved.table_name == "customers"

    res3 = schema.resolve_column("dbo.orders.order_date")
    assert res3.resolved is not None
    assert res3.resolved.table_name == "orders"


def test_cat_e_02_ambiguous_column():
    schema = _build_synthetic_sales_schema()
    res = schema.resolve_column("status")
    assert res.is_ambiguous is True
    assert res.resolved is None
    assert len(res.matching_tables) == 2


def test_cat_e_03_unknown_column():
    schema = _build_synthetic_sales_schema()
    res = schema.resolve_column("non_existent_column")
    assert res.resolved is None
    assert res.is_ambiguous is False
    assert res.error is not None


# =============================================================================
# Category F — Entity / Table Selection
# =============================================================================

def test_cat_f_01_singular_plural_matching():
    schema = _build_synthetic_sales_schema()
    selected = select_tables("How many customers are there?", schema.tables)
    assert len(selected) > 0
    assert selected[0]["table"] == "customers"


def test_cat_f_02_compound_entity_matching():
    schema = _build_synthetic_sales_schema()
    selected = select_tables("Show all order items", schema.tables)
    assert len(selected) > 0
    assert selected[0]["table"] == "order_items"


def test_cat_f_03_column_oriented_selection():
    schema = _build_synthetic_sales_schema()
    selected = select_tables("What is the unit price of items?", schema.tables)
    assert len(selected) > 0
    assert any(t["table"] == "order_items" for t in selected)


# =============================================================================
# Category G — Relationship / JOIN Tests
# =============================================================================

def test_cat_g_01_direct_relationship_join():
    schema = _build_synthetic_sales_schema()
    plan = QueryPlan(
        intent="lookup",
        target_columns=["customers.name", "orders.amount"],
        joins=[
            QueryJoin(
                left_schema="dbo",
                left_table="customers",
                left_column="customer_id",
                right_schema="dbo",
                right_table="orders",
                right_column="customer_id",
            )
        ],
    )
    res = validate_query_plan_joins(plan, schema)
    assert res.valid is True
    assert len(res.errors) == 0


def test_cat_g_02_bridge_table_join():
    schema = _build_synthetic_sales_schema()
    plan = QueryPlan(
        intent="lookup",
        target_columns=["orders.order_id", "products.product_name"],
        joins=[
            QueryJoin(
                left_schema="dbo",
                left_table="orders",
                left_column="order_id",
                right_schema="dbo",
                right_table="order_items",
                right_column="order_id",
            ),
            QueryJoin(
                left_schema="dbo",
                left_table="order_items",
                left_column="product_id",
                right_schema="dbo",
                right_table="products",
                right_column="product_id",
            ),
        ],
    )
    res = validate_query_plan_joins(plan, schema)
    assert res.valid is True
    assert len(res.errors) == 0


def test_cat_g_03_disconnected_join_rejected():
    schema = _build_synthetic_sales_schema()
    plan = QueryPlan(
        intent="lookup",
        target_columns=["customers.name"],
        joins=[
            QueryJoin(
                left_schema="dbo",
                left_table="customers",
                left_column="non_existent",
                right_schema="dbo",
                right_table="products",
                right_column="product_id",
            )
        ],
    )
    res = validate_query_plan_joins(plan, schema)
    assert res.valid is False
    assert len(res.errors) > 0


def test_cat_g_04_ambiguous_relationship_safety():
    schema = _build_synthetic_sales_schema()
    plan = QueryPlan(
        intent="lookup",
        joins=[
            QueryJoin(
                left_schema="dbo",
                left_table="customers",
                left_column="customer_id",
                right_schema="dbo",
                right_table="ghost_table",
                right_column="customer_id",
            )
        ],
    )
    res = validate_query_plan_joins(plan, schema)
    assert res.valid is False


# =============================================================================
# Category H — Fan-out Correctness
# =============================================================================

def test_cat_h_01_parent_count_fanout_protection():
    schema = _build_synthetic_sales_schema()
    plan = QueryPlan(
        intent="count",
        joins=[
            QueryJoin(
                left_schema="dbo",
                left_table="customers",
                left_column="customer_id",
                right_schema="dbo",
                right_table="orders",
                right_column="customer_id",
            )
        ],
    )
    executor = SQLQueryExecutor()
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.description = [("aggregation_value",)]
    mock_cursor.fetchall.return_value = [(42,)]
    mock_conn.cursor.return_value = mock_cursor
    mock_conn.__enter__.return_value = mock_conn

    with patch("app.database.sql_executor.get_connection", return_value=mock_conn):
        result = executor.execute(
            plan=plan,
            table=schema.get_table("dbo", "customers"),
            tables=[schema.get_table("dbo", "customers"), schema.get_table("dbo", "orders")],
        )
        assert result == [{"aggregation_value": 42}]
        sql = mock_cursor.execute.call_args[0][0]
        assert "COUNT(DISTINCT" in sql or "DISTINCT" in sql


def test_cat_h_02_parent_sum_fanout_protection():
    schema = _build_synthetic_sales_schema()
    plan = QueryPlan(
        intent="aggregation",
        aggregation="sum",
        target_columns=["customers.balance"],
        joins=[
            QueryJoin(
                left_schema="dbo",
                left_table="customers",
                left_column="customer_id",
                right_schema="dbo",
                right_table="orders",
                right_column="customer_id",
            )
        ],
    )
    executor = SQLQueryExecutor()
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.description = [("aggregation_value",)]
    mock_cursor.fetchall.return_value = [(10000,)]
    mock_conn.cursor.return_value = mock_cursor
    mock_conn.__enter__.return_value = mock_conn

    with patch("app.database.sql_executor.get_connection", return_value=mock_conn):
        result = executor.execute(
            plan=plan,
            table=schema.get_table("dbo", "customers"),
            tables=[schema.get_table("dbo", "customers"), schema.get_table("dbo", "orders")],
        )
        assert result == [{"aggregation_value": 10000}]


def test_cat_h_03_child_aggregation_preservation():
    schema = _build_synthetic_sales_schema()
    plan = QueryPlan(
        intent="aggregation",
        aggregation="sum",
        target_columns=["orders.amount"],
        joins=[
            QueryJoin(
                left_schema="dbo",
                left_table="customers",
                left_column="customer_id",
                right_schema="dbo",
                right_table="orders",
                right_column="customer_id",
            )
        ],
    )
    executor = SQLQueryExecutor()
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.description = [("aggregation_value",)]
    mock_cursor.fetchall.return_value = [(55000,)]
    mock_conn.cursor.return_value = mock_cursor
    mock_conn.__enter__.return_value = mock_conn

    with patch("app.database.sql_executor.get_connection", return_value=mock_conn):
        result = executor.execute(
            plan=plan,
            table=schema.get_table("dbo", "orders"),
            tables=[schema.get_table("dbo", "customers"), schema.get_table("dbo", "orders")],
        )
        assert result == [{"aggregation_value": 55000}]
        sql = mock_cursor.execute.call_args[0][0]
        assert "SUM(" in sql


# =============================================================================
# Category I — Conversation / Follow-up
# =============================================================================

def test_cat_i_01_mode1_in_memory_followup():
    memory = ConversationMemory()
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    mock_conn.__enter__.return_value = mock_conn

    with patch("app.conversation.conversation_memory.get_connection", return_value=mock_conn):
        prior_data = [
            {"name": "Beta", "status": "Active"},
            {"name": "Alpha", "status": "Inactive"},
        ]
        ref_id = memory.save(
            session_id="session_acc_1",
            question="Show customers",
            result=prior_data,
            plan=QueryPlan(intent="lookup"),
        )
        assert ref_id is not None


def test_cat_i_02_mode2_sql_requery_with_context():
    memory = ConversationMemory()
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    mock_conn.__enter__.return_value = mock_conn

    with patch("app.conversation.conversation_memory.get_connection", return_value=mock_conn):
        ref_id = memory.save(
            session_id="session_acc_2",
            question="How many customers have orders?",
            result=20,
            plan=QueryPlan(intent="count"),
            tables=[{"schema_name": "dbo", "table_name": "customers"}],
        )
        assert ref_id is not None


def test_cat_i_03_session_isolation_and_invalid_ref():
    memory = ConversationMemory()
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = []
    mock_conn.cursor.return_value = mock_cursor
    mock_conn.__enter__.return_value = mock_conn

    with patch("app.conversation.conversation_memory.get_connection", return_value=mock_conn):
        ctx = memory.get_context("non_existent_session")
        assert ctx.get("history", []) == []


# =============================================================================
# Category J — Cache Behavior
# =============================================================================

def test_cat_j_01_metadata_and_fingerprint_cache(tmp_path: Path):
    cache = MetadataCache(cache_dir=tmp_path / "metadata")
    schema = _build_synthetic_sales_schema()
    meta = DatabaseMetadata(
        database_name="testdb",
        server_name="localhost",
        schema=schema,
    )
    cache.save(meta, fingerprint="fp_1")

    loaded = cache.load("localhost", "testdb", fingerprint="fp_1")
    assert loaded is not None
    assert len(loaded.tables) == 4

    missed = cache.load("localhost", "testdb", fingerprint="fp_2")
    assert missed is None


def test_cat_j_02_semantic_cache_isolation_and_validation(tmp_path: Path):
    cache = SemanticQueryCache(cache_dir=tmp_path / "semantic")
    plan = QueryPlan(intent="count", target_columns=[])
    cache.set(
        question="how many orders?",
        server_name="localhost",
        database_name="testdb",
        schema_fingerprint="fp_1",
        plan=plan,
    )

    hit = cache.get(
        question="how many orders?",
        server_name="localhost",
        database_name="testdb",
        schema_fingerprint="fp_1",
    )
    assert hit is not None
    assert hit.intent == "count"

    diff_db = cache.get(
        question="how many orders?",
        server_name="localhost",
        database_name="other_db",
        schema_fingerprint="fp_1",
    )
    assert diff_db is None


def test_cat_j_03_relationship_cache_persistence(tmp_path: Path):
    cache = RelationshipCache(
        cache_dir=tmp_path / "rel",
        server_name="localhost",
        database_name="testdb",
        schema_fingerprint="fp_1",
    )
    rel = RelationshipResult(
        relationship_type="inferred",
        status="validated",
        left_schema="dbo",
        left_table="orders",
        left_column="customer_id",
        right_schema="dbo",
        right_table="customers",
        right_column="customer_id",
        reason="Empirically verified",
        confidence=0.99,
    )
    cache.set(rel)
    assert cache.get("dbo", "orders", "customer_id", "dbo", "customers", "customer_id") is not None


# =============================================================================
# Category K — Unsupported / Ambiguous Questions
# =============================================================================

def test_cat_k_01_unknown_table_rejection():
    schema = _build_synthetic_sales_schema()
    selected = select_tables("What are the cosmic flight details?", schema.tables)
    assert "cosmic_flight" not in [t.get("table") for t in selected]


def test_cat_k_02_unsupported_intent_handling():
    plan = QueryPlan(
        intent="unsupported",
        explanation="The request could not be mapped to a supported query intent.",
    )
    assert plan.intent == "unsupported"
    assert "could not be mapped" in plan.explanation


# =============================================================================
# Category L — Security
# =============================================================================

def test_cat_l_01_sql_injection_in_filters():
    executor = SQLQueryExecutor()
    schema = _build_synthetic_sales_schema()
    table = schema.get_table("dbo", "customers")

    payloads = [
        "1; DROP TABLE customers; --",
        "' OR '1'='1",
        "admin' --",
        "'; EXEC xp_cmdshell('dir'); --",
    ]
    for injection in payloads:
        where_sql, params = executor._build_where_clause(
            [QueryFilter(column="name", operator="equals", value=injection)],
            table,
        )
        assert injection not in where_sql
        assert params == [injection]


def test_cat_l_02_identifier_quoting_safety():
    quoted = SQLQueryExecutor._quote_identifier("malicious]name")
    assert quoted == "[malicious]]name]"

    with pytest.raises(SQLQueryExecutionError):
        SQLQueryExecutor._quote_identifier("")


def test_cat_l_03_conversation_payload_safety():
    memory = ConversationMemory()
    malicious_data = [{"comment": "'; DROP TABLE orders; --"}]
    cols, data = memory._prepare_result(malicious_data)
    assert "comment" in cols
    assert data[0]["comment"] == "'; DROP TABLE orders; --"


# =============================================================================
# Category M — Result Contract
# =============================================================================

def test_cat_m_01_result_types_end_to_end():
    val = QueryResultValidator()
    plan_count = QueryPlan(intent="count")
    plan_agg = QueryPlan(intent="aggregation")
    plan_lookup = QueryPlan(intent="lookup")
    plan_cols = QueryPlan(intent="column_names")

    # Int
    assert val.validate(plan_count, 42).valid
    # Float (aggregation)
    assert val.validate(plan_agg, 3.14).valid
    # Decimal (aggregation)
    assert val.validate(plan_agg, Decimal("99.95")).valid
    # None (aggregation)
    assert val.validate(plan_agg, None).valid
    # Column names (list[str])
    assert val.validate(plan_cols, ["col1", "col2"]).valid
    # Empty list
    assert val.validate(plan_lookup, []).valid
    # List of dicts
    assert val.validate(plan_lookup, [{"id": 1, "name": "Test"}]).valid
    assert val.validate(plan_lookup, [{"id": 1, "created": datetime.datetime.now()}]).valid
