from __future__ import annotations

import datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch
import uuid
import pytest

from app.database.schema import (
    ColumnInfo,
    DatabaseSchema,
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
# Synthetic generic schema fixtures
# =============================================================================

def _build_test_schema() -> DatabaseSchema:
    table_customers = TableInfo(
        schema_name="dbo",
        table_name="customers",
        columns=[
            ColumnInfo("customer_id", "int", False, 1),
            ColumnInfo("name", "nvarchar", True, 2),
            ColumnInfo("balance", "decimal", True, 3),
            ColumnInfo("tier", "nvarchar", True, 4),
            ColumnInfo("created_at", "datetime2", True, 5),
            ColumnInfo("guid", "uniqueidentifier", True, 6),
        ],
        primary_key_columns=["customer_id"],
    )
    table_orders = TableInfo(
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
    return DatabaseSchema(tables=[table_customers, table_orders])


class MockDBRow(tuple):
    """Simulates pyodbc.Row which supports both indexing and attribute access."""
    def __new__(cls, values, field_names):
        obj = super().__new__(cls, values)
        obj._field_names = field_names
        for name, val in zip(field_names, values):
            setattr(obj, name, val)
        return obj


def _mock_cursor(rows=None, description=None):
    cursor = MagicMock()
    cursor.fetchall.return_value = rows or []
    cursor.fetchone.return_value = rows[0] if rows else None
    cursor.description = description
    return cursor


def _mock_connection(cursor):
    conn = MagicMock()
    conn.cursor.return_value = cursor
    conn.__enter__.return_value = conn
    conn.__exit__.return_value = None
    return conn


# =============================================================================
# SCENARIO 1: Metadata result contracts
# =============================================================================

def test_01_metadata_result_contracts():
    schema = _build_test_schema()
    table = schema.get_table(None, "customers")
    executor = SQLQueryExecutor()
    validator = QueryResultValidator()

    # row_count
    plan_row_count = QueryPlan(intent="row_count", target_columns=[])
    cursor_rc = _mock_cursor(rows=[(42,)], description=[("row_count", None)])
    with patch("app.database.sql_executor.get_connection", return_value=_mock_connection(cursor_rc)):
        rc = executor.execute(plan=plan_row_count, table=table)
    assert isinstance(rc, int)
    assert rc == 42
    assert validator.validate(plan_row_count, rc).valid is True

    # column_count
    plan_col_count = QueryPlan(intent="column_count", target_columns=[])
    cc = executor.execute(plan=plan_col_count, table=table)
    assert isinstance(cc, int)
    assert cc == 6
    assert validator.validate(plan_col_count, cc).valid is True

    # column_names
    plan_col_names = QueryPlan(intent="column_names", target_columns=[])
    cnames = executor.execute(plan=plan_col_names, table=table)
    assert isinstance(cnames, list)
    assert all(isinstance(c, str) for c in cnames)
    assert cnames == ["customer_id", "name", "balance", "tier", "created_at", "guid"]
    assert validator.validate(plan_col_names, cnames).valid is True


# =============================================================================
# SCENARIO 2: Simple lookup contract
# =============================================================================

def test_02_simple_lookup_shape_and_keys():
    schema = _build_test_schema()
    table = schema.get_table(None, "customers")
    executor = SQLQueryExecutor()
    validator = QueryResultValidator()

    plan = QueryPlan(
        intent="lookup",
        target_columns=["customer_id", "name"],
    )
    cursor = _mock_cursor(
        rows=[(1, "Alice"), (2, "Bob")],
        description=[("customer_id", None), ("name", None)],
    )
    with patch("app.database.sql_executor.get_connection", return_value=_mock_connection(cursor)):
        data = executor.execute(plan=plan, table=table)

    assert isinstance(data, list)
    assert len(data) == 2
    assert data[0] == {"customer_id": 1, "name": "Alice"}
    assert data[1] == {"customer_id": 2, "name": "Bob"}
    res = validator.validate(plan, data)
    assert res.valid is True


# =============================================================================
# SCENARIO 3: Multi-column lookup contract
# =============================================================================

def test_03_multi_column_lookup():
    schema = _build_test_schema()
    table = schema.get_table(None, "customers")
    executor = SQLQueryExecutor()
    validator = QueryResultValidator()

    plan = QueryPlan(
        intent="lookup",
        target_columns=["customer_id", "name", "balance", "tier"],
    )
    cursor = _mock_cursor(
        rows=[(1, "Alice", Decimal("100.00"), "gold")],
        description=[("customer_id", None), ("name", None), ("balance", None), ("tier", None)],
    )
    with patch("app.database.sql_executor.get_connection", return_value=_mock_connection(cursor)):
        data = executor.execute(plan=plan, table=table)

    assert len(data) == 1
    assert set(data[0].keys()) == {"customer_id", "name", "balance", "tier"}
    assert validator.validate(plan, data).valid is True


# =============================================================================
# SCENARIO 4: Empty lookup contract
# =============================================================================

def test_04_empty_lookup_returns_empty_list():
    schema = _build_test_schema()
    table = schema.get_table(None, "customers")
    executor = SQLQueryExecutor()
    validator = QueryResultValidator()

    plan = QueryPlan(
        intent="lookup",
        target_columns=["customer_id", "name"],
        filters=[QueryFilter("tier", "equals", "platinum")],
    )
    cursor = _mock_cursor(
        rows=[],
        description=[("customer_id", None), ("name", None)],
    )
    with patch("app.database.sql_executor.get_connection", return_value=_mock_connection(cursor)):
        data = executor.execute(plan=plan, table=table)

    assert data == []
    assert isinstance(data, list)
    assert validator.validate(plan, data).valid is True


# =============================================================================
# SCENARIO 5: Scalar count contract
# =============================================================================

def test_05_scalar_count_row_semantics():
    schema = _build_test_schema()
    table = schema.get_table(None, "customers")
    executor = SQLQueryExecutor()
    validator = QueryResultValidator()

    # No target columns
    plan = QueryPlan(intent="count", target_columns=[])
    cursor = _mock_cursor(rows=[(15,)], description=[("value_count", None)])
    with patch("app.database.sql_executor.get_connection", return_value=_mock_connection(cursor)):
        data = executor.execute(plan=plan, table=table)

    assert isinstance(data, int)
    assert data == 15
    assert validator.validate(plan, data).valid is True

    # With target column (validates column exists, counts rows via COUNT(*))
    plan_with_col = QueryPlan(intent="count", target_columns=["customer_id"])
    with patch("app.database.sql_executor.get_connection", return_value=_mock_connection(cursor)):
        data2 = executor.execute(plan=plan_with_col, table=table)
    assert isinstance(data2, int)
    assert data2 == 15
    assert validator.validate(plan_with_col, data2).valid is True


# =============================================================================
# SCENARIO 6: Filtered count contract
# =============================================================================

def test_06_filtered_count():
    schema = _build_test_schema()
    table = schema.get_table(None, "customers")
    executor = SQLQueryExecutor()
    validator = QueryResultValidator()

    plan = QueryPlan(
        intent="count",
        target_columns=[],
        filters=[QueryFilter("tier", "equals", "gold")],
    )
    cursor = _mock_cursor(rows=[(7,)], description=[("value_count", None)])
    with patch("app.database.sql_executor.get_connection", return_value=_mock_connection(cursor)):
        data = executor.execute(plan=plan, table=table)

    assert isinstance(data, int)
    assert data == 7
    assert validator.validate(plan, data).valid is True
    # Verify parameter binding
    cursor.execute.assert_called_once()
    called_sql, called_params = cursor.execute.call_args[0]
    assert "WHERE [tier] = ?" in called_sql
    assert called_params == ["gold"]


# =============================================================================
# SCENARIO 7: Grouped count without target columns
# =============================================================================

def test_07_grouped_count_without_target_columns():
    schema = _build_test_schema()
    table = schema.get_table(None, "customers")
    executor = SQLQueryExecutor()
    validator = QueryResultValidator()

    plan = QueryPlan(
        intent="aggregation",
        aggregation="count",
        group_by=["tier"],
        target_columns=[],
    )
    cursor = _mock_cursor(
        rows=[("gold", 5), ("silver", 10)],
        description=[("tier", None), ("aggregation_value", None)],
    )
    with patch("app.database.sql_executor.get_connection", return_value=_mock_connection(cursor)):
        data = executor.execute(plan=plan, table=table)

    assert isinstance(data, list)
    assert len(data) == 2
    assert data[0] == {"tier": "gold", "aggregation_value": 5}
    assert data[1] == {"tier": "silver", "aggregation_value": 10}
    assert validator.validate(plan, data).valid is True

    called_sql = cursor.execute.call_args[0][0]
    assert "COUNT(*) AS aggregation_value" in called_sql
    assert "GROUP BY [tier]" in called_sql


# =============================================================================
# SCENARIO 8: SUM aggregation contract
# =============================================================================

def test_08_scalar_sum_aggregation():
    schema = _build_test_schema()
    table = schema.get_table(None, "customers")
    executor = SQLQueryExecutor()
    validator = QueryResultValidator()

    plan = QueryPlan(
        intent="aggregation",
        aggregation="sum",
        target_columns=["balance"],
    )
    cursor = _mock_cursor(
        rows=[MockDBRow((Decimal("5432.10"),), ["aggregation_value"])],
        description=[("aggregation_value", None)],
    )
    with patch("app.database.sql_executor.get_connection", return_value=_mock_connection(cursor)):
        data = executor.execute(plan=plan, table=table)

    assert data == Decimal("5432.10")
    assert validator.validate(plan, data).valid is True

    called_sql = cursor.execute.call_args[0][0]
    assert "SELECT SUM([balance]) AS aggregation_value" in called_sql


# =============================================================================
# SCENARIO 9: AVG aggregation contract
# =============================================================================

def test_09_scalar_avg_aggregation():
    schema = _build_test_schema()
    table = schema.get_table(None, "customers")
    executor = SQLQueryExecutor()
    validator = QueryResultValidator()

    plan = QueryPlan(
        intent="aggregation",
        aggregation="average",
        target_columns=["balance"],
    )
    cursor = _mock_cursor(
        rows=[(123.456,)],
        description=[("aggregation_value", None)],
    )
    with patch("app.database.sql_executor.get_connection", return_value=_mock_connection(cursor)):
        data = executor.execute(plan=plan, table=table)

    assert isinstance(data, float)
    assert data == 123.456
    assert validator.validate(plan, data).valid is True

    called_sql = cursor.execute.call_args[0][0]
    assert "SELECT AVG([balance]) AS aggregation_value" in called_sql


# =============================================================================
# SCENARIO 10: MIN and MAX aggregation contract
# =============================================================================

def test_10_scalar_min_max_aggregation():
    schema = _build_test_schema()
    table = schema.get_table(None, "customers")
    executor = SQLQueryExecutor()
    validator = QueryResultValidator()

    plan_min = QueryPlan(intent="aggregation", aggregation="min", target_columns=["balance"])
    cursor_min = _mock_cursor(rows=[(Decimal("10.00"),)], description=[("aggregation_value", None)])
    with patch("app.database.sql_executor.get_connection", return_value=_mock_connection(cursor_min)):
        data_min = executor.execute(plan=plan_min, table=table)
    assert data_min == Decimal("10.00")
    assert validator.validate(plan_min, data_min).valid is True

    plan_max = QueryPlan(intent="aggregation", aggregation="max", target_columns=["balance"])
    cursor_max = _mock_cursor(rows=[(Decimal("999.99"),)], description=[("aggregation_value", None)])
    with patch("app.database.sql_executor.get_connection", return_value=_mock_connection(cursor_max)):
        data_max = executor.execute(plan=plan_max, table=table)
    assert data_max == Decimal("999.99")
    assert validator.validate(plan_max, data_max).valid is True


# =============================================================================
# SCENARIO 11: Grouped aggregation (SUM and AVG)
# =============================================================================

def test_11_grouped_aggregation():
    schema = _build_test_schema()
    table = schema.get_table(None, "customers")
    executor = SQLQueryExecutor()
    validator = QueryResultValidator()

    plan = QueryPlan(
        intent="aggregation",
        aggregation="sum",
        group_by=["tier"],
        target_columns=["balance"],
    )
    cursor = _mock_cursor(
        rows=[("gold", Decimal("5000")), ("silver", Decimal("2000"))],
        description=[("tier", None), ("aggregation_value", None)],
    )
    with patch("app.database.sql_executor.get_connection", return_value=_mock_connection(cursor)):
        data = executor.execute(plan=plan, table=table)

    assert isinstance(data, list)
    assert len(data) == 2
    assert data[0] == {"tier": "gold", "aggregation_value": Decimal("5000")}
    assert validator.validate(plan, data).valid is True


# =============================================================================
# SCENARIO 12: Grouped aggregation with HAVING filter
# =============================================================================

def test_12_grouped_aggregation_having_filter():
    schema = _build_test_schema()
    table = schema.get_table(None, "customers")
    executor = SQLQueryExecutor()
    validator = QueryResultValidator()

    plan = QueryPlan(
        intent="aggregation",
        aggregation="count",
        group_by=["tier"],
        target_columns=[],
        having_filters=[QueryFilter("count", "greater_than", 5)],
    )
    cursor = _mock_cursor(
        rows=[("gold", 12)],
        description=[("tier", None), ("aggregation_value", None)],
    )
    with patch("app.database.sql_executor.get_connection", return_value=_mock_connection(cursor)):
        data = executor.execute(plan=plan, table=table)

    assert data == [{"tier": "gold", "aggregation_value": 12}]
    assert validator.validate(plan, data).valid is True

    called_sql, called_params = cursor.execute.call_args[0]
    assert "HAVING COUNT(*) > ?" in called_sql
    assert 5 in called_params


# =============================================================================
# SCENARIO 13: Ascending sort contract
# =============================================================================

def test_13_ascending_sort():
    schema = _build_test_schema()
    table = schema.get_table(None, "customers")
    executor = SQLQueryExecutor()

    plan = QueryPlan(
        intent="lookup",
        target_columns=["name"],
        sort_column="name",
        sort_direction="asc",
    )
    cursor = _mock_cursor(rows=[("Alice",)], description=[("name", None)])
    with patch("app.database.sql_executor.get_connection", return_value=_mock_connection(cursor)):
        executor.execute(plan=plan, table=table)

    called_sql = cursor.execute.call_args[0][0]
    assert "ORDER BY [name] ASC" in called_sql


# =============================================================================
# SCENARIO 14: Descending sort contract
# =============================================================================

def test_14_descending_sort():
    schema = _build_test_schema()
    table = schema.get_table(None, "customers")
    executor = SQLQueryExecutor()

    plan = QueryPlan(
        intent="aggregation",
        aggregation="count",
        group_by=["tier"],
        target_columns=[],
        sort_column="aggregation_value",
        sort_direction="desc",
    )
    cursor = _mock_cursor(rows=[("silver", 10)], description=[("tier", None), ("aggregation_value", None)])
    with patch("app.database.sql_executor.get_connection", return_value=_mock_connection(cursor)):
        executor.execute(plan=plan, table=table)

    called_sql = cursor.execute.call_args[0][0]
    assert "ORDER BY [aggregation_value] DESC" in called_sql


# =============================================================================
# SCENARIO 15: Limit contract
# =============================================================================

def test_15_limit_clause():
    schema = _build_test_schema()
    table = schema.get_table(None, "customers")
    executor = SQLQueryExecutor()

    plan = QueryPlan(
        intent="lookup",
        target_columns=["customer_id"],
        limit=10,
    )
    cursor = _mock_cursor(rows=[(1,)], description=[("customer_id", None)])
    with patch("app.database.sql_executor.get_connection", return_value=_mock_connection(cursor)):
        executor.execute(plan=plan, table=table)

    called_sql = cursor.execute.call_args[0][0]
    assert "SELECT TOP (10) [customer_id] FROM" in called_sql


# =============================================================================
# SCENARIO 16: Include ties contract with deterministic ORDER BY
# =============================================================================

def test_16_include_ties_deterministic_order():
    schema = _build_test_schema()
    table = schema.get_table(None, "customers")
    executor = SQLQueryExecutor()

    # 1. Lookup with include_ties and no sort_column
    plan_lookup = QueryPlan(
        intent="lookup",
        target_columns=["name"],
        limit=5,
        include_ties=True,
    )
    cursor = _mock_cursor(rows=[("Alice",)], description=[("name", None)])
    with patch("app.database.sql_executor.get_connection", return_value=_mock_connection(cursor)):
        executor.execute(plan=plan_lookup, table=table)
    called_sql = cursor.execute.call_args[0][0]
    assert "TOP (5) WITH TIES" in called_sql
    assert "ORDER BY [name] ASC" in called_sql

    # 2. Grouped aggregation with include_ties and no sort_column
    plan_grouped = QueryPlan(
        intent="aggregation",
        aggregation="count",
        group_by=["tier"],
        target_columns=[],
        limit=3,
        include_ties=True,
    )
    cursor2 = _mock_cursor(rows=[("gold", 5)], description=[("tier", None), ("aggregation_value", None)])
    with patch("app.database.sql_executor.get_connection", return_value=_mock_connection(cursor2)):
        executor.execute(plan=plan_grouped, table=table)
    called_sql2 = cursor2.execute.call_args[0][0]
    assert "TOP (3) WITH TIES" in called_sql2
    assert "ORDER BY [aggregation_value] DESC" in called_sql2


# =============================================================================
# SCENARIO 17: Qualified column resolution in single-table execution
# =============================================================================

def test_17_qualified_column_resolution():
    schema = _build_test_schema()
    table = schema.get_table(None, "customers")
    executor = SQLQueryExecutor()

    plan = QueryPlan(
        intent="lookup",
        target_columns=["customers.name", "dbo.customers.balance"],
        filters=[QueryFilter("dbo.customers.tier", "equals", "gold")],
        sort_column="customers.name",
        sort_direction="asc",
    )
    cursor = _mock_cursor(
        rows=[("Alice", Decimal("100.00"))],
        description=[("customers.name", None), ("dbo.customers.balance", None)],
    )
    with patch("app.database.sql_executor.get_connection", return_value=_mock_connection(cursor)):
        data = executor.execute(plan=plan, table=table)

    assert len(data) == 1
    called_sql = cursor.execute.call_args[0][0]
    assert "[name] AS [customers.name]" in called_sql
    assert "[balance] AS [dbo.customers.balance]" in called_sql
    assert "WHERE [tier] = ?" in called_sql
    assert "ORDER BY [name] ASC" in called_sql


# =============================================================================
# SCENARIO 18: JOIN lookup execution contract
# =============================================================================

def test_18_join_lookup_execution():
    schema = _build_test_schema()
    table_customers = schema.get_table(None, "customers")
    table_orders = schema.get_table(None, "orders")
    executor = SQLQueryExecutor()
    validator = QueryResultValidator()

    plan = QueryPlan(
        intent="lookup",
        target_columns=["customers.name", "orders.amount"],
        target_column_refs=[
            QueryColumn(schema="dbo", table="customers", column="name"),
            QueryColumn(schema="dbo", table="orders", column="amount"),
        ],
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
    )
    cursor = _mock_cursor(
        rows=[("Alice", Decimal("250.00"))],
        description=[("customers.name", None), ("orders.amount", None)],
    )
    with patch("app.database.sql_executor.get_connection", return_value=_mock_connection(cursor)):
        data = executor.execute(plan=plan, table=table_customers, tables=[table_customers, table_orders])

    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0] == {"customers.name": "Alice", "orders.amount": Decimal("250.00")}
    assert validator.validate(plan, data).valid is True


# =============================================================================
# SCENARIO 19: JOIN aggregation with subquery fan-out protection
# =============================================================================

def test_19_join_aggregation_execution():
    schema = _build_test_schema()
    table_customers = schema.get_table(None, "customers")
    table_orders = schema.get_table(None, "orders")
    executor = SQLQueryExecutor()
    validator = QueryResultValidator()

    plan = QueryPlan(
        intent="aggregation",
        aggregation="sum",
        target_columns=["orders.amount"],
        target_column_refs=[
            QueryColumn(schema="dbo", table="orders", column="amount"),
        ],
        group_by=["customers.tier"],
        group_by_refs=[
            QueryColumn(schema="dbo", table="customers", column="tier"),
        ],
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
    )
    cursor = _mock_cursor(
        rows=[("gold", Decimal("5000.00"))],
        description=[("customers.tier", None), ("aggregation_value", None)],
    )
    with patch("app.database.sql_executor.get_connection", return_value=_mock_connection(cursor)):
        data = executor.execute(plan=plan, table=table_customers, tables=[table_customers, table_orders])

    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0] == {"customers.tier": "gold", "aggregation_value": Decimal("5000.00")}
    assert validator.validate(plan, data).valid is True


