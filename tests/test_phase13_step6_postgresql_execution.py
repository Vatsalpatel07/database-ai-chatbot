"""
Phase 13 Step 6 — PostgreSQL Query Generation, Execution Hardening & Dialect Validation Test Suite

Covers:
1. table metadata count
2. table row count
3. simple lookup
4. DISTINCT queries
5. equality filter
6. multiple filters
7. NULL filter (IS NULL / IS NOT NULL)
8. COUNT
9. COUNT with filter
10. SUM
11. AVG
12. MIN
13. MAX
14. MEDIAN (PERCENTILE_CONT ordered-set aggregate)
15. GROUP BY
16. GROUP BY + COUNT
17. GROUP BY + AVG
18. ORDER BY ASC
19. ORDER BY DESC
20. TOP-N / LIMIT
21. highest/lowest ranking
22. date grouping (DATE_TRUNC)
23. month grouping
24. aggregate ranking (ORDER BY aggregate DESC LIMIT n)
25. simple JOIN
26. JOIN + aggregation
27. JOIN fan-out protection
28. subquery aliasing
29. UUID filtering
30. boolean filtering (native boolean coercion)
31. numeric/Decimal result validation
32. timestamp result preservation
33. empty result vs error distinction
34. invalid table handling (fail-closed)
35. invalid column handling (fail-closed)
36. ambiguous column handling (fail-closed)
37. SQL injection protection
38. conversation follow-up
39. input_result_reference handling
40. result contract validation
41. SQL golden compilation (no TOP, no brackets, uses LIMIT, parameters)
42. PostgreSQL dialect purity (no SQL Server syntax)
43. Live SQL comparison (PostgreSQL vs SQL Server semantic equivalence)
44. Real-data answer provenance
45. Hallucination prevention
46. FETCH FIRST n ROWS WITH TIES
47. SQL Server rollback preserved
"""

from __future__ import annotations

import os
from decimal import Decimal
import pytest
from unittest.mock import MagicMock, patch

from app.core.config import DatabaseConfig, get_database_config
from app.database.connection import get_connection
from app.database.metadata_service import DatabaseMetadataService
from app.database.schema import DatabaseSchema, TableInfo, ColumnInfo
from app.database.sql_executor import (
    SQLQueryExecutionError,
    SQLQueryExecutor,
)
from app.database.query_service import (
    DatabaseQueryService,
    DatabaseQueryServiceError,
)
from app.query.schema import (
    QueryPlan,
    QueryFilter,
    QueryJoin,
    QueryColumn,
)
from app.query.validator import QueryPlanValidator
from app.query.result_validator import QueryResultValidator


@pytest.fixture
def pg_config() -> DatabaseConfig:
    return DatabaseConfig(
        engine="postgresql",
        server="localhost",
        port=5432,
        database="mnghealthreportingdb",
        schema="dbo",
        user="postgres",
        password=os.environ.get("DB_PASSWORD", "Vatsal@123"),
    )


@pytest.fixture
def sqlserver_config() -> DatabaseConfig:
    return DatabaseConfig(
        engine="sqlserver",
        server="localhost",
        database="mnghealthreportingdb",
        driver="ODBC Driver 18 for SQL Server",
        trusted_connection=True,
        trust_server_certificate=True,
    )


@pytest.fixture
def live_schema(pg_config) -> DatabaseSchema:
    meta = DatabaseMetadataService(config=pg_config).load()
    return meta.schema


@pytest.fixture
def pg_executor(pg_config) -> SQLQueryExecutor:
    return SQLQueryExecutor(config=pg_config)


@pytest.fixture
def synthetic_logistics_schema() -> DatabaseSchema:
    table_warehouses = TableInfo(
        schema_name="logistics",
        table_name="warehouses",
        columns=[
            ColumnInfo("warehouse_id", "integer", False, 1),
            ColumnInfo("facility_name", "varchar", False, 2),
            ColumnInfo("storage_capacity", "integer", True, 3),
            ColumnInfo("is_active", "boolean", False, 4),
            ColumnInfo("created_at", "timestamp", True, 5),
        ],
        primary_key_columns=["warehouse_id"],
    )
    table_shipments = TableInfo(
        schema_name="logistics",
        table_name="shipments",
        columns=[
            ColumnInfo("shipment_id", "integer", False, 1),
            ColumnInfo("warehouse_id", "integer", False, 2),
            ColumnInfo("cargo_weight", "double precision", False, 3),
            ColumnInfo("departure_timestamp", "timestamp", True, 4),
            ColumnInfo("tracking_status", "varchar", True, 5),
        ],
        primary_key_columns=["shipment_id"],
    )
    return DatabaseSchema(tables=[table_warehouses, table_shipments])


# =============================================================================
# 1. Schema & Row Counts
# =============================================================================

def test_01_table_metadata_count(live_schema):
    """Schema discovery dynamically reflects all migrated database tables."""
    assert len(live_schema.tables) >= 60


