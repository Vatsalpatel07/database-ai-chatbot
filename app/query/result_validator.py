from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from app.query.schema import QueryPlan


@dataclass
class ResultValidationResult:
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class QueryResultValidator:
    """
    Validates the top-level shape of a SQL execution result.

    This validator does not:
    - execute SQL,
    - call an LLM,
    - inspect business-specific table/column names,
    - or determine whether a numerical result is semantically correct.

    It only verifies that the result returned by SQLQueryExecutor
    matches the result shape expected for the QueryPlan.
    """

    NUMERIC_TYPES = (
        int,
        float,
        Decimal,
    )

    def validate(
        self,
        plan: QueryPlan,
        data: Any,
    ) -> ResultValidationResult:
        errors: list[str] = []
        warnings: list[str] = []

        # JOIN execution returns tabular data (unless derived aggregation).
        if plan.joins and plan.intent != "derived_aggregation":
            self._validate_tabular_result(
                data=data,
                errors=errors,
                operation="JOIN",
            )

            return ResultValidationResult(
                valid=len(errors) == 0,
                errors=errors,
                warnings=warnings,
            )

        # --------------------------------------------------
        # Scalar / structural query operations
        # --------------------------------------------------

        if plan.intent == "row_count":
            self._validate_integer_result(
                data=data,
                errors=errors,
                operation="row_count",
            )

        elif plan.intent == "column_count":
            self._validate_integer_result(
                data=data,
                errors=errors,
                operation="column_count",
            )

        elif plan.intent == "column_names":
            self._validate_column_names_result(
                data=data,
                errors=errors,
            )

        elif plan.intent in {"lookup", "distinct", "ranking"}:
            self._validate_tabular_result(
                data=data,
                errors=errors,
                operation=plan.intent,
            )

        elif plan.intent == "count":
            self._validate_integer_result(
                data=data,
                errors=errors,
                operation="count",
            )

        elif plan.intent == "percentage":
            self._validate_numeric_result(
                data=data,
                errors=errors,
                operation="percentage",
                allow_none=False,
            )

        elif plan.intent == "aggregation":
            if plan.group_by:
                self._validate_tabular_result(
                    data=data,
                    errors=errors,
                    operation="grouped aggregation",
                )
            else:
                self._validate_numeric_result(
                    data=data,
                    errors=errors,
                    operation="aggregation",
                    allow_none=True,
                )

        elif plan.intent == "derived_aggregation":
            self._validate_numeric_result(
                data=data,
                errors=errors,
                operation="derived_aggregation",
                allow_none=True,
            )

        return ResultValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
        )

    @staticmethod
    def _validate_integer_result(
        data: Any,
        errors: list[str],
        operation: str,
    ) -> None:
        if isinstance(data, bool) or not isinstance(data, int):
            errors.append(
                f"{operation} execution returned an invalid result type: "
                f"expected int, got {type(data).__name__}."
            )

    @classmethod
    def _validate_numeric_result(
        cls,
        data: Any,
        errors: list[str],
        operation: str,
        allow_none: bool,
    ) -> None:
        if data is None and allow_none:
            return

        if isinstance(data, bool) or not isinstance(
            data,
            cls.NUMERIC_TYPES,
        ):
            errors.append(
                f"{operation} execution returned an invalid result type: "
                f"expected a numeric value"
                f"{' or None' if allow_none else ''}, "
                f"got {type(data).__name__}."
            )

    @staticmethod
    def _validate_column_names_result(
        data: Any,
        errors: list[str],
    ) -> None:
        if not isinstance(data, list):
            errors.append(
                "column_names execution returned an invalid result type: "
                f"expected list[str], got {type(data).__name__}."
            )
            return

        invalid_items = [
            item
            for item in data
            if not isinstance(item, str)
        ]

        if invalid_items:
            errors.append(
                "column_names execution returned a list containing "
                "non-string values."
            )

    @staticmethod
    def _validate_tabular_result(
        data: Any,
        errors: list[str],
        operation: str,
    ) -> None:
        if not isinstance(data, list):
            errors.append(
                f"{operation} execution returned an invalid result type: "
                f"expected list[dict], got {type(data).__name__}."
            )
            return

        invalid_rows = [
            row
            for row in data
            if not isinstance(row, dict)
        ]

        if invalid_rows:
            errors.append(
                f"{operation} execution returned a tabular result "
                "containing a non-dictionary row."
            )
            return

        invalid_key_rows = [
            row
            for row in data
            if any(
                not isinstance(key, str)
                for key in row.keys()
            )
        ]

        if invalid_key_rows:
            errors.append(
                f"{operation} execution returned a tabular result "
                "containing a non-string column name."
            )