# =============================================================================
# SCENARIO 20: NULL handling across scalar aggregations
# =============================================================================

def test_20_null_handling():
    schema = _build_test_schema()
    table = schema.get_table(None, "customers")
    executor = SQLQueryExecutor()
    validator = QueryResultValidator()

    # Empty table scalar sum returns None
    plan = QueryPlan(intent="aggregation", aggregation="sum", target_columns=["balance"])
    cursor = _mock_cursor(rows=[(None,)], description=[("aggregation_value", None)])
    with patch("app.database.sql_executor.get_connection", return_value=_mock_connection(cursor)):
        data = executor.execute(plan=plan, table=table)

    assert data is None
    # Result validator explicitly allows None when allow_none=True
    assert validator.validate(plan, data).valid is True
    # AnswerGenerator serializes None to "null"
    serialized = AnswerGenerator._serialize_result(data)
    assert serialized == "null"


# =============================================================================
# SCENARIO 21: Decimal numeric handling
# =============================================================================

def test_21_decimal_numeric_handling():
    validator = QueryResultValidator()
    val = Decimal("123456.78")

    plan = QueryPlan(intent="aggregation", aggregation="sum", target_columns=["balance"])
    assert validator.validate(plan, val).valid is True

    serialized = AnswerGenerator._serialize_result(val)
    assert "123456.78" in serialized