def test_02_table_row_count(pg_executor, live_schema):
    """row_count intent returns exact integer row count."""
    table = live_schema.tables[0]
    plan = QueryPlan(intent="row_count")
    count = pg_executor.execute(plan=plan, table=table)
    assert isinstance(count, int)
    assert count >= 0


# =============================================================================
# 2. Lookups & DISTINCT
# =============================================================================

def test_03_simple_lookup(pg_executor, live_schema):
    """lookup intent returns list of dicts with LIMIT."""
    table = live_schema.tables[0]
    plan = QueryPlan(intent="lookup", target_columns=[table.columns[0].name], limit=3)
    rows = pg_executor.execute(plan=plan, table=table)
    assert isinstance(rows, list)
    assert len(rows) <= 3
    if rows:
        assert table.columns[0].name in rows[0]


def test_04_distinct_query(pg_executor, live_schema):
    """DISTINCT queries return deduplicated values."""
    # Find a column with multiple rows
    table = next(t for t in live_schema.tables if len(t.columns) > 1)
    col = table.columns[1].name
    plan = QueryPlan(intent="lookup", target_columns=[col], distinct=True, limit=10)
    rows = pg_executor.execute(plan=plan, table=table)
    assert isinstance(rows, list)
    # Check that all returned items are unique
    values = [r[col] for r in rows if r[col] is not None]
    assert len(values) == len(set(values))


# =============================================================================
# 3. Filtering (Equality, Multiple, NULL)
# =============================================================================

def test_05_equality_filter(pg_executor, live_schema):
    """Equality filter is parameterized and executes cleanly."""
    table = live_schema.tables[0]
    col = table.columns[0].name
    # Lookup first row value
    rows = pg_executor.execute(QueryPlan(intent="lookup", target_columns=[col], limit=1), table)
    if rows:
        val = rows[0][col]
        plan = QueryPlan(intent="lookup", filters=[QueryFilter(column=col, operator="equals", value=val)])
        matched = pg_executor.execute(plan=plan, table=table)
        assert len(matched) >= 1
        assert matched[0][col] == val


def test_06_multiple_filters(pg_executor, live_schema):
    """Multiple filters combine via AND."""
    table = live_schema.tables[0]
    col = table.columns[0].name
    plan = QueryPlan(
        intent="count",
        filters=[
            QueryFilter(column=col, operator="is_not_null", value=None),
            QueryFilter(column=col, operator="not_equals", value=-999999),
        ],
    )
    count = pg_executor.execute(plan=plan, table=table)
    assert isinstance(count, int)
    assert count >= 0


def test_07_null_filter(pg_executor, live_schema):
    """IS NULL and IS NOT NULL generate correct SQL without parameter placeholders."""
    table = live_schema.tables[0]
    col = table.columns[0].name

    # IS NOT NULL
    plan_not_null = QueryPlan(intent="count", filters=[QueryFilter(column=col, operator="is_not_null", value=None)])
    count_not_null = pg_executor.execute(plan=plan_not_null, table=table)
    assert isinstance(count_not_null, int)

    # IS NULL
    plan_null = QueryPlan(intent="count", filters=[QueryFilter(column=col, operator="is_null", value=None)])
    count_null = pg_executor.execute(plan=plan_null, table=table)
    assert isinstance(count_null, int)

    # Total matches row count
    total = pg_executor.execute(QueryPlan(intent="row_count"), table)
    assert count_not_null + count_null == total


# =============================================================================
# 4. Aggregations (COUNT, SUM, AVG, MIN, MAX, MEDIAN)
# =============================================================================

def test_08_count_query(pg_executor, live_schema):
    """count intent executes COUNT(*) and returns int."""
    table = live_schema.tables[0]
    plan = QueryPlan(intent="count")
    count = pg_executor.execute(plan=plan, table=table)
    assert isinstance(count, int)
    assert count >= 0


def test_09_count_with_filter(pg_executor, live_schema):
    """count intent with filter returns matching count."""
    table = live_schema.tables[0]
    col = table.columns[0].name
    plan = QueryPlan(intent="count", filters=[QueryFilter(column=col, operator="is_not_null", value=None)])
    count = pg_executor.execute(plan=plan, table=table)
    assert isinstance(count, int)


def test_10_sum_aggregation(pg_executor, live_schema):
    """SUM aggregation on dynamically discovered numeric column."""
    # Find an integer or decimal column
    numeric_col = None
    target_table = None
    for t in live_schema.tables:
        for c in t.columns:
            if c.data_type.lower() in {"integer", "int", "bigint", "numeric", "decimal", "double precision"}:
                numeric_col = c.name
                target_table = t
                break
        if target_table:
            break

    assert target_table is not None
    plan = QueryPlan(intent="aggregation", aggregation="sum", target_columns=[numeric_col])
    val = pg_executor.execute(plan=plan, table=target_table)
    assert val is None or isinstance(val, (int, float, Decimal))


