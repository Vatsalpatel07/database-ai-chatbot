from unittest.mock import MagicMock, patch

from app.database.schema import ColumnInfo, TableInfo
from app.database.sql_executor import SQLQueryExecutor
from app.query.schema import QueryFilter, QueryPlan

 
def test_grouped_count_uses_count_star():
    """
    Regression test for Phase 8B.

    A grouped COUNT query must count rows in each group.
    It must not COUNT(DISTINCT <grouping_column>), which
    incorrectly returns 1 for every non-null group.
    """

    connection = MagicMock()
    cursor = MagicMock()

    cursor.description = [
        ("event_sitecore_id",),
        ("aggregation_value",),
    ]

    cursor.fetchall.return_value = [
        ("EVENT-A", 3),
        ("EVENT-B", 2),
        ("EVENT-C", 1),
    ]

    connection.cursor.return_value = cursor

    plan = QueryPlan(
        intent="aggregation",
        target_columns=["event_sitecore_id"],
        group_by=["event_sitecore_id"],
        aggregation="count",
    )

    table = TableInfo(
        schema_name="dbo",
        table_name="site_event_leads",
        columns=[
            ColumnInfo(
                name="event_sitecore_id",
                data_type="uniqueidentifier",
                nullable=False,
                ordinal_position=1,
            )
        ],
    )

    with patch(
        "app.database.sql_executor.get_connection"
    ) as mock_get_connection:

        mock_get_connection.return_value.__enter__.return_value = connection

        executor = SQLQueryExecutor()

        result = executor.execute(
            plan=plan,
            table=table,
        )

    executed_sql = cursor.execute.call_args[0][0]

    assert "COUNT(*)" in executed_sql
    assert "COUNT(DISTINCT" not in executed_sql

    assert result == [
        {
            "event_sitecore_id": "EVENT-A",
            "aggregation_value": 3,
        },
        {
            "event_sitecore_id": "EVENT-B",
            "aggregation_value": 2,
        },
        {
            "event_sitecore_id": "EVENT-C",
            "aggregation_value": 1,
        },
    ]

def test_grouped_count_supports_having_filter():
    """
    Regression test for Phase 8B.

    An aggregate filter such as COUNT(*) > 50 must be
    translated into a SQL HAVING condition rather than
    a WHERE condition.
    """

    connection = MagicMock()
    cursor = MagicMock()

    cursor.description = [
        ("event_status",),
        ("aggregation_value",),
    ]

    cursor.fetchall.return_value = [
        ("Active", 70),
        ("Completed", 87),
    ]

    connection.cursor.return_value = cursor

    plan = QueryPlan(
        intent="aggregation",
        target_columns=["event_sitecore_id"],
        group_by=["event_status"],
        aggregation="count",
        having_filters=[
            QueryFilter(
                column="count",
                operator="greater_than",
                value=50,
            )
        ],
    )

    table = TableInfo(
        schema_name="dbo",
        table_name="site_events",
        columns=[
            ColumnInfo(
                name="event_sitecore_id",
                data_type="uniqueidentifier",
                nullable=False,
                ordinal_position=1,
            ),
            ColumnInfo(
                name="event_status",
                data_type="nvarchar",
                nullable=True,
                ordinal_position=2,
            ),
        ],
    )

    with patch(
        "app.database.sql_executor.get_connection"
    ) as mock_get_connection:

        mock_get_connection.return_value.__enter__.return_value = connection

        executor = SQLQueryExecutor()

        result = executor.execute(
            plan=plan,
            table=table,
        )

    executed_sql = cursor.execute.call_args[0][0]
    executed_parameters = cursor.execute.call_args[0][1]

    assert "HAVING COUNT(*) > ?" in executed_sql
    assert "WHERE" not in executed_sql
    assert executed_parameters == [50]

    assert result == [
        {
            "event_status": "Active",
            "aggregation_value": 70,
        },
        {
            "event_status": "Completed",
            "aggregation_value": 87,
        },
    ]