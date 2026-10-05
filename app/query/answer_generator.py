from __future__ import annotations

import json
from typing import Any

from app.llm.deepseek_client import DeepSeekClient


class AnswerGenerationError(Exception):
    """Raised when a natural-language answer cannot be generated."""


class AnswerGenerator:
    """
    Converts a verified deterministic query result into a concise,
    natural-language answer.

    Architecture:

        User question
              ↓
        Query Analyzer
              ↓
        Query Validator
              ↓
        SQL Query Executor
              ↓
        VERIFIED RESULT
              ↓
        AnswerGenerator / DeepSeek
              ↓
        Natural-language answer

    DeepSeek is used only to explain/present the verified result.

    It must not:
        - execute SQL
        - calculate database values
        - invent missing information
        - reinterpret the verified result
    """

    def __init__(
        self,
        client: DeepSeekClient | None = None,
    ):
        self.client = client or DeepSeekClient()

    # ==========================================================
    # PUBLIC API
    # ==========================================================

    def generate(
        self,
        question: str,
        result: Any,
        plan: Any,
        semantic_schema: Any | None = None,
        warnings: list[str] | None = None,
    ) -> str:

        question = (question or "").strip()

        if not question:
            raise AnswerGenerationError(
                "Question cannot be empty."
            )

        result_text = self._serialize_result(result)

        system_prompt = self._build_system_prompt()

        user_prompt = self._build_user_prompt(
            question=question,
            result_text=result_text,
            plan=plan,
            warnings=warnings or [],
        )

        try:
            answer = self.client.generate_text(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
            )

        except Exception as exc:
            raise AnswerGenerationError(
                f"Natural-language answer generation failed: {exc}"
            ) from exc

        answer = (answer or "").strip()

        if not answer:
            raise AnswerGenerationError(
                "DeepSeek returned an empty natural-language answer."
            )

        return answer

    # ==========================================================
    # SYSTEM PROMPT
    # ==========================================================

    @staticmethod
    def _build_system_prompt() -> str:
        return """
You are the final answer-writing component of a general-purpose
database data chatbot.

The user's question has already been analyzed, validated, and
executed by a deterministic SQL query engine.

Your job is ONLY to convert the VERIFIED QUERY RESULT into a
clear, natural-language answer to the user's question.

The database may contain ANY type of structured data, including
but not limited to:

- sales
- orders
- customers
- employees
- products
- finance
- inventory
- education
- healthcare
- logistics
- offices
- transactions
- events
- users
- accounts
- dates
- locations
- measurements
- or any other structured information.

Do NOT assume that the database belongs to any particular domain.

==================================================
STRICT FACTUAL RULES
==================================================

1. The VERIFIED QUERY RESULT is the authoritative factual source.

2. Do NOT independently calculate, recalculate, estimate, approximate,
   or modify the verified result.

3. Do NOT invent values, records, names, categories, dates, percentages,
   relationships, explanations, or conclusions.

4. Do NOT add facts merely because they appear in the database schema
   context. The schema is provided only to help understand terminology.

5. The verified query result is the factual source for the answer.

6. Never use outside knowledge to fill missing database information.

7. If the verified result does not contain enough information to answer
   the exact question safely, clearly state that the available result
   does not contain enough information. Do not guess.

8. If the verified result is a scalar, present it naturally.

9. Preserve numeric values exactly as supplied by the verified result.

10. Do not change the meaning of units, currencies, percentages,
    quantities, dates, or other values.

11. If the verified result contains records, convert those records into
    readable natural language rather than exposing raw JSON.

12. If several records are returned, use a concise bullet list or
    compact table-like wording when that improves readability.

13. If the verified result contains a single record, summarize it
    naturally.

14. If the verified result is empty, clearly state that no matching
    records were found.

15. If the verified result is boolean, answer naturally using the
    supplied boolean value.

16. If the verified result already represents a calculated value such
    as an average, percentage, total, count, minimum, maximum, ratio,
    or other aggregation, present that value. Do not recalculate it.

17. If the user asks for a list, provide the list represented by the
    verified result.

18. If the user asks for details, present the fields contained in the
    verified result clearly.

19. Do not return JSON unless the user explicitly asks for JSON.

20. Do not expose internal QueryPlan details.

21. Do not expose internal conversation-memory reference IDs, session tracking tokens,
    or internal implementation identifiers.
    However, database record identifiers, entity IDs, codes, or primary/foreign keys
    already present in the VERIFIED QUERY RESULT are valid factual data and should be
    used to identify records when relevant to answering the user's question (e.g. when
    asked which entity or record meets a condition). Do NOT invent human-readable
    names or descriptions if the verified result only contains identifiers.

22. Do not mention internal implementation details.

23. Do not mention that DeepSeek was used.

24. Do not claim to have inspected database rows that are not contained
    in the verified result.

25. Keep the answer concise but sufficiently informative.

26. Answer the exact question asked.

==================================================
IMPORTANT DISTINCTION
==================================================

The SQL query engine has already performed the data operation.

For example, if the verified result is:

    125

and the question asks for a total, simply communicate that verified
total naturally.

If the verified result is:

    [{"Product":"A","Quantity":25}]

communicate the supplied record naturally.

If the verified result is:

    []

say that no matching records were found.

Do NOT perform a new calculation from the question.

==================================================
MISSING INFORMATION
==================================================

If the query engine determines that the database does not contain the
information required by the question, the result may contain an
explanation instead of data.

In that situation, communicate the explanation naturally.

Do not try to answer the question using assumptions or general
knowledge.

==================================================
OUTPUT STYLE
==================================================

Prefer responses such as:

"There are 125 matching records."

"The total sales are 45,230."

"The average unit price is 769.44."

"The matching products are:
- Product A
- Product B
- Product C"

"The highest-value record is:
- Product: Product A
- Value: 12,500"

These are only style patterns.

Do NOT assume that these entities, values, calculations, or fields
exist in the user's database.

Always use the actual verified result supplied to you.

Return ONLY the final natural-language answer.
""".strip()

    # ==========================================================
    # USER PROMPT
    # ==========================================================

    @staticmethod
    def _build_user_prompt(
        question: str,
        result_text: str,
        plan: Any,
        warnings: list[str],
    ) -> str:

        plan_text = AnswerGenerator._serialize_plan(plan)

        warnings_text = (
            json.dumps(
                warnings,
                ensure_ascii=False,
                default=str,
            )
            if warnings
            else "[]"
        )

        return f"""
USER QUESTION:
{question}

VERIFIED QUERY RESULT:
{result_text}

QUERY PLAN:
{plan_text}

WARNINGS:
{warnings_text}

Write the final natural-language answer.

IMPORTANT:
- Use the VERIFIED QUERY RESULT as the factual source.
- Do not perform new calculations.
- Do not infer missing information.
- Do not invent facts.
- Do not return JSON unless the user explicitly requested JSON.
- Do not expose internal QueryPlan details.
- Do not expose internal implementation details.
- Answer only what the verified result supports.
""".strip()

    # ==========================================================
    # RESULT SERIALIZATION
    # ==========================================================

    @staticmethod
    def _serialize_result(data: Any) -> str:
        """
        Convert the deterministic query result into text that can be
        safely supplied to the answer-generation model.

        Supports SQL/database result types and tabular record sets.
        """

        if data is None:
            return "null"

        # Tabular data compatibility (e.g. record-like objects with to_dict).
        if hasattr(data, "to_dict") and callable(getattr(data, "to_dict")):
            try:
                if hasattr(data, "empty") and bool(data.empty):
                    return "[]"

                records = data.to_dict("records")
                return json.dumps(
                    records,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    default=str,
                )
            except Exception:
                pass

        if isinstance(data, bool):
            return "true" if data else "false"

        # Handle scalar wrapper values (e.g. objects with .item()).
        if hasattr(data, "item"):

            try:
                data = data.item()

            except Exception:
                pass

        if isinstance(
            data,
            (
                int,
                float,
                str,
            ),
        ):
            return json.dumps(
                data,
                ensure_ascii=False,
                default=str,
            )

        try:
            return json.dumps(
                data,
                ensure_ascii=False,
                separators=(",", ":"),
                default=str,
            )

        except (TypeError, ValueError):
            return str(data)

    # ==========================================================
    # QUERY PLAN SERIALIZATION
    # ==========================================================

    @staticmethod
    def _serialize_plan(plan: Any) -> str:
        """
        Serialize only useful public query-plan information.

        This is contextual information for the answer writer.
        It is NOT treated as the factual result.
        """

        if plan is None:
            return "{}"

        values = {
            "intent": getattr(
                plan,
                "intent",
                None,
            ),
            "target_columns": getattr(
                plan,
                "target_columns",
                [],
            ),
            "filters": [
                {
                    "column": getattr(
                        item,
                        "column",
                        None,
                    ),
                    "operator": getattr(
                        item,
                        "operator",
                        None,
                    ),
                    "value": getattr(
                        item,
                        "value",
                        None,
                    ),
                }
                for item in getattr(
                    plan,
                    "filters",
                    [],
                )
            ],
            "group_by": getattr(
                plan,
                "group_by",
                [],
            ),
            "aggregation": getattr(
                plan,
                "aggregation",
                None,
            ),
            "inner_aggregation": getattr(
                plan,
                "inner_aggregation",
                None,
            ),
            "sort_column": getattr(
                plan,
                "sort_column",
                None,
            ),
            "sort_direction": getattr(
                plan,
                "sort_direction",
                None,
            ),
            "limit": getattr(
                plan,
                "limit",
                None,
            ),
        }

        return json.dumps(
            values,
            ensure_ascii=False,
            default=str,
        )

    # ==========================================================
    # DATABASE SCHEMA CONTEXT
    # ==========================================================

    @staticmethod
    def _schema_to_context(
        semantic_schema: Any,
    ) -> str:
        """
        Build generic database schema context.

        Supports the current DatabaseSchema/TableInfo/ColumnInfo
        structures and contains no domain-specific assumptions.
        """

        lines: list[str] = []

        # ------------------------------------------------------
        # Current database schema structure
        # ------------------------------------------------------

        tables = getattr(
            semantic_schema,
            "tables",
            None,
        )

        if tables:

            for table in tables:

                schema_name = getattr(
                    table,
                    "schema_name",
                    "",
                )

                table_name = getattr(
                    table,
                    "table_name",
                    "",
                )

                if schema_name and table_name:
                    lines.append(
                        f"Table: {schema_name}.{table_name}"
                    )

                elif table_name:
                    lines.append(
                        f"Table: {table_name}"
                    )

                for column in getattr(
                    table,
                    "columns",
                    [],
                ):

                    column_name = getattr(
                        column,
                        "name",
                        "",
                    )

                    data_type = getattr(
                        column,
                        "data_type",
                        "",
                    )

                    nullable = getattr(
                        column,
                        "nullable",
                        None,
                    )

                    if not column_name:
                        continue

                    column_text = (
                        f"- {column_name}"
                    )

                    if data_type:
                        column_text += (
                            f" ({data_type})"
                        )

                    if nullable is not None:
                        column_text += (
                            f", nullable={nullable}"
                        )

                    lines.append(
                        column_text
                    )

                primary_key_columns = getattr(
                    table,
                    "primary_key_columns",
                    [],
                )

                if primary_key_columns:
                    lines.append(
                        "Primary key: "
                        + ", ".join(
                            primary_key_columns
                        )
                    )

                lines.append("")

            return "\n".join(lines).strip()

        return ""