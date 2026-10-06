from __future__ import annotations

from dataclasses import dataclass
import re

from app.database.schema import (
    ColumnInfo,
    DatabaseSchema,
    TableInfo,
)


@dataclass(frozen=True)
class RelationshipCandidate:
    left_schema: str
    left_table: str
    left_column: str
    right_schema: str
    right_table: str
    right_column: str
    reason: str
    confidence: float = 0.0
    evidence: tuple[str, ...] = ()


def _normalize_identifier(name: str) -> str:
    value = re.sub(
        r"([a-z0-9])([A-Z])",
        r"\1_\2",
        name,
    ).lower()

    value = re.sub(
        r"[^a-z0-9]+",
        "_",
        value,
    ).strip("_")

    for suffix in (
        "_id",
        "_key",
        "_code",
        "_number",
        "_no",
    ):
        if value.endswith(suffix):
            value = value[: -len(suffix)]
            break

    return value


def _is_identifier_column(
    column: ColumnInfo,
    table: TableInfo,
) -> bool:
    name = column.name.lower()

    return (
        column.name in table.primary_key_columns
        or name.endswith(
            (
                "_id",
                "_key",
                "_code",
                "_number",
                "_no",
            )
        )
        or name in {
            "id",
            "key",
            "code",
            "identifier",
        }
    )


def _compatible_types(
    left: ColumnInfo,
    right: ColumnInfo,
) -> bool:
    lt = left.data_type.lower()
    rt = right.data_type.lower()

    if lt == rt:
        return True

    groups = (
        {
            "int",
            "bigint",
            "smallint",
            "tinyint",
        },
        {
            "decimal",
            "numeric",
            "money",
            "smallmoney",
        },
        {
            "varchar",
            "nvarchar",
            "char",
            "nchar",
        },
        {
            "date",
            "datetime",
            "datetime2",
            "smalldatetime",
        },
        {
            "uuid",
            "uniqueidentifier",
        },
    )

    return any(
        lt in group and rt in group
        for group in groups
    )


def _column_score(
    left: ColumnInfo,
    left_table: TableInfo,
    right: ColumnInfo,
    right_table: TableInfo,
) -> tuple[float, list[str]]:
    evidence: list[str] = []
    score = 0.0

    if not _compatible_types(left, right):
        return 0.0, []

    left_identifier = _is_identifier_column(
        left,
        left_table,
    )
    right_identifier = _is_identifier_column(
        right,
        right_table,
    )

    norm_left = _normalize_identifier(left.name)
    norm_right = _normalize_identifier(right.name)

    if left.name.lower() == right.name.lower():
        score += 0.45
        evidence.append("same column name")

    elif norm_left == norm_right:
        score += 0.35
        evidence.append(
            "same normalized identifier"
        )

    else:
        left_tokens = set(norm_left.split("_")) - {""}
        right_tokens = set(norm_right.split("_")) - {""}
        common_tokens = {t for t in (left_tokens & right_tokens) if len(t) > 2}

        if (left_identifier or right_identifier) and common_tokens:
            score += 0.25
            evidence.append(
                f"shared identifier token(s): {', '.join(sorted(common_tokens))}"
            )
        elif left_identifier and right_identifier and (
            left.data_type.lower() in ("uuid", "uniqueidentifier")
            and right.data_type.lower() in ("uuid", "uniqueidentifier")
        ):
            score += 0.20
            evidence.append("compatible UUID identifier pair")
        else:
            return 0.0, []

    # Generic relationship evidence:
    # both columns independently look like identifiers.
    if left_identifier and right_identifier:
        score += 0.15
        evidence.append(
            "both columns are identifier columns"
        )

    if left.data_type.lower() in ("uuid", "uniqueidentifier") and right.data_type.lower() in ("uuid", "uniqueidentifier"):
        score += 0.10
        evidence.append("both columns are UUID type")

    if left.name in left_table.primary_key_columns:
        score += 0.20
        evidence.append(
            "left column is a primary key"
        )

    if right.name in right_table.primary_key_columns:
        score += 0.20
        evidence.append(
            "right column is a primary key"
        )

    if not left.nullable:
        score += 0.05
        evidence.append(
            "left column is non-nullable"
        )

    if not right.nullable:
        score += 0.05
        evidence.append(
            "right column is non-nullable"
        )

    return min(score, 1.0), evidence