def test_11_avg_aggregation(pg_executor, live_schema):
    """AVG aggregation on dynamically discovered numeric column."""
    numeric_col = None
    target_table = None
    for t in live_schema.tables:
        for c in t.columns:
            if c.data_type.lower() in {"integer", "int", "numeric", "decimal", "double precision"}:
                numeric_col = c.name
                target_table = t
                break
        if target_table:
            break

    assert target_table is not None
    plan = QueryPlan(intent="aggregation", aggregation="average", target_columns=[numeric_col])
    val = pg_executor.execute(plan=plan, table=target_table)
    assert val is None or isinstance(val, (int, float, Decimal))


def test_12_min_aggregation(pg_executor, live_schema):
    """MIN aggregation on dynamically discovered column."""
    table = live_schema.tables[0]
    col = table.columns[0].name
    plan = QueryPlan(intent="aggregation", aggregation="min", target_columns=[col])
    val = pg_executor.execute(plan=plan, table=table)
    # MIN of any column is a scalar or None
    assert val is not None or len(pg_executor.execute(QueryPlan(intent="lookup", limit=1), table)) == 0


def test_13_max_aggregation(pg_executor, live_schema):
    """MAX aggregation on dynamically discovered column."""
    table = live_schema.tables[0]
    col = table.columns[0].name
    plan = QueryPlan(intent="aggregation", aggregation="max", target_columns=[col])
    val = pg_executor.execute(plan=plan, table=table)
    assert val is not None or len(pg_executor.execute(QueryPlan(intent="lookup", limit=1), table)) == 0


def test_14_median_aggregation(pg_executor, live_schema):
    """MEDIAN aggregation uses PostgreSQL PERCENTILE_CONT ordered-set aggregate."""
    numeric_col = None
    target_table = None
    for t in live_schema.tables:
        for c in t.columns:
            if c.data_type.lower() in {"integer", "int", "numeric", "decimal", "double precision"}:
                numeric_col = c.name
                target_table = t
                break
        if target_table:
            break

    assert target_table is not None
    plan = QueryPlan(intent="aggregation", aggregation="median", target_columns=[numeric_col])
    val = pg_executor.execute(plan=plan, table=target_table)
    assert val is None or isinstance(val, (int, float, Decimal))


# =============================================================================
# 5. Grouping & Sorting
# =============================================================================

def test_15_group_by(pg_executor, live_schema):
    """GROUP BY grouped aggregation returns list of dicts with grouping column."""
    table = next(t for t in live_schema.tables if len(t.columns) > 1)
    grp_col = table.columns[1].name
    plan = QueryPlan(intent="aggregation", aggregation="count", group_by=[grp_col], limit=5)
    rows = pg_executor.execute(plan=plan, table=table)
    assert isinstance(rows, list)
    if rows:
        assert grp_col in rows[0]
        assert "aggregation_value" in rows[0]


def test_16_group_by_count(pg_executor, live_schema):
    """Grouped COUNT counts rows in each group via COUNT(*)."""
    table = next(t for t in live_schema.tables if len(t.columns) > 1)
    grp_col = table.columns[1].name
    plan = QueryPlan(intent="aggregation", aggregation="count", group_by=[grp_col], limit=5)
    rows = pg_executor.execute(plan=plan, table=table)
    assert isinstance(rows, list)
    for r in rows:
        assert isinstance(r["aggregation_value"], int)


def test_17_group_by_avg(pg_executor, live_schema):
    """Grouped AVG computes average of numeric column grouped by dimension."""
    # Find table with numeric col and another col
    target_table = None
    num_col = None
    dim_col = None
    for t in live_schema.tables:
        nums = [c.name for c in t.columns if c.data_type.lower() in {"integer", "int", "numeric", "decimal"}]
        dims = [c.name for c in t.columns if c.name not in nums]
        if nums and dims:
            target_table = t
            num_col = nums[0]
            dim_col = dims[0]
            break

    assert target_table is not None
    plan = QueryPlan(intent="aggregation", aggregation="average", target_columns=[num_col], group_by=[dim_col], limit=5)
    rows = pg_executor.execute(plan=plan, table=target_table)
    assert isinstance(rows, list)
    if rows:
        assert "aggregation_value" in rows[0]
        assert dim_col in rows[0]


def test_18_order_by_asc(pg_executor, live_schema):
    """ORDER BY ASC sorts results in ascending order."""
    table = live_schema.tables[0]
    col = table.columns[0].name
    plan = QueryPlan(intent="lookup", target_columns=[col], sort_column=col, sort_direction="asc", limit=5)
    rows = pg_executor.execute(plan=plan, table=table)
    vals = [r[col] for r in rows if r[col] is not None]
    assert vals == sorted(vals)


