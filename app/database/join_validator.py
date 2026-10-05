from __future__ import annotations

from dataclasses import dataclass, field

from app.database.relationship_service import RelationshipDiscoveryService
from app.database.schema import DatabaseSchema
from app.query.schema import QueryPlan


@dataclass(frozen=True)
class JoinValidationResult:
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _table_key(schema: str, table: str) -> tuple[str, str]:
    return (schema.strip(), table.strip())


def _relationship_key(
    left_schema: str,
    left_table: str,
    left_column: str,
    right_schema: str,
    right_table: str,
    right_column: str,
) -> tuple[str, str, str, str, str, str]:
    return (
        left_schema,
        left_table,
        left_column,
        right_schema,
        right_table,
        right_column,
    )


def validate_query_plan_joins(
    plan: QueryPlan,
    database_schema: DatabaseSchema,
    relationship_service: Any | None = None,
) -> JoinValidationResult:
    """
    Validate JOINs against the database schema and the relationship
    intelligence layer.

    A JOIN is allowed only when:
    1. Both tables exist.
    2. Both columns exist on their declared tables.
    3. The JOIN graph is connected.
    4. The relationship is either a declared FK or a data-validated
       inferred relationship.

    This keeps the LLM responsible for proposing a relationship while
    deterministic application code decides whether that relationship
    is safe enough to execute.
    """
    if not plan.joins:
        return JoinValidationResult(valid=True)

    errors: list[str] = []
    warnings: list[str] = []

    selected_keys: set[tuple[str, str]] = set()

    for join in plan.joins:
        left_key = _table_key(join.left_schema, join.left_table)
        right_key = _table_key(join.right_schema, join.right_table)

        selected_keys.add(left_key)
        selected_keys.add(right_key)

        left_table = database_schema.get_table(*left_key)
        right_table = database_schema.get_table(*right_key)

        if left_table is None:
            errors.append(
                "JOIN references an unknown left table: "
                f"{join.left_schema}.{join.left_table}"
            )
            continue

        if right_table is None:
            errors.append(
                "JOIN references an unknown right table: "
                f"{join.right_schema}.{join.right_table}"
            )
            continue

        left_columns = {column.name for column in left_table.columns}
        right_columns = {column.name for column in right_table.columns}

        if join.left_column not in left_columns:
            errors.append(
                "JOIN references an unknown left column: "
                f"{join.left_schema}.{join.left_table}.{join.left_column}"
            )

        if join.right_column not in right_columns:
            errors.append(
                "JOIN references an unknown right column: "
                f"{join.right_schema}.{join.right_table}.{join.right_column}"
            )

        if join.join_type not in {"inner", "left", "right"}:
            errors.append(
                f"Unsupported JOIN type: {join.join_type}"
            )

    if errors:
        return JoinValidationResult(
            valid=False,
            errors=errors,
            warnings=warnings,
        )

    # ---------------------------------------------------------
    # The graph must be connected.
    # ---------------------------------------------------------

    graph: dict[tuple[str, str], set[tuple[str, str]]] = {
        key: set() for key in selected_keys
    }

    for join in plan.joins:
        left_key = _table_key(join.left_schema, join.left_table)
        right_key = _table_key(join.right_schema, join.right_table)
        graph[left_key].add(right_key)
        graph[right_key].add(left_key)

    root = next(iter(selected_keys))
    visited = {root}
    pending = [root]

    while pending:
        current = pending.pop()
        for neighbour in graph[current]:
            if neighbour not in visited:
                visited.add(neighbour)
                pending.append(neighbour)

    if visited != selected_keys:
        disconnected = sorted(selected_keys - visited)
        errors.append(
            "JOIN graph is disconnected. Every table in a multi-table "
            "query must be reachable from the same relationship graph: "
            + ", ".join(f"{s}.{t}" for s, t in disconnected)
        )

    # ---------------------------------------------------------
    # Resolve relationships using the Phase 5 canonical relationship layer.
    # ---------------------------------------------------------

    if relationship_service is None:
        relationship_service = RelationshipDiscoveryService(database_schema)

    relationships = relationship_service.discover(
        selected_tables=sorted(selected_keys),
    )

    allowed: set[tuple[str, str, str, str, str, str]] = set()

    for relationship in relationships:
        if relationship.status not in {"confirmed", "validated", "candidate_validated"}:
            continue

        key = _relationship_key(
            relationship.left_schema,
            relationship.left_table,
            relationship.left_column,
            relationship.right_schema,
            relationship.right_table,
            relationship.right_column,
        )
        reverse = (
            relationship.right_schema,
            relationship.right_table,
            relationship.right_column,
            relationship.left_schema,
            relationship.left_table,
            relationship.left_column,
        )

        allowed.add(key)
        allowed.add(reverse)

    for join in plan.joins:
        key = _relationship_key(
            join.left_schema,
            join.left_table,
            join.left_column,
            join.right_schema,
            join.right_table,
            join.right_column,
        )

        if key not in allowed:
            errors.append(
                "JOIN relationship is not validated by the database "
                "relationship intelligence layer: "
                f"{join.left_schema}.{join.left_table}.{join.left_column} "
                f"-> {join.right_schema}.{join.right_table}.{join.right_column}"
            )

    # ---------------------------------------------------------
    # Duplicate relationship protection.
    # ---------------------------------------------------------

    seen: set[tuple[str, str, str, str, str, str]] = set()

    for join in plan.joins:
        key = _relationship_key(
            join.left_schema,
            join.left_table,
            join.left_column,
            join.right_schema,
            join.right_table,
            join.right_column,
        )
        reverse = (
            key[3],
            key[4],
            key[5],
            key[0],
            key[1],
            key[2],
        )

        if key in seen or reverse in seen:
            errors.append(
                "The QueryPlan contains the same JOIN relationship more "
                "than once."
            )
        seen.add(key)

    # ---------------------------------------------------------
    # Conservative aggregation warning.
    # ---------------------------------------------------------

    if plan.aggregation and len(plan.joins) > 1:
        warnings.append(
            "Multiple JOINs with aggregation can multiply rows. "
            "The SQL executor must use relationship-aware aggregation "
            "before presenting numeric results."
        )

    # ---------------------------------------------------------
    # Ambiguous path detection across selected tables
    # ---------------------------------------------------------
    graph = None
    if relationship_service is not None:
        graph = (
            relationship_service.get_graph()
            if hasattr(relationship_service, "get_graph")
            else getattr(relationship_service, "graph", None)
        )
    if graph and hasattr(graph, "detect_ambiguous_paths"):
        sorted_keys = sorted(selected_keys)
        for i in range(len(sorted_keys)):
            for j in range(i + 1, len(sorted_keys)):
                ambiguous = graph.detect_ambiguous_paths(
                    sorted_keys[i],
                    sorted_keys[j],
                )
                if ambiguous:
                    warnings.append(
                        f"Multiple relationship paths exist between {sorted_keys[i][0]}.{sorted_keys[i][1]} "
                        f"and {sorted_keys[j][0]}.{sorted_keys[j][1]}; plan uses explicit join conditions."
                    )

    return JoinValidationResult(
        valid=not errors,
        errors=errors,
        warnings=warnings,
    )