def discover_relationships(
    database_schema: DatabaseSchema,
    selected_tables: list[tuple[str, str]],
    minimum_confidence: float = 0.45,
) -> list[RelationshipCandidate]:
    lookup = {
        (
            table.schema_name,
            table.table_name,
        ): table
        for table in database_schema.tables
    }

    relevant = [
        lookup[key]
        for key in selected_tables
        if key in lookup
    ]

    candidates: list[RelationshipCandidate] = []

    for index, left_table in enumerate(relevant):
        for right_table in relevant[index + 1:]:
            for left in left_table.columns:
                if not _is_identifier_column(
                    left,
                    left_table,
                ):
                    continue

                for right in right_table.columns:
                    if not _is_identifier_column(
                        right,
                        right_table,
                    ):
                        continue

                    score, evidence = _column_score(
                        left,
                        left_table,
                        right,
                        right_table,
                    )

                    if score < minimum_confidence:
                        continue

                    candidates.append(
                        RelationshipCandidate(
                            left_schema=left_table.schema_name,
                            left_table=left_table.table_name,
                            left_column=left.name,
                            right_schema=right_table.schema_name,
                            right_table=right_table.table_name,
                            right_column=right.name,
                            reason="; ".join(evidence),
                            confidence=round(
                                score,
                                3,
                            ),
                            evidence=tuple(evidence),
                        )
                    )

    return sorted(
        candidates,
        key=lambda candidate: (
            -candidate.confidence,
            candidate.left_table,
            candidate.right_table,
            candidate.left_column,
            candidate.right_column,
        ),
    )


def find_candidate_bridge_tables(
    database_schema: DatabaseSchema,
    left_key: tuple[str, str],
    right_key: tuple[str, str],
) -> list[TableInfo]:
    """
    Find candidate bridge/intermediate tables that could connect left_key and right_key.

    A table qualifies as a candidate bridge if and only if it possesses:
    - at least one identifier column matching or compatible with an identifier in left_table, AND
    - at least one identifier column matching or compatible with an identifier in right_table.

    This is strictly bounded, generic, and runs in sub-millisecond time.
    """
    left_table = database_schema.get_table(*left_key)
    right_table = database_schema.get_table(*right_key)

    if left_table is None or right_table is None:
        return []

    left_id_tokens = {
        _normalize_identifier(col.name)
        for col in left_table.columns
        if _is_identifier_column(col, left_table)
    }
    right_id_tokens = {
        _normalize_identifier(col.name)
        for col in right_table.columns
        if _is_identifier_column(col, right_table)
    }

    if not left_id_tokens or not right_id_tokens:
        return []

    excluded = {left_key, right_key}
    bridge_candidates: list[TableInfo] = []

    for table in database_schema.tables:
        t_key = (table.schema_name, table.table_name)
        if t_key in excluded:
            continue

        table_id_tokens = {
            _normalize_identifier(col.name)
            for col in table.columns
            if _is_identifier_column(col, table)
        }

        # Must have at least one identifier matching left AND one matching right
        left_words = {w for t in left_id_tokens for w in t.split("_") if len(w) > 2}
        right_words = {w for t in right_id_tokens for w in t.split("_") if len(w) > 2}
        table_words = {w for t in table_id_tokens for w in t.split("_") if len(w) > 2}

        has_left_match = bool((table_id_tokens & left_id_tokens) or (table_words & left_words))
        has_right_match = bool((table_id_tokens & right_id_tokens) or (table_words & right_words))

        if has_left_match and has_right_match:
            bridge_candidates.append(table)

    return bridge_candidates