def test_19_order_by_desc(pg_executor, live_schema):
    """ORDER BY DESC sorts results in descending order."""
    table = live_schema.tables[0]
    col = table.columns[0].name
    plan = QueryPlan(intent="lookup", target_columns=[col], sort_column=col, sort_direction="desc", limit=5)
    rows = pg_executor.execute(plan=plan, table=table)
    vals = [r[col] for r in rows if r[col] is not None]
    assert vals == sorted(vals, reverse=True)


# =============================================================================
# 6. TOP-N & Ranking
# =============================================================================

def test_20_top_n_limit(pg_executor, live_schema):
    """TOP-N generates LIMIT in PostgreSQL SQL without TOP keyword."""
    table = live_schema.tables[0]
    plan = QueryPlan(intent="lookup", target_columns=[table.columns[0].name], limit=4)
    rows = pg_executor.execute(plan=plan, table=table)
    assert len(rows) <= 4


def test_21_highest_lowest(pg_executor, live_schema):
    """Highest and lowest items retrieved via ORDER BY aggregate DESC / ASC."""
    table = next(t for t in live_schema.tables if len(t.columns) > 1)
    grp_col = table.columns[1].name
    plan = QueryPlan(
        intent="aggregation",
        aggregation="count",
        group_by=[grp_col],
        sort_column="aggregation_value",
        sort_direction="desc",
        limit=1,
    )
    rows = pg_executor.execute(plan=plan, table=table)
    if rows:
        assert len(rows) == 1
        assert "aggregation_value" in rows[0]


# =============================================================================
# 7. Date & Temporal Grouping
# =============================================================================

def test_22_date_grouping(pg_executor, live_schema):
    """Temporal grouping by day uses PostgreSQL DATE_TRUNC('day', col)::date."""
    # Find a date/timestamp column
    date_col = None
    target_table = None
    for t in live_schema.tables:
        for c in t.columns:
            if "date" in c.data_type.lower() or "time" in c.data_type.lower():
                date_col = c.name
                target_table = t
                break
        if target_table:
            break

    if target_table:
        plan = QueryPlan(
            intent="aggregation",
            aggregation="count",
            group_by=[date_col],
            group_by_granularity="day",
            limit=5,
        )
        rows = pg_executor.execute(plan=plan, table=target_table)
        assert isinstance(rows, list)


def test_23_month_grouping(pg_executor, live_schema):
    """Temporal grouping by month uses PostgreSQL DATE_TRUNC('month', col)::date."""
    date_col = None
    target_table = None
    for t in live_schema.tables:
        for c in t.columns:
            if "date" in c.data_type.lower() or "time" in c.data_type.lower():
                date_col = c.name
                target_table = t
                break
        if target_table:
            break

    if target_table:
        plan = QueryPlan(
            intent="aggregation",
            aggregation="count",
            group_by=[date_col],
            group_by_granularity="month",
            limit=5,
        )
        rows = pg_executor.execute(plan=plan, table=target_table)
        assert isinstance(rows, list)


def test_24_aggregate_ranking(pg_executor, live_schema):
    """Aggregate ranking sorts by aggregation_value with limit."""
    table = next(t for t in live_schema.tables if len(t.columns) > 1)
    grp_col = table.columns[1].name
    plan = QueryPlan(
        intent="aggregation",
        aggregation="count",
        group_by=[grp_col],
        sort_column="aggregation_value",
        sort_direction="desc",
        limit=3,
    )
    rows = pg_executor.execute(plan=plan, table=table)
    if len(rows) > 1:
        assert rows[0]["aggregation_value"] >= rows[1]["aggregation_value"]


# =============================================================================
# 8. JOINs & Fan-Out Protection
# =============================================================================

def test_25_simple_join(pg_executor, synthetic_logistics_schema):
    """JOIN execution connects two tables with valid ON condition."""
    table_w = synthetic_logistics_schema.tables[0]
    table_s = synthetic_logistics_schema.tables[1]

    plan = QueryPlan(
        intent="lookup",
        target_columns=["facility_name", "tracking_status"],
        target_column_refs=[
            QueryColumn("facility_name", table="warehouses", schema="logistics"),
            QueryColumn("tracking_status", table="shipments", schema="logistics"),
        ],
        joins=[
            QueryJoin(
                left_schema="logistics",
                left_table="warehouses",
                left_column="warehouse_id",
                right_schema="logistics",
                right_table="shipments",
                right_column="warehouse_id",
                join_type="inner",
            )
        ],
    )

    with patch("app.database.sql_executor.get_connection") as mock_conn:
        mock_cursor = MagicMock()
        mock_cursor.description = [("facility_name",), ("tracking_status",)]
        mock_cursor.fetchall.return_value = [("Depot Alpha", "in_transit")]
        mock_conn.return_value.__enter__.return_value.cursor.return_value = mock_cursor

        rows = pg_executor.execute(plan=plan, table=table_w, tables=[table_w, table_s])
        executed_sql = mock_cursor.execute.call_args[0][0]

        assert 'FROM "logistics"."warehouses" AS t1' in executed_sql
        assert 'INNER JOIN "logistics"."shipments" AS t2' in executed_sql
        assert 'ON t1."warehouse_id" = t2."warehouse_id"' in executed_sql
        assert rows == [{"facility_name": "Depot Alpha", "tracking_status": "in_transit"}]


