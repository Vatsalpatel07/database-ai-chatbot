from __future__ import annotations

from unittest.mock import MagicMock, patch
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
from app.database.join_validator import (
    validate_query_plan_joins,
)
from app.database.relationship_service import (
    RelationshipGraph,
    RelationshipResult,
)
from app.database.relationship_validator import (
    RelationshipCandidate,
    validate_relationship,
)
from app.query.schema import (
    QueryColumn,
    QueryFilter,
    QueryJoin,
    QueryPlan,
)


# =============================================================================
# Helper fixtures for Phase 6 synthetic schemas
# =============================================================================

def _build_parent_child_schema() -> DatabaseSchema:
    table_customers = TableInfo(
        schema_name="dbo",
        table_name="customers",
        columns=[
            ColumnInfo("customer_id", "int", False, 1),
            ColumnInfo("name", "nvarchar", True, 2),
            ColumnInfo("balance", "decimal", True, 3),
            ColumnInfo("tier", "nvarchar", True, 4),
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
        ],
        primary_key_columns=["order_id"],
    )
    table_items = TableInfo(
        schema_name="dbo",
        table_name="order_items",
        columns=[
            ColumnInfo("item_id", "int", False, 1),
            ColumnInfo("order_id", "int", False, 2),
            ColumnInfo("price", "decimal", True, 3),
        ],
        primary_key_columns=["item_id"],
    )
    table_status_lookup = TableInfo(
        schema_name="dbo",
        table_name="status_lookup",
        columns=[
            ColumnInfo("status_code", "nvarchar", False, 1),
            ColumnInfo("description", "nvarchar", True, 2),
        ],
        primary_key_columns=["status_code"],
    )
    table_profiles = TableInfo(
        schema_name="dbo",
        table_name="customer_profiles",
        columns=[
            ColumnInfo("customer_id", "int", False, 1),
            ColumnInfo("bio", "nvarchar", True, 2),
        ],
        primary_key_columns=["customer_id"],
    )
    return DatabaseSchema(
        tables=[table_customers, table_orders, table_items, table_status_lookup, table_profiles]
    )


def _build_m2m_schema() -> DatabaseSchema:
    table_events = TableInfo(
        schema_name="dbo",
        table_name="events",
        columns=[
            ColumnInfo("event_id", "int", False, 1),
            ColumnInfo("duration", "int", True, 2),
        ],
        primary_key_columns=["event_id"],
    )
    table_bridge = TableInfo(
        schema_name="dbo",
        table_name="event_topics",
        columns=[
            ColumnInfo("event_id", "int", False, 1),
            ColumnInfo("topic_id", "int", False, 2),
        ],
        primary_key_columns=["event_id", "topic_id"],
    )
    table_topics = TableInfo(
        schema_name="dbo",
        table_name="topics",
        columns=[
            ColumnInfo("topic_id", "int", False, 1),
            ColumnInfo("topic_name", "nvarchar", True, 2),
        ],
        primary_key_columns=["topic_id"],
    )
    return DatabaseSchema(tables=[table_events, table_bridge, table_topics])


# =============================================================================
# 1. Parent-child count with 1-to-many child rows
# =============================================================================

def test_parent_child_count_fanout_protection():
    schema = _build_parent_child_schema()
    executor = SQLQueryExecutor()

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
                join_type="inner",
            )
        ],
    )

    with patch("app.database.sql_executor.get_connection") as mock_conn:
        cur = MagicMock()
        cur.description = [("aggregation_value",)]
        cur.fetchall.return_value = [(2,)]
        mock_conn.return_value.__enter__.return_value.cursor.return_value = cur

        res = executor.execute(
            plan=plan,
            table=schema.tables[0],
            tables=schema.tables,
        )

        sql = cur.execute.call_args[0][0]
        assert "SELECT COUNT(*) AS [aggregation_value] FROM (SELECT DISTINCT t1.[customer_id] AS [__sub_id_0]" in sql
        assert "INNER JOIN [dbo].[orders] AS t2 ON t1.[customer_id] = t2.[customer_id]" in sql
        assert res == [{"aggregation_value": 2}]


# =============================================================================
# 2. Parent-child sum with 1-to-many child rows
# =============================================================================