def discover_bounded_candidates(
    database_schema: DatabaseSchema,
    selected_tables: list[tuple[str, str]],
    include_bridges: bool = True,
    minimum_confidence: float = 0.45,
) -> list[RelationshipCandidate]:
    """
    Bounded relationship candidate discovery.

    Prevents O(N^2) exhaustive pair comparisons for large table sets.
    - Small selected sets (<= 5 tables): direct pair comparisons plus bounded
      bridge candidate inspection for unconnected pairs.
    - Large table sets (> 5 tables): inverted identifier index to only evaluate
      table pairs that actually share identifier tokens.
    """
    lookup = {
        (table.schema_name, table.table_name): table
        for table in database_schema.tables
    }

    relevant = [
        lookup[key]
        for key in selected_tables
        if key in lookup
    ]

    if not relevant:
        return []

    candidates: list[RelationshipCandidate] = []
    evaluated_pairs: set[tuple[tuple[str, str], tuple[str, str]]] = set()

    def _eval_pair(left_table: TableInfo, right_table: TableInfo) -> None:
        l_key = (left_table.schema_name, left_table.table_name)
        r_key = (right_table.schema_name, right_table.table_name)
        pair_key = (min(l_key, r_key), max(l_key, r_key))
        if pair_key in evaluated_pairs:
            return
        evaluated_pairs.add(pair_key)

        for left in left_table.columns:
            if not _is_identifier_column(left, left_table):
                continue
            for right in right_table.columns:
                if not _is_identifier_column(right, right_table):
                    continue

                score, evidence = _column_score(
                    left, left_table, right, right_table
                )
                if score >= minimum_confidence:
                    candidates.append(
                        RelationshipCandidate(
                            left_schema=left_table.schema_name,
                            left_table=left_table.table_name,
                            left_column=left.name,
                            right_schema=right_table.schema_name,
                            right_table=right_table.table_name,
                            right_column=right.name,
                            reason="; ".join(evidence),
                            confidence=round(score, 3),
                            evidence=tuple(evidence),
                        )
                    )

    if len(relevant) <= 5:
        # Small set: evaluate all pairs in relevant
        for i, t1 in enumerate(relevant):
            for t2 in relevant[i + 1:]:
                _eval_pair(t1, t2)

        if include_bridges and len(relevant) >= 2:
            # Check for unconnected pairs that might have a bridge
            connected_pairs = {
                (
                    (c.left_schema, c.left_table),
                    (c.right_schema, c.right_table),
                )
                for c in candidates
            }
            connected_pairs.update({(r, l) for (l, r) in connected_pairs})

            for i, t1 in enumerate(relevant):
                for t2 in relevant[i + 1:]:
                    k1 = (t1.schema_name, t1.table_name)
                    k2 = (t2.schema_name, t2.table_name)
                    if (k1, k2) not in connected_pairs:
                        bridge_tables = find_candidate_bridge_tables(
                            database_schema, k1, k2
                        )
                        for bridge in bridge_tables:
                            _eval_pair(t1, bridge)
                            _eval_pair(bridge, t2)
    else:
        # Large set: use inverted identifier index
        id_to_tables: dict[str, list[TableInfo]] = {}
        for table in relevant:
            for col in table.columns:
                if _is_identifier_column(col, table):
                    token = _normalize_identifier(col.name)
                    id_to_tables.setdefault(token, []).append(table)

        for token, tables in id_to_tables.items():
            if len(tables) > 1:
                for i, t1 in enumerate(tables):
                    for t2 in tables[i + 1:]:
                        _eval_pair(t1, t2)

    return sorted(
        candidates,
        key=lambda candidate: (
            -candidate.confidence,
            candidate.left_table,
            candidate.right_table,
            candidate.left_column,
            candidate.right_column,
        ),
    )