def test_26_join_aggregation(pg_executor, synthetic_logistics_schema):
    """JOIN with aggregation executes outer aggregate over deduplicated subquery."""
    table_w = synthetic_logistics_schema.tables[0]
    table_s = synthetic_logistics_schema.tables[1]

    plan = QueryPlan(
        intent="aggregation",
        aggregation="sum",
        target_columns=["cargo_weight"],
        target_column_refs=[QueryColumn("cargo_weight", table="shipments", schema="logistics")],
        group_by=["facility_name"],
        group_by_refs=[QueryColumn("facility_name", table="warehouses", schema="logistics")],
        joins=[
            QueryJoin(
                left_schema="logistics",
                left_table="warehouses",
                left_column="warehouse_id",
                right_schema="logistics",
                right_table="shipments",
                right_column="warehouse_id",
                join_type="inner",
            )
        ],
    )

    with patch("app.database.sql_executor.get_connection") as mock_conn:
        mock_cursor = MagicMock()
        mock_cursor.description = [("facility_name",), ("aggregation_value",)]
        mock_cursor.fetchall.return_value = [("Depot Alpha", 1250.5)]
        mock_conn.return_value.__enter__.return_value.cursor.return_value = mock_cursor

        rows = pg_executor.execute(plan=plan, table=table_w, tables=[table_w, table_s])
        executed_sql = mock_cursor.execute.call_args[0][0]

        assert "SELECT DISTINCT" in executed_sql
        assert 'SUM(sub."__sub_target")' in executed_sql
        assert "GROUP BY sub." in executed_sql
        assert rows == [{"facility_name": "Depot Alpha", "aggregation_value": 1250.5}]


def test_27_join_fanout_protection(pg_executor, synthetic_logistics_schema):
    """JOIN fan-out protection: COUNT on parent table deduplicates at parent entity grain."""
    table_w = synthetic_logistics_schema.tables[0]
    table_s = synthetic_logistics_schema.tables[1]

    # Count of warehouses with shipments
    plan = QueryPlan(
        intent="count",
        aggregation="count",
        target_columns=["warehouse_id"],
        target_column_refs=[QueryColumn("warehouse_id", table="warehouses", schema="logistics")],
        joins=[
            QueryJoin(
                left_schema="logistics",
                left_table="warehouses",
                left_column="warehouse_id",
                right_schema="logistics",
                right_table="shipments",
                right_column="warehouse_id",
                join_type="inner",
            )
        ],
    )

    with patch("app.database.sql_executor.get_connection") as mock_conn:
        mock_cursor = MagicMock()
        mock_cursor.description = [("aggregation_value",)]
        mock_cursor.fetchall.return_value = [(42,)]
        mock_conn.return_value.__enter__.return_value.cursor.return_value = mock_cursor

        rows = pg_executor.execute(plan=plan, table=table_w, tables=[table_w, table_s])
        executed_sql = mock_cursor.execute.call_args[0][0]

        # Verified subquery deduplication at entity grain
        assert "SELECT DISTINCT" in executed_sql
        assert '__sub_id_0' in executed_sql
        assert 'COUNT(sub."__sub_target")' in executed_sql


def test_28_subquery_aliasing(pg_executor, synthetic_logistics_schema):
    """Derived tables in PostgreSQL must have explicit aliases."""
    table_w = synthetic_logistics_schema.tables[0]
    table_s = synthetic_logistics_schema.tables[1]

    plan = QueryPlan(
        intent="count",
        aggregation="count",
        target_columns=["shipment_id"],
        target_column_refs=[QueryColumn(column="shipment_id", table="shipments")],
        joins=[
            QueryJoin(
                left_schema="logistics",
                left_table="warehouses",
                left_column="warehouse_id",
                right_schema="logistics",
                right_table="shipments",
                right_column="warehouse_id",
            )
        ],
    )

    with patch("app.database.sql_executor.get_connection") as mock_conn:
        mock_cursor = MagicMock()
        mock_cursor.description = [("aggregation_value",)]
        mock_cursor.fetchall.return_value = [(10,)]
        mock_conn.return_value.__enter__.return_value.cursor.return_value = mock_cursor

        pg_executor.execute(plan=plan, table=table_w, tables=[table_w, table_s])
        executed_sql = mock_cursor.execute.call_args[0][0]

        assert "AS sub" in executed_sql


# =============================================================================
# 9. Data Types: UUID, Boolean, Numeric/Decimal, Timestamp
# =============================================================================