def test_parent_child_sum_fanout_protection():
    schema = _build_parent_child_schema()
    executor = SQLQueryExecutor()

    plan = QueryPlan(
        intent="aggregation",
        aggregation="sum",
        target_columns=["customers.balance"],
        target_column_refs=[
            QueryColumn(schema="dbo", table="customers", column="balance")
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

    with patch("app.database.sql_executor.get_connection") as mock_conn:
        cur = MagicMock()
        cur.description = [("aggregation_value",)]
        cur.fetchall.return_value = [(200.0,)]
        mock_conn.return_value.__enter__.return_value.cursor.return_value = cur

        res = executor.execute(
            plan=plan,
            table=schema.tables[0],
            tables=schema.tables,
        )

        sql = cur.execute.call_args[0][0]
        assert "SELECT SUM(sub.[__sub_target]) AS [aggregation_value]" in sql
        assert "SELECT DISTINCT t1.[customer_id] AS [__sub_id_0], t1.[balance] AS [__sub_target]" in sql
        assert res == [{"aggregation_value": 200.0}]


# =============================================================================
# 3. Parent-child avg with 1-to-many child rows
# =============================================================================

def test_parent_child_avg_fanout_protection():
    schema = _build_parent_child_schema()
    executor = SQLQueryExecutor()

    plan = QueryPlan(
        intent="aggregation",
        aggregation="average",
        target_columns=["customers.balance"],
        target_column_refs=[
            QueryColumn(schema="dbo", table="customers", column="balance")
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

    with patch("app.database.sql_executor.get_connection") as mock_conn:
        cur = MagicMock()
        cur.description = [("aggregation_value",)]
        cur.fetchall.return_value = [(100.0,)]
        mock_conn.return_value.__enter__.return_value.cursor.return_value = cur

        res = executor.execute(
            plan=plan,
            table=schema.tables[0],
            tables=schema.tables,
        )

        sql = cur.execute.call_args[0][0]
        assert "SELECT AVG(sub.[__sub_target]) AS [aggregation_value]" in sql
        assert "t1.[balance] AS [__sub_target]" in sql
        assert res == [{"aggregation_value": 100.0}]


# =============================================================================
# 4. Parent-child min/max
# =============================================================================

def test_parent_child_min_max_fanout_protection():
    schema = _build_parent_child_schema()
    executor = SQLQueryExecutor()

    for agg in ["min", "max"]:
        plan = QueryPlan(
            intent="aggregation",
            aggregation=agg,
            target_columns=["customers.balance"],
            target_column_refs=[
                QueryColumn(schema="dbo", table="customers", column="balance")
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

        with patch("app.database.sql_executor.get_connection") as mock_conn:
            cur = MagicMock()
            cur.description = [("aggregation_value",)]
            cur.fetchall.return_value = [(100.0,)]
            mock_conn.return_value.__enter__.return_value.cursor.return_value = cur

            res = executor.execute(
                plan=plan,
                table=schema.tables[0],
                tables=schema.tables,
            )

            sql = cur.execute.call_args[0][0]
            assert f"SELECT {agg.upper()}(sub.[__sub_target]) AS [aggregation_value]" in sql


# =============================================================================
# 5. Parent-child grouped sum
# =============================================================================

def test_parent_child_grouped_sum():
    schema = _build_parent_child_schema()
    executor = SQLQueryExecutor()

    plan = QueryPlan(
        intent="aggregation",
        aggregation="sum",
        target_columns=["customers.balance"],
        target_column_refs=[
            QueryColumn(schema="dbo", table="customers", column="balance")
        ],
        group_by=["customers.tier"],
        group_by_refs=[
            QueryColumn(schema="dbo", table="customers", column="tier")
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

    with patch("app.database.sql_executor.get_connection") as mock_conn:
        cur = MagicMock()
        cur.description = [("customers.tier",), ("aggregation_value",)]
        cur.fetchall.return_value = [("Gold", 200.0)]
        mock_conn.return_value.__enter__.return_value.cursor.return_value = cur

        res = executor.execute(
            plan=plan,
            table=schema.tables[0],
            tables=schema.tables,
        )

        sql = cur.execute.call_args[0][0]
        assert "SELECT sub.[__sub_grp_0] AS [customers.tier], SUM(sub.[__sub_target]) AS [aggregation_value]" in sql
        assert "t1.[tier] AS [__sub_grp_0]" in sql
        assert "GROUP BY sub.[__sub_grp_0]" in sql
        assert res == [{"customers.tier": "Gold", "aggregation_value": 200.0}]


# =============================================================================
# 6. Parent-child grouped count
# =============================================================================

def test_parent_child_grouped_count():
    schema = _build_parent_child_schema()
    executor = SQLQueryExecutor()

    plan = QueryPlan(
        intent="count",
        group_by=["customers.tier"],
        group_by_refs=[
            QueryColumn(schema="dbo", table="customers", column="tier")
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

    with patch("app.database.sql_executor.get_connection") as mock_conn:
        cur = MagicMock()
        cur.description = [("customers.tier",), ("aggregation_value",)]
        cur.fetchall.return_value = [("Gold", 2)]
        mock_conn.return_value.__enter__.return_value.cursor.return_value = cur

        res = executor.execute(
            plan=plan,
            table=schema.tables[0],
            tables=schema.tables,
        )

        sql = cur.execute.call_args[0][0]
        assert "SELECT sub.[__sub_grp_0] AS [customers.tier], COUNT(*) AS [aggregation_value]" in sql
        assert "GROUP BY sub.[__sub_grp_0]" in sql
        assert res == [{"customers.tier": "Gold", "aggregation_value": 2}]


# =============================================================================
# 7. Parent-child grouped avg
# =============================================================================

def test_parent_child_grouped_avg():
    schema = _build_parent_child_schema()
    executor = SQLQueryExecutor()

    plan = QueryPlan(
        intent="aggregation",
        aggregation="average",
        target_columns=["customers.balance"],
        target_column_refs=[
            QueryColumn(schema="dbo", table="customers", column="balance")
        ],
        group_by=["customers.tier"],
        group_by_refs=[
            QueryColumn(schema="dbo", table="customers", column="tier")
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

    with patch("app.database.sql_executor.get_connection") as mock_conn:
        cur = MagicMock()
        cur.description = [("customers.tier",), ("aggregation_value",)]
        cur.fetchall.return_value = [("Gold", 100.0)]
        mock_conn.return_value.__enter__.return_value.cursor.return_value = cur

        res = executor.execute(
            plan=plan,
            table=schema.tables[0],
            tables=schema.tables,
        )

        sql = cur.execute.call_args[0][0]
        assert "SELECT sub.[__sub_grp_0] AS [customers.tier], AVG(sub.[__sub_target]) AS [aggregation_value]" in sql
        assert "GROUP BY sub.[__sub_grp_0]" in sql


# =============================================================================
# 8. Parent-child grouped having
# =============================================================================

def test_parent_child_grouped_having():
    schema = _build_parent_child_schema()
    executor = SQLQueryExecutor()

    plan = QueryPlan(
        intent="aggregation",
        aggregation="sum",
        target_columns=["customers.balance"],
        target_column_refs=[
            QueryColumn(schema="dbo", table="customers", column="balance")
        ],
        group_by=["customers.tier"],
        group_by_refs=[
            QueryColumn(schema="dbo", table="customers", column="tier")
        ],
        having_filters=[
            QueryFilter(
                column="aggregation_value",
                operator="greater_than",
                value=150.0,
            )
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

    with patch("app.database.sql_executor.get_connection") as mock_conn:
        cur = MagicMock()
        cur.description = [("customers.tier",), ("aggregation_value",)]
        cur.fetchall.return_value = [("Gold", 200.0)]
        mock_conn.return_value.__enter__.return_value.cursor.return_value = cur

        res = executor.execute(
            plan=plan,
            table=schema.tables[0],
            tables=schema.tables,
        )

        sql = cur.execute.call_args[0][0]
        params = cur.execute.call_args[0][1]
        assert "HAVING SUM(sub.[__sub_target]) > ?" in sql
        assert params == [150.0]


# =============================================================================
# 9. Child-grain sum (no fan-out reduction needed)
# =============================================================================

def test_child_grain_sum():
    schema = _build_parent_child_schema()
    executor = SQLQueryExecutor()

    plan = QueryPlan(
        intent="aggregation",
        aggregation="sum",
        target_columns=["orders.amount"],
        target_column_refs=[
            QueryColumn(schema="dbo", table="orders", column="amount")
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

    with patch("app.database.sql_executor.get_connection") as mock_conn:
        cur = MagicMock()
        cur.description = [("aggregation_value",)]
        cur.fetchall.return_value = [(180.0,)]
        mock_conn.return_value.__enter__.return_value.cursor.return_value = cur

        res = executor.execute(
            plan=plan,
            table=schema.tables[0],
            tables=schema.tables,
        )

        sql = cur.execute.call_args[0][0]
        # Target table is orders (t2), deduplicating at order_id grain
        assert "t2.[order_id] AS [__sub_id_0]" in sql
        assert "t2.[amount] AS [__sub_target]" in sql
        assert "SUM(sub.[__sub_target])" in sql
        assert res == [{"aggregation_value": 180.0}]


# =============================================================================
# 10. Child-grain count
# =============================================================================

def test_child_grain_count():
    schema = _build_parent_child_schema()
    executor = SQLQueryExecutor()

    plan = QueryPlan(
        intent="count",
        target_columns=["orders.order_id"],
        target_column_refs=[
            QueryColumn(schema="dbo", table="orders", column="order_id")
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

    with patch("app.database.sql_executor.get_connection") as mock_conn:
        cur = MagicMock()
        cur.description = [("aggregation_value",)]
        cur.fetchall.return_value = [(4,)]
        mock_conn.return_value.__enter__.return_value.cursor.return_value = cur

        res = executor.execute(
            plan=plan,
            table=schema.tables[0],
            tables=schema.tables,
        )

        sql = cur.execute.call_args[0][0]
        assert "t2.[order_id] AS [__sub_id_0]" in sql
        assert "COUNT(sub.[__sub_target])" in sql
        assert res == [{"aggregation_value": 4}]


# =============================================================================
# 11. Filter-only child table join
# =============================================================================

def test_filter_only_child_table_join():
    schema = _build_parent_child_schema()
    executor = SQLQueryExecutor()

    plan = QueryPlan(
        intent="count",
        target_columns=["customers.customer_id"],
        target_column_refs=[
            QueryColumn(schema="dbo", table="customers", column="customer_id")
        ],
        filters=[
            QueryFilter(
                column="orders.status",
                operator="equals",
                value="Completed",
            )
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

    with patch("app.database.sql_executor.get_connection") as mock_conn:
        cur = MagicMock()
        cur.description = [("aggregation_value",)]
        cur.fetchall.return_value = [(2,)]
        mock_conn.return_value.__enter__.return_value.cursor.return_value = cur

        res = executor.execute(
            plan=plan,
            table=schema.tables[0],
            tables=schema.tables,
        )

        sql = cur.execute.call_args[0][0]
        params = cur.execute.call_args[0][1]
        assert "t1.[customer_id] AS [__sub_id_0]" in sql
        assert "WHERE t2.[status] = ?" in sql
        assert params == ["Completed"]
        assert res == [{"aggregation_value": 2}]


# =============================================================================
# 12. Bridge / many-to-many join aggregate
# =============================================================================

def test_bridge_many_to_many_join_aggregate():
    schema = _build_m2m_schema()
    executor = SQLQueryExecutor()

    plan = QueryPlan(
        intent="aggregation",
        aggregation="average",
        target_columns=["events.duration"],
        target_column_refs=[
            QueryColumn(schema="dbo", table="events", column="duration")
        ],
        filters=[
            QueryFilter(
                column="topics.topic_name",
                operator="equals",
                value="AI",
            )
        ],
        joins=[
            QueryJoin(
                left_schema="dbo",
                left_table="events",
                left_column="event_id",
                right_schema="dbo",
                right_table="event_topics",
                right_column="event_id",
                join_type="inner",
            ),
            QueryJoin(
                left_schema="dbo",
                left_table="event_topics",
                left_column="topic_id",
                right_schema="dbo",
                right_table="topics",
                right_column="topic_id",
                join_type="inner",
            ),
        ],
    )

    with patch("app.database.sql_executor.get_connection") as mock_conn:
        cur = MagicMock()
        cur.description = [("aggregation_value",)]
        cur.fetchall.return_value = [(60.0,)]
        mock_conn.return_value.__enter__.return_value.cursor.return_value = cur

        res = executor.execute(
            plan=plan,
            table=schema.tables[0],
            tables=schema.tables,
        )

        sql = cur.execute.call_args[0][0]
        params = cur.execute.call_args[0][1]
        assert "SELECT AVG(sub.[__sub_target]) AS [aggregation_value]" in sql
        assert "t1.[event_id] AS [__sub_id_0]" in sql
        assert "WHERE t3.[topic_name] = ?" in sql
        assert params == ["AI"]


# =============================================================================
# 13. 1-to-1 join aggregate
# =============================================================================

def test_one_to_one_join_aggregate():
    schema = _build_parent_child_schema()
    executor = SQLQueryExecutor()

    plan = QueryPlan(
        intent="count",
        joins=[
            QueryJoin(
                left_schema="dbo",
                left_table="customers",
                left_column="customer_id",
                right_schema="dbo",
                right_table="customer_profiles",
                right_column="customer_id",
                join_type="inner",
            )
        ],
    )

    with patch("app.database.sql_executor.get_connection") as mock_conn:
        cur = MagicMock()
        cur.description = [("aggregation_value",)]
        cur.fetchall.return_value = [(10,)]
        mock_conn.return_value.__enter__.return_value.cursor.return_value = cur

        res = executor.execute(
            plan=plan,
            table=schema.tables[0],
            tables=schema.tables,
        )

        sql = cur.execute.call_args[0][0]
        assert "SELECT COUNT(*) AS [aggregation_value]" in sql
        assert res == [{"aggregation_value": 10}]


# =============================================================================
# 14. 1-row lookup table join guard
# =============================================================================

def test_one_row_lookup_table_guard():
    candidate = RelationshipCandidate(
        left_schema="dbo",
        left_table="orders",
        left_column="status",
        right_schema="dbo",
        right_table="status_lookup",
        right_column="status_code",
        reason="lookup_table_test",
    )

    with patch("app.database.relationship_validator.get_connection") as mock_conn:
        cur = MagicMock()
        cur.fetchone.side_effect = [
            (100,),  # left_rows
            (1,),    # right_rows (1-row lookup table)
            (1,),    # left_distinct
            (1,),    # right_distinct
            (1,),    # matches: 1 distinct matching value
        ]
        mock_conn.return_value = mock_conn
        mock_conn.cursor.return_value = cur

        validation = validate_relationship(candidate)
        # Must NOT be rejected because smaller_distinct == 1
        assert validation.status == "validated"
        assert "100.0%" in validation.reason


# =============================================================================
# 15. Ambiguous path detection
# =============================================================================

def test_ambiguous_path_detection():
    graph = RelationshipGraph()
    # Add diamond: A -> B -> D and A -> C -> D
    rel_ab = RelationshipResult(relationship_type="fk", status="validated", left_schema="dbo", left_table="A", left_column="b_id", right_schema="dbo", right_table="B", right_column="id", reason="test")
    rel_bd = RelationshipResult(relationship_type="fk", status="validated", left_schema="dbo", left_table="B", left_column="d_id", right_schema="dbo", right_table="D", right_column="id", reason="test")
    rel_ac = RelationshipResult(relationship_type="fk", status="validated", left_schema="dbo", left_table="A", left_column="c_id", right_schema="dbo", right_table="C", right_column="id", reason="test")
    rel_cd = RelationshipResult(relationship_type="fk", status="validated", left_schema="dbo", left_table="C", left_column="d_id", right_schema="dbo", right_table="D", right_column="id", reason="test")

    for r in [rel_ab, rel_bd, rel_ac, rel_cd]:
        graph.add(r)

    ambiguous = graph.detect_ambiguous_paths(("dbo", "A"), ("dbo", "D"))
    assert len(ambiguous) == 2
    assert [("dbo", "A"), ("dbo", "B"), ("dbo", "D")] in ambiguous
    assert [("dbo", "A"), ("dbo", "C"), ("dbo", "D")] in ambiguous

    # For a simple linear tree with only 1 path, returns empty list
    tree_graph = RelationshipGraph()
    rel_xy = RelationshipResult(relationship_type="fk", status="validated", left_schema="dbo", left_table="X", left_column="y_id", right_schema="dbo", right_table="Y", right_column="id", reason="test")
    rel_yz = RelationshipResult(relationship_type="fk", status="validated", left_schema="dbo", left_table="Y", left_column="z_id", right_schema="dbo", right_table="Z", right_column="id", reason="test")
    tree_graph.add(rel_xy)
    tree_graph.add(rel_yz)
    not_ambiguous = tree_graph.detect_ambiguous_paths(("dbo", "X"), ("dbo", "Z"))
    assert not_ambiguous == []


# =============================================================================
# 16. Disconnected join rejection
# =============================================================================

def test_disconnected_join_rejection():
    schema = _build_parent_child_schema()
    executor = SQLQueryExecutor()

    # customers -> orders, but order_items joins status_lookup (disconnected from customers/orders)
    plan = QueryPlan(
        intent="lookup",
        target_columns=["customers.name"],
        joins=[
            QueryJoin("dbo", "customers", "customer_id", "dbo", "orders", "customer_id", "inner"),
            QueryJoin("dbo", "order_items", "item_id", "dbo", "status_lookup", "status_code", "inner"),
        ],
    )

    with pytest.raises(SQLQueryExecutionError, match="disconnected"):
        executor.execute(plan=plan, table=schema.tables[0], tables=schema.tables)


# =============================================================================
# 17. Unknown column in join rejection
# =============================================================================

def test_unknown_column_in_join_rejection():
    schema = _build_parent_child_schema()
    executor = SQLQueryExecutor()

    plan = QueryPlan(
        intent="count",
        joins=[
            QueryJoin("dbo", "customers", "non_existent_column", "dbo", "orders", "customer_id", "inner")
        ],
    )

    with pytest.raises(SQLQueryExecutionError, match="unknown left column"):
        executor.execute(plan=plan, table=schema.tables[0], tables=schema.tables)


# =============================================================================
# 18. Redundant join rejection
# =============================================================================

def test_redundant_join_rejection():
    schema = _build_parent_child_schema()
    executor = SQLQueryExecutor()

    # Join customers to orders twice
    plan = QueryPlan(
        intent="count",
        joins=[
            QueryJoin("dbo", "customers", "customer_id", "dbo", "orders", "customer_id", "inner"),
            QueryJoin("dbo", "orders", "customer_id", "dbo", "customers", "customer_id", "inner"),
        ],
    )

    with pytest.raises(SQLQueryExecutionError, match="already joined"):
        executor.execute(plan=plan, table=schema.tables[0], tables=schema.tables)


# =============================================================================
# 19. Duplicate distinct value preservation (No Blind DISTINCT on Measure)
# =============================================================================

def test_duplicate_distinct_value_preservation():
    """
    Two distinct parent entities (customer 1 and customer 2) each have balance 100.
    Child multiplication occurs.
    The query must evaluate SUM(sub.[__sub_target]), preserving both 100 values to get 200.
    It must NOT use SUM(DISTINCT balance) which would erroneously produce 100.
    """
    schema = _build_parent_child_schema()
    executor = SQLQueryExecutor()

    plan = QueryPlan(
        intent="aggregation",
        aggregation="sum",
        target_columns=["customers.balance"],
        target_column_refs=[
            QueryColumn(schema="dbo", table="customers", column="balance")
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

    with patch("app.database.sql_executor.get_connection") as mock_conn:
        cur = MagicMock()
        cur.description = [("aggregation_value",)]
        cur.fetchall.return_value = [(200.0,)]
        mock_conn.return_value.__enter__.return_value.cursor.return_value = cur

        res = executor.execute(
            plan=plan,
            table=schema.tables[0],
            tables=schema.tables,
        )

        sql = cur.execute.call_args[0][0]
        # Verify outer query does NOT blind DISTINCT the measure
        assert "SUM(sub.[__sub_target])" in sql
        assert "SUM(DISTINCT" not in sql
        assert res == [{"aggregation_value": 200.0}]


# =============================================================================
# 20. Regression check on existing single-table plans
# =============================================================================

def test_single_table_regression():
    schema = _build_parent_child_schema()
    customer_table = schema.tables[0]
    executor = SQLQueryExecutor()

    # 1. Row count
    with patch("app.database.sql_executor.get_connection") as mock_conn:
        cur = MagicMock()
        mock_row = MagicMock()
        mock_row.row_count = 10
        cur.fetchone.return_value = mock_row
        mock_conn.return_value.__enter__.return_value.cursor.return_value = cur
        assert executor.execute(QueryPlan(intent="row_count"), customer_table) == 10

    # 2. Column count
    assert executor.execute(QueryPlan(intent="column_count"), customer_table) == 4

    # 3. Column names
    assert executor.execute(QueryPlan(intent="column_names"), customer_table) == [
        "customer_id", "name", "balance", "tier"
    ]

    # 4. Scalar count
    with patch("app.database.sql_executor.get_connection") as mock_conn:
        cur = MagicMock()
        mock_row_count = MagicMock()
        mock_row_count.value_count = 5
        cur.fetchone.return_value = mock_row_count
        mock_conn.return_value.__enter__.return_value.cursor.return_value = cur
        assert executor.execute(QueryPlan(intent="count"), customer_table) == 5

    # 5. Scalar sum
    with patch("app.database.sql_executor.get_connection") as mock_conn:
        cur = MagicMock()
        mock_row_agg = MagicMock()
        mock_row_agg.aggregation_value = 500.0
        cur.fetchone.return_value = mock_row_agg
        mock_conn.return_value.__enter__.return_value.cursor.return_value = cur
        plan_sum = QueryPlan(
            intent="aggregation",
            aggregation="sum",
            target_columns=["balance"],
        )
        assert executor.execute(plan_sum, customer_table) == 500.0
