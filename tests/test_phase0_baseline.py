from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.database.query_service import DatabaseQueryService
from app.database.relationship_discovery import discover_relationships
from app.database.schema import ColumnInfo, DatabaseSchema, TableInfo
from app.database.semantic_query_cache import SemanticQueryCache
from app.database.sql_executor import SQLQueryExecutor
from app.query.schema import (
    QueryColumn,
    QueryFilter,
    QueryJoin,
    QueryPlan,
)
from app.query.validator import QueryPlanValidator


def _make_table(
    schema_name: str,
    table_name: str,
    columns_spec: list[tuple[str, str, bool]],
    pk_columns: list[str] | None = None,
) -> TableInfo:
    return TableInfo(
        schema_name=schema_name,
        table_name=table_name,
        columns=[
            ColumnInfo(
                name=name,
                data_type=dtype,
                nullable=nullable,
                ordinal_position=idx,
            )
            for idx, (name, dtype, nullable) in enumerate(columns_spec, start=1)
        ],
        primary_key_columns=pk_columns or [],
    )


# -----------------------------------------------------------------------------
# 1. Simple lookup
# -----------------------------------------------------------------------------
def test_simple_lookup():
    table = _make_table(
        "dbo",
        "members",
        [("member_id", "int", False), ("member_name", "nvarchar", True)],
        ["member_id"],
    )

    plan = QueryPlan(
        intent="lookup",
        target_columns=["member_id", "member_name"],
    )

    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.description = [("member_id",), ("member_name",)]
    mock_cursor.fetchall.return_value = [(101, "Alice"), (102, "Bob")]
    mock_conn.cursor.return_value = mock_cursor

    with patch("app.database.sql_executor.get_connection") as mock_get_conn:
        mock_get_conn.return_value.__enter__.return_value = mock_conn
        executor = SQLQueryExecutor()
        result = executor.execute(plan=plan, table=table)

    executed_sql = mock_cursor.execute.call_args[0][0]
    assert "SELECT [member_id], [member_name] FROM [dbo].[members]" in executed_sql
    assert result == [
        {"member_id": 101, "member_name": "Alice"},
        {"member_id": 102, "member_name": "Bob"},
    ]


# -----------------------------------------------------------------------------
# 2. Scalar count
# -----------------------------------------------------------------------------
def test_scalar_count():
    table = _make_table(
        "dbo",
        "orders",
        [("order_id", "int", False)],
        ["order_id"],
    )

    plan = QueryPlan(intent="count")

    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_row = MagicMock(value_count=42)
    mock_cursor.fetchone.return_value = mock_row
    mock_conn.cursor.return_value = mock_cursor

    with patch("app.database.sql_executor.get_connection") as mock_get_conn:
        mock_get_conn.return_value.__enter__.return_value = mock_conn
        executor = SQLQueryExecutor()
        result = executor.execute(plan=plan, table=table)

    executed_sql = mock_cursor.execute.call_args[0][0]
    assert "SELECT COUNT(*) AS value_count FROM [dbo].[orders]" in executed_sql
    assert result == 42


# -----------------------------------------------------------------------------
# 3. Grouped count
# -----------------------------------------------------------------------------
def test_grouped_count():
    table = _make_table(
        "dbo",
        "tasks",
        [("task_id", "int", False), ("status", "nvarchar", True)],
        ["task_id"],
    )

    plan = QueryPlan(
        intent="aggregation",
        target_columns=["task_id"],
        group_by=["status"],
        aggregation="count",
    )

    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.description = [("status",), ("aggregation_value",)]
    mock_cursor.fetchall.return_value = [("Open", 15), ("Closed", 30)]
    mock_conn.cursor.return_value = mock_cursor

    with patch("app.database.sql_executor.get_connection") as mock_get_conn:
        mock_get_conn.return_value.__enter__.return_value = mock_conn
        executor = SQLQueryExecutor()
        result = executor.execute(plan=plan, table=table)

    executed_sql = mock_cursor.execute.call_args[0][0]
    assert "COUNT(*)" in executed_sql
    assert "GROUP BY [status]" in executed_sql
    assert result == [
        {"status": "Open", "aggregation_value": 15},
        {"status": "Closed", "aggregation_value": 30},
    ]