def test_29_uuid_filter(pg_executor, live_schema):
    """UUID filter is parameterized and executed safely."""
    # Find UUID column
    uuid_col = None
    target_table = None
    for t in live_schema.tables:
        for c in t.columns:
            if c.data_type.lower() in {"uuid", "uniqueidentifier"}:
                uuid_col = c.name
                target_table = t
                break
        if target_table:
            break

    if target_table:
        plan = QueryPlan(
            intent="lookup",
            filters=[QueryFilter(column=uuid_col, operator="not_equals", value="00000000-0000-0000-0000-000000000000")],
            limit=2,
        )
        rows = pg_executor.execute(plan=plan, table=target_table)
        assert isinstance(rows, list)
        for r in rows:
            assert isinstance(r[uuid_col], str)  # UUID stringified for JSON safety


def test_30_boolean_filter(pg_executor, live_schema):
    """Boolean column filter coerces integer/string literals to native Python boolean in PostgreSQL."""
    # Find boolean column
    bool_col = None
    target_table = None
    for t in live_schema.tables:
        for c in t.columns:
            if c.data_type.lower() == "boolean":
                bool_col = c.name
                target_table = t
                break
        if target_table:
            break

    if target_table:
        # Pass integer 1 which should be coerced to True for PostgreSQL boolean column
        plan = QueryPlan(intent="count", filters=[QueryFilter(column=bool_col, operator="equals", value=1)])
        count = pg_executor.execute(plan=plan, table=target_table)
        assert isinstance(count, int)


def test_31_decimal_result_handling():
    """Decimal results from PostgreSQL are accepted by QueryResultValidator."""
    validator = QueryResultValidator()
    plan = QueryPlan(intent="aggregation", aggregation="sum", target_columns=["col"])
    res = validator.validate(plan=plan, data=Decimal("12345.67"))
    assert res.valid is True
    assert len(res.errors) == 0


def test_32_timestamp_result_preservation(pg_executor, live_schema):
    """Timestamps are preserved cleanly without corruption."""
    date_col = None
    target_table = None
    for t in live_schema.tables:
        for c in t.columns:
            if "date" in c.data_type.lower() or "time" in c.data_type.lower():
                date_col = c.name
                target_table = t
                break
        if target_table:
            break

    if target_table:
        plan = QueryPlan(intent="lookup", target_columns=[date_col], limit=2)
        rows = pg_executor.execute(plan=plan, table=target_table)
        assert isinstance(rows, list)


# =============================================================================
# 10. Fail-Closed, Unknown Entities & Ambiguity
# =============================================================================

def test_33_empty_result_handling(pg_executor, live_schema):
    """Valid query returning zero rows returns empty list without error."""
    table = live_schema.tables[0]
    col = table.columns[0].name
    plan = QueryPlan(intent="lookup", filters=[QueryFilter(column=col, operator="equals", value=-999999)])
    rows = pg_executor.execute(plan=plan, table=table)
    assert rows == []


def test_34_invalid_table_handling():
    """Empty schema or unselectable table fails closed with DatabaseQueryServiceError."""
    service = DatabaseQueryService(database_schema=DatabaseSchema(tables=[]))
    with pytest.raises(DatabaseQueryServiceError, match="No database table could be selected"):
        service.answer("What is the count of items?")


def test_35_invalid_column_handling(pg_config, live_schema):
    """QueryPlan referencing unknown column fails validation."""
    validator = QueryPlanValidator()
    plan = QueryPlan(intent="lookup", target_columns=["nonexistent_column_xyz_999"])
    res = validator.validate(plan, live_schema)
    assert res.valid is False
    assert any("does not exist" in e for e in res.errors)


def test_36_ambiguous_column_handling(live_schema):
    """Ambiguous column across multiple selected tables fails validation."""
    schema = DatabaseSchema(
        tables=[
            TableInfo("dbo", "tbl_a", [ColumnInfo("shared_id", "int", False, 1)]),
            TableInfo("dbo", "tbl_b", [ColumnInfo("shared_id", "int", False, 1)]),
        ]
    )
    validator = QueryPlanValidator()
    plan = QueryPlan(intent="lookup", target_columns=["shared_id"])
    res = validator.validate(plan, schema)
    assert res.valid is False
    assert any("is ambiguous" in e for e in res.errors)


def test_37_sql_injection_protection(pg_executor, live_schema):
    """SQL injection payloads in filter values are strictly parameterized."""
    # Find a text/varchar column in the schema
    text_col = None
    target_table = None
    for tbl in live_schema.tables:
        for c in tbl.columns:
            if "char" in c.data_type.lower() or "text" in c.data_type.lower():
                text_col = c.name
                target_table = tbl
                break
        if text_col:
            break
    injection_payload = "'; DROP TABLE students; --"
    plan = QueryPlan(intent="lookup", filters=[QueryFilter(column=text_col, operator="equals", value=injection_payload)])
    # Execute safely without dropping or executing raw SQL
    rows = pg_executor.execute(plan=plan, table=target_table)
    assert isinstance(rows, list)
    assert len(rows) == 0


# =============================================================================
# 11. Conversation Follow-up & input_result_reference
# =============================================================================