# =============================================================================
# SCENARIO 22: Datetime handling
# =============================================================================

def test_22_datetime_handling():
    validator = QueryResultValidator()
    now = datetime.datetime(2026, 9, 29, 12, 0, 0)
    data = [{"created_at": now, "name": "Alice"}]

    plan = QueryPlan(intent="lookup", target_columns=["created_at", "name"])
    assert validator.validate(plan, data).valid is True

    serialized = AnswerGenerator._serialize_result(data)
    assert "2026-09-29 12:00:00" in serialized or "2026-09-29T12:00:00" in serialized


# =============================================================================
# SCENARIO 23: Uniqueidentifier / UUID handling
# =============================================================================

def test_23_uniqueidentifier_handling():
    validator = QueryResultValidator()
    uid = uuid.UUID("12345678-1234-5678-1234-567812345678")
    data = [{"guid": uid, "name": "Bob"}]

    plan = QueryPlan(intent="lookup", target_columns=["guid", "name"])
    assert validator.validate(plan, data).valid is True

    serialized = AnswerGenerator._serialize_result(data)
    assert "12345678-1234-5678-1234-567812345678" in serialized


# =============================================================================
# SCENARIO 24: Invalid or unsupported plan does not hit SQL executor
# =============================================================================

def test_24_invalid_or_unsupported_plan_does_not_execute():
    schema = _build_test_schema()
    executor = MagicMock()

    # 1. Unsupported plan
    analyzer_unsupported = MagicMock()
    analyzer_unsupported.analyze.return_value = QueryPlan(
        intent="unsupported",
        explanation="Requested table does not exist in schema.",
    )
    service = DatabaseQueryService(
        database_schema=schema,
        analyzer=analyzer_unsupported,
        executor=executor,
        metadata_service=MagicMock(load=MagicMock(return_value=MagicMock(server_name="s", database_name="d", schema_fingerprint="f"))),
        semantic_cache=MagicMock(get=MagicMock(return_value=None)),
        relationship_service=MagicMock(),
    )
    result = service.answer("List customer product warranties")
    assert result.plan.intent == "unsupported"
    assert "Requested table does not exist" in result.data
    executor.execute.assert_not_called()

    # 2. Invalid plan (validation failure)
    analyzer_invalid = MagicMock()
    analyzer_invalid.analyze.return_value = QueryPlan(
        intent="lookup",
        target_columns=["non_existent_column"],
    )
    service2 = DatabaseQueryService(
        database_schema=schema,
        analyzer=analyzer_invalid,
        executor=executor,
        metadata_service=MagicMock(load=MagicMock(return_value=MagicMock(server_name="s", database_name="d", schema_fingerprint="f"))),
        semantic_cache=MagicMock(get=MagicMock(return_value=None)),
        relationship_service=MagicMock(),
    )
    with pytest.raises(DatabaseQueryServiceError) as exc_info:
        service2.answer("List customers non_existent_column")
    assert "QueryPlan validation failed" in str(exc_info.value)
    executor.execute.assert_not_called()