# -----------------------------------------------------------------------------
# 4. Filters & parameterized bindings
# -----------------------------------------------------------------------------
def test_filter_parameterized_bindings():
    table = _make_table(
        "dbo",
        "inventory",
        [
            ("item_id", "int", False),
            ("category", "nvarchar", True),
            ("quantity", "int", False),
        ],
        ["item_id"],
    )

    plan = QueryPlan(
        intent="lookup",
        target_columns=["item_id"],
        filters=[
            QueryFilter(column="category", operator="equals", value="Electronics"),
            QueryFilter(column="quantity", operator="greater_than", value=10),
            QueryFilter(column="item_id", operator="in", value=[100, 200]),
        ],
    )

    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.description = [("item_id",)]
    mock_cursor.fetchall.return_value = [(100,)]
    mock_conn.cursor.return_value = mock_cursor

    with patch("app.database.sql_executor.get_connection") as mock_get_conn:
        mock_get_conn.return_value.__enter__.return_value = mock_conn
        executor = SQLQueryExecutor()
        executor.execute(plan=plan, table=table)

    executed_sql = mock_cursor.execute.call_args[0][0]
    executed_params = mock_cursor.execute.call_args[0][1]

    assert "WHERE [category] = ?" in executed_sql
    assert "[quantity] > ?" in executed_sql
    assert "[item_id] IN (?, ?)" in executed_sql
    assert executed_params == ["Electronics", 10, 100, 200]


# -----------------------------------------------------------------------------
# 5. Aggregation (SUM, AVG, MIN, MAX)
# -----------------------------------------------------------------------------
def test_aggregation_sum():
    table = _make_table(
        "dbo",
        "payments",
        [("payment_id", "int", False), ("amount", "decimal", False)],
        ["payment_id"],
    )

    plan = QueryPlan(
        intent="aggregation",
        target_columns=["amount"],
        aggregation="sum",
    )

    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_row = MagicMock(aggregation_value=1500.50)
    mock_cursor.fetchone.return_value = mock_row
    mock_conn.cursor.return_value = mock_cursor

    with patch("app.database.sql_executor.get_connection") as mock_get_conn:
        mock_get_conn.return_value.__enter__.return_value = mock_conn
        executor = SQLQueryExecutor()
        result = executor.execute(plan=plan, table=table)

    executed_sql = mock_cursor.execute.call_args[0][0]
    assert "SUM([amount]) AS aggregation_value FROM [dbo].[payments]" in executed_sql
    assert result == 1500.50


# -----------------------------------------------------------------------------
# 6. Multi-table JOIN execution
# -----------------------------------------------------------------------------
def test_multi_table_join_execution():
    table_cust = _make_table(
        "dbo",
        "customers",
        [("customer_id", "int", False), ("name", "nvarchar", True)],
        ["customer_id"],
    )
    table_orders = _make_table(
        "dbo",
        "orders",
        [
            ("order_id", "int", False),
            ("customer_id", "int", False),
            ("total", "decimal", True),
        ],
        ["order_id"],
    )

    plan = QueryPlan(
        intent="lookup",
        target_columns=["name", "total"],
        joins=[
            QueryJoin(
                left_schema="dbo",
                left_table="customers",
                left_column="customer_id",
                right_schema="dbo",
                right_table="orders",
                right_column="customer_id",
                join_type="inner",
            )
        ],
        target_column_refs=[
            QueryColumn(schema="dbo", table="customers", column="name"),
            QueryColumn(schema="dbo", table="orders", column="total"),
        ],
    )

    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.description = [("name",), ("total",)]
    mock_cursor.fetchall.return_value = [("Acme Corp", 500)]
    mock_conn.cursor.return_value = mock_cursor

    with patch("app.database.sql_executor.get_connection") as mock_get_conn:
        mock_get_conn.return_value.__enter__.return_value = mock_conn
        executor = SQLQueryExecutor()
        result = executor.execute(
            plan=plan,
            table=table_cust,
            tables=[table_cust, table_orders],
        )

    executed_sql = mock_cursor.execute.call_args[0][0]
    assert "FROM [dbo].[customers] AS t1 INNER JOIN [dbo].[orders] AS t2 ON t1.[customer_id] = t2.[customer_id]" in executed_sql
    assert "t1.[name] AS [name], t2.[total] AS [total]" in executed_sql
    assert result == [{"name": "Acme Corp", "total": 500}]