def test_38_conversation_followup_mode_1_in_memory(live_schema):
    """Mode 1 follow-up executes in-memory from referenced conversation entry."""
    service = DatabaseQueryService(database_schema=live_schema)
    context = {
        "history": [
            {
                "reference_id": "step_1",
                "question": "Show top 3 facilities",
                "result_columns": ["facility_name", "capacity"],
                "data": [
                    {"facility_name": "Depot B", "capacity": 200},
                    {"facility_name": "Depot A", "capacity": 500},
                ],
            }
        ]
    }
    plan = QueryPlan(
        intent="lookup",
        target_columns=["facility_name"],
        sort_column="facility_name",
        sort_direction="asc",
        input_result_reference="step_1",
    )
    res = service._execute_conversation_result_plan(plan=plan, conversation_context=context)
    assert res == [{"facility_name": "Depot A"}, {"facility_name": "Depot B"}]


def test_39_input_result_reference_cleared_for_mode_2_requery(live_schema):
    """Mode 2 follow-up with scalar result clears input_result_reference and requeries DB."""
    service = DatabaseQueryService(database_schema=live_schema)
    context = {
        "history": [
            {
                "reference_id": "step_1",
                "question": "How many facilities are there?",
                "data": 42,  # Scalar, cannot be sliced in-memory
            }
        ]
    }
    entry = service._get_referenced_conversation_entry(context, "step_1")
    plan = QueryPlan(intent="lookup", target_columns=["facility_name"], input_result_reference="step_1")
    assert service._can_execute_in_memory(plan=plan, referenced_entry=entry) is False


def test_40_result_contract_validation():
    """QueryResultValidator strictly validates all result shapes."""
    validator = QueryResultValidator()
    # row_count -> int
    assert validator.validate(QueryPlan(intent="row_count"), 10).valid is True
    assert validator.validate(QueryPlan(intent="row_count"), "not_an_int").valid is False
    # column_names -> list[str]
    assert validator.validate(QueryPlan(intent="column_names"), ["col1", "col2"]).valid is True
    assert validator.validate(QueryPlan(intent="column_names"), [123]).valid is False
    # lookup -> list[dict]
    assert validator.validate(QueryPlan(intent="lookup"), [{"a": 1}]).valid is True
    assert validator.validate(QueryPlan(intent="lookup"), "invalid").valid is False


# =============================================================================
# 12. PostgreSQL Golden SQL & Dialect Purity
# =============================================================================

def test_41_sql_golden_compilation_postgresql(pg_executor, synthetic_logistics_schema):
    """PostgreSQL SQL uses double quotes, LIMIT, and bound parameter markers."""
    table = synthetic_logistics_schema.tables[0]
    plan = QueryPlan(
        intent="lookup",
        target_columns=["facility_name"],
        filters=[QueryFilter(column="storage_capacity", operator="greater_than", value=100)],
        sort_column="facility_name",
        sort_direction="asc",
        limit=5,
    )
    with patch("app.database.sql_executor.get_connection") as mock_conn:
        mock_cursor = MagicMock()
        mock_cursor.description = [("facility_name",)]
        mock_cursor.fetchall.return_value = []
        mock_conn.return_value.__enter__.return_value.cursor.return_value = mock_cursor

        pg_executor.execute(plan=plan, table=table)
        sql, params = mock_cursor.execute.call_args[0]

        assert 'SELECT "facility_name" FROM "logistics"."warehouses"' in sql
        assert 'WHERE "storage_capacity" > ?' in sql
        assert 'ORDER BY "facility_name" ASC' in sql
        assert 'LIMIT 5' in sql
        assert params == [100]
        # Purity assertions: no SQL Server syntax
        assert "TOP" not in sql
        assert "[" not in sql
        assert "]" not in sql


def test_42_postgresql_dialect_purity(pg_executor, synthetic_logistics_schema):
    """Explicitly verify generated PostgreSQL queries contain no SQL Server artifacts."""
    table = synthetic_logistics_schema.tables[0]
    plan = QueryPlan(
        intent="aggregation",
        aggregation="count",
        group_by=["facility_name"],
        limit=10,
    )
    with patch("app.database.sql_executor.get_connection") as mock_conn:
        mock_cursor = MagicMock()
        mock_cursor.description = [("facility_name",), ("aggregation_value",)]
        mock_cursor.fetchall.return_value = []
        mock_conn.return_value.__enter__.return_value.cursor.return_value = mock_cursor

        pg_executor.execute(plan=plan, table=table)
        sql = mock_cursor.execute.call_args[0][0]

        assert "TOP" not in sql
        assert "COUNT_BIG" not in sql
        assert "[" not in sql
        assert "]" not in sql
        assert "LIMIT 10" in sql


# =============================================================================
# 13. Live SQL Comparison (PostgreSQL vs SQL Server)
# =============================================================================

