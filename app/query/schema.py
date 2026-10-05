from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class QueryFilter:
    column: str
    operator: str
    value: Any


@dataclass
class QueryColumn:
    """
    Identifies a database column.

    For single-table queries, schema/table can be omitted.
    For multi-table queries, schema and table can be supplied
    to remove column ambiguity.
    """

    column: str
    schema: Optional[str] = None
    table: Optional[str] = None


@dataclass
class QueryJoin:
    """
    Describes one generic JOIN between two database tables.

    This contains structural information only.
    It does not contain hard-coded business/domain logic.
    """

    left_schema: str
    left_table: str
    left_column: str

    right_schema: str
    right_table: str
    right_column: str

    join_type: str = "inner"


@dataclass
class QueryPlan:
    """
    Structured representation of what the user is asking.

    This is an intermediate representation only.
    It does not execute SQL.
    """

    intent: str

    target_columns: list[str] = field(
        default_factory=list
    )

    filters: list[QueryFilter] = field(
        default_factory=list
    )

    having_filters: list[QueryFilter] = field(
        default_factory=list
    )

    group_by: list[str] = field(
        default_factory=list
    )

    aggregation: Optional[str] = None
    inner_aggregation: Optional[str] = None

    sort_column: Optional[str] = None

    sort_direction: Optional[str] = None

    limit: Optional[int] = None

    include_ties: bool = False

    distinct: bool = False

    # When true, all specified values of the same filter dimension
    # must be present within each grouped result.
    require_all_filter_values: bool = False

    input_result_reference: Optional[str] = None

    explanation: str = ""

    confidence: float = 0.0

    # ----------------------------------------------------------
    # Multi-table query support
    # ----------------------------------------------------------

    joins: list[QueryJoin] = field(
        default_factory=list
    )

    # ----------------------------------------------------------
    # Qualified column references
    # ----------------------------------------------------------

    target_column_refs: list[QueryColumn] = field(
        default_factory=list
    )

    group_by_refs: list[QueryColumn] = field(
        default_factory=list
    )

    # ----------------------------------------------------------
    # Time grouping metadata
    # ----------------------------------------------------------
    # Used when a GROUP BY dimension is a date/time column and
    # the user asks for a specific temporal granularity such as
    # day, week, month, quarter, or year.
    #
    # This contains semantic query information only. It does not
    # contain any database-specific table or column names.
    #
    group_by_granularity: Optional[str] = None