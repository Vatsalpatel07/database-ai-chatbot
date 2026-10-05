from __future__ import annotations

from dataclasses import dataclass

from app.database.connection import get_connection
from app.database.relationship_discovery import RelationshipCandidate


@dataclass(frozen=True)
class RelationshipValidation:
    candidate: RelationshipCandidate
    left_row_count: int | None
    right_row_count: int | None
    left_distinct_count: int | None
    right_distinct_count: int | None
    matching_value_count: int | None
    status: str
    reason: str


def _quote(identifier: str, is_postgresql: bool = False) -> str:
    if is_postgresql:
        return '"' + identifier.replace('"', '""') + '"'
    return "[" + identifier.replace("]", "]]") + "]"


def validate_relationship(
    candidate: RelationshipCandidate,
    config: Any | None = None,
) -> RelationshipValidation:
    from app.core.config import DatabaseConfig
    is_postgresql = config.is_postgresql if config else DatabaseConfig.from_env().is_postgresql

    left_table = (
        f"{_quote(candidate.left_schema, is_postgresql)}."
        f"{_quote(candidate.left_table, is_postgresql)}"
    )

    right_table = (
        f"{_quote(candidate.right_schema, is_postgresql)}."
        f"{_quote(candidate.right_table, is_postgresql)}"
    )

    left_col = _quote(candidate.left_column, is_postgresql)
    right_col = _quote(candidate.right_column, is_postgresql)

    connection = get_connection(config)

    try:
        cursor = connection.cursor()

        cursor.execute(
            f"SELECT COUNT(*) FROM {left_table}"
        )
        left_rows = int(cursor.fetchone()[0])

        cursor.execute(
            f"SELECT COUNT(*) FROM {right_table}"
        )
        right_rows = int(cursor.fetchone()[0])

        cursor.execute(
            f"""
            SELECT COUNT(DISTINCT {left_col})
            FROM {left_table}
            WHERE {left_col} IS NOT NULL
            """
        )
        left_distinct = int(cursor.fetchone()[0])

        cursor.execute(
            f"""
            SELECT COUNT(DISTINCT {right_col})
            FROM {right_table}
            WHERE {right_col} IS NOT NULL
            """
        )
        right_distinct = int(cursor.fetchone()[0])

        cursor.execute(
            f"""
            SELECT COUNT(*)
            FROM (
                SELECT DISTINCT
                    {left_col} AS value
                FROM {left_table}
                WHERE {left_col} IS NOT NULL
            ) l
            INNER JOIN (
                SELECT DISTINCT
                    {right_col} AS value
                FROM {right_table}
                WHERE {right_col} IS NOT NULL
            ) r
                ON l.value = r.value
            """
        )

        matches = int(cursor.fetchone()[0])

        if left_rows == 0 or right_rows == 0:
            return RelationshipValidation(
                candidate,
                left_rows,
                right_rows,
                left_distinct,
                right_distinct,
                matches,
                "insufficient_data",
                "One or both tables contain no rows.",
            )

        if matches == 0:
            return RelationshipValidation(
                candidate,
                left_rows,
                right_rows,
                left_distinct,
                right_distinct,
                matches,
                "rejected",
                "No matching non-null values were found.",
            )

        smaller_distinct = max(
            1,
            min(
                left_distinct,
                right_distinct,
            ),
        )

        # An inferred relationship must have at least two distinct
        # overlapping values unless one table has only 1 distinct row.
        # A single overlap on larger tables is too weak because
        # low-cardinality columns can produce accidental matches.
        if matches < 2 and smaller_distinct > 1:
            return RelationshipValidation(
                candidate,
                left_rows,
                right_rows,
                left_distinct,
                right_distinct,
                matches,
                "rejected",
                "Fewer than two distinct matching values were found; "
                "relationship evidence is too weak.",
            )

        overlap_ratio = (
            matches / smaller_distinct
        )

        return RelationshipValidation(
            candidate,
            left_rows,
            right_rows,
            left_distinct,
            right_distinct,
            matches,
            "validated",
            (
                f"{matches} distinct values overlap "
                f"({overlap_ratio:.1%} of the smaller "
                f"distinct-value set)."
            ),
        )

    finally:
        connection.close()