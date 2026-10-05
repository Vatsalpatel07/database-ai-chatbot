from __future__ import annotations

import json
import re
from typing import Any

from app.database.schema import DatabaseSchema, TableInfo, parse_column_reference
from app.database.table_selector import select_tables
from app.database.relationship_service import RelationshipDiscoveryService
from app.query.schema import (
    QueryPlan,
    QueryFilter,
    QueryJoin,
    QueryColumn,
)


class QuestionAnalyzer:
    """
    Converts a natural-language user question into a QueryPlan.

    DeepSeek is used for semantic interpretation.
    Python logic normalizes and repairs the returned plan so that
    common query structures are represented correctly.

    This component does not execute queries.
    """

    VALID_INTENTS = {
        "lookup",
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

    OPERATOR_ALIASES = {
        "=": "equals",
        "==": "equals",
        "equals": "equals",
        "equal": "equals",
        "is": "equals",
        "in": "in",
        "one_of": "in",
        "one of": "in",
        "among": "in",

        "!=": "not_equals",
        "<>": "not_equals",
        "not_equals": "not_equals",
        "not equal": "not_equals",
        "not_equal": "not_equals",

        ">": "greater_than",
        "greater_than": "greater_than",
        "greater than": "greater_than",

        ">=": "greater_than_or_equal",
        "greater_than_or_equal": "greater_than_or_equal",
        "greater than or equal": "greater_than_or_equal",

        "<": "less_than",
        "less_than": "less_than",
        "less than": "less_than",

        "<=": "less_than_or_equal",
        "less_than_or_equal": "less_than_or_equal",
        "less than or equal": "less_than_or_equal",

        "contains": "contains",
        "contain": "contains",

        "starts_with": "starts_with",
        "starts with": "starts_with",

        "ends_with": "ends_with",
        "ends with": "ends_with",

        "is_null": "is_null",
        "is null": "is_null",
        "null": "is_null",
        "is_not_null": "is_not_null",
        "is not null": "is_not_null",
        "not null": "is_not_null",
        "not_null": "is_not_null",

        # SQL-style operator accepted from LLM output. It is converted
        # deterministically to starts_with/ends_with/contains/equals
        # before QueryPlan validation.
        "like": "like",

        # Year filter operator variations accepted from LLM output.
        # Converted deterministically to canonical date ranges.
        "year": "year",
        "year_equals": "year",
        "year equal": "year",
        "year_is": "year",
        "in_year": "year",
        "in year": "year",
    }

    VALID_SORT_DIRECTIONS = {
        "asc",
        "desc",
    }

    def __init__(
        self,
        client: Any | None = None,
    ):
        if client is None:
            from app.llm.deepseek_client import DeepSeekClient

            client = DeepSeekClient()

        self.client = client

    # ==========================================================
    # PUBLIC API
    # ==========================================================

    def analyze(
        self,
        question: str,
        semantic_schema: Any,
        conversation_context: dict[str, Any] | None = None,
    ) -> QueryPlan:

        question = (question or "").strip()

        if not question:
            raise ValueError(
                "Question cannot be empty."
            )

        # If the schema is already scoped as the authoritative execution schema
        # (e.g. from DatabaseQueryService) or has at most 5 tables, use the
        # provided tables directly. This avoids duplicate selection overhead
        # and prevents bridge tables (score: 0) from being dropped.
        if (
            getattr(semantic_schema, "is_execution_schema", False)
            or len(semantic_schema.tables) <= 5
        ):
            selected_tables = list(semantic_schema.tables)
        else:
            selected_tables = self._select_database_tables(
                question=question,
                database_schema=semantic_schema,
            )

        selected_schema = DatabaseSchema(
            tables=selected_tables,
            foreign_keys=[
                fk
                for fk in semantic_schema.foreign_keys
                if any(
                    table.schema_name == fk.schema_name
                    and table.table_name == fk.table_name
                    for table in selected_tables
                )
                and any(
                    table.schema_name == fk.referenced_schema_name
                    and table.table_name == fk.referenced_table_name
                    for table in selected_tables
                )
            ],
            unique_constraints=[
                uc
                for uc in semantic_schema.unique_constraints
                if any(
                    table.schema_name == uc.schema_name
                    and table.table_name == uc.table_name
                    for table in selected_tables
                )
            ],
        )

        semantic_context = self._schema_to_context(
            selected_schema
        )

        # ------------------------------------------------------
        # Discover relationships between the selected tables
        # ------------------------------------------------------
        relationship_context = self._get_relationship_context(
            selected_tables=selected_tables,
            database_schema=semantic_schema,
        )

        system_prompt = self._build_system_prompt()

        user_prompt = self._build_user_prompt(
            question=question,
            semantic_context=semantic_context,
            conversation_context=conversation_context,
            relationship_context=relationship_context,
        )

        raw_response = self.client.generate_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )

        plan = self._parse_response(
            raw_response
        )

        # ------------------------------------------------------
        # Deterministic plan normalization / repair
        # ------------------------------------------------------

        plan = self._normalize_plan(
            plan=plan,
            question=question,
            semantic_schema=semantic_schema,
            conversation_context=conversation_context,
        )

        # Debug after normalization so the actual plan being
        # passed to the validator/executor is visible.
        print("\n========== ANALYZER DEBUG ==========")
        print("QUESTION:", question)
        print("RAW RESPONSE:", raw_response)
        print("NORMALIZED PLAN:", plan)

        print("JOINS:")
        for join in plan.joins:
            print(
                f"  {join.left_schema}.{join.left_table}"
                f".{join.left_column}"
                f" -> "
                f"{join.right_schema}.{join.right_table}"
                f".{join.right_column}"
                f" [{join.join_type}]"
            )

        print("====================================\n")

        return plan

    # ==========================================================
    # SMALL GENERIC LLM PROMPT
    # ==========================================================

    @staticmethod
    def _build_system_prompt() -> str:
        return """
    Convert the user's question into a QueryPlan for the supplied SQL Server database schema.

    Use only tables and columns present in the supplied database schema.
    Do not answer the question.
    Do not calculate values.
    Do not invent tables or columns.
    Return only valid JSON.

    Interpret the question semantically.

    Preserve every explicit constraint in the user's question. In particular,
    prepositions such as "in", "of", "for", "within", and "among" can express
    a filter or scope constraint when they identify a database value/category.
    Do not drop such a constraint merely because the same question also asks
    for an aggregate such as an average, sum, minimum, maximum, or count.
    For example, a request for an average "in" a named category must include
    that category as a filter when the database schema supports it.

    For follow-up questions, resolve pronouns and references such as 'he',
    'she', 'they', 'him', 'her', 'them', 'this person', 'that person',
    'that record', or 'that entity' to the most recent prior result that
    identifies the specific entity or record being discussed.
    Set input_result_reference ONLY when the user's question explicitly refers to a prior result,
    such as using demonstratives ('those', 'these', 'them', 'the same'), result references ('that result',
    'the above', 'from above'), slicing ('now show only the top 5', 'just the first 3'), or comparative
    follow-ups ('what about the lowest one', 'sort those'). Do NOT set input_result_reference for standalone
    questions or queries that ask about entities directly (e.g. "Show 5th event" or "Which event has the highest capacity?").

    Use:
    - lookup for requested values or records
    - count for number or frequency of records/entities
    - aggregation for sum, average, min, max, median, or grouped aggregates
    - derived_aggregation for aggregating over an inner grouped result (e.g. "average number of registrations per event", "median count of items per order", "maximum registrations per event")
    - filter for records matching conditions
    - ranking for ordering individual records
    - comparison for comparing values or groups
    - existence for whether matching records exist
    - percentage for a percentage/share of records
    - row_count for the total number of data rows/records in the relevant table
    - column_count for the total number of columns in the relevant table
    - column_names when the user requests the names/list of columns in the relevant table
    - unsupported when the required information is not represented in the database schema

    For derived aggregate questions (calculating a summary over per-entity counts or sums, such as "average number of X per Y", "median count of X per Y"):
    - intent = derived_aggregation
    - aggregation = outer operation (average, median, max, min, sum)
    - inner_aggregation = inner operation (count, sum, etc.)
    - group_by = inner grouping dimension (e.g. entity/parent ID)
    - target_columns = column used by inner aggregation (or entity row column for count)

    For grouped aggregate questions:
    - target_columns = measure or entity being aggregated
    - group_by = grouping dimension
    - aggregation = requested operation
    - sort_column = source measure when sorting by that measure
    - sort_direction = desc for highest/largest/most and asc for lowest/smallest/least
    - limit = 1 when one winner is requested
    - include_ties = true when all records sharing the ranking boundary are requested
    - include_ties = false when only the requested number of ranked records is wanted
    - require_all_filter_values = true when every requested value of the same filter dimension must be present within each grouped entity (for example, "both A and B")
    - require_all_filter_values = true when the question requires a group/entity to contain every requested value of the same filter dimension (for example, "both A and B")

    For date/time grouped questions, preserve the requested temporal granularity separately from the physical date/time column.

    Supported temporal granularities are:
    - day
    - week
    - month
    - quarter
    - year

    Semantic wording should map as follows:
    - "by day", "each day", "daily" -> day
    - "by week", "each week", "weekly" -> week
    - "by month", "each month", "in each month", "monthly" -> month
    - "by quarter", "each quarter", "quarterly" -> quarter
    - "by year", "each year", "yearly", "annually" -> year

    For a temporal grouping:
    - group_by must contain the actual date/time column name
    - group_by_granularity must contain the requested granularity
    - group_by_refs must identify the actual date/time column when needed

    Do not put SQL expressions such as MONTH(column), YEAR(column), DATEPART(...),
    or DATE_TRUNC(...) into group_by.

    For grouped count/frequency questions:
    - target_columns = an appropriate record/entity column when available
    - group_by = grouping dimension
    - aggregation = count
    - sort_column = "count" when selecting the group with the highest/lowest count
    - sort_direction = desc for highest/most/frequent and asc for lowest/least/fewest
    - limit = 1 when one group is requested

    When multiple tables are relevant, use the supplied table and relationship
    metadata to determine which tables and columns are appropriate.

    Do not invent relationships that are not supported by the supplied
    database context.

    If the question requires data from multiple related tables, return
    the required JOINs in the "joins" array.

    Each JOIN must use only a relationship supplied in the database context.

    For multi-table queries, column references may be ambiguous when
    the same column name exists in more than one selected table.

    When a target column belongs to a specific table, also return it
    in "target_column_refs".

    When a GROUP BY column belongs to a specific table, also return it
    in "group_by_refs".

    Qualified column reference format:

    {
        "schema": "...",
        "table": "...",
        "column": "..."
    }

    For single-table or unambiguous queries, these arrays may be empty.

    The qualified references must use only tables and columns present
    in the supplied database schema.

    JOIN format:

    {
        "left_schema": "...",
        "left_table": "...",
        "left_column": "...",
        "right_schema": "...",
        "right_table": "...",
        "right_column": "...",
        "join_type": "inner"
    }

    Allowed join_type values:

    - inner
    - left
    - right

    When the question asks to identify an entity (e.g. "Which entity has the highest/lowest number of related records?") and a related entity table contains descriptive attributes (such as a name, title, description, or code) while the detail table contains the relationship or count:
    - Include the generic JOIN between the detail table and entity table using an available relationship.
    - Put both the identifying column and the descriptive attribute into group_by (and group_by_refs) so the entity descriptor is projected in the result.
    - Set sort_column = "count", sort_direction = "desc" (or "asc"), and limit appropriately.

    If the question does not require related descriptive attributes and can be fully and accurately answered using one table only, return:

    "joins": []

    Return this JSON structure:

    {
        "intent": "...",
        "target_columns": [],
        "filters": [],
        "group_by": [],
        "group_by_granularity": null,
        "aggregation": null,
        "inner_aggregation": null,
        "sort_column": null,
        "sort_direction": null,
        "limit": null,
        "include_ties": false,
        "require_all_filter_values": false,
        "input_result_reference": null,
        "explanation": "",
        "confidence": 0.0,
        "joins": [],
        "target_column_refs": [],
        "group_by_refs": []
    }
    """.strip()

    def _build_user_prompt(
        self,
        question: str,
        semantic_context: str,
        relationship_context: list[dict[str, Any]],
        conversation_context: dict[str, Any] | None = None,
    ) -> str:

        return f"""
    DATABASE SCHEMA:
    {semantic_context}

    AVAILABLE RELATIONSHIPS:
    {json.dumps(
        relationship_context,
        ensure_ascii=False,
        default=str,
        indent=2,
    )}

    CONVERSATION CONTEXT:
    {json.dumps(
        conversation_context or {},
        ensure_ascii=False,
        default=str,
    )}

    QUESTION:
    {question}

    Return only the QueryPlan JSON.
    """.strip()

    # ==========================================================
    # RELATIONSHIP CONTEXT
    # ==========================================================

    @staticmethod
    def _get_relationship_context(
        selected_tables: list[TableInfo],
        database_schema: DatabaseSchema,
    ) -> list[dict[str, Any]]:
        """
        Discover structural relationships between the selected tables.

        This is completely generic. No business/domain-specific
        table names or column names are hardcoded here.
        """

        if len(selected_tables) < 2:
            return []

        selected_table_keys = [
            (
                table.schema_name,
                table.table_name,
            )
            for table in selected_tables
        ]

        discovery_service = RelationshipDiscoveryService(
            database_schema
        )

        relationships = discovery_service.discover(
            selected_table_keys
        )

        relationship_context: list[dict[str, Any]] = []

        for relationship in relationships:

            relationship_context.append(
                {
                    "relationship_type": (
                        relationship.relationship_type
                    ),
                    "status": relationship.status,
                    "left_schema": relationship.left_schema,
                    "left_table": relationship.left_table,
                    "left_column": relationship.left_column,
                    "right_schema": relationship.right_schema,
                    "right_table": relationship.right_table,
                    "right_column": relationship.right_column,
                    "reason": relationship.reason,
                }
            )

        return relationship_context


    @classmethod
    def _normalize_operator(
        cls,
        value: Any,
    ) -> str | None:

        if value is None:
            return None

        normalized = (
            str(value)
            .strip()
            .casefold()
        )

        # Normalize SQL-style LIKE patterns into the canonical,
        # database-independent operators used by QueryPlan.
        #
        # Examples:
        #   LIKE "C%"   -> starts_with, "C"
        #   LIKE "%C"   -> ends_with, "C"
        #   LIKE "%C%"  -> contains, "C"
        #
        # The parser stores only the operator here, so LIKE-pattern
        # value conversion is handled immediately after parsing.
        return cls.OPERATOR_ALIASES.get(
            normalized,
            normalized,
        )

    @staticmethod
    def _normalize_like_filter(
        operator: str | None,
        value: Any,
    ) -> tuple[str | None, Any]:
        """
        Convert SQL-style LIKE patterns into canonical QueryPlan
        operators without exposing SQL operators to the rest of the
        pipeline.
        """
        if operator is None:
            return None, value

        normalized_operator = str(operator).strip().casefold()

        if normalized_operator != "like":
            return normalized_operator, value

        if not isinstance(value, str):
            return None, value

        pattern = value

        if pattern.startswith("%") and pattern.endswith("%") and len(pattern) >= 2:
            return "contains", pattern[1:-1]

        if pattern.endswith("%"):
            return "starts_with", pattern[:-1]

        if pattern.startswith("%"):
            return "ends_with", pattern[1:]

        # LIKE without a wildcard has equality semantics.
        return "equals", pattern

    @classmethod
    def _is_aggregate_detail_request(
        cls,
        question: str,
    ) -> bool:
        """
        Detect whether a question is asking for underlying detail rows/records
        of a previous query or result.
        Generic and schema-independent.
        """
        text = (question or "").strip().casefold()
        if not text:
            return False

        cleaned = re.sub(r"[.?!]+$", "", text).strip()

        exact_phrases = {
            "show details", "show the details", "show me details", "show me the details",
            "show details of this", "show details of that", "show details of these", "show details of those",
            "show details of it", "show details of them",
            "show details of the result", "show details of this result", "show details of that result",
            "show details of the above", "show details of the above result",
            "details of this", "details of that", "details of these", "details of those",
            "details of it", "details of them",
            "details of the above", "details of the result", "details of this result",
            "show records", "show the records", "show me records", "show me the records",
            "show those records", "show these records", "show all records", "show the matching records",
            "show rows", "show the rows", "show me rows", "show me the rows",
            "show those rows", "show these rows", "show all rows", "show the matching rows",
            "show underlying records", "show the underlying records", "show underlying data", "show the underlying data",
            "show underlying rows", "show the underlying rows",
            "list details", "list the details", "list records", "list the records",
            "list those records", "list these records", "list the rows", "list rows",
            "give me details", "give me the details", "give details", "give the details",
            "what are the details", "what are these records", "what are those records", "what are the records",
            "what are these rows", "what are those rows", "what are the rows",
            "view details", "view the details", "view records", "view the records",
            "details please", "details",
        }
        if cleaned in exact_phrases:
            return True

        if re.search(
            r"^(?:(?:can\s+you\s+|please\s+)?(?:show|list|display|give|get|view|see)\s+(?:me\s+)?)?"
            r"(?:the\s+|those\s+|these\s+|all\s+|only\s+)?"
            r"(?:(?:top|first|last)\s+(?:\d+\s+)?|\d+\s+)?"
            r"(?:underlying\s+|matching\s+)?"
            r"(?:details|records|rows|data)"
            r"(?:\s+(?:of|for|about|behind)\s+(?:this|that|these|those|it|them|the\s+above|the\s+result(?:s)?|this\s+result))?$",
            cleaned,
        ):
            return True

        if re.search(
            r"^(?:the\s+)?details\s+(?:of|for|about|behind)\s+(?:this|that|these|those|it|them|the\s+above|the\s+result(?:s)?|this\s+result)$",
            cleaned,
        ):
            return True

        if re.search(
            r"^what\s+are\s+(?:the\s+|these\s+|those\s+)?(?:underlying\s+|matching\s+)?(?:details|records|rows)(?:\s+(?:of|for|behind)\s+(?:this|that|these|those|it|the\s+above))?$",
            cleaned,
        ):
            return True

        return False

    @classmethod
    def _is_explicit_result_reference(
        cls,
        question: str,
    ) -> bool:
        """
        Detect whether the user's question explicitly references a previous result.

        Evaluates to True ONLY for explicit continuation or referencing patterns:
        - Demonstratives: those, these, them, the same
        - Result references: that result, the result, previous result(s), prior result(s),
          the above, from above, out of the results
        - Result slicing/filtering: now show only the top N, only the top N, just the first N,
          now show only, show only the top/bottom
        - Comparative follow-ups: what about the lowest one, which one, what about the rest
        - Operations on prior results: sort those, order those, filter those, sort them
        - Prepositions: among them, of them, from those, out of those

        Standalone questions or queries specifying entity nouns directly (e.g. "Show 5th event",
        "Which event has highest capacity?") evaluate to False.
        """
        text = (question or "").strip().casefold()
        if not text:
            return False

        if cls._is_aggregate_detail_request(question):
            return True

        # Explicit result references
        if re.search(r"\b(?:that|this|the|previous|prior)\s+result(?:s)?\b", text):
            return True
        if re.search(r"\b(?:the\s+above|from\s+above|above\s+mentioned)\b", text):
            return True
        if re.search(r"\b(?:from|in|of)\s+(?:the\s+)?(?:results?|output)\b", text):
            return True
        if re.search(r"\b(?:details|records|rows)\s+(?:of|for|behind)\s+(?:this|that|these|those|it|them)\b", text):
            return True
        if re.search(r"\bshow\s+(?:the\s+|those\s+|these\s+)?(?:details|records|rows)\b", text):
            return True

        # Prepositions pointing to previous set
        if re.search(r"\b(?:among|out\s+of|from|of)\s+(?:them|these|those|the\s+above)\b", text):
            return True

        # Demonstratives: those, these, them, the same
        if re.search(r"\b(?:those|these|them|the\s+same)\b", text):
            return True

        # Operations on previous items
        if re.search(r"\b(?:sort|filter|order|group|limit|show)\s+(?:those|these|them)\b", text):
            return True

        # Continuation operations
        if text.startswith((
            "sort by ", "order by ", "filter by ", "filter where ",
            "group by ", "limit to ",
        )):
            return True

        # Slicing / filtering of prior result
        if re.search(r"^(?:now\s+)?(?:show\s+)?(?:only|just)\s+(?:the\s+)?(?:top|bottom|first|last|\d+)\b", text):
            return True
        if re.search(r"\bonly\s+(?:the\s+)?(?:top|bottom|first|last)\b", text):
            return True
        if text.startswith("now show only "):
            return True

        # Comparative references / follow-ups
        if re.search(r"\bwhat\s+about\s+(?:the\s+)?(?:lowest|highest|rest|other|others|next|one)\b", text):
            return True
        if re.search(r"\bhow\s+about\s+(?:the\s+)?(?:lowest|highest|rest|other|others|next|one)\b", text):
            return True
        if re.search(r"\bwhich\s+one\b", text):
            return True

        return False

    @classmethod
    def _extract_plan_field(cls, plan_obj: Any, field_name: str, default: Any = None) -> Any:
        if isinstance(plan_obj, dict):
            return plan_obj.get(field_name, default)
        return getattr(plan_obj, field_name, default)

    @classmethod
    def _reconstruct_aggregate_detail_plan(
        cls,
        plan: QueryPlan,
        recent_entry: dict[str, Any],
        recent_plan_obj: Any,
        semantic_schema: Any,
        question_lower: str,
    ) -> QueryPlan:
        plan.intent = "lookup"
        plan.aggregation = None
        plan.inner_aggregation = None
        plan.group_by = []
        plan.group_by_granularity = None
        plan.group_by_refs = []
        plan.having_filters = []

        # 1. Recover filters
        prior_filters: list[QueryFilter] = []
        raw_filters = cls._extract_plan_field(recent_plan_obj, "filters") or []
        for f in raw_filters:
            col = f.get("column") if isinstance(f, dict) else getattr(f, "column", None)
            op = f.get("operator", "equals") if isinstance(f, dict) else getattr(f, "operator", "equals")
            val = f.get("value") if isinstance(f, dict) else getattr(f, "value", None)
            if col:
                prior_filters.append(QueryFilter(column=col, operator=op, value=val))
        plan.filters = prior_filters
        plan.require_all_filter_values = cls._extract_plan_field(recent_plan_obj, "require_all_filter_values", False)

        # 2. Recover joins
        prior_joins: list[QueryJoin] = []
        raw_joins = cls._extract_plan_field(recent_plan_obj, "joins") or []
        for j in raw_joins:
            left_s = j.get("left_schema", "") if isinstance(j, dict) else getattr(j, "left_schema", "")
            left_t = j.get("left_table", "") if isinstance(j, dict) else getattr(j, "left_table", "")
            left_c = j.get("left_column", "") if isinstance(j, dict) else getattr(j, "left_column", "")
            right_s = j.get("right_schema", "") if isinstance(j, dict) else getattr(j, "right_schema", "")
            right_t = j.get("right_table", "") if isinstance(j, dict) else getattr(j, "right_table", "")
            right_c = j.get("right_column", "") if isinstance(j, dict) else getattr(j, "right_column", "")
            j_type = j.get("join_type", "inner") if isinstance(j, dict) else getattr(j, "join_type", "inner")
            if left_t and right_t:
                prior_joins.append(
                    QueryJoin(
                        left_schema=left_s,
                        left_table=left_t,
                        left_column=left_c,
                        right_schema=right_s,
                        right_table=right_t,
                        right_column=right_c,
                        join_type=j_type,
                    )
                )
        plan.joins = prior_joins
        if plan.joins:
            plan.distinct = True
        else:
            plan.distinct = False

        # 3. Recover / project target columns
        schema_tables = getattr(semantic_schema, "tables", []) or []
        target_table = None

        if plan.joins:
            raw_refs = cls._extract_plan_field(recent_plan_obj, "target_column_refs") or []
            if raw_refs:
                first_ref = raw_refs[0]
                ref_tbl = (first_ref.get("table", "") if isinstance(first_ref, dict) else getattr(first_ref, "table", "") or "").lower()
                ref_sch = (first_ref.get("schema", "") if isinstance(first_ref, dict) else getattr(first_ref, "schema", "") or "").lower()
                for t in schema_tables:
                    if t.table_name.lower() == ref_tbl:
                        if not ref_sch or t.schema_name.lower() == ref_sch:
                            target_table = t
                            break

            if target_table is None and schema_tables:
                first_join = plan.joins[0]
                for t in schema_tables:
                    if t.table_name.lower() == first_join.left_table.lower():
                        if not first_join.left_schema or t.schema_name.lower() == first_join.left_schema.lower():
                            target_table = t
                            break

            if target_table and getattr(target_table, "columns", None):
                plan.target_columns = [c.name for c in target_table.columns]
                plan.target_column_refs = [
                    QueryColumn(
                        column=c.name,
                        schema=target_table.schema_name,
                        table=target_table.table_name,
                    )
                    for c in target_table.columns
                ]
            else:
                plan.target_columns = []
                plan.target_column_refs = []
        else:
            if schema_tables:
                raw_recent_tables = recent_entry.get("tables") or []
                if raw_recent_tables:
                    first_entry_tbl = raw_recent_tables[0]
                    et_name = (first_entry_tbl.get("table", "") if isinstance(first_entry_tbl, dict) else getattr(first_entry_tbl, "table_name", "") or "").lower()
                    et_sch = (first_entry_tbl.get("schema", "") if isinstance(first_entry_tbl, dict) else getattr(first_entry_tbl, "schema_name", "") or "").lower()
                    for t in schema_tables:
                        if t.table_name.lower() == et_name:
                            if not et_sch or t.schema_name.lower() == et_sch:
                                target_table = t
                                break
                if target_table is None:
                    target_table = schema_tables[0]

                plan.target_columns = [c.name for c in target_table.columns]
                plan.target_column_refs = [
                    QueryColumn(
                        column=c.name,
                        schema=target_table.schema_name,
                        table=target_table.table_name,
                    )
                    for c in target_table.columns
                ]
            else:
                plan.target_columns = []
                plan.target_column_refs = []

        # 4. Limit if explicitly requested
        retrieval_limit = cls._detect_row_retrieval_limit(question_lower)
        if retrieval_limit is not None:
            plan.limit = retrieval_limit

        plan.explanation = "Retrieved details for the previous aggregate query."
        return plan

    # ==========================================================
    # PLAN NORMALIZATION
    # ==========================================================

    @classmethod
    def _normalize_plan(
        cls,
        plan: QueryPlan,
        question: str,
        semantic_schema: Any,
        conversation_context: dict[str, Any] | None = None,
    ) -> QueryPlan:

        question_lower = question.casefold()

        # ------------------------------------------------------
        # Unsupported query preservation
        # ------------------------------------------------------
        # If the LLM determined the request is unsupported (e.g. the required
        # entity or information is not represented in the schema), preserve that
        # decision. An unsupported request must NEVER be silently converted into
        # a successful metadata query against an arbitrary or unrelated table.
        if plan.intent == "unsupported" and not plan.input_result_reference:
            history = conversation_context.get("history") if conversation_context else []
            is_follow_up_phrase = bool(
                re.search(r"\b(those|these|them|that|their|they|this)\b", question_lower)
                or cls._is_aggregate_detail_request(question_lower)
                or question_lower.startswith((
                    "sort ", "order ", "filter ", "show only ", "only ",
                    "show first ", "show the first ", "first ", "top ", "limit to ",
                    "show details", "details of",
                ))
            )
            if not (history and is_follow_up_phrase):
                return plan

        # ------------------------------------------------------
        # Database metadata requests
        # ------------------------------------------------------
        # These are domain-independent structural questions. They
        # must not be converted into data aggregations because the
        # answer comes directly from the database schema structure.
        metadata_intent = cls._detect_metadata_intent(
            question_lower
        )

        if metadata_intent is not None:
            plan.intent = metadata_intent
            plan.target_columns = []
            plan.filters = []
            plan.group_by = []
            plan.group_by_granularity = None
            plan.aggregation = None
            plan.sort_column = None
            plan.sort_direction = None
            plan.limit = None
            return plan

        columns = cls._get_schema_columns(
            semantic_schema
        )

        schema_names = set(columns)

        # Resolve input_result_reference from conversation history if needed
        history = conversation_context.get("history") if conversation_context else []
        recent_entry = history[-1] if history else None
        recent_ref = recent_entry.get("reference_id") if recent_entry else None

        known_refs = {e.get("reference_id") for e in history if e.get("reference_id")}

        if recent_ref and cls._is_explicit_result_reference(question_lower):
            current_ref = getattr(plan, "input_result_reference", None)
            if current_ref and current_ref in known_refs:
                plan.input_result_reference = current_ref
            else:
                plan.input_result_reference = recent_ref
        else:
            plan.input_result_reference = None

        # ------------------------------------------------------
        # Aggregate -> Detail follow-up reconstruction
        # ------------------------------------------------------
        if recent_entry and cls._is_aggregate_detail_request(question_lower):
            recent_plan_obj = recent_entry.get("plan") or (recent_entry.get("query_context") or {}).get("plan")
            is_prior_aggregate = False
            if recent_plan_obj is not None:
                prior_intent = cls._extract_plan_field(recent_plan_obj, "intent")
                prior_agg = cls._extract_plan_field(recent_plan_obj, "aggregation")
                if prior_intent in ("count", "row_count", "aggregation", "derived_aggregation") or prior_agg is not None:
                    is_prior_aggregate = True
            elif (recent_entry.get("query_context") or {}).get("is_scalar"):
                is_prior_aggregate = True
            elif isinstance(recent_entry.get("data"), (int, float)):
                is_prior_aggregate = True
            elif (
                isinstance(recent_entry.get("data"), list)
                and len(recent_entry.get("data")) == 1
                and isinstance(recent_entry["data"][0], dict)
                and any(k in ("count", "row_count", "aggregation_value") for k in recent_entry["data"][0].keys())
            ):
                is_prior_aggregate = True

            if is_prior_aggregate:
                plan = cls._reconstruct_aggregate_detail_plan(
                    plan=plan,
                    recent_entry=recent_entry,
                    recent_plan_obj=recent_plan_obj,
                    semantic_schema=semantic_schema,
                    question_lower=question_lower,
                )

        # A follow-up may legitimately reference columns created by the
        # previous deterministic query result. These are not database
        # schema columns, so obtain them only from the actual referenced
        # result represented in the conversation context.
        referenced_result_columns = cls._get_referenced_result_columns(
            conversation_context,
            plan.input_result_reference,
        )
        available_names = schema_names | referenced_result_columns

        # ------------------------------------------------------
        # Generic bounded row retrieval repair
        # ------------------------------------------------------
        # DeepSeek may return "unsupported" for natural row-list wording
        # such as "display 5 records" or may return lookup with no target
        # columns for "show first 10 rows". When the request contains only
        # a retrieval verb plus an explicit record count, represent it as a
        # complete-record lookup using the supplied database schema.
        row_retrieval_limit = cls._detect_row_retrieval_limit(
            question_lower
        )
        if (
            row_retrieval_limit is not None
            and not plan.filters
            and not plan.group_by
            and plan.aggregation is None
            and plan.sort_column is None
            and plan.input_result_reference is None
            and not cls._detect_ranking_direction(question_lower)
            and cls._detect_aggregate_operation(question_lower) is None
        ):
            plan.intent = "lookup"
            plan.target_columns = list(columns.keys())
            plan.filters = []
            plan.group_by = []
            plan.aggregation = None
            plan.sort_column = None
            plan.sort_direction = None
            plan.limit = row_retrieval_limit

        # ------------------------------------------------------
        # 1. Normalize intent from the structure of the plan
        # ------------------------------------------------------

        raw_intent = (
            plan.intent or ""
        ).strip().casefold()

        # A follow-up may be semantically clear from its reference even when
        # the LLM returns a free-form intent and no target columns. In that
        # case, use the exact columns exposed by the referenced result. This
        # is deliberately data-driven: no derived column names are assumed.
        if (
            plan.input_result_reference
            and referenced_result_columns
            and (
                raw_intent == "unsupported"
                or raw_intent not in cls.VALID_INTENTS
            )
            and not plan.target_columns
            and not plan.group_by
            and not plan.filters
            and plan.aggregation is None
            and plan.sort_column is None
        ):
            plan.intent = "lookup"
            plan.target_columns = sorted(referenced_result_columns)
            raw_intent = "lookup"

        if raw_intent not in cls.VALID_INTENTS:

            if (
                plan.group_by
                and plan.target_columns
                and plan.aggregation
            ):
                plan.intent = "aggregation"

            elif plan.sort_column:
                plan.intent = "ranking"

            elif plan.filters and plan.target_columns:
                plan.intent = "filter"

            elif plan.filters:
                plan.intent = "filter"

            elif plan.aggregation:
                plan.intent = "aggregation"

            elif plan.target_columns:
                plan.intent = "lookup"

            else:
                plan.intent = "unsupported"
                plan.explanation = (
                    "The question could not be mapped to a supported query type."
                )
                return plan

        elif raw_intent == "unsupported":
            # If the referenced-result recovery above did not apply, keep the
            # plan unsupported rather than guessing a database operation.
            return plan

        else:
            plan.intent = raw_intent

        # ------------------------------------------------------
        # 2. Normalize aggregation
        # ------------------------------------------------------

        plan.aggregation = cls._normalize_aggregation(
            plan.aggregation
        )

        # ------------------------------------------------------
        # 2.1. Normalize row-count plans
        # ------------------------------------------------------
        # A row count counts records in the selected table. It does not
        # require a source-column reference or an aggregation target.
        # This prevents an LLM from attaching an unnecessary target
        # column to a natural-language row-count question.
        if plan.intent == "row_count":
            plan.target_columns = []
            plan.target_column_refs = []
            plan.group_by = []
            plan.group_by_refs = []
            plan.group_by_granularity = None
            plan.aggregation = None
            plan.sort_column = None
            plan.sort_direction = None
            plan.limit = None

        # ------------------------------------------------------
        # 2.2. Normalize derived aggregation
        # ------------------------------------------------------
        derived_agg_detected = cls._detect_derived_aggregation_request(
            question_lower
        )
        if (
            plan.intent == "derived_aggregation"
            or plan.inner_aggregation is not None
            or derived_agg_detected is not None
        ):
            plan.intent = "derived_aggregation"
            if derived_agg_detected is not None:
                plan.aggregation = derived_agg_detected[0]
                plan.inner_aggregation = derived_agg_detected[1]
            else:
                plan.aggregation = (
                    cls._normalize_aggregation(plan.aggregation)
                    or "average"
                )
                plan.inner_aggregation = (
                    cls._normalize_aggregation(plan.inner_aggregation)
                    or "count"
                )

            plan.sort_column = None
            plan.sort_direction = None
            plan.limit = None

        # ------------------------------------------------------
        # 2.5. Normalize temporal GROUP BY semantics
        # ------------------------------------------------------
        # Preserve the physical date/time column separately from the
        # requested temporal bucket. This prevents expressions such as
        # MONTH(column) from being discarded by schema-name validation.
        # The implementation is completely schema-independent.
        plan = cls._normalize_temporal_grouping(
            plan=plan,
            question=question_lower,
            available_names=available_names,
        )

        # ------------------------------------------------------
        # 3. Normalize sort direction
        # ------------------------------------------------------

        plan.sort_direction = cls._normalize_sort_direction(
            plan.sort_direction
        )

        # ------------------------------------------------------
        # 4. Normalize limit
        # ------------------------------------------------------

        plan.limit = cls._normalize_limit(
            plan.limit
        )

        # ------------------------------------------------------
        # 5. Generic question semantics
        # ------------------------------------------------------

        aggregate_operation = (
            cls._detect_aggregate_operation(
                question_lower
            )
        )

        ranking_direction = (
            cls._detect_ranking_direction(
                question_lower
            )
        )

        include_ties_requested = (
            plan.include_ties
            or cls._detect_include_ties_request(
                question_lower,
                ranking_direction,
            )
        )

        asks_for_single_winner = (
            cls._asks_for_single_winner(
                question_lower
            )
        )

        if include_ties_requested:
            plan.include_ties = True
            plan.limit = None

        # ------------------------------------------------------
        # 6. Normalize scalar count semantics
        # ------------------------------------------------------
        # A scalar count asks for the number of matching records/entities.
        # It must remain a dedicated ``count`` intent and must not be
        # represented as a generic aggregation over a source column. The
        # SQL executor implements count as COUNT(*), so the target column is
        # optional and must never change the meaning of the count.
        #
        # Grouped count questions are deliberately excluded here. They are
        # normalized below as aggregation + group_by so the grouped executor
        # can produce one count per group.
        count_request = cls._detect_count_request(
            question_lower
        )

        if (
            count_request
            and not plan.group_by
            and not plan.input_result_reference
        ):
            plan.intent = "count"
            plan.aggregation = None
            plan.group_by = []
            plan.group_by_refs = []
            plan.group_by_granularity = None
            plan.sort_column = None
            plan.sort_direction = None
            plan.limit = None

        # ------------------------------------------------------
        # 6.1. Detect frequency/count language
        # ------------------------------------------------------

        frequency_request = (
            cls._detect_frequency_request(
                question_lower
            )
        )

        # If the question asks which group/entity is used,
        # appears, occurs, or happens most/least frequently,
        # a grouped count is the appropriate generic structure.
        if (
            frequency_request
            and plan.group_by
        ):
            plan.intent = "aggregation"
            plan.aggregation = "count"

            if not plan.target_columns:
                plan.target_columns = cls._choose_count_target(
                    columns
                )

            if (
                ranking_direction is not None
            ):
                plan.sort_direction = ranking_direction

            elif plan.sort_direction is None:
                plan.sort_direction = "desc"

            # IMPORTANT:
            # "count" is a virtual result column produced by
            # grouped count aggregation. Do not replace it with
            # a source database column.
            if plan.sort_column is None:
                plan.sort_column = "count"

            if asks_for_single_winner and plan.limit is None:
                plan.limit = 1

        # ------------------------------------------------------
        # 7. Repair grouped aggregate plans
        # ------------------------------------------------------

        if (
            plan.intent != "derived_aggregation"
            and plan.group_by
            and plan.target_columns
            and plan.aggregation
        ):
            plan.intent = "aggregation"

            if (
                aggregate_operation is not None
                and plan.aggregation != "count"
            ):
                plan.aggregation = aggregate_operation

            if ranking_direction is not None:
                plan.sort_direction = ranking_direction

            if plan.sort_column is None:
                if plan.aggregation == "count":
                    plan.sort_column = "count"
                else:
                    plan.sort_column = plan.target_columns[0]

            if (
                asks_for_single_winner
                and plan.limit is None
                and not cls._asks_for_multiple_values(
                    question_lower
                )
            ):
                plan.limit = 1


        # ------------------------------------------------------
        # 8. Repair aggregate ranking classified as ranking
        # ------------------------------------------------------

        if (
            plan.intent == "ranking"
            and plan.group_by
            and plan.target_columns
            and plan.aggregation
        ):
            plan.intent = "aggregation"

            if (
                aggregate_operation is not None
                and plan.aggregation != "count"
            ):
                plan.aggregation = aggregate_operation

            if ranking_direction is not None:
                plan.sort_direction = ranking_direction

            if plan.sort_column is None:
                if plan.aggregation == "count":
                    plan.sort_column = "count"
                else:
                    plan.sort_column = plan.target_columns[0]

            if (
                asks_for_single_winner
                and plan.limit is None
                and not cls._asks_for_multiple_values(
                    question_lower
                )
            ):
                plan.limit = 1


        # ------------------------------------------------------
        # 9. Repair grouped aggregate ranking when the LLM
        #    omitted aggregation but supplied grouping/measure.
        # ------------------------------------------------------

        if (
            plan.intent != "derived_aggregation"
            and plan.group_by
            and plan.target_columns
            and plan.intent in {
                "aggregation",
                "ranking",
                "comparison",
            }
        ):

            if (
                plan.aggregation is None
                and aggregate_operation is not None
            ):
                plan.intent = "aggregation"
                plan.aggregation = aggregate_operation

            if (
                plan.aggregation is not None
                and ranking_direction is not None
            ):
                plan.intent = "aggregation"
                plan.sort_direction = ranking_direction

            if (
                plan.aggregation is not None
                and plan.sort_column is None
            ):
                if plan.aggregation == "count":
                    plan.sort_column = "count"
                else:
                    plan.sort_column = plan.target_columns[0]

            if (
                plan.aggregation is not None
                and asks_for_single_winner
                and not cls._asks_for_multiple_values(
                    question_lower
                )
            ):
                plan.limit = 1

        # ------------------------------------------------------
        # 10. Infer count for explicit frequency questions
        # ------------------------------------------------------

        if (
            frequency_request
            and plan.group_by
            and plan.aggregation is None
        ):
            plan.intent = "aggregation"
            plan.aggregation = "count"

            if not plan.target_columns:
                plan.target_columns = cls._choose_count_target(
                    columns
                )

            plan.sort_column = "count"

            if ranking_direction is not None:
                plan.sort_direction = ranking_direction
            else:
                plan.sort_direction = "desc"

            if asks_for_single_winner and plan.limit is None:
                plan.limit = 1


        # ------------------------------------------------------
        # 10.5. Normalize comparison follow-ups
        # ------------------------------------------------------
        #
        # A follow-up comparison may refer to a previous grouped
        # result instead of requesting a new aggregation.
        #
        # When the previous result contains the comparison values,
        # treat the request as a ranking over that referenced result.
        # This keeps the execution deterministic and avoids requiring
        # a new aggregation operation.
        #
        # This is schema-independent.
        if (
            plan.intent == "comparison"
            and plan.input_result_reference
            and plan.target_columns
            and plan.sort_column
            and plan.aggregation is None
            and not plan.group_by
        ):
            plan.intent = "ranking"

            if ranking_direction is not None:
                plan.sort_direction = ranking_direction

            if plan.limit is None:
                plan.limit = 1

        # ------------------------------------------------------
        # 10.7. Normalize "all requested values" semantics
        # ------------------------------------------------------
        # A grouped question such as "which entities have both A and B"
        # must not be represented as a simple IN filter. The executor
        # needs to verify that every requested value occurs within the
        # same group/entity.
        if plan.group_by:
            plan.require_all_filter_values = (
                bool(getattr(plan, "require_all_filter_values", False))
                or cls._detect_require_all_filter_values(
                    question_lower,
                    plan.filters,
                )
            )

        # ------------------------------------------------------
        # 11. Normalize referenced columns
        # ------------------------------------------------------

        plan.target_columns = [
            column
            for column in plan.target_columns
            if column in available_names
        ]

        plan.group_by = [
            column
            for column in plan.group_by
            if column in available_names
        ]

        # ------------------------------------------------------
        # 11.5. Repair ranking references
        # ------------------------------------------------------

        if (
            include_ties_requested
            and ranking_direction is not None
        ):
            reference_column = (
                cls._extract_reference_column(
                    plan.filters,
                    schema_names,
                )
            )

            if reference_column:
                plan.intent = "ranking"
                plan.sort_column = reference_column
                plan.sort_direction = ranking_direction
                plan.include_ties = True
                plan.limit = None

                # The previous result is contextual information only.
                # Recompute the ranking from the source table so
                # all records tied at the boundary can be returned.
                plan.filters = []

        # ------------------------------------------------------
        # 12. Normalize filters
        # ------------------------------------------------------
        #
        # Physical-column filters belong in WHERE.
        # Aggregate-result filters belong in HAVING.
        #
        # Example:
        #   count > 50
        #
        # "count" is not a physical database column, so it must
        # not be discarded as an ordinary WHERE filter.
        aggregate_filter_columns = {
            "count",
            "sum",
            "average",
            "min",
            "max",
            "median",
        }

        normalized_filters = []
        normalized_having_filters = list(
            getattr(plan, "having_filters", [])
        )

        for item in plan.filters:
            # Convert year operators into canonical date range filters
            if item.operator in ("year", "year_equals", "year_is", "in_year"):
                try:
                    yr = int(item.value)
                    if yr >= 1:
                        normalized_filters.append(
                            QueryFilter(
                                column=item.column,
                                operator="greater_than_or_equal",
                                value=f"{yr:04d}-01-01",
                            )
                        )
                        normalized_filters.append(
                            QueryFilter(
                                column=item.column,
                                operator="less_than",
                                value=f"{yr + 1:04d}-01-01",
                            )
                        )
                        continue
                except (TypeError, ValueError):
                    pass

            if item.operator in ("equals", "=="):
                try:
                    yr = int(item.value)
                    if 1900 <= yr <= 2100:
                        is_temporal = False
                        col_lower = str(item.column or "").casefold()
                        if any(s in col_lower for s in ("date", "time")):
                            is_temporal = True
                        elif semantic_schema:
                            resolved = semantic_schema.resolve_column(item.column).resolved
                            if resolved and any(t in (resolved.data_type or "").lower() for t in ("date", "time", "timestamp")):
                                is_temporal = True
                        if is_temporal:
                            normalized_filters.append(
                                QueryFilter(
                                    column=item.column,
                                    operator="greater_than_or_equal",
                                    value=f"{yr:04d}-01-01",
                                )
                            )
                            normalized_filters.append(
                                QueryFilter(
                                    column=item.column,
                                    operator="less_than",
                                    value=f"{yr + 1:04d}-01-01",
                                )
                            )
                            continue
                except (TypeError, ValueError):
                    pass

            if item.operator not in cls.VALID_OPERATORS:
                continue

            column_name = str(item.column or "").strip().casefold()

            # DeepSeek may represent an aggregate filter in either
            # of these generic forms:
            #
            #   {"column": "count", "operator": ">", "value": 20}
            #
            # or:
            #
            #   {"aggregation": "count", "operator": ">", "value": 20}
            #
            # The second form has no physical database column.
            # Convert it into the canonical QueryFilter representation
            # used by the executor's HAVING logic.
            aggregate_name = str(
                getattr(item, "aggregation", "") or ""
            ).strip().casefold()

            if column_name in aggregate_filter_columns:
                normalized_having_filters.append(item)

            elif aggregate_name in aggregate_filter_columns:
                normalized_having_filters.append(
                    QueryFilter(
                        column=aggregate_name,
                        operator=item.operator,
                        value=item.value,
                    )
                )

            else:
                _, _, base_col_name = parse_column_reference(item.column)
                if (
                    item.column in schema_names
                    or base_col_name in schema_names
                    or (semantic_schema and semantic_schema.resolve_column(item.column).resolved is not None)
                ):
                    normalized_filters.append(item)

        plan.filters = normalized_filters
        plan.having_filters = normalized_having_filters

        # ------------------------------------------------------
        # 12.5. Repair lookup/filter plans with missing target columns
        # ------------------------------------------------------
        # DeepSeek may correctly identify filter conditions but omit the
        # projection. Use the actual database schema generically.
        if (
            plan.intent in {"lookup", "filter"}
            and plan.filters
            and not plan.target_columns
        ):
            plan.target_columns = list(columns.keys())

        # ------------------------------------------------------
        # 13. Validate / repair sort column
        #
        # IMPORTANT:
        # Grouped aggregations create virtual result columns:
        #   count
        #   sum
        #   average
        #   min
        #   max
        #   median
        #
        # These are NOT source database columns.
        # ------------------------------------------------------

        virtual_sort_columns = {
            "count",
            "sum",
            "average",
            "min",
            "max",
            "median",
        }

        if plan.sort_column:

            sort_column = str(
                plan.sort_column
            ).strip()

            if (
                plan.group_by
                and plan.aggregation
                and sort_column in virtual_sort_columns
            ):
                # Valid grouped aggregate result column.
                plan.sort_column = sort_column

            elif sort_column in schema_names:
                plan.sort_column = sort_column

            elif (
                plan.input_result_reference
                and sort_column in referenced_result_columns
            ):
                # Follow-up may sort by any column actually
                # exposed by the referenced deterministic result.
                plan.sort_column = sort_column

            elif (
                plan.group_by
                and plan.aggregation
                and plan.target_columns
            ):
                # If the LLM returned an invalid sort column for a
                # grouped aggregate, use the source measure.
                plan.sort_column = (
                    "count"
                    if plan.aggregation == "count"
                    else plan.target_columns[0]
                )

            else:
                plan.sort_column = None

        # ------------------------------------------------------
        # 13.1. Follow-up query normalization (Phases 8 & 10)
        # ------------------------------------------------------
        if plan.input_result_reference and referenced_result_columns:
            # 1. Follow-up sorting
            if not plan.sort_column and any(w in question_lower for w in ("sort", "order", "alphabetical", "alphabetically")):
                if not plan.sort_direction:
                    plan.sort_direction = "desc" if cls._detect_ranking_direction(question_lower) == "desc" else "asc"
                chosen_col = None
                for col in referenced_result_columns:
                    col_words = col.lower().replace("_", " ").split()
                    if any(cw in question_lower for cw in col_words):
                        chosen_col = col
                        break
                if not chosen_col:
                    chosen_col = next(iter(referenced_result_columns))
                plan.sort_column = chosen_col
                if plan.intent in ("lookup", "unsupported"):
                    plan.intent = "ranking"

            # 2. Follow-up limiting
            if plan.limit is None:
                detected_limit = cls._detect_row_retrieval_limit(question_lower)
                if detected_limit:
                    plan.limit = detected_limit

            # 3. Follow-up string filter
            if not plan.filters:
                m_starts = re.search(r"\b(?:start(?:s)?\s+with)\s+['\"]?([a-zA-Z0-9_-]+)['\"]?", question_lower)
                if m_starts:
                    target_col = next(iter(referenced_result_columns))
                    for col in referenced_result_columns:
                        col_words = col.lower().replace("_", " ").split()
                        if any(cw in question_lower for cw in col_words):
                            target_col = col
                            break
                    plan.filters = [
                        QueryFilter(
                            column=target_col,
                            operator="starts_with",
                            value=m_starts.group(1),
                        )
                    ]
                    if plan.intent in ("lookup", "unsupported"):
                        plan.intent = "filter"

            # 4. Follow-up aggregate value filter (e.g. more than 100)
            if not plan.filters and not getattr(plan, "having_filters", None):
                agg_cols = {"aggregation_value", "count"} & referenced_result_columns
                if agg_cols:
                    col = "aggregation_value" if "aggregation_value" in agg_cols else "count"
                    m_gt = re.search(r"\b(?:more\s+than|greater\s+than|over|above|\>)\s+(\d+)\b", question_lower)
                    m_lt = re.search(r"\b(?:less\s+than|under|below|\<)\s+(\d+)\b", question_lower)
                    if m_gt:
                        plan.filters = [
                            QueryFilter(
                                column=col,
                                operator="greater_than",
                                value=int(m_gt.group(1)),
                            )
                        ]
                        if plan.intent in ("lookup", "unsupported"):
                            plan.intent = "filter"
                    elif m_lt:
                        plan.filters = [
                            QueryFilter(
                                column=col,
                                operator="less_than",
                                value=int(m_lt.group(1)),
                            )
                        ]
                        if plan.intent in ("lookup", "unsupported"):
                            plan.intent = "filter"

        # ------------------------------------------------------
        # 13.5. Canonicalize grouped aggregation projection
        # ------------------------------------------------------
        #
        # GROUP BY columns are dimensions; target_columns are measures.
        # DeepSeek can return both in target_columns. Remove dimensions
        # from the measure projection before execution.
        #
        # Example:
        #   target_columns = ["site_name", "event_sitecore_id"]
        #   group_by       = ["site_name"]
        # becomes:
        #   target_columns = ["event_sitecore_id"]
        # ------------------------------------------------------

        if plan.group_by and plan.aggregation:

            group_names = {
                str(name).strip().casefold()
                for name in plan.group_by
            }

            plan.target_columns = [
                column
                for column in plan.target_columns
                if str(column).strip().casefold() not in group_names
            ]

            plan.target_column_refs = [
                ref
                for ref in plan.target_column_refs
                if str(ref.column).strip().casefold() not in group_names
            ]

            # QueryPlan currently represents one aggregate expression,
            # so a grouped aggregate must have exactly one measure.
            if not plan.target_columns:
                if plan.target_column_refs:
                    plan.target_columns = [
                        plan.target_column_refs[0].column
                    ]
                elif plan.aggregation == "count":
                    plan.target_columns = cls._choose_count_target(columns)

            if len(plan.target_columns) > 1:
                plan.target_columns = [
                    plan.target_columns[0]
                ]

            if plan.target_columns:
                target_name = plan.target_columns[0]
                matching_refs = [
                    ref
                    for ref in plan.target_column_refs
                    if ref.column.casefold() == target_name.casefold()
                ]

                if matching_refs:
                    plan.target_column_refs = [matching_refs[0]]
                else:
                    plan.target_column_refs = []

        # ------------------------------------------------------
        # 14. Final grouped aggregate repair
        # ------------------------------------------------------
        # Grouped aggregates return every group by default.
        # A single-group limit is applied only when the question
        # actually asks for one winner.
        #
        # Some natural-language breakdown questions contain words
        # such as "which", "what", or "who". Those words alone do
        # NOT mean that one group should be returned.
        if (
            plan.intent == "aggregation"
            and plan.group_by
            and plan.aggregation
        ):

            if plan.aggregation == "count":

                if not plan.sort_column:
                    plan.sort_column = "count"

            elif (
                plan.target_columns
                and not plan.sort_column
            ):
                plan.sort_column = (
                    plan.target_columns[0]
                )

            if (
                ranking_direction is not None
            ):
                plan.sort_direction = ranking_direction

            grouped_breakdown = (
                cls._is_grouped_breakdown_request(
                    question_lower
                )
            )

            if (
                asks_for_single_winner
                and not cls._asks_for_multiple_values(
                    question_lower
                )
                and plan.limit is None
                and not grouped_breakdown
            ):
                plan.limit = 1

            # An explicit comparison needs all candidate groups in the
            # verified result. The answer generator can then identify and
            # communicate the winner from the complete deterministic result.
            # Do not truncate a comparison to one row at the query-plan stage.
            if (
                cls._is_comparison_request(question_lower)
                and plan.group_by
                and plan.aggregation
                and not cls._has_explicit_limit_request(
                    question_lower
                )
            ):
                plan.limit = None

            # If the request is clearly a grouped breakdown,
            # remove an accidental single-group limit introduced
            # earlier by generic "which/what/who" or ranking
            # detection.
            #
            # Explicit numeric limits such as "top 5" must always
            # be preserved.
            if (
                grouped_breakdown
                and not cls._has_explicit_limit_request(
                    question_lower
                )
            ):
                plan.limit = None

        return plan

    # ==========================================================
    # GENERIC QUESTION PATTERN DETECTION
    # ==========================================================

    @staticmethod
    def _normalize_temporal_grouping(
        plan: QueryPlan,
        question: str,
        available_names: set[str],
    ) -> QueryPlan:
        """Normalize date/time grouping without knowing domain columns.

        The LLM may return a SQL-like grouping expression such as
        ``MONTH(date_column)`` even though the QueryPlan contract stores
        physical column names. Convert that representation into the
        physical column plus ``group_by_granularity``.

        If the LLM already returned the physical column, infer the
        requested granularity from the user's wording. Only actual
        schema/result column names are accepted.
        """

        granularity = plan.group_by_granularity
        if granularity is not None:
            granularity = str(granularity).strip().casefold()
            if granularity not in {
                "day",
                "week",
                "month",
                "quarter",
                "year",
            }:
                granularity = None

        # First normalize SQL-like expressions returned by the LLM.
        # Expressions are converted to their underlying physical column.
        expression_patterns = [
            (r"^\s*year\s*\(\s*(.*?)\s*\)\s*$", "year"),
            (r"^\s*month\s*\(\s*(.*?)\s*\)\s*$", "month"),
            (r"^\s*week\s*\(\s*(.*?)\s*\)\s*$", "week"),
            (r"^\s*quarter\s*\(\s*(.*?)\s*\)\s*$", "quarter"),
            (r"^\s*day\s*\(\s*(.*?)\s*\)\s*$", "day"),
        ]

        normalized_group_by: list[str] = []

        for item in plan.group_by:
            value = str(item).strip()
            matched = False

            for pattern, expression_granularity in expression_patterns:
                match = re.match(pattern, value, flags=re.IGNORECASE)
                if not match:
                    continue

                underlying_column = match.group(1).strip()
                if underlying_column in available_names:
                    normalized_group_by.append(underlying_column)
                    if granularity is None:
                        granularity = expression_granularity
                matched = True
                break

            if not matched and value in available_names:
                normalized_group_by.append(value)

        plan.group_by = list(dict.fromkeys(normalized_group_by))

        # If the LLM supplied a qualified group reference but omitted the
        # physical group_by name, use the referenced actual column.
        if not plan.group_by and plan.group_by_refs:
            for ref in plan.group_by_refs:
                if ref.column in available_names:
                    plan.group_by.append(ref.column)
                    break

        # Infer granularity from explicit natural-language temporal wording
        # only when a group-by dimension exists. This is intentionally
        # conservative so an unrelated date mention is not turned into a
        # temporal grouping.
        if plan.group_by and granularity is None:
            temporal_patterns = [
                (r"\b(?:by|each|every|per|in each|for each)\s+day\b", "day"),
                (r"\b(?:by|each|every|per|in each|for each)\s+week\b", "week"),
                (r"\b(?:by|each|every|per|in each|for each)\s+month\b", "month"),
                (r"\b(?:by|each|every|per|in each|for each)\s+quarter\b", "quarter"),
                (r"\b(?:by|each|every|per|in each|for each)\s+year\b", "year"),
                (r"\bmonthly\b", "month"),
                (r"\bweekly\b", "week"),
                (r"\bquarterly\b", "quarter"),
                (r"\b(?:yearly|annually)\b", "year"),
                (r"\bdaily\b", "day"),
            ]

            for pattern, detected_granularity in temporal_patterns:
                if re.search(pattern, question):
                    granularity = detected_granularity
                    break

        plan.group_by_granularity = granularity

        if plan.intent == "derived_aggregation":
            plan.sort_column = None
            plan.sort_direction = None
            plan.limit = None
            if not plan.group_by:
                per_match = re.search(r"\bper\s+(\w+)", question_lower)
                if per_match:
                    entity_word = per_match.group(1).casefold()
                    matches = [
                        c for c in available_names
                        if entity_word in c.casefold()
                        and ("id" in c.casefold() or "key" in c.casefold() or "code" in c.casefold())
                    ]
                    if matches:
                        plan.group_by.append(matches[0])

        return plan

    @staticmethod
    def _detect_row_retrieval_limit(
        question: str,
    ) -> int | None:
        """Detect generic requests to display a bounded number of records.

        This is schema-independent. It only recognizes retrieval verbs
        together with an explicit row count.
        """

        text = (question or "").strip().casefold()

        patterns = [
            r"\b(?:show|display|give|list|return|get|fetch)\s+(?:me\s+)?(?:the\s+)?(?:first|top)\s+(\d+)\b",
            r"\b(?:show|display|give|list|return|get|fetch)\s+(?:me\s+)?(\d+)\s+([a-zA-Z_-]+)\b",
            r"\b(?:show|display|give|list|return|get|fetch)\s+(?:me\s+)?(?:the\s+)?(\d+)(?:st|nd|rd|th)\b",
            r"\b(?:the\s+)?(?:first|top)\s+(\d+)\b",
            r"\b(?:the\s+)?(\d+)(?:st|nd|rd|th)\s+([a-zA-Z_-]+)\b",
        ]

        for pattern in patterns:
            match = re.search(pattern, text)

            if match:
                try:
                    value = int(match.group(1))
                except (TypeError, ValueError):
                    continue

                if value > 0:
                    return value

        word_ordinals = {
            "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
            "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10,
        }
        for word, val in word_ordinals.items():
            if re.search(r"\b(?:show|display|give|list|return|get|fetch)\s+(?:me\s+)?(?:the\s+)?" + word + r"\b", text):
                return val
            if re.search(r"\b(?:the\s+)?" + word + r"\s+[a-zA-Z_-]+\b", text):
                return val

        return None

    @staticmethod
    def _detect_require_all_filter_values(
        question: str,
        filters: list[QueryFilter],
    ) -> bool:
        """
        Detect grouped semantics where all requested values of one
        filter dimension must be present in the same group.

        This is intentionally domain-independent.
        """
        text = (question or "").casefold()
        if not re.search(r"\bboth\b", text):
            return False
        if not re.search(r"\band\b", text):
            return False

        grouped_values: dict[str, list[Any]] = {}

        for item in filters:
            operator = str(item.operator or "").casefold()
            if operator == "in" and isinstance(item.value, (list, tuple)):
                if len(item.value) >= 2:
                    grouped_values.setdefault(item.column, []).extend(item.value)
            elif operator == "equals":
                grouped_values.setdefault(item.column, []).append(item.value)

        return any(len(set(map(str, values))) >= 2 for values in grouped_values.values())

    @staticmethod
    def _detect_metadata_intent(
        question: str,
    ) -> str | None:
        """Detect schema-structure questions without using domain terms.

        These requests concern the shape of the database schema rather
        than values stored in a particular business/domain column.
        """

        text = (question or "").strip().casefold()

        column_name_request = bool(
            re.search(
                r"\b(column|field)s?\b.*\b(name|names|list|listed)\b",
                text,
            )
            or re.search(
                r"\b(name|names|list|listed)\b.*\b(column|field)s?\b",
                text,
            )
        )

        if column_name_request:
            return "column_names"

        column_count_request = bool(
            re.search(
                r"\b(number|count|how many|total)\b.*\b(column|field)s?\b",
                text,
            )
            or re.search(
                r"\b(column|field)s?\b.*\b(number|count|how many|total)\b",
                text,
            )
        )

        if column_count_request:
            return "column_count"

        # A grouped question may contain the same words used by a
        # structural row-count request, for example:
        #   "For each event, how many lead records are there?"
        #   "How many records are there by status?"
        #
        # Those questions ask for a count per group, not one total row
        # count. Keep structural row_count detection conservative so the
        # later grouped-aggregation normalization can handle them.
        grouped_count_request = bool(
            re.search(
                r"\b(?:for\s+each|for\s+every|each|every|per|by)\s+\w+",
                text,
            )
        )

        row_count_request = bool(
            re.search(
                r"\b(number|count|how many|total)\b.*\b(row|record|entry|entries)s?\b",
                text,
            )
            or re.search(
                r"\b(row|record|entry|entries)s?\b.*\b(number|count|how many|total)\b",
                text,
            )
        ) and not grouped_count_request

        if row_count_request:
            return "row_count"

        return None

    @staticmethod
    def _detect_aggregate_operation(
        question: str,
    ) -> str | None:

        patterns = [
            (
                r"\b(total|sum|summed|combined|overall)\b",
                "sum",
            ),
            (
                r"\b(average|avg|mean)\b",
                "average",
            ),
            (
                r"\b(maximum|max)\b",
                "max",
            ),
            (
                r"\b(minimum|min)\b",
                "min",
            ),
            (
                r"\bmedian\b",
                "median",
            ),
        ]

        for pattern, operation in patterns:
            if re.search(
                pattern,
                question,
            ):
                return operation

        return None

    @staticmethod
    def _detect_derived_aggregation_request(
        question: str,
    ) -> tuple[str, str] | None:
        """
        Detect requests asking for an aggregate over grouped counts, e.g.:
        "average number/count of X per Y" -> ("average", "count")
        "median number/count of X per Y" -> ("median", "count")
        "max/maximum count of X per Y" -> ("max", "count")
        "min/minimum number of X per Y" -> ("min", "count")
        "total/sum number of X per Y" -> ("sum", "count")
        """
        outer_patterns = [
            (r"\b(average|avg|mean)\b", "average"),
            (r"\bmedian\b", "median"),
            (r"\b(maximum|max)\b", "max"),
            (r"\b(minimum|min)\b", "min"),
            (r"\b(total|sum)\b", "sum"),
        ]

        has_per_group = bool(
            re.search(
                r"\b(per|for\s+each|in\s+each)\b",
                question,
            )
        )

        has_inner_count = bool(
            re.search(
                r"\b(number\s+of|count\s+of|number|count|occurrences\s+of|occurrences)\b",
                question,
            )
        )

        if has_per_group and has_inner_count:
            for pattern, outer_agg in outer_patterns:
                if re.search(pattern, question):
                    return (outer_agg, "count")

        return None

    @staticmethod
    def _detect_count_request(
        question: str,
    ) -> bool:
        """
        Detect scalar natural-language count questions.

        This is intentionally domain-independent. It recognizes wording such
        as ``how many events``, ``number of records`` and ``count of users``
        without assuming any particular table or column. Grouped wording is
        handled separately by the grouped-aggregation normalization.
        """

        text = (question or "").strip().casefold()

        if not text:
            return False

        patterns = [
            r"\bhow\s+many\b",
            r"\bhow\s+much\b",
            r"\b(?:number|count)\s+of\b",
            r"\btotal\s+(?:number|count)\s+of\b",
            r"\bwhat\s+is\s+the\s+(?:number|count)\s+of\b",
            r"\b(?:give|show|tell)\s+(?:me\s+)?(?:the\s+)?(?:number|count)\s+of\b",
        ]

        return any(
            re.search(pattern, text)
            for pattern in patterns
        )


    @staticmethod
    def _detect_frequency_request(
        question: str,
    ) -> bool:
        """
        Detect generic questions asking how often something occurs.

        This deliberately does not reference any schema-specific
        column, entity, or business domain.
        """

        patterns = [
            r"\bused\s+(?:the\s+)?(?:most|maximum|least|minimum|fewest)\b",
            r"\bused\s+(?:the\s+)?(?:highest|lowest)\s+(?:number\s+of\s+)?times\b",
            r"\bused\s+(?:maximum|minimum)\s+times\b",
            r"\b(?:most|least)\s+used\b",
            r"\b(?:most|least)\s+frequent(?:ly)?\b",
            r"\b(?:most|least)\s+often\b",
            r"\bappears?\s+(?:most|least)\s+(?:often|frequently)\b",
            r"\boccurs?\s+(?:most|least)\s+(?:often|frequently)\b",
            r"\b(?:highest|lowest)\s+(?:usage|frequency)\b",
            r"\b(?:maximum|minimum)\s+(?:usage|frequency)\b",
            r"\b(?:highest|lowest)\s+(?:count|number)\b",
            r"\b(?:most|fewest)\s+(?:times|occurrences)\b",
        ]

        return any(
            re.search(
                pattern,
                question,
            )
            for pattern in patterns
        )

    @staticmethod
    def _detect_ranking_direction(
        question: str,
    ) -> str | None:

        descending_words = {
            "highest",
            "largest",
            "most",
            "top",
            "maximum",
            "greatest",
            "best",
            "maximum",
        }

        ascending_words = {
            "lowest",
            "smallest",
            "least",
            "minimum",
            "fewest",
            "worst",
        }

        words = set(
            re.findall(
                r"\b[a-z]+\b",
                question,
            )
        )

        if words & descending_words:
            return "desc"

        if words & ascending_words:
            return "asc"

        return None

    @staticmethod
    def _is_comparison_request(
        question: str,
    ) -> bool:
        """Return True for explicit comparative questions.

        This is intentionally domain-independent. It detects comparative
        language and comparison structures without assuming any database
        column names or category values.
        """

        text = (question or "").strip().lower()

        comparative_language = re.search(
            r"\b(higher|lower|greater|lesser|more|less|better|worse)\b",
            text,
        )

        comparison_structure = (
            re.search(r"\bcompare\b", text)
            or re.search(r"\bbetween\b.+\band\b", text)
            or re.search(r"\b(which|what|who)\b.+\bor\b", text)
        )

        return bool(
            comparative_language
            or comparison_structure
        )

    @staticmethod
    def _is_grouped_breakdown_request(
        question: str,
    ) -> bool:
        """
        Detect generic wording that asks for an aggregate/value
        across multiple groups rather than one winning group.

        This is schema-independent. It does not inspect database
        column names or assume a particular business domain.
        """
        patterns = [
            r"\bfor\s+each\s+\w+",
            r"\beach\s+\w+",
            r"\bevery\s+\w+",
            r"\bper\s+\w+",
            r"\bby\s+\w+",
            r"\bacross\s+\w+",
        ]

        return any(
            re.search(pattern, question)
            for pattern in patterns
        )

    @staticmethod
    def _has_explicit_limit_request(
        question: str,
    ) -> bool:
        """
        Detect whether the user explicitly requested a numeric result size.

        This is intentionally schema-independent.
        """

        patterns = [
            r"\btop\s+\d+\b",
            r"\bbottom\s+\d+\b",
            r"\bfirst\s+\d+\b",
            r"\blast\s+\d+\b",
            r"\b(?:show|give|list|return|find|display)\s+(?:me\s+)?\d+\b",
            r"\b\d+\s+(?:groups?|categories?|items?|records?|results?|entries?)\b",
        ]

        return any(
            re.search(
                pattern,
                question,
            )
            for pattern in patterns
        )

    @staticmethod
    def _asks_for_multiple_values(
        question: str,
    ) -> bool:
        """
        Detect generic wording that requests multiple values
        rather than a single winning value.

        This is schema-independent.
        """

        patterns = [
            # Explicit plural/multiple-value wording.
            # Do not treat the singular word "average" as a request for
            # multiple values because it also appears in single-winner
            # questions such as "Which has the highest average?".
            r"\bvalues?\b",
            r"\baverages\b",
            r"\bresults\b",
            r"\bnumbers\b",
            r"\bfigures\b",
            r"\bamounts\b",
            r"\bstatistics\b",
            r"\b(?:each|every|their|respective|individual)\s+values?\b",
            r"\b(?:each|every|their|respective|individual)\s+averages?\b",
        ]

        return any(
            re.search(
                pattern,
                question,
            )
            for pattern in patterns
        )

    @staticmethod
    def _detect_include_ties_request(
        question: str,
        ranking_direction: str | None,
    ) -> bool:
        """
        Detect whether a ranking request asks for all records
        sharing the ranking boundary.

        This is schema-independent and does not reference any
        schema-specific column, entity, or business domain.
        """

        if ranking_direction is None:
            return False

        words = set(
            re.findall(
                r"\b[a-z]+\b",
                question,
            )
        )

        return "all" in words

    @classmethod
    def _asks_for_single_winner(
        cls,
        question: str,
    ) -> bool:
        """
        Detect whether the user is asking for one winning result.

        Explicit multi-result requests such as "top 5", "bottom 10",
        "first 5", or "10 results" must never be treated as a
        single-winner request.

        This is schema-independent.
        """

        text = (question or "").strip().casefold()

        # ----------------------------------------------------------
        # Explicitly requested multiple results take precedence.
        # ----------------------------------------------------------
        if cls._has_explicit_limit_request(text):
            return False

        # ----------------------------------------------------------
        # Natural-language indicators of a single winner.
        # ----------------------------------------------------------
        phrases = [
            "which",
            "what",
            "who",
            "the highest",
            "the lowest",
            "the largest",
            "the smallest",
            "the most",
            "the least",
            "the best",
            "the worst",
            "maximum",
            "minimum",
        ]

        return any(
            phrase in text
            for phrase in phrases
        )

    @staticmethod
    def _extract_reference_column(
        filters: list[QueryFilter],
        schema_names: set[str],
    ) -> str | None:
        """
        Extract the source column represented by a previous-result
        reference inside a filter.
        """

        for item in filters:
            if item.column not in schema_names:
                continue

            value = item.value

            if isinstance(value, dict):
                reference = value.get("reference")
                column = value.get("column")

                if reference and column in schema_names:
                    return column

        return None


    @staticmethod
    def _get_referenced_result_columns(
        conversation_context: dict[str, Any] | None,
        reference_id: str | None,
    ) -> set[str]:
        """Return columns actually exposed by a referenced prior result.

        Conversation context is intentionally treated as untrusted metadata.
        Only columns associated with the exact requested reference are
        accepted. No virtual or domain-specific column names are hardcoded.
        """
        if not conversation_context or not reference_id:
            return set()

        def as_columns(value: Any) -> set[str]:
            if isinstance(value, dict):
                columns = value.get("columns")
                if isinstance(columns, (list, tuple, set)):
                    return {str(c) for c in columns if c is not None}

                data = value.get("data")
                if isinstance(data, list) and data and isinstance(data[0], dict):
                    return {str(c) for c in data[0].keys()}
                if isinstance(data, dict):
                    return {str(c) for c in data.keys()}
            elif isinstance(value, list) and value and isinstance(value[0], dict):
                return {str(c) for c in value[0].keys()}
            return set()

        def walk(node: Any) -> set[str]:
            if isinstance(node, dict):
                if str(node.get("reference_id", node.get("id", ""))) == str(reference_id):
                    found = as_columns(node)
                    if found:
                        return found
                for value in node.values():
                    found = walk(value)
                    if found:
                        return found
            elif isinstance(node, list):
                for value in node:
                    found = walk(value)
                    if found:
                        return found
            return set()

        return walk(conversation_context)

    # ==========================================================
    # COUNT TARGET SELECTION
    # ==========================================================

    @staticmethod
    def _choose_count_target(
        columns: dict[str, dict[str, Any]],
    ) -> list[str]:

        """
        Choose a stable record/entity column for grouped counts.

        This is schema-driven and does not contain any
        domain-specific column name.
        """

        preferred_roles = {
            "identifier",
            "id",
            "key",
            "record_id",
            "entity_id",
        }

        for name, metadata in columns.items():

            role = str(
                metadata.get(
                    "semantic_role",
                    "",
                )
            ).casefold()

            if role in preferred_roles:
                return [name]

        # If no identifier role exists, use the first available
        # schema column. The executor's count operation will count
        # non-null values in that column.
        if columns:
            return [
                next(iter(columns))
            ]

        return []

    # ==========================================================
    # SCHEMA HELPERS
    # ==========================================================

    @staticmethod
    def _get_schema_columns(
        database_schema: DatabaseSchema,
    ) -> dict[str, dict[str, Any]]:
        columns: dict[str, dict[str, Any]] = {}

        for table in database_schema.tables:
            for column in table.columns:
                columns[column.name] = {
                    "schema": table.schema_name,
                    "table": table.table_name,
                    "data_type": column.data_type,
                    "nullable": column.nullable,
                }

        return columns

    @staticmethod
    def _select_database_tables(
        question: str,
        database_schema: DatabaseSchema,
        max_tables: int = 5,
    ) -> list[TableInfo]:
        selected = select_tables(
            question=question,
            schema=database_schema.tables,
            max_tables=max_tables,
            relationships=database_schema.foreign_keys,
        )

        selected_tables: list[TableInfo] = []

        for item in selected:
            table = database_schema.get_table(
                item["schema"],
                item["table"],
            )

            if table is not None:
                selected_tables.append(table)

        return selected_tables

    @staticmethod
    def _schema_to_context(
        database_schema: DatabaseSchema,
    ) -> str:
        lines: list[str] = []

        lines.append("Database schema:")

        for table in database_schema.tables:
            lines.append(
                f"\nTable: {table.schema_name}.{table.table_name}"
            )

            if table.primary_key_columns:
                lines.append(
                    "Primary key: "
                    + ", ".join(table.primary_key_columns)
                )

            lines.append("Columns:")

            for column in table.columns:
                lines.append(
                    f"- {column.name}"
                    f" | type={column.data_type}"
                    f" | nullable={column.nullable}"
                )

        if database_schema.foreign_keys:
            lines.append("\nDeclared foreign keys:")

            for fk in database_schema.foreign_keys:
                lines.append(
                    f"- {fk.schema_name}.{fk.table_name}"
                    f".{fk.column_name}"
                    f" -> "
                    f"{fk.referenced_schema_name}."
                    f"{fk.referenced_table_name}."
                    f"{fk.referenced_column_name}"
                )

        return "\n".join(lines)

    # ==========================================================
    # RESPONSE PARSING
    # ==========================================================

    @staticmethod
    def _parse_response(
        raw_response: str,
    ) -> QueryPlan:

        try:
            data = json.loads(
                raw_response
            )

        except json.JSONDecodeError as exc:

            raise ValueError(
                "Question analyzer returned "
                "invalid JSON."
            ) from exc

        if not isinstance(
            data,
            dict,
        ):
            raise ValueError(
                "Question analyzer response "
                "must be a JSON object."
            )

        # --------------------------------------------------
        # Intent
        # --------------------------------------------------

        intent = QuestionAnalyzer._normalize_intent(
            data.get("intent"),
            aggregation=data.get("aggregation"),
            group_by=data.get("group_by"),
            sort_column=data.get("sort_column"),
            filters=data.get("filters"),
            input_result_reference=data.get("input_result_reference"),
            target_columns=data.get("target_columns"),
        )

        # --------------------------------------------------
        # Filters
        # --------------------------------------------------

        filters = []

        for filter_data in data.get(
            "filters",
            [],
        ):

            if isinstance(filter_data, str):
                reference_match = re.match(
                    r"^\s*(.*?)\s*(?:=|equals)\s*"
                    r"\(input\s+result:\s*([^)]+)\)\s*$",
                    filter_data,
                    flags=re.IGNORECASE,
                )

                if reference_match:
                    column = reference_match.group(1).strip()
                    reference = reference_match.group(2).strip()

                    filters.append(
                        QueryFilter(
                            column=column,
                            operator="equals",
                            value={
                                "reference": reference,
                                "column": column,
                            },
                        )
                    )

                continue

            if not isinstance(
                filter_data,
                dict,
            ):
                continue

            column = filter_data.get("column")
            is_aggregate_filter = False
            if not column:
                column = filter_data.get("aggregation")
                is_aggregate_filter = True

            # Preserve explicit table / schema qualification from LLM filter dictionary
            tbl_qual = filter_data.get("table")
            sch_qual = filter_data.get("schema")
            if tbl_qual and column and "." not in str(column) and not is_aggregate_filter:
                if sch_qual:
                    column = f"{sch_qual}.{tbl_qual}.{column}"
                else:
                    column = f"{tbl_qual}.{column}"

            # Accept both "operator" and "operation".
            # Some LLM responses use one or the other.
            operator = filter_data.get("operator")
            if operator is None:
                operator = filter_data.get("op")

            if operator is None:
                operator = filter_data.get("operation")

            if not column or operator is None:
                continue

            filter_value = filter_data.get("value")
            if filter_value is None and "values" in filter_data:
                filter_value = filter_data.get("values")

            # Canonicalize anti-join / NOT IN with empty values or NULL checks
            raw_op_lower = str(operator).strip().casefold()
            if raw_op_lower in ("not_in", "not in") and (filter_value is None or not filter_value):
                operator = "is_null"
                filter_value = None
            elif raw_op_lower in ("equals", "=", "==") and str(filter_value).strip().casefold() in ("null", "none"):
                operator = "is_null"
                filter_value = None
            elif raw_op_lower in ("not_equals", "!=", "<>") and str(filter_value).strip().casefold() in ("null", "none"):
                operator = "is_not_null"
                filter_value = None
            else:
                operator = QuestionAnalyzer._normalize_operator(
                    operator
                )

            if operator in ("is_null", "is_not_null"):
                filter_value = None

            operator, filter_value = (
                QuestionAnalyzer._normalize_like_filter(
                    operator,
                    filter_value,
                )
            )

            if operator is None:
                continue

            # --------------------------------------------------
            # Normalize date/range operators into the canonical
            # comparison operators understood by the executor.
            # This keeps the QueryPlan contract simple while still
            # accepting natural LLM representations such as
            # between [start, end] and year 2025.
            # --------------------------------------------------
            if operator == "between":
                if (
                    isinstance(filter_value, (list, tuple))
                    and len(filter_value) == 2
                ):
                    filters.append(
                        QueryFilter(
                            column=str(column),
                            operator="greater_than_or_equal",
                            value=filter_value[0],
                        )
                    )
                    filters.append(
                        QueryFilter(
                            column=str(column),
                            operator="less_than_or_equal",
                            value=filter_value[1],
                        )
                    )
                continue

            if operator in ("year", "year_equals", "year_is", "in_year"):
                try:
                    year = int(filter_value)
                except (TypeError, ValueError):
                    continue

                if year < 1:
                    continue

                filters.append(
                    QueryFilter(
                        column=str(column),
                        operator="greater_than_or_equal",
                        value=f"{year:04d}-01-01",
                    )
                )
                filters.append(
                    QueryFilter(
                        column=str(column),
                        operator="less_than",
                        value=f"{year + 1:04d}-01-01",
                    )
                )
                continue

            if operator not in QuestionAnalyzer.VALID_OPERATORS:
                continue

            filters.append(
                QueryFilter(
                    column=str(column),
                    operator=operator,
                    value=filter_value,
                )
            )

        # --------------------------------------------------
        # Input result reference
        # --------------------------------------------------

        input_result_reference = (
            data.get(
                "input_result_reference"
            )
        )

        # --------------------------------------------------
        # Confidence
        # --------------------------------------------------

        confidence = (
            QuestionAnalyzer
            ._safe_confidence(
                data.get(
                    "confidence",
                    0.0,
                )
            )
        )

        # --------------------------------------------------
        # Aggregation
        # --------------------------------------------------

        aggregation = (
            QuestionAnalyzer
            ._normalize_aggregation(
                data.get(
                    "aggregation"
                )
            )
        )

        inner_aggregation = (
            QuestionAnalyzer
            ._normalize_aggregation(
                data.get(
                    "inner_aggregation"
                )
            )
        )

        # --------------------------------------------------
        # Sort direction
        # --------------------------------------------------

        sort_direction = (
            QuestionAnalyzer
            ._normalize_sort_direction(
                data.get(
                    "sort_direction"
                )
            )
        )

        # --------------------------------------------------
        # Limit
        # --------------------------------------------------

        limit = (
            QuestionAnalyzer
            ._normalize_limit(
                data.get(
                    "limit"
                )
            )
        )

        include_ties = QuestionAnalyzer._normalize_include_ties(
            data.get("include_ties")
        )

        require_all_filter_values = bool(
            data.get("require_all_filter_values", False)
        )

        # --------------------------------------------------
        # Target columns
        # --------------------------------------------------

        target_columns = data.get(
            "target_columns",
            [],
        )

        if not isinstance(
            target_columns,
            list,
        ):
            target_columns = []

        # --------------------------------------------------
        # Group-by
        # --------------------------------------------------

        group_by = data.get(
            "group_by",
            [],
        )

        if not isinstance(
            group_by,
            list,
        ):
            group_by = []

        # --------------------------------------------------
        # Time grouping granularity
        # --------------------------------------------------

        group_by_granularity = data.get(
            "group_by_granularity"
        )

        if group_by_granularity is not None:
            group_by_granularity = (
                str(group_by_granularity)
                .strip()
                .lower()
            )

            if group_by_granularity not in {
                "day",
                "week",
                "month",
                "quarter",
                "year",
            }:
                group_by_granularity = None

        # --------------------------------------------------
        # Qualified target column references
        # --------------------------------------------------

        target_column_refs = []

        raw_target_column_refs = data.get(
            "target_column_refs",
            [],
        )

        if isinstance(
            raw_target_column_refs,
            list,
        ):
            for column_data in raw_target_column_refs:

                if not isinstance(
                    column_data,
                    dict,
                ):
                    continue

                schema = column_data.get("schema")
                table = column_data.get("table")
                column = column_data.get("column")

                if not all(
                    [
                        schema,
                        table,
                        column,
                    ]
                ):
                    continue

                target_column_refs.append(
                    QueryColumn(
                        schema=str(schema),
                        table=str(table),
                        column=str(column),
                    )
                )

        # --------------------------------------------------
        # Qualified GROUP BY references
        # --------------------------------------------------

        group_by_refs = []

        raw_group_by_refs = data.get(
            "group_by_refs",
            [],
        )

        if isinstance(
            raw_group_by_refs,
            list,
        ):
            for column_data in raw_group_by_refs:

                if not isinstance(
                    column_data,
                    dict,
                ):
                    continue

                schema = column_data.get("schema")
                table = column_data.get("table")
                column = column_data.get("column")

                if not all(
                    [
                        schema,
                        table,
                        column,
                    ]
                ):
                    continue

                group_by_refs.append(
                    QueryColumn(
                        schema=str(schema),
                        table=str(table),
                        column=str(column),
                    )
                )

        # --------------------------------------------------
        # Joins
        # --------------------------------------------------

        joins = []

        raw_joins = data.get(
            "joins",
            [],
        )

        if isinstance(
            raw_joins,
            list,
        ):
            for join_data in raw_joins:

                if not isinstance(
                    join_data,
                    dict,
                ):
                    continue

                left_schema = join_data.get(
                    "left_schema"
                )

                left_table = join_data.get(
                    "left_table"
                )

                left_column = join_data.get(
                    "left_column"
                )

                right_schema = join_data.get(
                    "right_schema"
                )

                right_table = join_data.get(
                    "right_table"
                )

                right_column = join_data.get(
                    "right_column"
                )

                if not all(
                    [
                        left_schema,
                        left_table,
                        left_column,
                        right_schema,
                        right_table,
                        right_column,
                    ]
                ):
                    continue

                join_type = str(
                    join_data.get(
                        "join_type",
                        "inner",
                    )
                ).strip().lower()

                if join_type not in {
                    "inner",
                    "left",
                    "right",
                }:
                    join_type = "inner"

                joins.append(
                    QueryJoin(
                        left_schema=str(
                            left_schema
                        ),
                        left_table=str(
                            left_table
                        ),
                        left_column=str(
                            left_column
                        ),
                        right_schema=str(
                            right_schema
                        ),
                        right_table=str(
                            right_table
                        ),
                        right_column=str(
                            right_column
                        ),
                        join_type=join_type,
                    )
                )

        return QueryPlan(
            intent=intent,

            target_columns=[
                str(column)
                for column in target_columns
                if column
            ],

            filters=filters,

            group_by=[
                str(column)
                for column in group_by
                if column
            ],

            group_by_granularity=group_by_granularity,

            aggregation=aggregation,
            inner_aggregation=inner_aggregation,

            sort_column=(
                str(
                    data["sort_column"]
                )
                if data.get(
                    "sort_column"
                ) is not None
                else None
            ),

            sort_direction=sort_direction,

            limit=limit,

            include_ties=include_ties,

            require_all_filter_values=require_all_filter_values,

            explanation=str(
                data.get(
                    "explanation",
                    "",
                )
            ),

            confidence=confidence,

            input_result_reference=(
                str(input_result_reference)
                if input_result_reference
                else None
            ),

            joins=joins,

            target_column_refs=target_column_refs,

            group_by_refs=group_by_refs,
        )

    # ==========================================================
    # INTENT NORMALIZATION
    # ==========================================================

    @staticmethod
    def _normalize_intent(
        value: Any,
        aggregation: Any = None,
        group_by: Any = None,
        sort_column: Any = None,
        filters: Any = None,
        input_result_reference: Any = None,
        target_columns: Any = None,
    ) -> str:

        valid_intents = {
            "lookup",
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

        if isinstance(
            value,
            str,
        ):

            intent = (
                value.strip().lower()
            )

            if intent in valid_intents:
                return intent

        # Structured fields are more reliable than a
        # free-form description returned in "intent".

        has_grouping = bool(
            group_by
        )

        has_aggregation = (
            aggregation is not None
            and str(
                aggregation
            ).strip() != ""
        )

        has_sort = (
            sort_column is not None
            and str(
                sort_column
            ).strip() != ""
        )

        has_filters = bool(
            filters
        )

        has_input_result_reference = bool(
            input_result_reference
        )

        has_target_columns = bool(
            target_columns
        )

        # Follow-up questions can be expressed by the LLM as a
        # natural-language intent. If the plan explicitly references
        # a previous result and requests target columns, it is a
        # lookup over that referenced result/context.
        if (
            has_input_result_reference
            and has_target_columns
            and not has_grouping
            and not has_aggregation
            and not has_sort
            and not has_filters
        ):
            return "lookup"

        if has_grouping and has_aggregation:
            return "aggregation"

        if has_aggregation:
            return "aggregation"

        if has_sort:
            return "ranking"

        if has_filters:
            return "filter"

        return "unsupported"

    # ==========================================================
    # AGGREGATION NORMALIZATION
    # ==========================================================

    @staticmethod
    def _normalize_aggregation(
        value: Any,
    ) -> str | None:

        if value is None:
            return None

        value = str(
            value
        ).strip().lower()

        aliases = {
            "sum": "sum",
            "total": "sum",
            "total_sum": "sum",

            "average": "average",
            "avg": "average",
            "mean": "average",

            "minimum": "min",
            "minimum_value": "min",
            "min": "min",

            "maximum": "max",
            "maximum_value": "max",
            "max": "max",

            "count": "count",
            "frequency": "count",
            "number": "count",

            "median": "median",
        }

        return aliases.get(
            value,
            value,
        )

    # ==========================================================
    # SORT DIRECTION NORMALIZATION
    # ==========================================================

    @staticmethod
    def _normalize_sort_direction(
        value: Any,
    ) -> str | None:

        if value is None:
            return None

        value = str(
            value
        ).strip().lower()

        aliases = {
            "asc": "asc",
            "ascending": "asc",
            "lowest": "asc",
            "smallest": "asc",
            "least": "asc",
            "minimum": "asc",
            "min": "asc",

            "desc": "desc",
            "descending": "desc",
            "highest": "desc",
            "largest": "desc",
            "most": "desc",
            "maximum": "desc",
            "max": "desc",
        }

        return aliases.get(
            value,
            value,
        )

    # ==========================================================
    # LIMIT NORMALIZATION
    # ==========================================================

    @staticmethod
    def _normalize_limit(
        value: Any,
    ) -> int | None:

        if value is None:
            return None

        try:
            value = int(
                value
            )

        except (
            TypeError,
            ValueError,
        ):
            return None

        if value <= 0:
            return None

        return value

    # ==========================================================
    # INCLUDE-TIES NORMALIZATION
    # ==========================================================

    @staticmethod
    def _normalize_include_ties(
        value: Any,
    ) -> bool:

        if isinstance(value, bool):
            return value

        if value is None:
            return False

        normalized = str(
            value
        ).strip().casefold()

        if normalized in {
            "true",
            "1",
            "yes",
            "y",
        }:
            return True

        return False


    # ==========================================================
    # CONFIDENCE
    # ==========================================================

    @staticmethod
    def _safe_confidence(
        value: Any,
    ) -> float:

        try:
            value = float(
                value
            )

        except (
            TypeError,
            ValueError,
        ):
            value = 0.0

        return max(
            0.0,
            min(
                1.0,
                value,
            )
        )