# -----------------------------------------------------------------------------
# 7. Inferred relationship candidate discovery
# -----------------------------------------------------------------------------
def test_inferred_relationship_discovery():
    table_a = _make_table(
        "dbo",
        "site_profiles",
        [("profile_id", "int", False), ("site_id", "int", False)],
        ["profile_id"],
    )
    table_b = _make_table(
        "dbo",
        "site_logs",
        [("log_id", "int", False), ("site_id", "int", False)],
        ["log_id"],
    )

    schema = DatabaseSchema(
        tables=[table_a, table_b],
        foreign_keys=[],
        unique_constraints=[],
    )

    candidates = discover_relationships(
        database_schema=schema,
        selected_tables=[("dbo", "site_profiles"), ("dbo", "site_logs")],
    )

    assert len(candidates) >= 1
    cand = candidates[0]
    assert cand.left_column == "site_id"
    assert cand.right_column == "site_id"
    assert cand.confidence >= 0.60


# -----------------------------------------------------------------------------
# 8. Conversation follow-up in-memory execution
# -----------------------------------------------------------------------------
def test_conversation_followup_execution():
    plan = QueryPlan(
        intent="lookup",
        input_result_reference="ref-123",
        target_columns=["product_name", "price"],
        filters=[
            QueryFilter(column="price", operator="greater_than", value=50),
        ],
        sort_column="price",
        sort_direction="desc",
    )

    context = {
        "history": [
            {
                "reference_id": "ref-123",
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

    dummy_schema = DatabaseSchema(tables=[])
    service = DatabaseQueryService.__new__(DatabaseQueryService)
    service.database_schema = dummy_schema

    result = service._execute_conversation_result_plan(
        plan=plan,
        conversation_context=context,
    )

    assert result == [
        {"product_name": "Item C", "price": 120},
        {"product_name": "Item B", "price": 80},
    ]


# -----------------------------------------------------------------------------
# 9. Semantic cache behavior
# -----------------------------------------------------------------------------
def test_semantic_cache_behavior():
    with tempfile.TemporaryDirectory() as tmp_dir:
        cache = SemanticQueryCache(cache_dir=Path(tmp_dir))

        original_plan = QueryPlan(
            intent="count",
            target_columns=["user_id"],
            explanation="Count total users",
            confidence=0.95,
        )

        cache.set(
            question="How many users are there?",
            server_name="localhost",
            database_name="testdb",
            schema_fingerprint="fp12345",
            plan=original_plan,
        )

        # Retrieval with semantic paraphrase
        retrieved_plan = cache.get(
            question="What is the total number of users?",
            server_name="localhost",
            database_name="testdb",
            schema_fingerprint="fp12345",
        )

        assert retrieved_plan is not None
        assert retrieved_plan.intent == "count"
        assert retrieved_plan.target_columns == ["user_id"]
        assert retrieved_plan.explanation == "Count total users"

        # Cache miss on different fingerprint
        miss_plan = cache.get(
            question="What is the total number of users?",
            server_name="localhost",
            database_name="testdb",
            schema_fingerprint="fp_different",
        )
        assert miss_plan is None


# -----------------------------------------------------------------------------
# 10. Invalid QueryPlan validation
# -----------------------------------------------------------------------------
def test_invalid_query_plan_validation():
    table = _make_table(
        "dbo",
        "accounts",
        [
            ("account_id", "int", False),
            ("account_name", "nvarchar", True),
            ("balance", "decimal", True),
        ],
        ["account_id"],
    )
    schema = DatabaseSchema(tables=[table])
    validator = QueryPlanValidator()

    # Case A: Unknown target column
    plan_bad_col = QueryPlan(
        intent="lookup",
        target_columns=["non_existent_column"],
    )
    res_a = validator.validate(plan_bad_col, schema)
    assert not res_a.valid
    assert any("Target column does not exist" in e for e in res_a.errors)

    # Case B: Aggregation SUM on non-numeric column
    plan_non_numeric = QueryPlan(
        intent="aggregation",
        target_columns=["account_name"],
        aggregation="sum",
    )
    res_b = validator.validate(plan_non_numeric, schema)
    assert not res_b.valid
    assert any("requires a numeric column" in e for e in res_b.errors)

    # Case C: Invalid filter operator
    plan_bad_op = QueryPlan(
        intent="lookup",
        target_columns=["account_id"],
        filters=[QueryFilter(column="account_id", operator="is_magical", value=1)],
    )
    res_c = validator.validate(plan_bad_op, schema)
    assert not res_c.valid
    assert any("Unsupported filter operator" in e for e in res_c.errors)