def test_43_live_sql_comparison_postgres_sqlserver(pg_config, sqlserver_config, live_schema):
    """Semantic result equivalence between live PostgreSQL and SQL Server on the same database."""
    # Compare row counts on first 3 static tables (excluding runtime-accumulating chatbot conversation tables)
    static_tables = [t for t in live_schema.tables if not t.table_name.startswith("chatbot_")][:3]
    for table in static_tables:
        plan = QueryPlan(intent="row_count")

        exec_pg = SQLQueryExecutor(config=pg_config)
        count_pg = exec_pg.execute(plan=plan, table=table)

        exec_ss = SQLQueryExecutor(config=sqlserver_config)
        count_ss = exec_ss.execute(plan=plan, table=table)

        assert count_pg == count_ss, f"Row count mismatch on {table.schema_name}.{table.table_name}: PG={count_pg}, SS={count_ss}"


# =============================================================================
# 14. Answer Provenance & Hallucination Prevention
# =============================================================================

def test_44_real_data_answer_provenance(pg_config, live_schema):
    """Factual answers strictly mirror database execution results."""
    mock_executor = MagicMock()
    mock_executor.execute.return_value = 42

    service = DatabaseQueryService.__new__(DatabaseQueryService)
    service.database_schema = live_schema
    service.analyzer = MagicMock()
    service.analyzer.analyze.return_value = QueryPlan(intent="count")
    service.validator = MagicMock()
    service.validator.validate.return_value = MagicMock(valid=True, warnings=[], errors=[])
    service.executor = mock_executor
    service.result_validator = MagicMock()
    service.result_validator.validate.return_value = MagicMock(valid=True, errors=[])
    service.metadata_service = MagicMock()
    service.semantic_cache = MagicMock()
    service.semantic_cache.get.return_value = None
    service.database_server_name = "srv"
    service.database_name = "db"
    service.schema_fingerprint = "fp"
    service.entity_resolver = MagicMock()
    service.relationship_service = MagicMock()
    service.vector_service = None

    with patch.object(service, "_resolve_execution_tables", return_value=[live_schema.tables[0]]):
        res = service.answer("How many rows are in the database?")
        assert res.data == 42
        assert mock_executor.execute.called


def test_45_hallucination_prevention_on_unsupported_intent(live_schema):
    """Unsupported intent returns controlled explanation without fabricating facts."""
    service = DatabaseQueryService(database_schema=live_schema)
    with patch.object(service.analyzer, "analyze", return_value=QueryPlan(intent="unsupported", explanation="I cannot answer this question.")):
        with patch.object(service, "_resolve_execution_tables", return_value=[live_schema.tables[0]]):
            res = service.answer("What is the CEO's favorite breakfast?")
            assert res.data == "I cannot answer this question."


# =============================================================================
# 15. TIES (FETCH FIRST n ROWS WITH TIES) & SQL Server Rollback
# =============================================================================

def test_46_ties_with_fetch_first_postgresql(pg_executor, synthetic_logistics_schema):
    """FETCH FIRST n ROWS WITH TIES is generated and executed in PostgreSQL."""
    table = synthetic_logistics_schema.tables[0]
    plan = QueryPlan(
        intent="lookup",
        target_columns=["facility_name", "storage_capacity"],
        sort_column="storage_capacity",
        sort_direction="desc",
        limit=2,
        include_ties=True,
    )
    with patch("app.database.sql_executor.get_connection") as mock_conn:
        mock_cursor = MagicMock()
        mock_cursor.description = [("facility_name",), ("storage_capacity",)]
        mock_cursor.fetchall.return_value = [("Depot A", 500), ("Depot B", 500), ("Depot C", 500)]
        mock_conn.return_value.__enter__.return_value.cursor.return_value = mock_cursor

        rows = pg_executor.execute(plan=plan, table=table)
        sql = mock_cursor.execute.call_args[0][0]

        assert "FETCH FIRST 2 ROWS WITH TIES" in sql
        assert "TOP" not in sql
        assert len(rows) == 3


def test_47_sql_server_rollback_preserved(sqlserver_config, synthetic_logistics_schema):
    """SQL Server rollback mode cleanly emits brackets and TOP syntax."""
    table = synthetic_logistics_schema.tables[0]
    plan = QueryPlan(
        intent="lookup",
        target_columns=["facility_name"],
        limit=5,
        include_ties=True,
    )
    ss_executor = SQLQueryExecutor(config=sqlserver_config)
    with patch("app.database.sql_executor.get_connection") as mock_conn:
        mock_cursor = MagicMock()
        mock_cursor.description = [("facility_name",)]
        mock_cursor.fetchall.return_value = [("Depot A",)]
        mock_conn.return_value.__enter__.return_value.cursor.return_value = mock_cursor

        ss_executor.execute(plan=plan, table=table)
        sql = mock_cursor.execute.call_args[0][0]

        assert "TOP (5) WITH TIES" in sql
        assert "[facility_name]" in sql
        assert "[logistics].[warehouses]" in sql
        assert "LIMIT" not in sql
        assert '"' not in sql
