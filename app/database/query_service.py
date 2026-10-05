from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.core.config import get_database_config
from app.database.entity_resolver import EntityResolver
from app.database.metadata_service import DatabaseMetadataService
from app.database.semantic_query_cache import SemanticQueryCache
from app.database.join_validator import validate_query_plan_joins
from app.database.schema import (
    DatabaseSchema,
    TableInfo,
    parse_column_reference,
)
from app.database.sql_executor import (
    SQLQueryExecutionError,
    SQLQueryExecutor,
)
from app.database.table_selector import select_tables
from app.query.analyzer import QuestionAnalyzer
from app.query.schema import QueryPlan
from app.query.validator import QueryPlanValidator
from app.query.result_validator import QueryResultValidator


class DatabaseQueryServiceError(Exception):
    """
    Raised when a database question cannot be planned,
    validated, or executed.
    """


@dataclass
class DatabaseQueryResult:
    plan: QueryPlan
    data: Any
    warnings: list[str]
    tables: list[Any] = field(default_factory=list)


class DatabaseQueryService:
    """
    Analyze, validate, and execute a natural-language question
    against the SQL Server database.

    Current execution model:
        Question
            ↓
        Primary table selection
            ↓
        Question analysis against that table
            ↓
        QueryPlan validation against that table
            ↓
        SQL execution against that table

    This service intentionally supports one execution table at
    this stage. Multi-table JOIN planning will be added separately
    after the single-table path is stable.

    No business-specific table or column names are hardcoded here.
    """

    def __init__(
        self,
        database_schema: DatabaseSchema,
        analyzer: QuestionAnalyzer | None = None,
        validator: QueryPlanValidator | None = None,
        executor: SQLQueryExecutor | None = None,
        result_validator: QueryResultValidator | None = None,
        metadata_service: DatabaseMetadataService | None = None,
        semantic_cache: SemanticQueryCache | None = None,
        entity_resolver: EntityResolver | None = None,
        relationship_service: Any | None = None,
        vector_service: Any | None = None,
    ):
        self.database_schema = database_schema
        self.analyzer = analyzer or QuestionAnalyzer()
        self.validator = validator or QueryPlanValidator()
        self.result_validator = (
            result_validator or QueryResultValidator()
        )
        self.entity_resolver = entity_resolver or EntityResolver(
            self.database_schema
        )

        # Phase 4: the cache is keyed against the Phase 3 structural
        # fingerprint. Final answers are never cached.
        self.metadata_service = metadata_service or DatabaseMetadataService()
        active_config = self.metadata_service.config or get_database_config()
        self.executor = executor or SQLQueryExecutor(config=active_config)
        metadata = self.metadata_service.load()
        self.database_server_name = metadata.server_name
        self.database_name = metadata.database_name
        self.schema_fingerprint = metadata.schema_fingerprint
        self.semantic_cache = semantic_cache or SemanticQueryCache()

        if vector_service is not None:
            self.vector_service = vector_service
        elif active_config.is_postgresql:
            from app.database.schema_vector_intelligence import SchemaVectorIntelligence
            try:
                self.vector_service = SchemaVectorIntelligence(config=active_config)
                self.vector_service.index_schema(
                    database_schema=self.database_schema,
                    schema_fingerprint=self.schema_fingerprint,
                )
            except Exception:
                self.vector_service = None
        else:
            self.vector_service = None

        if relationship_service is not None:
            self.relationship_service = relationship_service
        else:
            from app.database.relationship_service import RelationshipDiscoveryService
            self.relationship_service = RelationshipDiscoveryService(
                database_schema=self.database_schema,
                server_name=self.database_server_name,
                database_name=self.database_name,
                schema_fingerprint=self.schema_fingerprint,
            )

    # ==========================================================
    # PUBLIC API
    # ==========================================================

    def answer(
        self,
        question: str,
        conversation_context: dict[str, Any] | None = None,
    ) -> DatabaseQueryResult:

        question = (question or "").strip()

        if not question:
            raise DatabaseQueryServiceError(
                "Question cannot be empty."
            )

        # ------------------------------------------------------
        # 2. Resolve MULTIPLE relevant execution tables.
        # ------------------------------------------------------
        #
        # The selected tables become the authoritative scope for:
        #
        #   - QuestionAnalyzer
        #   - QueryPlanValidator
        #
        # SQL execution will continue to use the existing
        # single-table executor until JOIN execution is added.
        # ------------------------------------------------------

        try:
            tables = self._resolve_execution_tables(
                question=question,
                conversation_context=conversation_context,
            )
        except DatabaseQueryServiceError as exc:
            has_conversation_history = bool(
                conversation_context
                and conversation_context.get("history")
            )

            if not has_conversation_history:
                raise

            if str(exc) != "No database table could be selected for the question.":
                raise

            # A contextual follow-up may operate entirely on a
            # previously stored result and therefore need no database
            # execution table. Let the analyzer resolve it from the
            # conversation context.
            tables = []

        # ------------------------------------------------------
        # 2. Build a database schema containing ALL selected
        #    execution tables.
        # ------------------------------------------------------

        execution_schema = self._build_execution_schema(
            tables=tables
        )

        # ------------------------------------------------------
        # 3. Semantic query cache lookup.
        # ------------------------------------------------------
        # A cache hit reuses only the previously validated QueryPlan.
        # SQL Server is still queried below, so data remains current.
        # ------------------------------------------------------

        has_conversation_history = bool(
            conversation_context
            and conversation_context.get("history")
        )

        cached_plan = None

        if not has_conversation_history:
            cached_plan = self.semantic_cache.get(
                question=question,
                server_name=self.database_server_name,
                database_name=self.database_name,
                schema_fingerprint=self.schema_fingerprint,
            )

        if cached_plan is not None:
            cached_tables = self._prune_execution_tables(
                plan=cached_plan,
                tables=tables,
            )
            cached_schema = self._build_execution_schema(
                tables=cached_tables,
            )
            cached_validation = self.validator.validate(
                cached_plan,
                cached_schema,
            )

            cached_join_validation = validate_query_plan_joins(
                plan=cached_plan,
                database_schema=cached_schema,
                relationship_service=self.relationship_service,
            )

            if (
                cached_validation.valid
                and cached_join_validation.valid
            ):
                tables = cached_tables
                execution_schema = cached_schema
                plan_warnings = [
                    *cached_validation.warnings,
                    *cached_join_validation.warnings,
                    "Semantic query cache hit; reused the validated query plan.",
                ]

                if cached_plan.intent == "unsupported":
                    return DatabaseQueryResult(
                        plan=cached_plan,
                        data=(
                            cached_plan.explanation.strip()
                            or "I can't answer that from the database."
                        ),
                        warnings=plan_warnings,
                        tables=tables,
                    )

                if cached_plan.joins:
                    cached_table = self._resolve_join_execution_table(
                        plan=cached_plan,
                        tables=tables,
                    )
                else:
                    cached_table = self._resolve_single_execution_table_for_plan(
                        plan=cached_plan,
                        tables=tables,
                    )

                try:
                    cached_data = self.executor.execute(
                        plan=cached_plan,
                        table=cached_table,
                        tables=tables,
                    )

                    cached_result_validation = (
                        self.result_validator.validate(
                            plan=cached_plan,
                            data=cached_data,
                        )
                    )

                    if not cached_result_validation.valid:
                        raise DatabaseQueryServiceError(
                            "Query result validation failed: "
                            + "; ".join(
                                cached_result_validation.errors
                            )
                        )

                except SQLQueryExecutionError as exc:
                    raise DatabaseQueryServiceError(
                        f"Query execution failed: {exc}"
                    ) from exc

                return DatabaseQueryResult(
                    plan=cached_plan,
                    data=cached_data,
                    warnings=plan_warnings,
                    tables=tables,
                )

            # A cached plan is never allowed to bypass current validation.
            self.semantic_cache.delete(
                question=question,
                server_name=self.database_server_name,
                database_name=self.database_name,
                schema_fingerprint=self.schema_fingerprint,
            )

        # ------------------------------------------------------
        # 4. Analyze the question against ALL selected tables.
        # ------------------------------------------------------

        try:
            plan = self.analyzer.analyze(
                question=question,
                semantic_schema=execution_schema,
                conversation_context=conversation_context,
            )

        except TypeError:
            # Compatibility with older analyzer signatures.
            try:
                plan = self.analyzer.analyze(
                    question,
                    execution_schema,
                )
            except Exception as exc:
                raise DatabaseQueryServiceError(
                    f"Question analysis failed: {exc}"
                ) from exc

        except Exception as exc:
            raise DatabaseQueryServiceError(
                f"Question analysis failed: {exc}"
            ) from exc

        # ------------------------------------------------------
        # Phase 10: a referenced conversation result has its own
        # column scope. Do not validate it against the newly selected
        # database tables.
        # ------------------------------------------------------
        # ------------------------------------------------------
        # Phase 8: Follow-up result execution check (Mode 1 vs Mode 2)
        # ------------------------------------------------------
        # Mode 1 (In-Memory): The referenced entry exists, contains
        # tabular data, and has all columns required for the follow-up
        # (projection, filtering, sorting, or aggregated result filter).
        #
        # Mode 2 (SQL Server Re-Query): The follow-up requests columns,
        # entities, or relationships not present in the saved result,
        # or the previous result was scalar (e.g. count 600).
        # In this mode, we clear input_result_reference and execute against
        # SQL Server using the semantic schema and prior query context.
        # ------------------------------------------------------
        if getattr(plan, "input_result_reference", None):
            referenced_entry = self._get_referenced_conversation_entry(
                conversation_context=conversation_context,
                reference_id=plan.input_result_reference,
            )

            if referenced_entry is None:
                # Stale or invalid reference. If tables were selected,
                # fall back to SQL Server execution; otherwise fail safely.
                if not tables:
                    raise DatabaseQueryServiceError(
                        "The referenced conversation result could not be found."
                    )
                plan.input_result_reference = None
            elif self._can_execute_in_memory(
                plan=plan,
                referenced_entry=referenced_entry,
            ):
                data = self._execute_conversation_result_plan(
                    plan=plan,
                    conversation_context=conversation_context,
                )

                result_validation = self.result_validator.validate(
                    plan=plan,
                    data=data,
                )

                if not result_validation.valid:
                    raise DatabaseQueryServiceError(
                        "Query result validation failed: "
                        + "; ".join(result_validation.errors)
                    )

                return DatabaseQueryResult(
                    plan=plan,
                    data=data,
                    warnings=[
                        "Executed against the referenced conversation result.",
                    ],
                    tables=tables,
                )
            else:
                # Mode 2: Clear input_result_reference so that the
                # plan executes as a normal database query against SQL Server.
                plan.input_result_reference = None
                if not tables and referenced_entry:
                    tables = self._extract_prior_tables_from_context(conversation_context)
                    if tables:
                        execution_schema = self._build_execution_schema(tables=tables)

        # ------------------------------------------------------
        # Phase 4 correction: unsupported plans
        # ------------------------------------------------------
        # If the analyzer determined that the request is unsupported
        # (e.g. required tables or columns do not exist in the schema),
        # return the explanation directly without attempting SQL execution
        # or failing query plan validation.
        # ------------------------------------------------------
        if plan.intent == "unsupported":
            return DatabaseQueryResult(
                plan=plan,
                data=(
                    plan.explanation.strip()
                    or "I can't answer that from the database."
                ),
                warnings=[],
                tables=tables,
            )

        # ------------------------------------------------------
        # Post-planning execution schema pruning.
        # Prune unreferenced candidate tables based on the
        # tables actually required by the QueryPlan.
        # ------------------------------------------------------
        tables = self._prune_execution_tables(
            plan=plan,
            tables=tables,
        )
        execution_schema = self._build_execution_schema(
            tables=tables,
        )

        # ------------------------------------------------------
        # 4. Validate the plan against the pruned execution schema.
        # ------------------------------------------------------

        validation = self.validator.validate(
            plan,
            execution_schema,
        )

        if not validation.valid:
            raise DatabaseQueryServiceError(
                "QueryPlan validation failed: "
                + "; ".join(validation.errors)
            )

        # ------------------------------------------------------
        # 4b. Validate JOINs against relationship intelligence.
        #
        # The LLM may propose JOINs, but it cannot authorize them.
        # Only declared or data-validated relationships may execute.
        # ------------------------------------------------------

        join_validation = validate_query_plan_joins(
            plan=plan,
            database_schema=execution_schema,
            relationship_service=self.relationship_service,
        )

        if not join_validation.valid:
            raise DatabaseQueryServiceError(
                "JOIN validation failed: "
                + "; ".join(join_validation.errors)
            )

        plan_warnings = [
            *validation.warnings,
            *join_validation.warnings,
        ]

        # ------------------------------------------------------
        # Phase 4 / Phase 9: persist only validated plans.
        # Only cache standalone queries; do NOT cache plans generated with conversation context.
        # ------------------------------------------------------
        # The final SQL result is intentionally NOT cached.
        if not has_conversation_history:
            self.semantic_cache.set(
                question=question,
                server_name=self.database_server_name,
                database_name=self.database_name,
                schema_fingerprint=self.schema_fingerprint,
                plan=plan,
            )


        # ------------------------------------------------------
        # 7. Execute single-table plans using the existing executor.
        # ------------------------------------------------------

        if plan.joins:
            table = self._resolve_join_execution_table(
                plan=plan,
                tables=tables,
            )
        else:
            table = self._resolve_single_execution_table_for_plan(
                plan=plan,
                tables=tables,
            )

        try:
            data = self.executor.execute(
                plan=plan,
                table=table,
                tables=tables,
            )

            result_validation = self.result_validator.validate(
                plan=plan,
                data=data,
            )

            if not result_validation.valid:
                raise DatabaseQueryServiceError(
                    "Query result validation failed: "
                    + "; ".join(result_validation.errors)
                )

        except SQLQueryExecutionError as exc:
            raise DatabaseQueryServiceError(
                f"Query execution failed: {exc}"
            ) from exc

        return DatabaseQueryResult(
            plan=plan,
            data=data,
            warnings=plan_warnings,
            tables=tables,
        )

    # ==========================================================
    # CONVERSATION RESULT EXECUTION
    # ==========================================================

    @staticmethod
    def _get_referenced_conversation_entry(
        conversation_context: dict[str, Any] | None,
        reference_id: str | None,
    ) -> dict[str, Any] | None:
        """
        Locate the specific conversation entry matching reference_id.
        """
        if not conversation_context or not reference_id:
            return None
        history = conversation_context.get("history") or []
        for entry in history:
            if str(entry.get("reference_id", "")) == str(reference_id):
                return entry
        return None

    @classmethod
    def _can_execute_in_memory(
        cls,
        plan: QueryPlan,
        referenced_entry: dict[str, Any],
    ) -> bool:
        """
        Determine whether a QueryPlan can execute entirely in memory against
        a previous conversation result (Mode 1), or whether it requires
        re-querying SQL Server (Mode 2).
        """
        source_data = referenced_entry.get("data")
        if not isinstance(source_data, list) or not source_data:
            return False

        if not all(isinstance(row, dict) for row in source_data):
            return False

        # Any query requiring JOINs must execute against SQL Server
        if plan.joins:
            return False

        # Extract available columns from the previous result
        first_row = source_data[0]
        available_columns = set(first_row.keys())
        if referenced_entry.get("columns"):
            available_columns |= {str(c) for c in referenced_entry["columns"]}

        # Aggregation aliases that map to the generic aggregation_value column
        agg_aliases = {
            "aggregation_value",
            "count",
            "sum",
            "average",
            "avg",
            "min",
            "max",
            "total",
            "value",
        }

        # Check target columns
        if plan.target_columns:
            for col in plan.target_columns:
                if col not in available_columns:
                    if col in agg_aliases and "aggregation_value" in available_columns:
                        continue
                    return False

        # Check filters
        filters = getattr(plan, "filters", []) or []
        for item in filters:
            if item is not None and getattr(item, "column", None):
                col = item.column
                if col not in available_columns:
                    if col in agg_aliases and "aggregation_value" in available_columns:
                        continue
                    return False

        # Check having filters
        having_filters = getattr(plan, "having_filters", []) or []
        for item in having_filters:
            if item is not None and getattr(item, "column", None):
                col = item.column
                if col not in available_columns:
                    if col in agg_aliases and "aggregation_value" in available_columns:
                        continue
                    return False

        # Check sort column
        sort_column = getattr(plan, "sort_column", None)
        if sort_column:
            if sort_column not in available_columns:
                if sort_column in agg_aliases and "aggregation_value" in available_columns:
                    pass
                else:
                    return False

        # Raw aggregations over underlying data (like average, sum) cannot be computed
        # from grouped or projected rows
        if plan.aggregation and plan.aggregation not in ("count",):
            return False

        return True

    def _execute_conversation_result_plan(
        self,
        plan: QueryPlan,
        conversation_context: dict[str, Any] | None,
    ) -> Any:
        """
        Execute a validated QueryPlan against a previous conversation
        result in memory (Mode 1).
        """
        if not conversation_context:
            raise DatabaseQueryServiceError(
                "This follow-up requires conversation context."
            )

        reference_id = getattr(
            plan,
            "input_result_reference",
            None,
        )

        if not reference_id:
            raise DatabaseQueryServiceError(
                "Conversation result execution requires a reference ID."
            )

        referenced_entry = self._get_referenced_conversation_entry(
            conversation_context=conversation_context,
            reference_id=reference_id,
        )

        if referenced_entry is None:
            raise DatabaseQueryServiceError(
                "The referenced conversation result could not be found."
            )

        source_data = referenced_entry.get("data")

        if not isinstance(source_data, list):
            raise DatabaseQueryServiceError(
                "The referenced conversation result is not a row-based result."
            )

        if not all(isinstance(row, dict) for row in source_data):
            raise DatabaseQueryServiceError(
                "The referenced conversation result does not contain named columns."
            )

        rows = [dict(row) for row in source_data]

        available_columns = set(rows[0].keys()) if rows else set()
        agg_aliases = {
            "aggregation_value", "count", "sum", "average", "avg", "min", "max", "total", "value"
        }

        def _resolve_col_alias(col: str) -> str:
            if col in available_columns:
                return col
            if col in agg_aliases and "aggregation_value" in available_columns:
                return "aggregation_value"
            return col

        # ------------------------------------------------------
        # Deterministic filtering & having filters.
        # ------------------------------------------------------
        all_filters = [
            item
            for item in [
                *getattr(plan, "filters", []),
                *getattr(plan, "having_filters", []),
            ]
            if item is not None
        ]

        if all_filters:
            missing_filter_columns = [
                item.column
                for item in all_filters
                if _resolve_col_alias(item.column) not in available_columns
            ]

            if missing_filter_columns:
                raise DatabaseQueryServiceError(
                    "Conversation result does not contain filter "
                    f"column(s): {missing_filter_columns}"
                )

            def _matches_filter(row: dict[str, Any], filter_item: Any) -> bool:
                col = _resolve_col_alias(filter_item.column)
                value = row.get(col)
                operator = str(filter_item.operator or "").strip().casefold()
                expected = filter_item.value

                if operator == "equals":
                    return value == expected

                if operator == "not_equals":
                    return value != expected

                if operator == "contains":
                    return (
                        value is not None
                        and str(expected).casefold()
                        in str(value).casefold()
                    )

                if operator == "starts_with":
                    return (
                        value is not None
                        and str(value).casefold().startswith(
                            str(expected).casefold()
                        )
                    )

                if operator == "ends_with":
                    return (
                        value is not None
                        and str(value).casefold().endswith(
                            str(expected).casefold()
                        )
                    )

                if operator == "in":
                    if not isinstance(expected, (list, tuple, set)):
                        return False
                    return value in expected

                # Numeric comparisons with type coercion
                try:
                    val_num = float(value) if value is not None else None
                    exp_num = float(expected) if expected is not None else None
                except (ValueError, TypeError):
                    val_num = None
                    exp_num = None

                if val_num is not None and exp_num is not None:
                    if operator == "greater_than":
                        return val_num > exp_num
                    if operator == "greater_than_or_equal":
                        return val_num >= exp_num
                    if operator == "less_than":
                        return val_num < exp_num
                    if operator == "less_than_or_equal":
                        return val_num <= exp_num
                else:
                    if operator == "greater_than":
                        return value is not None and value > expected
                    if operator == "greater_than_or_equal":
                        return value is not None and value >= expected
                    if operator == "less_than":
                        return value is not None and value < expected
                    if operator == "less_than_or_equal":
                        return value is not None and value <= expected

                raise DatabaseQueryServiceError(
                    "Unsupported conversation-result filter operator: "
                    f"{filter_item.operator}"
                )

            require_all = bool(
                getattr(plan, "require_all_filter_values", False)
            )

            if require_all:
                rows = [
                    row
                    for row in rows
                    if all(_matches_filter(row, item) for item in all_filters)
                ]
            else:
                rows = [
                    row
                    for row in rows
                    if all(_matches_filter(row, item) for item in all_filters)
                ]

        # ------------------------------------------------------
        # Target-column projection.
        # ------------------------------------------------------
        target_columns = [
            column
            for column in getattr(plan, "target_columns", [])
            if column
        ]

        if target_columns:
            missing_columns = [
                column
                for column in target_columns
                if _resolve_col_alias(column) not in available_columns
            ]

            if missing_columns:
                raise DatabaseQueryServiceError(
                    "Conversation result does not contain requested "
                    f"column(s): {missing_columns}"
                )

            rows = [
                {
                    column: row.get(_resolve_col_alias(column))
                    for column in target_columns
                }
                for row in rows
            ]

        # ------------------------------------------------------
        # Deterministic sorting.
        # ------------------------------------------------------
        sort_column = getattr(plan, "sort_column", None)

        if sort_column:
            sort_col_to_use = _resolve_col_alias(sort_column)

            if sort_col_to_use not in available_columns:
                raise DatabaseQueryServiceError(
                    "Conversation result does not contain sort column: "
                    f"{sort_column}"
                )

            reverse = (
                getattr(plan, "sort_direction", "asc") == "desc"
            )

            def _sort_key(row: dict[str, Any]) -> tuple:
                val = row.get(sort_col_to_use)
                if val is None:
                    return (1, "")
                if isinstance(val, str):
                    return (0, val.casefold())
                return (0, val)

            rows.sort(
                key=_sort_key,
                reverse=reverse,
            )

        # ------------------------------------------------------
        # Deterministic limiting.
        # ------------------------------------------------------
        limit = getattr(plan, "limit", None)
        if limit is not None and isinstance(limit, int) and limit > 0:
            rows = rows[:limit]

        if plan.intent in ("count", "row_count") or (plan.aggregation == "count" and not plan.group_by):
            return len(rows)

        return rows

    # ==========================================================
    # TABLE RESOLUTION
    # ==========================================================

    @classmethod
    def _is_contextual_follow_up(cls, question: str) -> bool:
        """
        Detect if a question is a contextual follow-up referring to previous turns.
        Generic lexical patterns only — no business or table names.
        """
        if QuestionAnalyzer._is_aggregate_detail_request(question):
            return True

        words = set(re.findall(r"\b\w+\b", question.casefold()))
        demonstratives = {"those", "these", "them", "that", "their", "they", "it", "this"}
        if words & demonstratives:
            return True

        q = question.strip().casefold()
        continuation_prefixes = (
            "only ", "also ", "and ", "sort by ", "order by ", "filter by ",
            "filter where ", "show only ", "show the first ", "show first ",
            "show top ", "limit to ", "which of these ", "who among them ",
            "what about ", "show details", "details of", "show the details",
            "show me details", "show me the details", "show records",
            "show the records", "show me the records", "show rows",
            "show the rows", "show me the rows", "show those ", "show these ",
        )
        if any(q.startswith(prefix) for prefix in continuation_prefixes):
            return True

        return False

    def _extract_prior_tables_from_context(
        self,
        conversation_context: dict[str, Any] | None,
    ) -> list[TableInfo]:
        """
        Extract resolved TableInfo objects from recent conversation history.
        Generic and backward-compatible.
        """
        if not conversation_context:
            return []

        history = conversation_context.get("history") or []
        if not history:
            return []

        prior_tables: list[TableInfo] = []
        seen_keys: set[tuple[str, str]] = set()

        for entry in reversed(history):
            raw_tables = entry.get("tables") or []
            for t in raw_tables:
                if isinstance(t, dict):
                    schema_name = t.get("schema")
                    table_name = t.get("table")
                    if schema_name and table_name:
                        key = (schema_name, table_name)
                        if key not in seen_keys:
                            tbl = self.database_schema.get_table(schema_name, table_name)
                            if tbl is None and t.get("columns"):
                                from app.database.schema import ColumnInfo
                                col_objs = [
                                    ColumnInfo(
                                        name=c.get("name", ""),
                                        data_type=c.get("data_type", ""),
                                        nullable=c.get("nullable", True),
                                        ordinal_position=c.get("ordinal_position", idx),
                                    )
                                    for idx, c in enumerate(t.get("columns", []))
                                ]
                                tbl = TableInfo(
                                    schema_name=schema_name,
                                    table_name=table_name,
                                    columns=col_objs,
                                    primary_key_columns=t.get("primary_key_columns", []),
                                )
                            if tbl is not None:
                                prior_tables.append(tbl)
                                seen_keys.add(key)

            plan = entry.get("plan")
            if isinstance(plan, dict):
                for ref in plan.get("target_column_refs") or []:
                    if isinstance(ref, dict):
                        s = ref.get("schema")
                        t = ref.get("table")
                        if s and t and (s, t) not in seen_keys:
                            tbl = self.database_schema.get_table(s, t)
                            if tbl is not None:
                                prior_tables.append(tbl)
                                seen_keys.add((s, t))
                for join in plan.get("joins") or []:
                    if isinstance(join, dict):
                        for s_key, t_key in [("left_schema", "left_table"), ("right_schema", "right_table")]:
                            s = join.get(s_key)
                            t = join.get(t_key)
                            if s and t and (s, t) not in seen_keys:
                                tbl = self.database_schema.get_table(s, t)
                                if tbl is not None:
                                    prior_tables.append(tbl)
                                    seen_keys.add((s, t))

            if not prior_tables and entry.get("question"):
                try:
                    cand = select_tables(
                        question=entry["question"],
                        schema=self.database_schema.tables,
                        max_tables=3,
                        relationships=self.database_schema.foreign_keys,
                        entity_resolver=self.entity_resolver,
                        relationship_service=self.relationship_service,
                        vector_service=getattr(self, "vector_service", None),
                        schema_fingerprint=getattr(self, "schema_fingerprint", None),
                    )
                    for c in cand:
                        key = (c["schema"], c["table"])
                        if key not in seen_keys:
                            tbl = self.database_schema.get_table(c["schema"], c["table"])
                            if tbl is not None:
                                prior_tables.append(tbl)
                                seen_keys.add(key)
                except Exception:
                    pass

            if prior_tables:
                break

        return prior_tables

    def _resolve_execution_tables(
        self,
        question: str,
        conversation_context: dict[str, Any] | None = None,
    ) -> list[TableInfo]:

        has_history = bool(
            conversation_context and conversation_context.get("history")
        )
        is_agg_detail = QuestionAnalyzer._is_aggregate_detail_request(question)

        # For an aggregate detail follow-up, the prior execution tables ARE the authoritative tables
        if is_agg_detail and has_history:
            prior_tables = self._extract_prior_tables_from_context(
                conversation_context
            )
            if prior_tables:
                print(
                    "\n========== DATABASE TABLE SELECTION (AGGREGATE DETAIL) =========="
                )
                print("QUESTION:", question)
                for index, table in enumerate(prior_tables, start=1):
                    print(
                        f"REUSED PRIOR TABLE {index}: {table.schema_name}.{table.table_name}"
                    )
                print("=================================================================\n")
                return prior_tables

        candidates = select_tables(
            question=question,
            schema=self.database_schema.tables,
            max_tables=5,
            relationships=self.database_schema.foreign_keys,
            entity_resolver=self.entity_resolver,
            relationship_service=self.relationship_service,
            vector_service=getattr(self, "vector_service", None),
            schema_fingerprint=getattr(self, "schema_fingerprint", None),
        )

        tables: list[TableInfo] = []

        if candidates:
            for candidate in candidates:
                table = self.database_schema.get_table(
                    candidate["schema"],
                    candidate["table"],
                )
                if table is not None:
                    tables.append(table)

        # Context-aware table augmentation/fallback
        is_follow_up = self._is_contextual_follow_up(question)

        if has_history and (not tables or is_follow_up):
            prior_tables = self._extract_prior_tables_from_context(
                conversation_context
            )
            existing_keys = {
                (t.schema_name, t.table_name) for t in tables
            }
            for prior_table in prior_tables:
                if (prior_table.schema_name, prior_table.table_name) not in existing_keys:
                    if len(tables) < 5:
                        tables.append(prior_table)
                        existing_keys.add(
                            (prior_table.schema_name, prior_table.table_name)
                        )

        if not tables:
            raise DatabaseQueryServiceError(
                "No database table could be selected for the question."
            )

        print(
            "\n========== DATABASE TABLE SELECTION =========="
        )
        print(
            "QUESTION:",
            question,
        )

        for index, table in enumerate(tables, start=1):
            print(
                f"SELECTED TABLE {index}: "
                f"{table.schema_name}.{table.table_name}"
            )

        print(
            "==============================================\n"
        )

        return tables

    def _prune_execution_tables(
        self,
        plan: QueryPlan,
        tables: list[TableInfo],
    ) -> list[TableInfo]:
        """
        Generic post-planning execution schema pruning.

        Derives the minimum sufficient set of database tables required by the
        QueryPlan and prunes unreferenced companion tables.
        Works generically for arbitrary schemas without hardcoded table names.
        """
        if not tables or len(tables) <= 1 or getattr(plan, "intent", None) == "unsupported":
            return tables

        required_table_keys: set[tuple[str, str]] = set()

        # 1. Collect tables from JOINs
        if getattr(plan, "joins", None):
            for j in plan.joins:
                required_table_keys.add((j.left_schema.lower(), j.left_table.lower()))
                required_table_keys.add((j.right_schema.lower(), j.right_table.lower()))

        # 2. Collect tables from explicit QueryColumn references
        for ref in (getattr(plan, "target_column_refs", []) or []) + (getattr(plan, "group_by_refs", []) or []):
            if ref and getattr(ref, "table", None):
                ref_tbl = str(ref.table).lower()
                ref_sch = str(ref.schema).lower() if getattr(ref, "schema", None) else None
                for t in tables:
                    if t.table_name.lower() == ref_tbl:
                        if ref_sch is None or t.schema_name.lower() == ref_sch:
                            required_table_keys.add((t.schema_name.lower(), t.table_name.lower()))

        # 3. Collect tables from qualified column strings in target_columns, group_by, filters, sort_column
        raw_cols = list(getattr(plan, "target_columns", []) or []) + list(getattr(plan, "group_by", []) or [])
        if getattr(plan, "sort_column", None):
            raw_cols.append(plan.sort_column)
        for f in (getattr(plan, "filters", []) or []):
            if f and getattr(f, "column", None):
                raw_cols.append(f.column)

        for col_str in raw_cols:
            sch_p, tbl_p, _ = parse_column_reference(str(col_str))
            if tbl_p:
                tbl_lower = tbl_p.lower()
                sch_lower = sch_p.lower() if sch_p else None
                for t in tables:
                    if t.table_name.lower() == tbl_lower:
                        if sch_lower is None or t.schema_name.lower() == sch_lower:
                            required_table_keys.add((t.schema_name.lower(), t.table_name.lower()))

        # If explicit required tables were identified
        if required_table_keys:
            matched = [
                t for t in tables
                if (t.schema_name.lower(), t.table_name.lower()) in required_table_keys
            ]
            if matched:
                return matched

        # 4. If no JOINs and no explicit table qualifications, attempt single-table resolution
        if not getattr(plan, "joins", None):
            try:
                single_table = self._resolve_single_execution_table_for_plan(plan, tables)
                if single_table:
                    return [single_table]
            except Exception:
                pass

        return tables

    def _resolve_join_execution_table(
        self,
        plan: QueryPlan,
        tables: list[TableInfo],
    ) -> TableInfo:
        """
        Resolve the base table for a JOIN query.

        The actual JOIN structure comes from QueryPlan.joins.
        This method only resolves the left table referenced
        by the JOIN against the selected database tables.
        """

        if not plan.joins:
            raise DatabaseQueryServiceError(
                "JOIN execution requires at least one JOIN."
            )

        join = plan.joins[0]

        for table in tables:
            if (
                table.schema_name == join.left_schema
                and table.table_name == join.left_table
            ):
                return table

        raise DatabaseQueryServiceError(
            "JOIN base table was not selected: "
            f"{join.left_schema}.{join.left_table}"
        )

    # ==========================================================
    # EXECUTION SCHEMA
    # ==========================================================

    def _build_execution_schema(
        self,
        tables: list[TableInfo],
    ) -> DatabaseSchema:
        """
        Create the schema visible to the analyzer and validator.

        All structurally selected tables are included.

        Declared foreign keys and unique constraints are retained
        only when their participating tables are present in the
        selected execution schema.

        This method contains no business-specific table or
        column logic.
        """

        selected_table_keys = {
            (
                table.schema_name,
                table.table_name,
            )
            for table in tables
        }

        foreign_keys = [
            fk
            for fk in self.database_schema.foreign_keys
            if (
                fk.schema_name,
                fk.table_name,
            ) in selected_table_keys
            and (
                fk.referenced_schema_name,
                fk.referenced_table_name,
            ) in selected_table_keys
        ]

        unique_constraints = [
            uc
            for uc in self.database_schema.unique_constraints
            if (
                uc.schema_name,
                uc.table_name,
            ) in selected_table_keys
        ]

        schema = DatabaseSchema(
            tables=tables,
            foreign_keys=foreign_keys,
            unique_constraints=unique_constraints,
        )
        schema.is_execution_schema = True
        return schema

    @staticmethod
    def _resolve_single_execution_table_for_plan(
        plan: QueryPlan,
        tables: list[TableInfo],
    ) -> TableInfo:
        """
        Resolve the table required by a single-table QueryPlan.

        Qualified QueryColumn references from the QueryPlan are treated
        as authoritative. This prevents ambiguity when multiple selected
        tables contain the same column name.

        If qualified references are unavailable, resolution falls back
        to the existing unqualified-column matching logic.
        """

        if not tables:
            raise DatabaseQueryServiceError(
                "No execution table is available."
            )

        if plan.joins:
            raise DatabaseQueryServiceError(
                "A multi-table plan cannot be executed by the "
                "single-table SQL executor."
            )

        # ------------------------------------------------------
        # 1. Prefer qualified target-column & group-by references.
        # ------------------------------------------------------
        qualified_table_keys: set[tuple[str | None, str]] = set()

        for ref in getattr(plan, "target_column_refs", []) + getattr(plan, "group_by_refs", []):
            if ref.table:
                qualified_table_keys.add(
                    (
                        ref.schema if ref.schema else None,
                        ref.table,
                    )
                )

        # Also inspect string column references for table qualification (e.g. "orders.id")
        raw_col_refs = list(plan.target_columns) + list(plan.group_by)
        if plan.sort_column:
            raw_col_refs.append(plan.sort_column)
        for f in plan.filters:
            if f.column:
                raw_col_refs.append(f.column)

        for col_str in raw_col_refs:
            sch, tbl, _ = parse_column_reference(col_str)
            if tbl:
                qualified_table_keys.add((sch, tbl))

        # ------------------------------------------------------
        # 2. Resolve qualified references against the selected
        #    execution tables.
        # ------------------------------------------------------

        if qualified_table_keys:
            matching_qualified_tables: list[TableInfo] = []
            for table in tables:
                table_schema_lower = table.schema_name.lower()
                table_name_lower = table.table_name.lower()
                for q_schema, q_table in qualified_table_keys:
                    if q_table.lower() == table_name_lower:
                        if q_schema is None or q_schema.lower() == table_schema_lower:
                            if table not in matching_qualified_tables:
                                matching_qualified_tables.append(table)

            if len(matching_qualified_tables) == 1:
                return matching_qualified_tables[0]

            if len(matching_qualified_tables) > 1:
                raise DatabaseQueryServiceError(
                    "QueryPlan references multiple tables but does "
                    "not contain JOIN information: "
                    + str(
                        sorted(
                            f"{s}.{t}" if s else t
                            for s, t in qualified_table_keys
                        )
                    )
                )

            raise DatabaseQueryServiceError(
                "QueryPlan references a table that was not selected: "
                + str(
                    sorted(
                        f"{s}.{t}" if s else t
                        for s, t in qualified_table_keys
                    )
                )
            )

        # ------------------------------------------------------
        # 3. Collect unqualified columns referenced by the plan.
        # ------------------------------------------------------

        referenced_columns: set[str] = set()

        aggregate_virtual_names = {
            "count",
            "sum",
            "average",
            "min",
            "max",
            "median",
            "aggregation_value",
            "percentage",
        }

        for col_str in raw_col_refs:
            if not col_str or col_str in aggregate_virtual_names:
                continue
            _, _, base_col = parse_column_reference(col_str)
            if base_col:
                referenced_columns.add(base_col.lower())

        # ------------------------------------------------------
        # 4. If no physical columns are referenced, preserve
        #    the existing deterministic behavior.
        # ------------------------------------------------------

        if not referenced_columns:
            return tables[0]

        # ------------------------------------------------------
        # 5. Find tables containing all referenced columns.
        # ------------------------------------------------------

        matching_tables: list[TableInfo] = []

        for table in tables:
            table_columns = {
                column.name.lower()
                for column in table.columns
            }

            if referenced_columns.issubset(table_columns):
                matching_tables.append(table)

        # ------------------------------------------------------
        # 6. Exactly one table contains all columns.
        # ------------------------------------------------------

        if len(matching_tables) == 1:
            return matching_tables[0]

        # ------------------------------------------------------
        # 7. Multiple tables contain all columns.
        #
        # Do NOT arbitrarily choose one. The previous behavior
        # could select the wrong table when common column names
        # existed across several tables.
        # ------------------------------------------------------

        if len(matching_tables) > 1:
            raise DatabaseQueryServiceError(
                "QueryPlan references columns that are ambiguous "
                "across multiple selected tables: "
                + str(
                    [
                        (
                            table.schema_name,
                            table.table_name,
                        )
                        for table in matching_tables
                    ]
                )
            )

        # ------------------------------------------------------
        # 8. No single table contains all referenced columns.
        # ------------------------------------------------------

        column_locations: dict[str, list[str]] = {}

        for column_name in referenced_columns:
            locations: list[str] = []

            for table in tables:
                if any(
                    column.name.lower() == column_name
                    for column in table.columns
                ):
                    locations.append(
                        f"{table.schema_name}.{table.table_name}"
                    )

            column_locations[column_name] = locations

        raise DatabaseQueryServiceError(
            "QueryPlan references columns that cannot be "
            "resolved to a single execution table: "
            + str(column_locations)
        )
    