# =============================================================================
# SCENARIO 25: Phase 6 fan-out regression check
# =============================================================================

def test_25_phase6_fan_out_regression_check():
    schema = _build_test_schema()
    table_customers = schema.get_table(None, "customers")
    table_orders = schema.get_table(None, "orders")
    executor = SQLQueryExecutor()

    # 1:M join count query
    plan = QueryPlan(
        intent="count",
        target_columns=[],
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
    )
    cursor = _mock_cursor(rows=[(MockDBRow((42,), ["aggregation_value"]))], description=[("aggregation_value", None)])
    with patch("app.database.sql_executor.get_connection", return_value=_mock_connection(cursor)):
        res = executor.execute(plan=plan, table=table_customers, tables=[table_customers, table_orders])

    assert isinstance(res, list)
    called_sql = cursor.execute.call_args[0][0]
    # Subquery DISTINCT customers.customer_id must be present for parent row grain
    assert "SELECT DISTINCT" in called_sql
    assert "COUNT(*)" in called_sql


# =============================================================================
# SCENARIO 26: QueryResultValidator complete contract verification
# =============================================================================

def test_26_query_result_validator_complete_contracts():
    validator = QueryResultValidator()

    # Valid contracts
    assert validator.validate(QueryPlan(intent="row_count"), 10).valid is True
    assert validator.validate(QueryPlan(intent="column_count"), 5).valid is True
    assert validator.validate(QueryPlan(intent="count"), 100).valid is True
    assert validator.validate(QueryPlan(intent="percentage"), 45.5).valid is True
    assert validator.validate(QueryPlan(intent="column_names"), ["a", "b"]).valid is True
    assert validator.validate(QueryPlan(intent="lookup"), [{"a": 1}]).valid is True
    assert validator.validate(QueryPlan(intent="aggregation", aggregation="sum"), Decimal("10")).valid is True
    assert validator.validate(QueryPlan(intent="aggregation", aggregation="sum"), None).valid is True
    assert validator.validate(QueryPlan(intent="aggregation", aggregation="count", group_by=["cat"]), [{"cat": "x", "aggregation_value": 1}]).valid is True

    # Invalid contracts
    assert validator.validate(QueryPlan(intent="row_count"), "not_an_int").valid is False
    assert validator.validate(QueryPlan(intent="row_count"), True).valid is False  # bool is subclass of int in python
    assert validator.validate(QueryPlan(intent="column_names"), [123]).valid is False
    assert validator.validate(QueryPlan(intent="lookup"), "not_tabular").valid is False
    assert validator.validate(QueryPlan(intent="lookup"), [("not_a_dict",)]).valid is False
    assert validator.validate(QueryPlan(intent="lookup"), [{123: "non_string_key"}]).valid is False
    assert validator.validate(QueryPlan(intent="percentage"), None).valid is False  # percentage disallows None
