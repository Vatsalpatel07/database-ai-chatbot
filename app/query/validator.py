from dataclasses import dataclass, field
from typing import Any

from app.database.schema import DatabaseSchema
from app.query.schema import QueryPlan, QueryColumn


@dataclass
class ValidationResult:
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class QueryPlanValidator:
    """
    Validates a QueryPlan against the SQL Server database schema.

    This class does not execute queries.
    """

    VALID_INTENTS = {
        "lookup",
        "distinct",
        "count",
        "aggregation",
        "derived_aggregation",
        "filter",
        "ranking",
        "comparison",
        "existence",
        "percentage",
        "row_count",
        "column_count",
        "column_names",
        "unsupported",
    }

    VALID_AGGREGATIONS = {
        "sum",
        "average",
        "min",
        "max",
        "count",
        "median",
    }

    VALID_OPERATORS = {
        "equals",
        "not_equals",
        "greater_than",
        "greater_than_or_equal",
        "less_than",
        "less_than_or_equal",
        "contains",
        "starts_with",
        "ends_with",
        "in",
        "is_null",
        "is_not_null",
    }

    VALID_HAVING_OPERATORS = {
        "equals",
        "not_equals",
        "greater_than",
        "greater_than_or_equal",
        "less_than",
        "less_than_or_equal",
    }

    VALID_SORT_DIRECTIONS = {
        "asc",
        "desc",
    }

    VIRTUAL_AGGREGATE_COLUMNS = {
        "sum",
        "average",
        "min",
        "max",
        "count",
        "median",
    }

    NUMERIC_DATA_TYPES = {
        "bigint",
        "decimal",
        "double precision",
        "float",
        "int",
        "integer",
        "money",
        "numeric",
        "real",
        "smallint",
        "smallmoney",
        "tinyint",
        "serial",
        "bigserial",
        "smallserial",
    }

    def validate(
        self,
        plan: QueryPlan,
        database_schema: DatabaseSchema,
    ) -> ValidationResult:
        errors: list[str] = []
        warnings: list[str] = []

        columns = self._get_columns(database_schema)
        column_names = set(columns.keys())

        # --------------------------------------------------
        # Intent
        # --------------------------------------------------

        if plan.intent not in self.VALID_INTENTS:
            errors.append(
                f"Unsupported intent: {plan.intent}"
            )

        if plan.intent == "unsupported":
            errors.append(
                "The question could not be reliably "
                "mapped to the database."
            )

        # --------------------------------------------------
        # Target columns
        # --------------------------------------------------

        for column in plan.target_columns:
            res = database_schema.resolve_column(
                column,
                explicit_refs=getattr(plan, "target_column_refs", []),
            )
            if res.is_ambiguous:
                errors.append(
                    f"Target column '{column}' is ambiguous across multiple selected tables: "
                    + ", ".join(sorted(f"{s}.{t}" for s, t in res.matching_tables))
                )
            elif res.error:
                if res.error.startswith("Table "):
                    errors.append(res.error)
                else:
                    errors.append(f"Target column does not exist: {column}")

        # --------------------------------------------------
        # Group-by columns
        # --------------------------------------------------

        for column in plan.group_by:
            res = database_schema.resolve_column(
                column,
                explicit_refs=getattr(plan, "group_by_refs", []),
            )
            if res.is_ambiguous:
                errors.append(
                    f"Group-by column '{column}' is ambiguous across multiple selected tables: "
                    + ", ".join(sorted(f"{s}.{t}" for s, t in res.matching_tables))
                )
            elif res.error:
                if res.error.startswith("Table "):
                    errors.append(res.error)
                else:
                    errors.append(f"Group-by column does not exist: {column}")

        # --------------------------------------------------
        # Qualified target-column references
        # --------------------------------------------------

        errors.extend(
            self._validate_qualified_column_refs(
                getattr(plan, "target_column_refs", []),
                database_schema,
                "Target column reference",
            )
        )

        # --------------------------------------------------
        # Qualified group-by references
        # --------------------------------------------------

        errors.extend(
            self._validate_qualified_column_refs(
                getattr(plan, "group_by_refs", []),
                database_schema,
                "Group-by column reference",
            )
        )

        # --------------------------------------------------
        # Filters
        # --------------------------------------------------

        for filter_item in plan.filters:
            res = database_schema.resolve_column(
                filter_item.column,
            )
            if res.is_ambiguous:
                errors.append(
                    f"Filter column '{filter_item.column}' is ambiguous across multiple selected tables: "
                    + ", ".join(sorted(f"{s}.{t}" for s, t in res.matching_tables))
                )
            elif res.error:
                if res.error.startswith("Table "):
                    errors.append(res.error)
                else:
                    errors.append(f"Filter column does not exist: {filter_item.column}")

            if filter_item.operator not in self.VALID_OPERATORS:
                errors.append(
                    "Unsupported filter operator: "
                    f"{filter_item.operator}"
                )

        # --------------------------------------------------
        # Having filters
        # --------------------------------------------------

        having_filters = getattr(plan, "having_filters", []) or []

        if having_filters:
            if plan.aggregation is None:
                errors.append(
                    "HAVING filter requires an aggregation function."
                )
            elif plan.aggregation == "median":
                errors.append(
                    "HAVING filters are not supported for median "
                    "grouped aggregation."
                )
            elif plan.aggregation not in self.VALID_AGGREGATIONS:
                errors.append(
                    f"Unsupported aggregation for HAVING filter: "
                    f"{plan.aggregation}"
                )
            elif plan.aggregation != "count" and not plan.target_columns:
                errors.append(
                    "HAVING filter with non-count aggregation requires "
                    "at least one target column."
                )

            if not plan.group_by:
                errors.append(
                    "HAVING filter requires at least one group-by column."
                )

            valid_having_columns = (
                column_names
                | self.VIRTUAL_AGGREGATE_COLUMNS
                | set(plan.target_columns)
                | set(plan.group_by)
                | {"aggregation_value"}
            )

            for having_item in having_filters:
                having_col = getattr(having_item, "column", None)
                if not having_col:
                    errors.append(
                        "HAVING filter missing column."
                    )
                    continue

                if (
                    having_col in self.VIRTUAL_AGGREGATE_COLUMNS
                    or having_col == "aggregation_value"
                    or (plan.aggregation and having_col == plan.aggregation)
                    or having_col in plan.target_columns
                    or having_col in plan.group_by
                ):
                    pass
                else:
                    res = database_schema.resolve_column(
                        having_col,
                        explicit_refs=(getattr(plan, "target_column_refs", []) + getattr(plan, "group_by_refs", [])),
                    )
                    if res.is_ambiguous:
                        errors.append(
                            f"HAVING filter column '{having_col}' is ambiguous across multiple selected tables: "
                            + ", ".join(sorted(f"{s}.{t}" for s, t in res.matching_tables))
                        )
                    elif res.error:
                        errors.append(
                            f"HAVING filter column does not exist: {having_col}"
                        )

                having_op = getattr(having_item, "operator", None)
                if having_op not in self.VALID_OPERATORS:
                    errors.append(
                        f"Unsupported filter operator: {having_op}"
                    )
                elif having_op not in self.VALID_HAVING_OPERATORS:
                    errors.append(
                        f"HAVING filter operator '{having_op}' is not "
                        "supported for aggregate filtering."
                    )

                having_val = getattr(having_item, "value", None)
                if (
                    having_val is None
                    or (isinstance(having_val, str) and not having_val.strip())
                ):
                    errors.append(
                        "HAVING filter requires a non-empty value for "
                        f"column '{having_col}'."
                    )
                elif not isinstance(having_val, (int, float, str)):
                    errors.append(
                        "HAVING filter value must be a scalar number or string, "
                        f"got {type(having_val).__name__}."
                    )

        # --------------------------------------------------
        # Derived Aggregation
        # --------------------------------------------------

        if plan.intent == "derived_aggregation":
            if not plan.aggregation:
                errors.append(
                    "Derived aggregation requires an outer aggregation function."
                )
            elif plan.aggregation not in self.VALID_AGGREGATIONS:
                errors.append(
                    f"Unsupported outer aggregation: {plan.aggregation}"
                )

            inner_agg = plan.inner_aggregation or "count"
            if inner_agg not in self.VALID_AGGREGATIONS:
                errors.append(
                    f"Unsupported inner aggregation: {inner_agg}"
                )

            if not plan.group_by:
                errors.append(
                    "Derived aggregation requires at least one group-by column."
                )

            if inner_agg != "count":
                if not plan.target_columns:
                    errors.append(
                        f"Derived aggregation with inner '{inner_agg}' requires "
                        "at least one target column."
                    )
                else:
                    for column in plan.target_columns:
                        res = database_schema.resolve_column(
                            column,
                            explicit_refs=getattr(plan, "target_column_refs", []),
                        )
                        if res.resolved and not self._is_numeric_type(res.resolved.data_type):
                            errors.append(
                                f"Inner aggregation '{inner_agg}' requires "
                                f"a numeric column, but '{column}' has SQL Server data type "
                                f"'{res.resolved.data_type}'."
                            )

        # --------------------------------------------------
        # Aggregation
        # --------------------------------------------------

        elif plan.aggregation is not None:

            # Percentage is a dedicated query intent,
            # not a normal SQL aggregation function.
            if (
                plan.intent == "percentage"
                and plan.aggregation == "percentage"
            ):
                pass

            elif plan.aggregation not in self.VALID_AGGREGATIONS:
                errors.append(
                    "Unsupported aggregation: "
                    f"{plan.aggregation}"
                )

            elif (
                plan.aggregation != "count"
                and not plan.target_columns
            ):
                errors.append(
                    "Aggregation requires at least "
                    "one target column."
                )

            elif plan.aggregation != "count":
                for column in plan.target_columns:
                    res = database_schema.resolve_column(
                        column,
                        explicit_refs=getattr(plan, "target_column_refs", []),
                    )
                    if res.resolved and not self._is_numeric_type(res.resolved.data_type):
                        errors.append(
                            f"Aggregation "
                            f"'{plan.aggregation}' requires "
                            f"a numeric column, but "
                            f"'{column}' has SQL Server data type "
                            f"'{res.resolved.data_type}'."
                        )

        # --------------------------------------------------
        # Ranking
        # --------------------------------------------------

        if plan.intent == "ranking":
            if not plan.sort_column:
                errors.append(
                    "Ranking requires a sort column."
                )

            if (
                plan.sort_direction
                and plan.sort_direction
                not in self.VALID_SORT_DIRECTIONS
            ):
                errors.append(
                    "Invalid sort direction: "
                    f"{plan.sort_direction}"
                )

        # --------------------------------------------------
        # Sort column
        # --------------------------------------------------

        if plan.sort_column:
            sort_column = plan.sort_column

            # Grouped aggregation produces a virtual result column
            if (
                (
                    sort_column in self.VIRTUAL_AGGREGATE_COLUMNS
                    or sort_column == "aggregation_value"
                    or (plan.aggregation and sort_column == plan.aggregation)
                )
                and (plan.intent in {"aggregation", "ranking"} or plan.aggregation)
            ):
                pass
            elif (
                plan.intent in {"aggregation", "ranking"}
                and plan.aggregation
                and sort_column in plan.target_columns
            ):
                pass
            else:
                res = database_schema.resolve_column(
                    sort_column,
                    explicit_refs=(getattr(plan, "target_column_refs", []) + getattr(plan, "group_by_refs", [])),
                )
                if res.is_ambiguous:
                    errors.append(
                        f"Sort column '{sort_column}' is ambiguous across multiple selected tables: "
                        + ", ".join(sorted(f"{s}.{t}" for s, t in res.matching_tables))
                    )
                elif res.error:
                    if res.error.startswith("Table "):
                        errors.append(res.error)
                    else:
                        errors.append(f"Sort column does not exist: {sort_column}")

        # --------------------------------------------------
        # Sort direction
        # --------------------------------------------------

        if (
            plan.sort_direction
            and plan.sort_direction
            not in self.VALID_SORT_DIRECTIONS
        ):
            errors.append(
                "Invalid sort direction: "
                f"{plan.sort_direction}"
            )

        # --------------------------------------------------
        # Limit
        # --------------------------------------------------

        if plan.limit is not None:
            if plan.limit <= 0:
                errors.append(
                    "Limit must be greater than zero."
                )

        # --------------------------------------------------
        # Confidence
        # --------------------------------------------------

        if plan.confidence < 0.50:
            warnings.append(
                "Question interpretation has low "
                f"confidence ({plan.confidence:.2f})."
            )

        elif plan.confidence < 0.75:
            warnings.append(
                "Question interpretation has moderate "
                f"confidence ({plan.confidence:.2f})."
            )

        return ValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
        )

    @staticmethod
    def _validate_qualified_column_refs(
        refs: list[QueryColumn],
        database_schema: Any,
        field_name: str,
    ) -> list[str]:
        """
        Validate qualified schema.table.column references.

        Qualified references are used when a query involves multiple
        tables and the same column name may exist in more than one table.
        """

        errors: list[str] = []

        tables = getattr(database_schema, "tables", [])

        table_lookup = {
            (
                str(table.schema_name).lower(),
                str(table.table_name).lower(),
            ): table
            for table in tables
        }

        for ref in refs or []:
            schema_name = str(ref.schema).strip() if ref.schema else ""
            table_name = str(ref.table).strip() if ref.table else ""
            column_name = str(ref.column).strip() if ref.column else ""

            if not table_name or not column_name:
                errors.append(
                    f"{field_name} contains an incomplete qualified column reference."
                )
                continue

            if schema_name:
                table = table_lookup.get(
                    (
                        schema_name.lower(),
                        table_name.lower(),
                    )
                )
            else:
                matches = [t for t in tables if t.table_name.lower() == table_name.lower()]
                table = matches[0] if matches else None

            if table is None:
                disp = f"{schema_name}.{table_name}" if schema_name else table_name
                errors.append(
                    f"{field_name} references a table that does not exist: "
                    f"{disp}"
                )
                continue

            table_columns = {
                str(column.name).lower()
                for column in table.columns
            }

            if column_name.lower() not in table_columns:
                disp = (
                    f"{table.schema_name}.{table.table_name}.{column_name}"
                    if table.schema_name
                    else f"{table.table_name}.{column_name}"
                )
                errors.append(
                    f"{field_name} references a column that does not exist: "
                    f"{disp}"
                )

        return errors

    @staticmethod
    def _get_columns(
        database_schema: DatabaseSchema,
    ) -> dict[str, dict[str, Any]]:
        """
        Build a database-wide column lookup.

        The query layer currently represents columns by name only.
        Table-aware resolution will be added when SQL query planning
        is migrated.
        """

        columns: dict[str, dict[str, Any]] = {}

        for table in database_schema.tables:
            for column in table.columns:
                # Keep the first occurrence for now.
                #
                # The current QueryPlan represents columns only by
                # name, not schema.table.column. Table-aware
                # resolution will be handled by the SQL planning
                # layer.
                if column.name not in columns:
                    columns[column.name] = {
                        "schema": table.schema_name,
                        "table": table.table_name,
                        "data_type": column.data_type,
                        "nullable": column.nullable,
                    }

        return columns

    @classmethod
    def _is_numeric_type(
        cls,
        data_type: str,
    ) -> bool:
        return data_type.lower() in cls.NUMERIC_DATA_TYPES