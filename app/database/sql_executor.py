from __future__ import annotations

from typing import Any
import uuid

from app.core.config import DatabaseConfig
from app.database.connection import get_connection
from app.database.schema import TableInfo, parse_column_reference
from app.query.schema import QueryPlan, QueryColumn, QueryFilter


class SQLQueryExecutionError(Exception):
    """Raised when a SQL QueryPlan cannot be executed safely."""


class SQLQueryTimeoutError(SQLQueryExecutionError):
    """Raised when a query exceeds the configured statement execution timeout."""


class SQLQueryExecutor:
    """
    Executes validated QueryPlans against the configured database engine (PostgreSQL or SQL Server).

    Currently supports:
    - row_count
    - column_count
    - column_names
    - lookup
    - count
    - aggregation (sum, average, min, max, median)
    - grouped aggregation
    - sorting
    """

    MAX_LOOKUP_ROWS: int = 5000

    def __init__(self, config: DatabaseConfig | None = None) -> None:
        self.config = config

    def _handle_execution_exception(self, exc: Exception) -> None:
        """Categorize database execution failures and map timeouts to SQLQueryTimeoutError."""
        err_msg = str(exc)
        err_lower = err_msg.lower()
        if (
            "statement timeout" in err_lower
            or "canceling statement due to statement timeout" in err_lower
            or "querycanceled" in err_lower
            or "query execution timed out" in err_lower
            or "query timed out" in err_lower
        ):
            timeout_sec = getattr(self.config, "query_timeout", None) or getattr(self.config, "connection_timeout", 30) or 30
            raise SQLQueryTimeoutError(
                f"SQL query execution timed out after {timeout_sec}s: {exc}"
            ) from exc
        raise SQLQueryExecutionError(
            f"SQL query execution failed: {exc}"
        ) from exc

    @property
    def is_postgresql(self) -> bool:
        if self.config is not None:
            return self.config.is_postgresql
        return False

    @staticmethod
    def quote_identifier(identifier: str, is_postgresql: bool = False) -> str:
        if not identifier:
            raise SQLQueryExecutionError("SQL identifier cannot be empty.")
        if is_postgresql:
            return '"' + identifier.replace('"', '""') + '"'
        return "[" + identifier.replace("]", "]]") + "]"

    def _quote_identifier(self_or_ident: Any, identifier: str | None = None) -> str:
        if isinstance(self_or_ident, SQLQueryExecutor):
            if not identifier:
                raise SQLQueryExecutionError("SQL identifier cannot be empty.")
            return SQLQueryExecutor.quote_identifier(identifier, is_postgresql=self_or_ident.is_postgresql)

        ident = self_or_ident
        if not ident:
            raise SQLQueryExecutionError("SQL identifier cannot be empty.")
        return SQLQueryExecutor.quote_identifier(ident, is_postgresql=False)

    def execute(
        self,
        plan: QueryPlan,
        table: TableInfo,
        tables: list[TableInfo] | None = None,
    ) -> Any:

        # ------------------------------------------------------
        # Multi-table execution
        # ------------------------------------------------------
        #
        # A QueryPlan containing joins requires the complete set
        # of tables selected for the question.
        #
        # Existing single-table callers remain compatible because
        # `tables` is optional.
        # ------------------------------------------------------

        if plan.intent == "derived_aggregation":
            return self._execute_derived_aggregation(
                plan=plan,
                table=table,
                tables=tables,
            )

        if plan.joins:
            execution_tables = tables or [table]

            return self._execute_joined_query(
                plan=plan,
                tables=execution_tables,
            )

        # ------------------------------------------------------
        # Existing single-table execution
        # ------------------------------------------------------

        if plan.intent == "row_count":
            return self._execute_row_count(plan, table)

        if plan.intent == "column_count":
            return self._execute_column_count(table)

        if plan.intent == "column_names":
            return self._execute_column_names(table)

        if plan.intent in ("lookup", "distinct", "ranking"):
            return self._execute_lookup(plan, table)

        if plan.intent == "count":
            return self._execute_count(plan, table)

        if plan.intent == "percentage":
            return self._execute_percentage(plan, table)

        if plan.intent == "aggregation":
            if plan.group_by:
                return self._execute_grouped_aggregation(
                    plan,
                    table,
                )

            return self._execute_aggregation(
                plan,
                table,
            )

        raise SQLQueryExecutionError(
            "Unsupported query intent for the initial SQL executor."
        )

    @staticmethod
    def _get_entity_identifying_columns(table: TableInfo) -> list[str]:
        """
        Derive the identifying column(s) that define row/entity grain for a table.
        Generic across arbitrary SQL Server schemas without hardcoded table/column names.
        """
        if table.primary_key_columns:
            return list(table.primary_key_columns)

        cols_lower = {c.name.lower(): c.name for c in table.columns}
        if "id" in cols_lower:
            return [cols_lower["id"]]

        t_name = table.table_name.lower()
        t_singular = t_name.rstrip("s")
        for candidate in [
            f"{t_name}_id",
            f"{t_singular}_id",
            f"{t_name}_sitecore_id",
            f"{t_singular}_sitecore_id",
            f"{t_name}id",
            f"{t_singular}id",
        ]:
            if candidate in cols_lower:
                return [cols_lower[candidate]]

        id_cols = [
            c.name for c in table.columns
            if c.name.lower().endswith(("_id", "_sitecore_id", "_key"))
        ]
        if id_cols:
            return id_cols

        guid_cols = [
            c.name for c in table.columns
            if c.data_type.lower() == "uniqueidentifier"
        ]
        if guid_cols:
            return guid_cols

        return [c.name for c in table.columns]

    def _execute_joined_query(
        self,
        plan: QueryPlan,
        tables: list[TableInfo],
    ) -> Any:
        """
        Execute a QueryPlan containing one or more JOINs.

        Supports:
        - target columns
        - filters
        - aggregation
        - GROUP BY
        - sorting
        - LIMIT

        JOIN structure comes entirely from QueryPlan.joins.
        No business-specific table or column names are hardcoded.
        """

        if not plan.joins:
            raise SQLQueryExecutionError(
                "Joined execution requires at least one JOIN."
            )

        if not tables:
            raise SQLQueryExecutionError(
                "Joined execution requires at least one table."
            )

        table_lookup = {
            (table.schema_name, table.table_name): table
            for table in tables
        }

        # ---------------------------------------------------------
        # Validate the JOIN graph and build aliases.
        # ---------------------------------------------------------

        aliases: dict[tuple[str, str], str] = {}
        joined_keys: set[tuple[str, str]] = set()
        join_sql_parts: list[str] = []

        def ensure_table_exists(
            key: tuple[str, str],
        ) -> TableInfo:
            table = table_lookup.get(key)

            if table is None:
                raise SQLQueryExecutionError(
                    "JOIN references a table that was not selected: "
                    f"{key[0]}.{key[1]}"
                )

            return table

        first_join = plan.joins[0]

        first_left_key = (
            first_join.left_schema,
            first_join.left_table,
        )
        ensure_table_exists(first_left_key)

        aliases[first_left_key] = "t1"
        joined_keys.add(first_left_key)

        next_alias_number = 2

        for join in plan.joins:
            left_key = (
                join.left_schema,
                join.left_table,
            )
            right_key = (
                join.right_schema,
                join.right_table,
            )

            left_table = ensure_table_exists(left_key)
            right_table = ensure_table_exists(right_key)

            left_columns = {
                column.name
                for column in left_table.columns
            }
            right_columns = {
                column.name
                for column in right_table.columns
            }

            if join.left_column not in left_columns:
                raise SQLQueryExecutionError(
                    "JOIN references an unknown left column: "
                    f"{join.left_schema}.{join.left_table}."
                    f"{join.left_column}"
                )

            if join.right_column not in right_columns:
                raise SQLQueryExecutionError(
                    "JOIN references an unknown right column: "
                    f"{join.right_schema}.{join.right_table}."
                    f"{join.right_column}"
                )

            if join.join_type not in {
                "inner",
                "left",
                "right",
            }:
                raise SQLQueryExecutionError(
                    f"Unsupported JOIN type: {join.join_type}"
                )

            left_is_joined = left_key in joined_keys
            right_is_joined = right_key in joined_keys

            # The first JOIN establishes the base relation.
            if not join_sql_parts:
                if not left_is_joined:
                    raise SQLQueryExecutionError(
                        "The first JOIN must reference its left table "
                        "as the base table."
                    )

                if right_is_joined:
                    raise SQLQueryExecutionError(
                        "The first JOIN cannot join two already-selected "
                        "tables without a new table."
                    )

                aliases[right_key] = f"t{next_alias_number}"
                next_alias_number += 1
                joined_keys.add(right_key)

            else:
                # Each subsequent JOIN must extend the existing JOIN graph.
                if left_is_joined and not right_is_joined:
                    aliases[right_key] = f"t{next_alias_number}"
                    next_alias_number += 1
                    joined_keys.add(right_key)

                elif right_is_joined and not left_is_joined:
                    aliases[left_key] = f"t{next_alias_number}"
                    next_alias_number += 1
                    joined_keys.add(left_key)

                elif left_is_joined and right_is_joined:
                    raise SQLQueryExecutionError(
                        "JOIN graph contains a relationship between tables "
                        "that are already joined. The relationship is "
                        "redundant for this query."
                    )

                else:
                    raise SQLQueryExecutionError(
                        "JOIN graph is disconnected. Each JOIN must connect "
                        "to a table already present in the joined query."
                    )

            left_alias = aliases[left_key]
            right_alias = aliases[right_key]

            left_schema = self._quote_identifier(
                left_table.schema_name
            )
            left_table_name = self._quote_identifier(
                left_table.table_name
            )
            right_schema = self._quote_identifier(
                right_table.schema_name
            )
            right_table_name = self._quote_identifier(
                right_table.table_name
            )

            left_join_column = self._quote_identifier(
                join.left_column
            )
            right_join_column = self._quote_identifier(
                join.right_column
            )

            join_keyword = {
                "inner": "INNER JOIN",
                "left": "LEFT JOIN",
                "right": "RIGHT JOIN",
            }[join.join_type]

            if not join_sql_parts:
                join_sql_parts.append(
                    f"FROM {left_schema}.{left_table_name} "
                    f"AS {left_alias} "
                    f"{join_keyword} "
                    f"{right_schema}.{right_table_name} "
                    f"AS {right_alias} "
                    f"ON {left_alias}.{left_join_column} = "
                    f"{right_alias}.{right_join_column}"
                )
            else:
                # Use the newly added table as the JOIN target while
                # preserving the exact relationship orientation supplied
                # by the QueryPlan.
                if right_key not in joined_keys:
                    raise SQLQueryExecutionError(
                        "Internal JOIN graph resolution error."
                    )

                # Determine which table was newly added. The JOIN SQL
                # must always introduce that table to the existing graph.
                # At this point both keys have aliases, so determine the
                # newly introduced table by comparing the aliases to the
                # graph state captured before this JOIN.
                # A simpler safe construction is to use the relationship
                # orientation and require the left side to already exist
                # when the right side is newly introduced, or vice versa.
                #
                # Because aliases were assigned above, both cases can be
                # emitted explicitly.
                if left_key in joined_keys and right_key in joined_keys:
                    # Find whether the current relationship added either
                    # endpoint. This is represented by the highest alias
                    # assigned during this JOIN.
                    new_alias = f"t{next_alias_number - 1}"

                    if aliases[right_key] == new_alias:
                        new_table = right_table
                        new_key = right_key
                        existing_alias = aliases[left_key]
                        new_alias_value = aliases[new_key]

                        join_sql_parts.append(
                            f"{join_keyword} "
                            f"{self._quote_identifier(new_table.schema_name)}."
                            f"{self._quote_identifier(new_table.table_name)} "
                            f"AS {new_alias_value} "
                            f"ON {existing_alias}."
                            f"{self._quote_identifier(join.left_column)} = "
                            f"{new_alias_value}."
                            f"{self._quote_identifier(join.right_column)}"
                        )

                    elif aliases[left_key] == new_alias:
                        new_table = left_table
                        new_key = left_key
                        existing_alias = aliases[right_key]
                        new_alias_value = aliases[new_key]

                        join_sql_parts.append(
                            f"{join_keyword} "
                            f"{self._quote_identifier(new_table.schema_name)}."
                            f"{self._quote_identifier(new_table.table_name)} "
                            f"AS {new_alias_value} "
                            f"ON {new_alias_value}."
                            f"{self._quote_identifier(join.left_column)} = "
                            f"{existing_alias}."
                            f"{self._quote_identifier(join.right_column)}"
                        )
                    else:
                        raise SQLQueryExecutionError(
                            "Internal JOIN alias resolution error."
                        )

        # ---------------------------------------------------------
        # Column resolution across the complete JOIN graph.
        # ---------------------------------------------------------

        table_columns = {
            key: {
                column.name
                for column in table.columns
            }
            for key, table in table_lookup.items()
        }

        def resolve_column(
            column_name: str,
            refs: list[QueryColumn] | None = None,
        ) -> str:
            refs = refs or []
            schema_part, table_part, base_col = parse_column_reference(column_name)

            matching_refs = []
            for ref in refs:
                ref_col = ref.column.lower() if ref.column else ""
                if ref_col == column_name.lower() or ref_col == base_col.lower():
                    if table_part and ref.table and ref.table.lower() != table_part.lower():
                        continue
                    if schema_part and ref.schema and ref.schema.lower() != schema_part.lower():
                        continue
                    matching_refs.append(ref)

            if matching_refs:
                if len(matching_refs) > 1 and table_part:
                    narrowed = [
                        r for r in matching_refs
                        if r.table and r.table.lower() == table_part.lower()
                        and (not schema_part or not r.schema or r.schema.lower() == schema_part.lower())
                    ]
                    if len(narrowed) == 1:
                        matching_refs = narrowed

                if len(matching_refs) > 1:
                    raise SQLQueryExecutionError(
                        "JOIN query contains multiple qualified references "
                        f"for column: {column_name}"
                    )

                ref = matching_refs[0]
                ref_keys = [
                    k for k in joined_keys
                    if k[1].lower() == ref.table.lower()
                    and (not ref.schema or k[0].lower() == ref.schema.lower())
                ]

                if not ref_keys:
                    raise SQLQueryExecutionError(
                        "Qualified column reference points to a table that "
                        "is not part of the JOIN: "
                        f"{ref.schema or ''}.{ref.table}.{ref.column}"
                    )

                ref_key = ref_keys[0]
                actual_col = next((c for c in table_columns[ref_key] if c.lower() == ref.column.lower()), None)
                if not actual_col:
                    raise SQLQueryExecutionError(
                        "Qualified column reference does not exist: "
                        f"{ref.schema or ''}.{ref.table}.{ref.column}"
                    )

                return (
                    f"{aliases[ref_key]}."
                    f"{self._quote_identifier(actual_col)}"
                )

            if table_part:
                matching_keys = [
                    k for k in joined_keys
                    if k[1].lower() == table_part.lower()
                    and (not schema_part or k[0].lower() == schema_part.lower())
                ]
                if not matching_keys:
                    raise SQLQueryExecutionError(
                        f"JOIN query references a table that is not part of the JOIN: {table_part}"
                    )
                target_key = matching_keys[0]
                actual_col = next((c for c in table_columns[target_key] if c.lower() == base_col.lower()), None)
                if not actual_col:
                    raise SQLQueryExecutionError(
                        f"JOIN query references unknown column: {column_name}"
                    )
                return (
                    f"{aliases[target_key]}."
                    f"{self._quote_identifier(actual_col)}"
                )

            matching_tables = [
                key
                for key in joined_keys
                if any(c.lower() == base_col.lower() for c in table_columns[key])
            ]

            if len(matching_tables) > 1:
                raise SQLQueryExecutionError(
                    "JOIN query cannot unambiguously resolve column: "
                    f"{column_name}"
                )

            if not matching_tables:
                raise SQLQueryExecutionError(
                    "JOIN query references an unknown column: "
                    f"{column_name}"
                )

            key = matching_tables[0]
            actual_col = next(c for c in table_columns[key] if c.lower() == base_col.lower())

            return (
                f"{aliases[key]}."
                f"{self._quote_identifier(actual_col)}"
            )

        def get_column_type(
            column_name: str,
            refs: list[QueryColumn] | None = None,
        ) -> str | None:
            refs = refs or []
            schema_part, table_part, base_col = parse_column_reference(column_name)

            matching_refs = []
            for ref in refs:
                ref_col = ref.column.lower() if ref.column else ""
                if ref_col == column_name.lower() or ref_col == base_col.lower():
                    matching_refs.append(ref)

            if matching_refs:
                first_ref = matching_refs[0]
                target_schema = first_ref.schema.lower() if first_ref.schema else None
                target_table = first_ref.table.lower() if first_ref.table else ""
                matched_key = None
                for key in joined_keys:
                    if key[1].lower() == target_table:
                        if target_schema is None or key[0].lower() == target_schema:
                            matched_key = key
                            break
                if matched_key:
                    for c in table_lookup[matched_key].columns:
                        if c.name.lower() == base_col.lower():
                            return c.data_type

            matching_tables = []
            for key in joined_keys:
                if schema_part and key[0].lower() != schema_part.lower():
                    continue
                if table_part and key[1].lower() != table_part.lower():
                    continue
                if any(c.lower() == base_col.lower() for c in table_columns[key]):
                    matching_tables.append(key)

            if len(matching_tables) == 1:
                key = matching_tables[0]
                for c in table_lookup[key].columns:
                    if c.name.lower() == base_col.lower():
                        return c.data_type

            return None

        # ---------------------------------------------------------
        # FROM & WHERE
        # ---------------------------------------------------------

        from_sql = " ".join(join_sql_parts)

        parameters: list[Any] = []
        where_parts: list[str] = []

        for query_filter in plan.filters:
            expression = resolve_column(
                query_filter.column
            )
            col_type = get_column_type(query_filter.column)
            operator = query_filter.operator
            value = query_filter.value

            # NULL checks
            if operator in {"is_null", "null"} or (operator == "equals" and value is None):
                where_parts.append(f"{expression} IS NULL")
                continue

            if operator in {"is_not_null", "not_null"} or (operator == "not_equals" and value is None):
                where_parts.append(f"{expression} IS NOT NULL")
                continue

            value = self._normalize_filter_value(value, col_type)

            if operator == "equals":
                where_parts.append(f"{expression} = ?")
                parameters.append(value)

            elif operator == "not_equals":
                where_parts.append(f"{expression} <> ?")
                parameters.append(value)

            elif operator == "greater_than":
                where_parts.append(f"{expression} > ?")
                parameters.append(value)

            elif operator == "greater_than_or_equal":
                where_parts.append(f"{expression} >= ?")
                parameters.append(value)

            elif operator == "less_than":
                where_parts.append(f"{expression} < ?")
                parameters.append(value)

            elif operator == "less_than_or_equal":
                where_parts.append(f"{expression} <= ?")
                parameters.append(value)

            elif operator == "contains":
                where_parts.append(f"{expression} LIKE ?")
                parameters.append(f"%{value}%")

            elif operator == "starts_with":
                where_parts.append(f"{expression} LIKE ?")
                parameters.append(f"{value}%")

            elif operator == "ends_with":
                where_parts.append(f"{expression} LIKE ?")
                parameters.append(f"%{value}")

            elif operator == "in":
                if not isinstance(value, (list, tuple)):
                    raise SQLQueryExecutionError(
                        "'in' filter requires a list or tuple."
                    )

                if not value:
                    raise SQLQueryExecutionError(
                        "'in' filter cannot contain an empty list."
                    )

                norm_values = [
                    self._normalize_filter_value(v, col_type)
                    for v in value
                ]
                placeholders = ", ".join(
                    "?" for _ in norm_values
                )

                where_parts.append(
                    f"{expression} IN ({placeholders})"
                )

                parameters.extend(norm_values)

            else:
                raise SQLQueryExecutionError(
                    f"Unsupported JOIN filter operator: {operator}"
                )

        aggregate_sort_names = {
            "count", "sum", "average", "min", "max", "median", "aggregation_value"
        }
        if plan.sort_column and plan.sort_column not in aggregate_sort_names and (
            plan.intent == "ranking"
            or plan.limit is not None
            or plan.sort_direction is not None
        ):
            has_explicit_null = any(
                (f.column == plan.sort_column or parse_column_reference(f.column)[2] == parse_column_reference(plan.sort_column)[2])
                and f.operator in ("is_null", "is_not_null")
                for f in plan.filters
            )
            if not has_explicit_null:
                try:
                    sort_expr = resolve_column(plan.sort_column)
                    where_parts.append(f"{sort_expr} IS NOT NULL")
                except Exception:
                    pass

        where_sql = ""
        if where_parts:
            where_sql = (
                " WHERE "
                + " AND ".join(where_parts)
            )

        aggregation = plan.aggregation or (
            "count" if plan.intent in ("count", "row_count") else None
        )

        if aggregation:
            # ---------------------------------------------------------
            # FAN-OUT PROTECTED AGGREGATION
            # ---------------------------------------------------------
            if aggregation != "count":
                if not plan.target_columns or len(plan.target_columns) != 1:
                    raise SQLQueryExecutionError(
                        "JOIN aggregation requires exactly one target column."
                    )
            elif plan.target_columns and len(plan.target_columns) > 1:
                raise SQLQueryExecutionError(
                    "JOIN count aggregation accepts at most one target column."
                )

            # Determine the target entity table for aggregation grain.
            target_table_key: tuple[str, str] | None = None
            if plan.target_columns and plan.target_columns[0] != "*":
                target_column = plan.target_columns[0]
                if plan.target_column_refs:
                    ref = plan.target_column_refs[0]
                    if ref.table:
                        matched = [
                            k for k in joined_keys
                            if k[1].lower() == ref.table.lower()
                            and (not ref.schema or k[0].lower() == ref.schema.lower())
                        ]
                        if matched:
                            target_table_key = matched[0]

                if target_table_key is None:
                    schema_part, table_part, base_col = parse_column_reference(target_column)
                    if table_part:
                        matched = [
                            k for k in joined_keys
                            if k[1].lower() == table_part.lower()
                            and (not schema_part or k[0].lower() == schema_part.lower())
                        ]
                        if matched:
                            target_table_key = matched[0]
                    else:
                        matching_tables = [
                            k for k in joined_keys
                            if any(c.lower() == base_col.lower() for c in table_columns[k])
                        ]
                        if len(matching_tables) == 1:
                            target_table_key = matching_tables[0]

            if target_table_key is None:
                target_table_key = first_left_key

            target_table = table_lookup[target_table_key]
            target_alias = aliases[target_table_key]
            identifying_columns = self._get_entity_identifying_columns(target_table)

            # Subquery projection deduplicating at the target entity grain
            subquery_parts: list[str] = []
            for idx, col in enumerate(identifying_columns):
                subquery_parts.append(
                    f"{target_alias}.{self._quote_identifier(col)} AS {self._quote_identifier(f'__sub_id_{idx}')}"
                )

            if plan.group_by:
                for idx, column_name in enumerate(plan.group_by):
                    ref_list = None
                    if plan.group_by_refs and len(plan.group_by_refs) == len(plan.group_by):
                        ref_list = [plan.group_by_refs[idx]]
                    else:
                        ref_list = plan.group_by_refs
                    grp_expr = resolve_column(column_name, ref_list)
                    granularity = getattr(plan, "group_by_granularity", None)
                    if granularity and self.is_postgresql:
                        col_t = get_column_type(column_name, ref_list)
                        temporal_types = {
                            "date", "datetime", "datetime2", "datetimeoffset", "smalldatetime",
                            "timestamp", "timestamptz", "timestamp without time zone", "timestamp with time zone"
                        }
                        if col_t and col_t.lower() in temporal_types:
                            norm_g = granularity.strip().lower()
                            if norm_g in {"day", "week", "month", "quarter", "year"}:
                                grp_expr = f"DATE_TRUNC('{norm_g}', {grp_expr})::date"
                    subquery_parts.append(f"{grp_expr} AS {self._quote_identifier(f'__sub_grp_{idx}')}")

            has_target_measure = False
            if plan.target_columns and plan.target_columns[0] != "*":
                target_expr = resolve_column(plan.target_columns[0], plan.target_column_refs)
                subquery_parts.append(f"{target_expr} AS {self._quote_identifier('__sub_target')}")
                has_target_measure = True

            req_col_map: dict[str, str] = {}
            if plan.require_all_filter_values and plan.group_by:
                req_filters = [
                    item for item in plan.filters
                    if item.operator in {"in", "equals"}
                ]
                for rf in req_filters:
                    if rf.column not in req_col_map:
                        rf_alias = f"__sub_req_{len(req_col_map)}"
                        rf_expr = resolve_column(rf.column)
                        subquery_parts.append(f"{rf_expr} AS {self._quote_identifier(rf_alias)}")
                        req_col_map[rf.column] = rf_alias

            subquery_select = ", ".join(subquery_parts)
            subquery_sql = (
                f"(SELECT DISTINCT {subquery_select} "
                f"{from_sql}"
                f"{where_sql}) AS sub"
            )

            # Outer SELECT and AGGREGATION
            outer_select_parts: list[str] = []
            if plan.group_by:
                for idx, column_name in enumerate(plan.group_by):
                    outer_select_parts.append(
                        f"sub.{self._quote_identifier(f'__sub_grp_{idx}')} AS {self._quote_identifier(column_name)}"
                    )

            sub_target_expr = f"sub.{self._quote_identifier('__sub_target')}"
            if aggregation == "count":
                if has_target_measure:
                    outer_agg_expr = f"COUNT({sub_target_expr})"
                else:
                    outer_agg_expr = "COUNT(*)"
            elif aggregation == "sum":
                outer_agg_expr = f"SUM({sub_target_expr})"
            elif aggregation == "average":
                outer_agg_expr = f"AVG({sub_target_expr})"
            elif aggregation == "min":
                outer_agg_expr = f"MIN({sub_target_expr})"
            elif aggregation == "max":
                outer_agg_expr = f"MAX({sub_target_expr})"
            elif aggregation == "median":
                if plan.group_by:
                    raise SQLQueryExecutionError(
                        "Grouped median is not supported by the JOIN executor."
                    )
                if self.is_postgresql:
                    outer_agg_expr = (
                        f"PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY {sub_target_expr})"
                    )
                else:
                    outer_agg_expr = (
                        f"PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY {sub_target_expr}) OVER ()"
                    )
            else:
                raise SQLQueryExecutionError(
                    f"Unsupported JOIN aggregation: {aggregation}"
                )

            outer_select_parts.append(
                f"{outer_agg_expr} AS {self._quote_identifier('aggregation_value')}"
            )
            outer_select_sql = ", ".join(outer_select_parts)

            # Outer GROUP BY
            outer_group_sql = ""
            if plan.group_by:
                grp_sub_cols = [f"sub.{self._quote_identifier(f'__sub_grp_{idx}')}" for idx in range(len(plan.group_by))]
                outer_group_sql = " GROUP BY " + ", ".join(grp_sub_cols)

            # Outer HAVING
            having_conditions: list[str] = []
            having_parameters: list[Any] = []

            if plan.require_all_filter_values and plan.group_by and req_col_map:
                candidate_filters = [
                    item for item in plan.filters
                    if item.operator in {"in", "equals"}
                ]
                by_column: dict[str, list[Any]] = {}
                for item in candidate_filters:
                    values = (
                        list(item.value)
                        if item.operator == "in" and isinstance(item.value, (list, tuple))
                        else [item.value]
                    )
                    by_column.setdefault(item.column, []).extend(values)

                for col_name, values in by_column.items():
                    unique_values = list(dict.fromkeys(values))
                    if len(unique_values) < 2:
                        continue
                    rf_alias = req_col_map.get(col_name)
                    if rf_alias:
                        placeholders = ", ".join("?" for _ in unique_values)
                        sub_rf = f"sub.{self._quote_identifier(rf_alias)}"
                        having_conditions.append(
                            f"COUNT(DISTINCT CASE WHEN {sub_rf} IN ({placeholders}) THEN {sub_rf} END) = {len(unique_values)}"
                        )
                        having_parameters.extend(unique_values)

            if getattr(plan, "having_filters", None):
                operator_map = {
                    "equals": "=",
                    "not_equals": "<>",
                    "greater_than": ">",
                    "greater_than_or_equal": ">=",
                    "less_than": "<",
                    "less_than_or_equal": "<=",
                }
                for item in plan.having_filters:
                    operator = operator_map.get(item.operator)
                    if operator is None:
                        raise SQLQueryExecutionError(
                            f"Unsupported aggregate filter operator: {item.operator}"
                        )
                    having_conditions.append(f"{outer_agg_expr} {operator} ?")
                    having_parameters.append(item.value)

            outer_having_sql = ""
            if having_conditions:
                outer_having_sql = " HAVING " + " AND ".join(having_conditions)

            # Outer ORDER BY
            outer_order_sql = ""
            if plan.sort_column:
                sort_direction = (plan.sort_direction or "asc").lower()
                if sort_direction not in {"asc", "desc"}:
                    raise SQLQueryExecutionError(f"Unsupported sort direction: {sort_direction}")

                aggregate_sort_names = {
                    "count", "sum", "average", "min", "max", "median", "aggregation_value"
                }
                if (
                    plan.sort_column in aggregate_sort_names
                    or (plan.target_columns and plan.sort_column in plan.target_columns)
                ):
                    sort_expression = self._quote_identifier("aggregation_value")
                elif plan.group_by and plan.sort_column in plan.group_by:
                    grp_idx = plan.group_by.index(plan.sort_column)
                    sort_expression = f"sub.{self._quote_identifier(f'__sub_grp_{grp_idx}')}"
                else:
                    sort_expression = self._quote_identifier("aggregation_value")

                nulls_clause = " NULLS LAST" if self.is_postgresql else ""
                outer_order_sql = f" ORDER BY {sort_expression} {sort_direction.upper()}{nulls_clause}"

            # Outer LIMIT
            top_sql = ""
            limit_sql = ""
            if plan.limit is not None:
                if plan.limit <= 0:
                    raise SQLQueryExecutionError("JOIN query limit must be greater than zero.")
                if not self.is_postgresql:
                    top_sql = (
                        f"TOP ({int(plan.limit)}) WITH TIES "
                        if plan.include_ties
                        else f"TOP ({int(plan.limit)}) "
                    )
                else:
                    limit_sql = (
                        f" FETCH FIRST {int(plan.limit)} ROWS WITH TIES"
                        if plan.include_ties
                        else f" LIMIT {int(plan.limit)}"
                    )
                if plan.include_ties and not outer_order_sql:
                    outer_order_sql = f" ORDER BY {self._quote_identifier('aggregation_value')} DESC"

            distinct_keyword = "DISTINCT " if aggregation == "median" else ""
            sql = (
                f"SELECT {distinct_keyword}{top_sql}{outer_select_sql} "
                f"FROM {subquery_sql}"
                f"{outer_group_sql}"
                f"{outer_having_sql}"
                f"{outer_order_sql}"
                f"{limit_sql}"
            )
            parameters = parameters + having_parameters

        else:
            # ---------------------------------------------------------
            # NON-AGGREGATE (LOOKUP) JOIN EXECUTION
            # ---------------------------------------------------------
            select_parts: list[str] = []

            if plan.group_by:
                for idx, column_name in enumerate(plan.group_by):
                    ref_list = None
                    if plan.group_by_refs and len(plan.group_by_refs) == len(plan.group_by):
                        ref_list = [plan.group_by_refs[idx]]
                    else:
                        ref_list = plan.group_by_refs
                    expression = resolve_column(
                        column_name,
                        ref_list,
                    )
                    select_parts.append(
                        f"{expression} AS "
                        f"{self._quote_identifier(column_name)}"
                    )

            if plan.target_columns:
                for idx, column_name in enumerate(plan.target_columns):
                    ref_list = None
                    if plan.target_column_refs and len(plan.target_column_refs) == len(plan.target_columns):
                        ref_list = [plan.target_column_refs[idx]]
                    else:
                        ref_list = plan.target_column_refs
                    expression = resolve_column(
                        column_name,
                        ref_list,
                    )
                    select_parts.append(
                        f"{expression} AS "
                        f"{self._quote_identifier(column_name)}"
                    )
            else:
                select_parts.append("*")

            select_sql = ", ".join(select_parts)

            group_sql = ""
            if plan.group_by:
                group_expressions = []
                for column_name in plan.group_by:
                    grp_expr = resolve_column(
                        column_name,
                        plan.group_by_refs,
                    )
                    granularity = getattr(plan, "group_by_granularity", None)
                    if granularity and self.is_postgresql:
                        col_t = get_column_type(column_name, plan.group_by_refs)
                        temporal_types = {
                            "date", "datetime", "datetime2", "datetimeoffset", "smalldatetime",
                            "timestamp", "timestamptz", "timestamp without time zone", "timestamp with time zone"
                        }
                        if col_t and col_t.lower() in temporal_types:
                            norm_g = granularity.strip().lower()
                            if norm_g in {"day", "week", "month", "quarter", "year"}:
                                grp_expr = f"DATE_TRUNC('{norm_g}', {grp_expr})::date"
                    group_expressions.append(grp_expr)
                group_sql = (
                    " GROUP BY "
                    + ", ".join(group_expressions)
                )

            having_sql = ""
            having_parameters: list[Any] = []

            if plan.require_all_filter_values and plan.group_by:
                candidate_filters = [
                    item
                    for item in plan.filters
                    if item.operator in {"in", "equals"}
                ]
                by_column = {}
                for item in candidate_filters:
                    values = (
                        list(item.value)
                        if item.operator == "in"
                        and isinstance(item.value, (list, tuple))
                        else [item.value]
                    )
                    by_column.setdefault(item.column, []).extend(values)

                all_value_conditions = []
                for column_name, values in by_column.items():
                    unique_values = list(dict.fromkeys(values))
                    if len(unique_values) < 2:
                        continue

                    expression = resolve_column(column_name)
                    placeholders = ", ".join("?" for _ in unique_values)
                    all_value_conditions.append(
                        f"COUNT(DISTINCT CASE WHEN {expression} IN "
                        f"({placeholders}) THEN {expression} END) = "
                        f"{len(unique_values)}"
                    )
                    having_parameters.extend(unique_values)

                if all_value_conditions:
                    having_sql = " HAVING " + " AND ".join(all_value_conditions)

            if having_parameters:
                parameters.extend(having_parameters)

            order_sql = ""
            if plan.sort_column:
                sort_direction = (
                    plan.sort_direction
                    or "asc"
                ).lower()
                if sort_direction not in {"asc", "desc"}:
                    raise SQLQueryExecutionError(
                        f"Unsupported sort direction: {sort_direction}"
                    )
                if plan.sort_column in plan.group_by:
                    sort_expression = resolve_column(
                        plan.sort_column,
                        plan.group_by_refs,
                    )
                else:
                    sort_expression = resolve_column(
                        plan.sort_column,
                        plan.target_column_refs,
                    )
                nulls_clause = " NULLS LAST" if self.is_postgresql else ""
                order_sql = (
                    f" ORDER BY {sort_expression} "
                    f"{sort_direction.upper()}{nulls_clause}"
                )

            top_sql = ""
            limit_sql = ""
            if plan.limit is not None:
                if plan.limit <= 0:
                    raise SQLQueryExecutionError(
                        "JOIN query limit must be greater than zero."
                    )
                if not self.is_postgresql:
                    top_sql = (
                        f"TOP ({int(plan.limit)}) WITH TIES "
                        if plan.include_ties
                        else f"TOP ({int(plan.limit)}) "
                    )
                else:
                    limit_sql = (
                        f" FETCH FIRST {int(plan.limit)} ROWS WITH TIES"
                        if plan.include_ties
                        else f" LIMIT {int(plan.limit)}"
                    )

                if plan.include_ties and not order_sql:
                    if plan.target_columns:
                        first_ref = (
                            plan.target_column_refs[0]
                            if getattr(plan, "target_column_refs", None) and len(plan.target_column_refs) > 0
                            else None
                        )
                        first_col_expr = resolve_column(plan.target_columns[0], [first_ref] if first_ref else None)
                        order_sql = f" ORDER BY {first_col_expr} ASC"
                    elif plan.group_by:
                        first_ref = (
                            plan.group_by_refs[0]
                            if getattr(plan, "group_by_refs", None) and len(plan.group_by_refs) > 0
                            else None
                        )
                        first_col_expr = resolve_column(plan.group_by[0], [first_ref] if first_ref else None)
                        order_sql = f" ORDER BY {first_col_expr} ASC"
                    elif primary_table.columns:
                        order_sql = f" ORDER BY {self._quote_identifier(primary_table.schema_name)}.{self._quote_identifier(primary_table.table_name)}.{self._quote_identifier(primary_table.columns[0].name)} ASC"

            distinct_keyword = "DISTINCT " if (getattr(plan, "distinct", False) or plan.intent == "distinct") else ""
            sql = (
                f"SELECT {distinct_keyword}{top_sql}{select_sql} "
                f"{from_sql}"
                f"{where_sql}"
                f"{group_sql}"
                f"{having_sql}"
                f"{order_sql}"
                f"{limit_sql}"
            )

        try:
            with get_connection(self.config) as connection:
                cursor = connection.cursor()
                cursor.execute(sql, parameters)

                if cursor.description is None:
                    return []

                column_names = [
                    description[0]
                    for description in cursor.description
                ]

                rows = cursor.fetchall()
                if plan.limit is None and len(rows) > getattr(self, "MAX_LOOKUP_ROWS", 5000):
                    rows = rows[: getattr(self, "MAX_LOOKUP_ROWS", 5000)]

                return [
                    {
                        col: str(val) if isinstance(val, uuid.UUID) else val
                        for col, val in zip(column_names, row)
                    }
                    for row in rows
                ]

        except SQLQueryExecutionError:
            raise

        except Exception as exc:
            self._handle_execution_exception(exc)

    def _validate_qualified_references(
        self,
        plan: QueryPlan,
        table: TableInfo,
    ) -> None:
        """
        Ensure qualified target/group references belong to the table being
        executed. The actual SQL remains safely identifier-quoted below.
        """
        table_key = (table.schema_name.lower(), table.table_name.lower())
        table_columns = {column.name.lower() for column in table.columns}

        for ref in getattr(plan, "target_column_refs", []):
            ref_schema = ref.schema.lower() if ref.schema else None
            ref_table = ref.table.lower() if ref.table else ""
            if ref_schema and (ref_schema, ref_table) != table_key:
                raise SQLQueryExecutionError(
                    "Target column reference points to a different table: "
                    f"{ref.schema}.{ref.table}.{ref.column}"
                )
            elif not ref_schema and ref_table and ref_table != table_key[1]:
                raise SQLQueryExecutionError(
                    "Target column reference points to a different table: "
                    f"{ref.table}.{ref.column}"
                )
            if ref.column.lower() not in table_columns:
                raise SQLQueryExecutionError(
                    "Target column reference does not exist: "
                    f"{ref.schema or table.schema_name}.{ref.table}.{ref.column}"
                )

        for ref in getattr(plan, "group_by_refs", []):
            ref_schema = ref.schema.lower() if ref.schema else None
            ref_table = ref.table.lower() if ref.table else ""
            if ref_schema and (ref_schema, ref_table) != table_key:
                raise SQLQueryExecutionError(
                    "Group-by column reference points to a different table: "
                    f"{ref.schema}.{ref.table}.{ref.column}"
                )
            elif not ref_schema and ref_table and ref_table != table_key[1]:
                raise SQLQueryExecutionError(
                    "Group-by column reference points to a different table: "
                    f"{ref.table}.{ref.column}"
                )
            if ref.column.lower() not in table_columns:
                raise SQLQueryExecutionError(
                    "Group-by column reference does not exist: "
                    f"{ref.schema or table.schema_name}.{ref.table}.{ref.column}"
                )

    def _resolve_single_table_column(
        self,
        column_identifier: str,
        table: TableInfo,
    ) -> str:
        """
        Resolve a column identifier (unqualified, table-qualified, or schema-qualified)
        to the matching column name on the single execution table.
        """
        schema_part, table_part, base_col = parse_column_reference(column_identifier)
        if schema_part and schema_part.lower() != table.schema_name.lower():
            raise SQLQueryExecutionError(
                f"Column reference '{column_identifier}' points to a different schema: {schema_part}"
            )
        if table_part and table_part.lower() != table.table_name.lower():
            raise SQLQueryExecutionError(
                f"Column reference '{column_identifier}' points to a different table: {table_part}"
            )
        for col in table.columns:
            if col.name.lower() == base_col.lower():
                return col.name
        raise SQLQueryExecutionError(
            f"Unknown column '{column_identifier}' for table {table.schema_name}.{table.table_name}"
        )

    def _normalize_filter_value(self, val: Any, col_type: str | None) -> Any:
        if self.is_postgresql and col_type == "boolean":
            if isinstance(val, bool):
                return val
            if isinstance(val, (int, float)):
                return bool(val)
            if isinstance(val, str):
                s = val.strip().lower()
                if s in {"1", "true", "t", "yes", "y"}:
                    return True
                if s in {"0", "false", "f", "no", "n"}:
                    return False
        return val

    def _build_where_clause(
        self,
        filters: list,
        table: TableInfo,
    ) -> tuple[str, list[Any]]:
        if not filters:
            return "", []

        clauses = []
        parameters: list[Any] = []

        table_col_types = {
            c.name.lower(): c.data_type.lower()
            for c in table.columns
        }

        for filter_item in filters:
            column_name = filter_item.column
            operator = filter_item.operator
            value = filter_item.value

            resolved_col = self._resolve_single_table_column(column_name, table)
            quoted_column = self._quote_identifier(resolved_col)
            col_type = table_col_types.get(resolved_col.lower())

            # NULL checks
            if operator in {"is_null", "null"} or (operator == "equals" and value is None):
                clauses.append(f"{quoted_column} IS NULL")
                continue

            if operator in {"is_not_null", "not_null"} or (operator == "not_equals" and value is None):
                clauses.append(f"{quoted_column} IS NOT NULL")
                continue

            value = self._normalize_filter_value(value, col_type)

            if operator == "equals":
                clauses.append(f"{quoted_column} = ?")
                parameters.append(value)

            elif operator == "not_equals":
                clauses.append(f"{quoted_column} <> ?")
                parameters.append(value)

            elif operator == "greater_than":
                clauses.append(f"{quoted_column} > ?")
                parameters.append(value)

            elif operator == "greater_than_or_equal":
                clauses.append(f"{quoted_column} >= ?")
                parameters.append(value)

            elif operator == "less_than":
                clauses.append(f"{quoted_column} < ?")
                parameters.append(value)

            elif operator == "less_than_or_equal":
                clauses.append(f"{quoted_column} <= ?")
                parameters.append(value)

            elif operator == "contains":
                clauses.append(f"{quoted_column} LIKE ?")
                parameters.append(f"%{value}%")

            elif operator == "starts_with":
                clauses.append(f"{quoted_column} LIKE ?")
                parameters.append(f"{value}%")

            elif operator == "ends_with":
                clauses.append(f"{quoted_column} LIKE ?")
                parameters.append(f"%{value}")

            elif operator == "in":
                if not isinstance(value, (list, tuple)) or not value:
                    raise SQLQueryExecutionError(
                        "The IN filter requires a non-empty list of values."
                    )

                norm_values = [
                    self._normalize_filter_value(v, col_type)
                    for v in value
                ]
                placeholders = ", ".join("?" for _ in norm_values)

                clauses.append(
                    f"{quoted_column} IN ({placeholders})"
                )

                parameters.extend(norm_values)

            else:
                raise SQLQueryExecutionError(
                    f"Unsupported filter operator: {operator}"
                )

        return " WHERE " + " AND ".join(clauses), parameters

    def _build_order_by_clause(
        self,
        plan: QueryPlan,
        table: TableInfo,
        allowed_columns: set[str] | None = None,
    ) -> str:
        if not plan.sort_column:
            return ""

        sort_column = plan.sort_column

        if allowed_columns and sort_column in allowed_columns:
            quoted_column = self._quote_identifier(sort_column)
        else:
            resolved_col = self._resolve_single_table_column(sort_column, table)
            quoted_column = self._quote_identifier(resolved_col)

        sort_direction = plan.sort_direction or "asc"

        if sort_direction not in {"asc", "desc"}:
            raise SQLQueryExecutionError(
                f"Unsupported sort direction: {sort_direction}"
            )

        nulls_clause = " NULLS LAST" if self.is_postgresql else ""
        return (
            f" ORDER BY {quoted_column} "
            f"{sort_direction.upper()}{nulls_clause}"
        )

    def _execute_row_count(
        self,
        plan: QueryPlan,
        table: TableInfo,
    ) -> int:
        self._validate_qualified_references(plan, table)

        schema_name = self._quote_identifier(table.schema_name)
        table_name = self._quote_identifier(table.table_name)

        where_clause, parameters = self._build_where_clause(
            plan.filters,
            table,
        )

        sql = (
            f"SELECT COUNT(*) AS row_count "
            f"FROM {schema_name}.{table_name}"
            f"{where_clause}"
        )

        try:
            with get_connection(self.config) as connection:
                cursor = connection.cursor()
                cursor.execute(sql, parameters)
                row = cursor.fetchone()

                if row is None:
                    raise SQLQueryExecutionError(
                        "Database returned no result."
                    )

                val = getattr(row, "row_count", None)
                if val is None:
                    val = row[0]
                return int(val)

        except SQLQueryExecutionError:
            raise

        except Exception as exc:
            self._handle_execution_exception(exc)

    def _execute_column_count(self, table: TableInfo) -> int:
        return len(table.columns)

    def _execute_column_names(self, table: TableInfo) -> list[str]:
        return [
            column.name
            for column in table.columns
        ]

    def _execute_lookup(
        self,
        plan: QueryPlan,
        table: TableInfo,
    ) -> list[dict[str, Any]]:
        self._validate_qualified_references(plan, table)

        schema_name = self._quote_identifier(table.schema_name)
        table_name = self._quote_identifier(table.table_name)

        table_columns = {
            column.name
            for column in table.columns
        }

        if plan.target_columns:
            selected_parts = []
            for column in plan.target_columns:
                resolved_col = self._resolve_single_table_column(column, table)
                if resolved_col != column:
                    selected_parts.append(
                        f"{self._quote_identifier(resolved_col)} AS {self._quote_identifier(column)}"
                    )
                else:
                    selected_parts.append(self._quote_identifier(resolved_col))
            selected_columns = ", ".join(selected_parts)

        else:
            selected_columns = "*"

        effective_filters = list(plan.filters) if plan.filters else []
        if plan.sort_column and (
            plan.intent == "ranking"
            or plan.limit is not None
            or plan.sort_direction is not None
        ):
            resolved_sort_col = self._resolve_single_table_column(plan.sort_column, table)
            has_explicit_null = any(
                (f.column == plan.sort_column or f.column == resolved_sort_col)
                and f.operator in ("is_null", "is_not_null")
                for f in effective_filters
            )
            if not has_explicit_null:
                effective_filters.append(
                    QueryFilter(
                        column=resolved_sort_col,
                        operator="is_not_null",
                        value=None,
                    )
                )

        where_clause, parameters = self._build_where_clause(
            effective_filters,
            table,
        )

        top_clause = ""
        limit_clause = ""

        if plan.limit is not None:
            if plan.limit <= 0:
                raise SQLQueryExecutionError(
                    "Lookup limit must be greater than zero."
                )

            if not self.is_postgresql:
                if plan.include_ties:
                    top_clause = (
                        f"TOP ({int(plan.limit)}) WITH TIES "
                    )
                else:
                    top_clause = (
                        f"TOP ({int(plan.limit)}) "
                    )
            else:
                if plan.include_ties:
                    limit_clause = f" FETCH FIRST {int(plan.limit)} ROWS WITH TIES"
                else:
                    limit_clause = f" LIMIT {int(plan.limit)}"

        distinct_clause = "DISTINCT " if (getattr(plan, "distinct", False) or plan.intent == "distinct") else ""
        sql = (
            f"SELECT {distinct_clause}{top_clause}"
            f"{selected_columns} "
            f"FROM {schema_name}.{table_name}"
            f"{where_clause}"
        )

        order_by_clause = self._build_order_by_clause(
            plan,
            table,
        )

        if plan.include_ties and not order_by_clause:
            fallback_col = None
            if plan.target_columns:
                fallback_col = self._resolve_single_table_column(plan.target_columns[0], table)
            elif getattr(table, "primary_key", None):
                fallback_col = table.primary_key
            elif table.columns:
                fallback_col = table.columns[0].name
            if fallback_col:
                order_by_clause = f" ORDER BY {self._quote_identifier(fallback_col)} ASC"

        sql += order_by_clause
        sql += limit_clause

        try:
            with get_connection(self.config) as connection:
                cursor = connection.cursor()

                cursor.execute(
                    sql,
                    parameters,
                )

                if cursor.description is None:
                    return []

                column_names = [
                    description[0]
                    for description in cursor.description
                ]

                rows = cursor.fetchall()
                if plan.limit is None and len(rows) > getattr(self, "MAX_LOOKUP_ROWS", 5000):
                    rows = rows[: getattr(self, "MAX_LOOKUP_ROWS", 5000)]

                return [
                    {
                        col: str(val) if isinstance(val, uuid.UUID) else val
                        for col, val in zip(column_names, row)
                    }
                    for row in rows
                ]

        except SQLQueryExecutionError:
            raise

        except Exception as exc:
            self._handle_execution_exception(exc)

    def _execute_count(
        self,
        plan: QueryPlan,
        table: TableInfo,
    ) -> int:
        """
        Execute a scalar COUNT query.

        COUNT is a row-count semantic in the canonical query contract.
        Therefore COUNT(*) is used when no target column is supplied.
        If the planner supplies one target column, that column is
        validated for compatibility, but it does not change COUNT's
        row-count semantics.
        """
        self._validate_qualified_references(plan, table)

        if len(plan.target_columns) > 1:
            raise SQLQueryExecutionError(
                "Count accepts zero or one target column."
            )

        if plan.target_columns:
            column_name = plan.target_columns[0]
            self._resolve_single_table_column(column_name, table)

        schema_name = self._quote_identifier(table.schema_name)
        table_name = self._quote_identifier(table.table_name)

        sql = (
            f"SELECT COUNT(*) AS value_count "
            f"FROM {schema_name}.{table_name}"
        )

        where_clause, parameters = self._build_where_clause(
            plan.filters,
            table,
        )

        sql += where_clause

        try:
            with get_connection(self.config) as connection:
                cursor = connection.cursor()

                cursor.execute(
                    sql,
                    parameters,
                )

                row = cursor.fetchone()

                if row is None:
                    raise SQLQueryExecutionError(
                        "Database returned no result."
                    )

                val = getattr(row, "value_count", None)
                if val is None:
                    val = row[0]
                return int(val)

        except SQLQueryExecutionError:
            raise

        except Exception as exc:
            self._handle_execution_exception(exc)

    def _execute_percentage(
        self,
        plan: QueryPlan,
        table: TableInfo,
    ) -> float:
        """
        Calculate the percentage of rows matching the plan filters.

        The calculation is generic:

            matching rows / total rows * 100

        No business-specific table or column names are hardcoded.
        The filters supplied by the QueryPlan determine the numerator.
        The denominator is the complete row count for the same table.
        """
        self._validate_qualified_references(plan, table)

        schema_name = self._quote_identifier(table.schema_name)
        table_name = self._quote_identifier(table.table_name)

        where_clause, parameters = self._build_where_clause(
            plan.filters,
            table,
        )

        sql = (
            "SELECT "
            "COUNT(*) AS matching_count, "
            "(SELECT COUNT(*) "
            f"FROM {schema_name}.{table_name}) AS total_count "
            f"FROM {schema_name}.{table_name}"
            f"{where_clause}"
        )

        try:
            with get_connection(self.config) as connection:
                cursor = connection.cursor()

                cursor.execute(
                    sql,
                    parameters,
                )

                row = cursor.fetchone()

                if row is None:
                    raise SQLQueryExecutionError(
                        "Database returned no result."
                    )

                m_val = getattr(row, "matching_count", None)
                if m_val is None:
                    m_val = row[0]
                t_val = getattr(row, "total_count", None)
                if t_val is None:
                    t_val = row[1]
                matching_count = int(m_val)
                total_count = int(t_val)

                if total_count == 0:
                    return 0.0

                return (
                    matching_count / total_count
                ) * 100.0

        except SQLQueryExecutionError:
            raise

        except Exception as exc:
            self._handle_execution_exception(exc)

    def _execute_aggregation(
        self,
        plan: QueryPlan,
        table: TableInfo,
    ) -> Any:
        self._validate_qualified_references(plan, table)

        if plan.aggregation not in {
            "sum",
            "average",
            "min",
            "max",
            "median",
            "count",
        }:
            raise SQLQueryExecutionError(
                "Unsupported aggregation. "
                "Supported aggregations are: "
                "sum, average, min, max, median, count."
            )

        if plan.aggregation == "count":
            # Scalar aggregation COUNT follows the same row-count
            # semantics as intent="count": COUNT(*) rather than
            # COUNT(target_column).
            if len(plan.target_columns) > 1:
                raise SQLQueryExecutionError(
                    "COUNT accepts zero or one target column."
                )

            schema_name = self._quote_identifier(table.schema_name)
            table_name = self._quote_identifier(table.table_name)

            where_clause, parameters = self._build_where_clause(
                plan.filters,
                table,
            )

            sql = (
                f"SELECT COUNT(*) AS aggregation_value "
                f"FROM {schema_name}.{table_name}"
                f"{where_clause}"
            )

            try:
                with get_connection(self.config) as connection:
                    cursor = connection.cursor()
                    cursor.execute(sql, parameters)
                    row = cursor.fetchone()

                    if row is None:
                        raise SQLQueryExecutionError(
                            "Database returned no result."
                        )

                    val = getattr(row, "aggregation_value", None)
                    if val is None:
                        val = row[0]
                    return int(val)

            except SQLQueryExecutionError:
                raise

            except Exception as exc:
                self._handle_execution_exception(exc)

        if len(plan.target_columns) != 1:
            raise SQLQueryExecutionError(
                "Aggregation requires exactly one target column."
            )

        column_name = plan.target_columns[0]
        resolved_column_name = self._resolve_single_table_column(column_name, table)

        table_column_lookup = {
            column.name.lower(): column
            for column in table.columns
        }

        column = table_column_lookup.get(
            resolved_column_name.lower()
        )

        if column is None:
            raise SQLQueryExecutionError(
                f"Aggregation contains unknown column: {column_name}"
            )

        numeric_types = {
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

        if (
            plan.aggregation == "sum"
            and column.data_type.lower() not in numeric_types
        ):
            raise SQLQueryExecutionError(
                f"SUM cannot be applied to non-numeric column: "
                f"{column_name}"
            )

        if (
            plan.aggregation == "average"
            and column.data_type.lower() not in numeric_types
        ):
            raise SQLQueryExecutionError(
                f"AVERAGE cannot be applied to non-numeric column: "
                f"{column_name}"
            )

        schema_name = self._quote_identifier(
            table.schema_name
        )

        table_name = self._quote_identifier(
            table.table_name
        )

        quoted_column = self._quote_identifier(
            resolved_column_name
        )

        where_clause, parameters = self._build_where_clause(
            plan.filters,
            table,
        )

        if plan.aggregation == "median":
            if self.is_postgresql:
                sql = (
                    "SELECT "
                    "PERCENTILE_CONT(0.5) "
                    f"WITHIN GROUP (ORDER BY {quoted_column}) "
                    "AS aggregation_value "
                    f"FROM {schema_name}.{table_name}"
                    f"{where_clause}"
                )
            else:
                sql = (
                    "SELECT "
                    "PERCENTILE_CONT(0.5) "
                    f"WITHIN GROUP (ORDER BY {quoted_column}) "
                    "OVER () AS aggregation_value "
                    f"FROM {schema_name}.{table_name}"
                    f"{where_clause}"
                )

        else:
            aggregation_sql = {
                "sum": "SUM",
                "average": "AVG",
                "min": "MIN",
                "max": "MAX",
            }[plan.aggregation]

            sql = (
                f"SELECT {aggregation_sql}({quoted_column}) "
                f"AS aggregation_value "
                f"FROM {schema_name}.{table_name}"
                f"{where_clause}"
            )

        try:
            with get_connection(self.config) as connection:
                cursor = connection.cursor()

                cursor.execute(
                    sql,
                    parameters,
                )

                row = cursor.fetchone()

                if row is None:
                    return None

                val = getattr(row, "aggregation_value", None)
                if val is None:
                    val = row[0]
                return val

        except SQLQueryExecutionError:
            raise

        except Exception as exc:
            self._handle_execution_exception(exc)

    def _build_group_expression(
        self,
        column_name: str,
        data_type: str,
        granularity: str | None,
    ) -> tuple[str, str]:
        """
        Build a grouping expression for an optional temporal granularity.
        Physical column names come only from the discovered database schema.
        """
        quoted_column = self._quote_identifier(column_name)

        if not granularity:
            return quoted_column, column_name

        normalized = granularity.strip().lower()

        temporal_types = {
            "date",
            "datetime",
            "datetime2",
            "datetimeoffset",
            "smalldatetime",
            "timestamp",
            "timestamptz",
            "timestamp without time zone",
            "timestamp with time zone",
        }

        if data_type.lower() not in temporal_types:
            raise SQLQueryExecutionError(
                f"Temporal grouping '{granularity}' cannot be applied "
                f"to non-temporal column: {column_name}"
            )

        if self.is_postgresql:
            if normalized in {"day", "week", "month", "quarter", "year"}:
                expression = f"DATE_TRUNC('{normalized}', {quoted_column})::date"
            else:
                raise SQLQueryExecutionError(
                    f"Unsupported temporal grouping granularity: {granularity}. "
                    "Supported values are: day, week, month, quarter, year."
                )
        else:
            if normalized == "day":
                expression = f"CAST({quoted_column} AS date)"
            elif normalized == "week":
                expression = (
                    "DATEADD(week, DATEDIFF(week, 0, "
                    f"{quoted_column}), 0)"
                )
            elif normalized == "month":
                expression = (
                    "DATEFROMPARTS("
                    f"YEAR({quoted_column}), MONTH({quoted_column}), 1)"
                )
            elif normalized == "quarter":
                expression = (
                    "DATEFROMPARTS("
                    f"YEAR({quoted_column}), "
                    f"((DATEPART(quarter, {quoted_column}) - 1) * 3) + 1, "
                    "1)"
                )
            elif normalized == "year":
                expression = (
                    "DATEFROMPARTS("
                    f"YEAR({quoted_column}), 1, 1)"
                )
            else:
                raise SQLQueryExecutionError(
                    f"Unsupported temporal grouping granularity: {granularity}. "
                    "Supported values are: day, week, month, quarter, year."
                )

        return expression, column_name

    def _execute_grouped_aggregation(
        self,
        plan: QueryPlan,
        table: TableInfo,
    ) -> list[dict[str, Any]]:
        self._validate_qualified_references(plan, table)

        if plan.aggregation not in {
            "count",
            "sum",
            "average",
            "min",
            "max",
            "median",
        }:
            raise SQLQueryExecutionError(
                "Unsupported grouped aggregation. "
                "Supported aggregations are: "
                "count, sum, average, min, max, median."
            )

        if not plan.group_by:
            raise SQLQueryExecutionError(
                "Grouped aggregation requires at least one "
                "group-by column."
            )

        table_columns = {
            column.name.lower(): column
            for column in table.columns
        }

        resolved_group_columns: list[str] = []
        for group_column in plan.group_by:
            resolved_col = self._resolve_single_table_column(group_column, table)
            resolved_group_columns.append(resolved_col)

        if plan.aggregation == "count":
            if len(plan.target_columns) > 1:
                raise SQLQueryExecutionError(
                    "Grouped COUNT accepts zero or one target column."
                )
            if plan.target_columns:
                target_column_name = plan.target_columns[0]
                resolved_target_column = self._resolve_single_table_column(target_column_name, table)
                target_column = table_columns.get(resolved_target_column.lower())
                if target_column is None:
                    raise SQLQueryExecutionError(
                        "Grouped aggregation contains unknown column: "
                        f"{target_column_name}"
                    )
                quoted_target_column = self._quote_identifier(resolved_target_column)
            else:
                target_column_name = None
                resolved_target_column = None
                quoted_target_column = None
        else:
            if len(plan.target_columns) != 1:
                raise SQLQueryExecutionError(
                    "Grouped aggregation requires exactly one "
                    "target column."
                )

            target_column_name = plan.target_columns[0]
            resolved_target_column = self._resolve_single_table_column(target_column_name, table)

            target_column = table_columns.get(
                resolved_target_column.lower()
            )

            if target_column is None:
                raise SQLQueryExecutionError(
                    "Grouped aggregation contains unknown column: "
                    f"{target_column_name}"
                )

            quoted_target_column = self._quote_identifier(
                resolved_target_column
            )

            numeric_types = {
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

            if (
                plan.aggregation in {"sum", "average"}
                and target_column.data_type.lower()
                not in numeric_types
            ):
                raise SQLQueryExecutionError(
                    f"{plan.aggregation.upper()} cannot be applied "
                    f"to non-numeric column: "
                    f"{target_column_name}"
                )

        # Verify that every requested filter value occurs within
        # the same group when the analyzer marked the query as requiring
        # all values.
        having_sql = ""
        having_parameters: list[Any] = []

        if plan.require_all_filter_values:
            by_column: dict[str, list[Any]] = {}
            for item in plan.filters:
                if item.operator == "in" and isinstance(item.value, (list, tuple)):
                    by_column.setdefault(item.column, []).extend(item.value)
                elif item.operator == "equals":
                    by_column.setdefault(item.column, []).append(item.value)

            conditions = []
            for column_name, values in by_column.items():
                unique_values = list(dict.fromkeys(values))
                if len(unique_values) < 2:
                    continue

                expression = self._quote_identifier(column_name)
                placeholders = ", ".join("?" for _ in unique_values)
                conditions.append(
                    f"COUNT(DISTINCT CASE WHEN {expression} IN "
                    f"({placeholders}) THEN {expression} END) = "
                    f"{len(unique_values)}"
                )
                having_parameters.extend(unique_values)

            if conditions:
                having_sql = " HAVING " + " AND ".join(conditions)


        # ---------------------------------------------------------
        # Aggregate-result filters
        # ---------------------------------------------------------
        # These are semantic HAVING conditions such as:
        #
        #     COUNT(*) > 50
        #
        # They must not be treated as physical-column WHERE
        # conditions.
        #
        # The aggregate expression is derived entirely from the
        # QueryPlan. No business-specific column names are used.
        aggregate_having_conditions = []

        aggregate_expression = None

        if getattr(plan, "having_filters", None):
            if plan.aggregation == "count":
                aggregate_expression = "COUNT(*)"
            elif plan.aggregation == "sum":
                aggregate_expression = f"SUM({quoted_target_column})"
            elif plan.aggregation == "average":
                aggregate_expression = f"AVG({quoted_target_column})"
            elif plan.aggregation == "min":
                aggregate_expression = f"MIN({quoted_target_column})"
            elif plan.aggregation == "max":
                aggregate_expression = f"MAX({quoted_target_column})"
            elif plan.aggregation == "median":
                raise SQLQueryExecutionError(
                    "HAVING filters are not supported for median "
                    "grouped aggregation."
                )
            else:
                raise SQLQueryExecutionError(
                    f"Unsupported aggregation for HAVING filter: "
                    f"{plan.aggregation}"
                )

            operator_map = {
                "equals": "=",
                "not_equals": "<>",
                "greater_than": ">",
                "greater_than_or_equal": ">=",
                "less_than": "<",
                "less_than_or_equal": "<=",
            }

            for item in plan.having_filters:
                operator = operator_map.get(item.operator)

                if operator is None:
                    raise SQLQueryExecutionError(
                        "Unsupported aggregate filter operator: "
                        f"{item.operator}"
                    )

                aggregate_having_conditions.append(
                    f"{aggregate_expression} {operator} ?"
                )
                having_parameters.append(item.value)

        if aggregate_having_conditions:
            if having_sql:
                having_sql += (
                    " AND "
                    + " AND ".join(aggregate_having_conditions)
                )
            else:
                having_sql = (
                    " HAVING "
                    + " AND ".join(aggregate_having_conditions)
                )

        if plan.aggregation == "median":
            aggregation_sql = None
        else:
            aggregation_sql = {
                "count": "COUNT",
                "sum": "SUM",
                "average": "AVG",
                "min": "MIN",
                "max": "MAX",
            }[plan.aggregation]

        # Apply semantic temporal grouping when requested.
        group_expressions: list[str] = []
        group_output_names: list[str] = []

        for group_column, resolved_group_col in zip(plan.group_by, resolved_group_columns):
            column_info = table_columns[resolved_group_col.lower()]
            expression, output_name = self._build_group_expression(
                column_name=resolved_group_col,
                data_type=column_info.data_type,
                granularity=getattr(
                    plan,
                    "group_by_granularity",
                    None,
                ),
            )
            group_expressions.append(expression)
            group_output_names.append(group_column)

        selected_group_columns = ", ".join(
            f"{expression} AS {self._quote_identifier(output_name)}"
            for expression, output_name in zip(
                group_expressions,
                group_output_names,
            )
        )

        group_by_sql = ", ".join(group_expressions)

        schema_name = self._quote_identifier(
            table.schema_name
        )

        table_name = self._quote_identifier(
            table.table_name
        )

        where_clause, parameters = self._build_where_clause(
            plan.filters,
            table,
        )

        if having_parameters:
            parameters.extend(having_parameters)

        select_prefix = ""
        limit_clause = ""
        if plan.limit is not None:
            if plan.limit <= 0:
                raise SQLQueryExecutionError(
                    "Grouped aggregation limit must be greater than zero."
                )

            if not self.is_postgresql:
                if plan.include_ties:
                    select_prefix = (
                        f"TOP ({int(plan.limit)}) WITH TIES "
                    )
                else:
                    select_prefix = (
                        f"TOP ({int(plan.limit)}) "
                    )
            else:
                if plan.include_ties:
                    limit_clause = f" FETCH FIRST {int(plan.limit)} ROWS WITH TIES"
                else:
                    limit_clause = f" LIMIT {int(plan.limit)}"

        if plan.aggregation == "median":
            if self.is_postgresql:
                sql = (
                    f"SELECT {selected_group_columns}, "
                    "PERCENTILE_CONT(0.5) "
                    f"WITHIN GROUP (ORDER BY {quoted_target_column}) "
                    "AS aggregation_value "
                    f"FROM {schema_name}.{table_name}"
                    f"{where_clause} "
                    f"GROUP BY {group_by_sql}"
                    f"{having_sql}"
                )
            else:
                sql = (
                    f"SELECT {select_prefix}{selected_group_columns}, "
                    "PERCENTILE_CONT(0.5) "
                    f"WITHIN GROUP (ORDER BY {quoted_target_column}) "
                    f"OVER (PARTITION BY {group_by_sql}) "
                    "AS aggregation_value "
                    f"FROM {schema_name}.{table_name}"
                    f"{where_clause}"
                )

                sql = (
                    "SELECT DISTINCT "
                    f"{selected_group_columns}, "
                    "aggregation_value "
                    "FROM ("
                    f"{sql}"
                    ") AS grouped_median"
                )
        else:
            # A grouped count answers "how many rows are in each group".
            # Counting the grouping column itself would return 1 for every
            # non-null group because all rows in a group share that value.
            # Therefore grouped COUNT must count rows with COUNT(*).
            aggregation_expression = (
                "COUNT(*) "
                if plan.aggregation == "count"
                else f"{aggregation_sql}({quoted_target_column}) "
            )
            sql = (
                f"SELECT {select_prefix}{selected_group_columns}, "
                f"{aggregation_expression}"
                f"AS aggregation_value "
                f"FROM {schema_name}.{table_name}"
                f"{where_clause} "
                f"GROUP BY {group_by_sql}"
                f"{having_sql}"
            )

        if plan.sort_column:
            sort_column = plan.sort_column

            # A grouped aggregation returns the grouping columns plus
            # the calculated aggregation_value. If the analyzer uses
            # the original target column as the sort column, sort by
            # the calculated aggregation value instead.
            resolved_sort = None
            try:
                resolved_sort = self._resolve_single_table_column(sort_column, table)
            except Exception:
                pass

            if (
                (target_column_name is not None and sort_column == target_column_name)
                or (
                    resolved_sort
                    and resolved_target_column
                    and resolved_sort.lower() == resolved_target_column.lower()
                )
            ):
                sort_column = "aggregation_value"

            elif sort_column == "aggregation_value":
                sort_column = "aggregation_value"

            elif sort_column in {
                "count",
                "sum",
                "average",
                "min",
                "max",
                "median",
            }:
                # These are virtual aggregate names, not physical
                # database columns. The SQL query exposes the
                # calculated value as aggregation_value.
                sort_column = "aggregation_value"

            elif sort_column in plan.group_by:
                sort_index = plan.group_by.index(sort_column)
                sort_expression = group_expressions[sort_index]

                sort_direction = plan.sort_direction or "asc"

                if sort_direction not in {"asc", "desc"}:
                    raise SQLQueryExecutionError(
                        f"Unsupported sort direction: {sort_direction}"
                    )

                sql += (
                    f" ORDER BY {sort_expression} "
                    f"{sort_direction.upper()}"
                )
                sort_column = None

            elif resolved_sort and any(resolved_sort.lower() == r.lower() for r in resolved_group_columns):
                matching_indices = [
                    idx for idx, r in enumerate(resolved_group_columns)
                    if r.lower() == resolved_sort.lower()
                ]
                sort_index = matching_indices[0]
                sort_expression = group_expressions[sort_index]

                sort_direction = plan.sort_direction or "asc"

                if sort_direction not in {"asc", "desc"}:
                    raise SQLQueryExecutionError(
                        f"Unsupported sort direction: {sort_direction}"
                    )

                sql += (
                    f" ORDER BY {sort_expression} "
                    f"{sort_direction.upper()}"
                )
                sort_column = None

            else:
                raise SQLQueryExecutionError(
                    f"Sort column '{plan.sort_column}' is not available "
                    "in the grouped result."
                )

            sort_direction = plan.sort_direction or "asc"

            if sort_direction not in {"asc", "desc"}:
                raise SQLQueryExecutionError(
                    f"Unsupported sort direction: {sort_direction}"
                )

            if sort_column is not None:
                sql += (
                    f" ORDER BY {self._quote_identifier(sort_column)} "
                    f"{sort_direction.upper()}"
                )

        if plan.include_ties and not plan.sort_column:
            sql += f" ORDER BY {self._quote_identifier('aggregation_value')} DESC"

        sql += limit_clause

        try:
            with get_connection(self.config) as connection:
                cursor = connection.cursor()

                cursor.execute(
                    sql,
                    parameters,
                )

                if cursor.description is None:
                    return []

                column_names = [
                    description[0]
                    for description in cursor.description
                ]

                rows = cursor.fetchall()

                return [
                    {
                        col: str(val) if isinstance(val, uuid.UUID) else val
                        for col, val in zip(column_names, row)
                    }
                    for row in rows
                ]

        except SQLQueryExecutionError:
            raise

        except Exception as exc:
            self._handle_execution_exception(exc)

    def _execute_derived_aggregation(
        self,
        plan: QueryPlan,
        table: TableInfo,
        tables: list[TableInfo] | None = None,
    ) -> Any:
        """
        Execute a derived aggregation query:
        Inner subquery computes grouped aggregation (e.g. COUNT per entity).
        Outer query computes aggregate over the inner metrics (e.g. AVG, MEDIAN, MIN, MAX, SUM).
        Dialect-aware and schema-generic.
        """
        outer_aggregation = (plan.aggregation or "average").lower()
        if outer_aggregation not in {"average", "median", "max", "min", "sum"}:
            raise SQLQueryExecutionError(
                f"Unsupported outer aggregation for derived aggregation: {outer_aggregation}"
            )

        inner_aggregation = (plan.inner_aggregation or "count").lower()
        if inner_aggregation not in {"count", "sum", "average", "min", "max", "median"}:
            raise SQLQueryExecutionError(
                f"Unsupported inner aggregation for derived aggregation: {inner_aggregation}"
            )

        if not plan.group_by:
            raise SQLQueryExecutionError(
                "Derived aggregation requires at least one group-by column."
            )

        parameters: list[Any] = []

        if plan.joins:
            execution_tables = tables or [table]
            table_lookup = {
                (t.schema_name, t.table_name): t
                for t in execution_tables
            }

            aliases: dict[tuple[str, str], str] = {}
            joined_keys: set[tuple[str, str]] = set()
            join_sql_parts: list[str] = []

            def ensure_table_exists(key: tuple[str, str]) -> TableInfo:
                t = table_lookup.get(key)
                if t is None:
                    raise SQLQueryExecutionError(
                        f"JOIN references a table that was not selected: {key[0]}.{key[1]}"
                    )
                return t

            first_join = plan.joins[0]
            first_left_key = (first_join.left_schema, first_join.left_table)
            ensure_table_exists(first_left_key)
            aliases[first_left_key] = "t1"
            joined_keys.add(first_left_key)

            next_alias_number = 2
            for join in plan.joins:
                left_key = (join.left_schema, join.left_table)
                right_key = (join.right_schema, join.right_table)
                left_table = ensure_table_exists(left_key)
                right_table = ensure_table_exists(right_key)

                left_is_joined = left_key in joined_keys
                right_is_joined = right_key in joined_keys

                if not join_sql_parts:
                    if not left_is_joined or right_is_joined:
                        raise SQLQueryExecutionError("Invalid initial JOIN definition.")
                    aliases[right_key] = f"t{next_alias_number}"
                    next_alias_number += 1
                    joined_keys.add(right_key)
                else:
                    if left_is_joined and not right_is_joined:
                        aliases[right_key] = f"t{next_alias_number}"
                        next_alias_number += 1
                        joined_keys.add(right_key)
                    elif right_is_joined and not left_is_joined:
                        aliases[left_key] = f"t{next_alias_number}"
                        next_alias_number += 1
                        joined_keys.add(left_key)

                left_alias = aliases[left_key]
                right_alias = aliases[right_key]
                left_schema_q = self._quote_identifier(left_table.schema_name)
                left_table_q = self._quote_identifier(left_table.table_name)
                right_schema_q = self._quote_identifier(right_table.schema_name)
                right_table_q = self._quote_identifier(right_table.table_name)
                left_col_q = self._quote_identifier(join.left_column)
                right_col_q = self._quote_identifier(join.right_column)
                join_keyword = {
                    "inner": "INNER JOIN",
                    "left": "LEFT JOIN",
                    "right": "RIGHT JOIN",
                }.get(join.join_type, "INNER JOIN")

                if not join_sql_parts:
                    join_sql_parts.append(
                        f"FROM {left_schema_q}.{left_table_q} AS {left_alias} "
                        f"{join_keyword} {right_schema_q}.{right_table_q} AS {right_alias} "
                        f"ON {left_alias}.{left_col_q} = {right_alias}.{right_col_q}"
                    )
                else:
                    target_key = right_key if aliases[right_key] == f"t{next_alias_number - 1}" else left_key
                    other_key = left_key if target_key == right_key else right_key
                    target_table_info = table_lookup[target_key]
                    t_schema_q = self._quote_identifier(target_table_info.schema_name)
                    t_table_q = self._quote_identifier(target_table_info.table_name)
                    t_alias = aliases[target_key]
                    o_alias = aliases[other_key]
                    t_col = right_col_q if target_key == right_key else left_col_q
                    o_col = left_col_q if target_key == right_key else right_col_q
                    join_sql_parts.append(
                        f"{join_keyword} {t_schema_q}.{t_table_q} AS {t_alias} "
                        f"ON {o_alias}.{o_col} = {t_alias}.{t_col}"
                    )

            table_columns = {
                key: [col.name for col in table_lookup[key].columns]
                for key in joined_keys
            }

            def resolve_col_joined(col_name: str, refs: list[QueryColumn] | None = None) -> str:
                s_part, t_part, b_col = parse_column_reference(col_name)
                for r in (refs or []):
                    if r.column.lower() == col_name.lower() or r.column.lower() == b_col.lower():
                        for k in joined_keys:
                            if k[1].lower() == r.table.lower():
                                if not r.schema or k[0].lower() == r.schema.lower():
                                    return f"{aliases[k]}.{self._quote_identifier(r.column)}"
                if t_part:
                    for k in joined_keys:
                        if k[1].lower() == t_part.lower():
                            if not s_part or k[0].lower() == s_part.lower():
                                actual = next((c for c in table_columns[k] if c.lower() == b_col.lower()), b_col)
                                return f"{aliases[k]}.{self._quote_identifier(actual)}"
                matching = [k for k in joined_keys if any(c.lower() == b_col.lower() for c in table_columns[k])]
                if matching:
                    k = matching[0]
                    actual = next(c for c in table_columns[k] if c.lower() == b_col.lower())
                    return f"{aliases[k]}.{self._quote_identifier(actual)}"
                return f"{aliases[first_left_key]}.{self._quote_identifier(b_col)}"

            # Inner filters / WHERE
            where_parts: list[str] = []
            for qf in plan.filters:
                expr = resolve_col_joined(qf.column)
                op = qf.operator
                val = qf.value
                if op in {"is_null", "null"} or (op == "equals" and val is None):
                    where_parts.append(f"{expr} IS NULL")
                elif op in {"is_not_null", "not_null"} or (op == "not_equals" and val is None):
                    where_parts.append(f"{expr} IS NOT NULL")
                elif op == "equals":
                    where_parts.append(f"{expr} = ?")
                    parameters.append(val)
                elif op == "not_equals":
                    where_parts.append(f"{expr} <> ?")
                    parameters.append(val)
                elif op == "greater_than":
                    where_parts.append(f"{expr} > ?")
                    parameters.append(val)
                elif op == "greater_than_or_equal":
                    where_parts.append(f"{expr} >= ?")
                    parameters.append(val)
                elif op == "less_than":
                    where_parts.append(f"{expr} < ?")
                    parameters.append(val)
                elif op == "less_than_or_equal":
                    where_parts.append(f"{expr} <= ?")
                    parameters.append(val)
                elif op == "in" and isinstance(val, (list, tuple)) and val:
                    placeholders = ", ".join("?" for _ in val)
                    where_parts.append(f"{expr} IN ({placeholders})")
                    parameters.extend(val)

            from_sql = " ".join(join_sql_parts)
            where_sql = (" WHERE " + " AND ".join(where_parts)) if where_parts else ""

            # Inner group by expressions
            grp_exprs = [
                resolve_col_joined(c, plan.group_by_refs)
                for c in plan.group_by
            ]
            inner_group_by_sql = ", ".join(grp_exprs)

            # Inner aggregation expression
            if inner_aggregation == "count":
                if plan.target_columns and plan.target_columns[0] != "*" and plan.target_columns[0] not in plan.group_by:
                    target_expr = resolve_col_joined(plan.target_columns[0], plan.target_column_refs)
                    inner_agg_expr = f"COUNT({target_expr})"
                else:
                    inner_agg_expr = "COUNT(*)"
            else:
                inner_func = {
                    "sum": "SUM", "average": "AVG", "min": "MIN", "max": "MAX"
                }.get(inner_aggregation, "COUNT")
                if plan.target_columns:
                    target_expr = resolve_col_joined(plan.target_columns[0], plan.target_column_refs)
                    inner_agg_expr = f"{inner_func}({target_expr})"
                else:
                    inner_agg_expr = f"{inner_func}(*)"

            inner_subquery_sql = (
                f"SELECT {inner_group_by_sql}, {inner_agg_expr} AS {self._quote_identifier('__derived_metric')} "
                f"{from_sql}"
                f"{where_sql} "
                f"GROUP BY {inner_group_by_sql}"
            )

        else:
            # Single-table execution
            self._validate_qualified_references(plan, table)
            schema_name = self._quote_identifier(table.schema_name)
            table_name = self._quote_identifier(table.table_name)

            where_clause, filter_params = self._build_where_clause(plan.filters, table)
            parameters.extend(filter_params)

            table_columns = {c.name.lower(): c for c in table.columns}
            resolved_group_columns: list[str] = [
                self._resolve_single_table_column(c, table)
                for c in plan.group_by
            ]

            group_expressions: list[str] = []
            for resolved_group_col in resolved_group_columns:
                col_info = table_columns[resolved_group_col.lower()]
                expr, _ = self._build_group_expression(
                    column_name=resolved_group_col,
                    data_type=col_info.data_type,
                    granularity=getattr(plan, "group_by_granularity", None),
                )
                group_expressions.append(expr)

            inner_group_by_sql = ", ".join(group_expressions)

            if inner_aggregation == "count":
                if plan.target_columns and plan.target_columns[0] != "*" and plan.target_columns[0] not in plan.group_by:
                    resolved_target = self._resolve_single_table_column(plan.target_columns[0], table)
                    inner_agg_expr = f"COUNT({self._quote_identifier(resolved_target)})"
                else:
                    inner_agg_expr = "COUNT(*)"
            else:
                inner_func = {
                    "sum": "SUM", "average": "AVG", "min": "MIN", "max": "MAX"
                }.get(inner_aggregation, "COUNT")
                if plan.target_columns:
                    resolved_target = self._resolve_single_table_column(plan.target_columns[0], table)
                    inner_agg_expr = f"{inner_func}({self._quote_identifier(resolved_target)})"
                else:
                    inner_agg_expr = f"{inner_func}(*)"

            inner_subquery_sql = (
                f"SELECT {inner_group_by_sql}, {inner_agg_expr} AS {self._quote_identifier('__derived_metric')} "
                f"FROM {schema_name}.{table_name}"
                f"{where_clause} "
                f"GROUP BY {inner_group_by_sql}"
            )

        # ---------------------------------------------------------
        # Outer aggregation SQL
        # ---------------------------------------------------------
        metric_col = f"CAST(sub.{self._quote_identifier('__derived_metric')} AS FLOAT)"
        top_prefix = ""

        if outer_aggregation == "average":
            outer_agg_expr = f"AVG({metric_col})"
        elif outer_aggregation == "sum":
            outer_agg_expr = f"SUM({metric_col})"
        elif outer_aggregation == "min":
            outer_agg_expr = f"MIN({metric_col})"
        elif outer_aggregation == "max":
            outer_agg_expr = f"MAX({metric_col})"
        elif outer_aggregation == "median":
            if self.is_postgresql:
                outer_agg_expr = f"PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY {metric_col})"
            else:
                outer_agg_expr = f"PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY {metric_col}) OVER ()"
                top_prefix = "TOP (1) "

        sql = (
            f"SELECT {top_prefix}{outer_agg_expr} AS {self._quote_identifier('aggregation_value')} "
            f"FROM ({inner_subquery_sql}) AS sub"
        )

        try:
            with get_connection(self.config) as connection:
                cursor = connection.cursor()
                cursor.execute(sql, parameters)
                row = cursor.fetchone()
                if row is None:
                    return None
                val = getattr(row, "aggregation_value", None)
                if val is None:
                    try:
                        val = row[0]
                    except Exception:
                        val = None
                return val
        except SQLQueryExecutionError:
            raise
        except Exception as exc:
            self._handle_execution_exception(exc)
