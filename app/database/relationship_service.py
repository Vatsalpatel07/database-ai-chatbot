from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.database.relationship_cache import RelationshipCache
from app.database.relationship_discovery import (
    RelationshipCandidate,
    discover_relationships,
    discover_bounded_candidates,
    find_candidate_bridge_tables,
)
from app.database.relationship_validator import (
    validate_relationship,
    RelationshipValidation,
)
from app.database.schema import DatabaseSchema


TableKey = tuple[str, str]


@dataclass(frozen=True)
class RelationshipResult:
    """
    Authoritative canonical relationship knowledge model.

    Distinguishes:
      - declared: derived from database FK metadata (status="confirmed")
      - inferred candidate: discovered but unvalidated (status="candidate")
      - validated inferred: empirically supported (status="validated")
      - rejected: candidate evaluated and not supported (status="rejected")
      - insufficient_data: cannot be evaluated reliably (status="insufficient_data")
    """

    relationship_type: str
    status: str
    left_schema: str
    left_table: str
    left_column: str
    right_schema: str
    right_table: str
    right_column: str
    reason: str
    confidence: float = 0.0
    matching_value_count: int | None = None
    left_distinct_count: int | None = None
    right_distinct_count: int | None = None

    @property
    def origin(self) -> str:
        return (
            "declared"
            if self.relationship_type == "declared_foreign_key"
            else "inferred"
        )


class RelationshipGraph:
    """
    Authoritative relationship graph combining declared foreign keys
    and validated inferred relationships.

    Supports:
      - direct relationships
      - inferred relationships
      - bridge/intermediate tables
      - shortest path discovery
      - multiple paths (ambiguity detection)
      - disconnected-table detection
    """

    def __init__(self) -> None:
        self._adjacency: dict[TableKey, dict[TableKey, list[RelationshipResult]]] = {}
        self._all_relationships: list[RelationshipResult] = []

    def add(self, rel: RelationshipResult) -> None:
        """
        Add a relationship to the graph. Only confirmed or validated
        relationships become traversable edges.
        """
        self._all_relationships.append(rel)

        if rel.status in {"confirmed", "validated", "candidate_validated"}:
            left = (rel.left_schema, rel.left_table)
            right = (rel.right_schema, rel.right_table)

            self._adjacency.setdefault(left, {}).setdefault(right, []).append(rel)
            self._adjacency.setdefault(right, {}).setdefault(left, []).append(rel)

    def get_neighbors(
        self,
        table: TableKey,
        accepted_only: bool = True,
    ) -> set[TableKey]:
        if table not in self._adjacency:
            return set()
        return set(self._adjacency[table].keys())

    def get_edges(
        self,
        table_a: TableKey,
        table_b: TableKey,
        accepted_only: bool = True,
    ) -> list[RelationshipResult]:
        edges = self._adjacency.get(table_a, {}).get(table_b, [])
        if accepted_only:
            return [
                e
                for e in edges
                if e.status in {"confirmed", "validated", "candidate_validated"}
            ]
        return edges

    def find_shortest_path(
        self,
        start: TableKey,
        target: TableKey,
        accepted_only: bool = True,
    ) -> list[TableKey] | None:
        """
        Breadth-first search for the shortest relationship path between two tables.
        """
        if start == target:
            return [start]

        if start not in self._adjacency or target not in self._adjacency:
            return None

        queue: deque[TableKey] = deque([start])
        previous: dict[TableKey, TableKey | None] = {start: None}

        while queue:
            current = queue.popleft()

            for neighbor in self._adjacency.get(current, {}):
                if neighbor in previous:
                    continue

                previous[neighbor] = current

                if neighbor == target:
                    path: list[TableKey] = []
                    node: TableKey | None = target
                    while node is not None:
                        path.append(node)
                        node = previous[node]
                    path.reverse()
                    return path

                queue.append(neighbor)

        return None

    def find_all_paths(
        self,
        start: TableKey,
        target: TableKey,
        max_depth: int = 3,
        accepted_only: bool = True,
    ) -> list[list[TableKey]]:
        """
        Find all simple relationship paths between start and target up to max_depth.
        Used to detect multiple/ambiguous paths.
        """
        if start == target:
            return [[start]]

        if start not in self._adjacency or target not in self._adjacency:
            return []

        all_paths: list[list[TableKey]] = []

        def _dfs(current: TableKey, current_path: list[TableKey], visited: set[TableKey]) -> None:
            if len(current_path) > max_depth + 1:
                return

            if current == target:
                all_paths.append(list(current_path))
                return

            for neighbor in self._adjacency.get(current, {}):
                if neighbor not in visited:
                    visited.add(neighbor)
                    current_path.append(neighbor)
                    _dfs(neighbor, current_path, visited)
                    current_path.pop()
                    visited.remove(neighbor)

        _dfs(start, [start], {start})
        return all_paths

    def is_connected(
        self,
        tables: set[TableKey] | list[TableKey],
        accepted_only: bool = True,
    ) -> bool:
        """
        Check if all supplied tables belong to the same connected component.
        """
        table_set = set(tables)
        if len(table_set) <= 1:
            return True

        # Check if every table is known to the graph
        for t in table_set:
            if t not in self._adjacency:
                return False

        root = next(iter(table_set))
        visited: set[TableKey] = {root}
        queue = deque([root])

        while queue:
            curr = queue.popleft()
            for neighbor in self._adjacency.get(curr, {}):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(neighbor)

        return table_set.issubset(visited)

    def get_bridge_tables(
        self,
        start: TableKey,
        target: TableKey,
    ) -> list[TableKey]:
        """
        Return intermediate tables on paths of length 2 connecting start and target.
        (start -> bridge -> target)
        """
        start_neighbors = self.get_neighbors(start)
        target_neighbors = self.get_neighbors(target)
        bridges = start_neighbors & target_neighbors
        return sorted(bridges)

    def detect_ambiguous_paths(
        self,
        start: TableKey,
        target: TableKey,
        max_depth: int = 3,
        accepted_only: bool = True,
    ) -> list[list[TableKey]]:
        """
        Return all simple paths if multiple distinct paths exist between start and target.
        Returns empty list if 0 or 1 path exists.
        """
        paths = self.find_all_paths(
            start=start,
            target=target,
            max_depth=max_depth,
            accepted_only=accepted_only,
        )
        if len(paths) > 1:
            return paths
        return []

    @property
    def relationships(self) -> list[RelationshipResult]:
        return list(self._all_relationships)


class RelationshipDiscoveryService:
    """
    Consolidated relationship lifecycle service.

    Responsibilities:
      1. Load declared foreign keys from DatabaseSchema.
      2. Bounded candidate discovery (avoiding O(N^2) exhaustive pair comparisons).
      3. Empirical validation against SQL Server when required, backed by persistent
         and in-memory caching.
      4. Canonical relationship graph construction and query-time path reasoning.
    """

    def __init__(
        self,
        database_schema: DatabaseSchema,
        cache_dir: str | Path | None = None,
        server_name: str | None = None,
        database_name: str | None = None,
        schema_fingerprint: str | None = None,
        cache: RelationshipCache | None = None,
    ) -> None:
        self.database_schema = database_schema
        self.server_name = server_name or "default"
        self.database_name = database_name or "default"
        self.schema_fingerprint = schema_fingerprint or ""

        self.cache = cache or RelationshipCache(
            cache_dir=cache_dir,
            server_name=self.server_name,
            database_name=self.database_name,
            schema_fingerprint=self.schema_fingerprint,
        )

        self.graph = RelationshipGraph()
        self._load_declared_relationships()
        self._load_cached_relationships()

    def _load_declared_relationships(self) -> None:
        for fk in self.database_schema.foreign_keys:
            rel = RelationshipResult(
                relationship_type="declared_foreign_key",
                status="confirmed",
                left_schema=fk.schema_name,
                left_table=fk.table_name,
                left_column=fk.column_name,
                right_schema=fk.referenced_schema_name,
                right_table=fk.referenced_table_name,
                right_column=fk.referenced_column_name,
                reason="Relationship is declared by a database foreign key.",
                confidence=1.0,
            )
            self.graph.add(rel)

    def _load_cached_relationships(self) -> None:
        for rel in self.cache.all_relationships():
            self.graph.add(rel)

    def discover(
        self,
        selected_tables: list[tuple[str, str]],
        include_bridges: bool = True,
    ) -> list[RelationshipResult]:
        """
        Discover and validate relationships relevant to selected_tables.
        Returns all confirmed and validated relationships connecting the tables.
        """
        selected_set = set(selected_tables)
        results: list[RelationshipResult] = []
        confirmed_pairs: set[tuple[str, str, str, str, str, str]] = set()

        # 1. Declared foreign keys among selected tables
        for fk in self.database_schema.foreign_keys:
            left_key = (fk.schema_name, fk.table_name)
            right_key = (fk.referenced_schema_name, fk.referenced_table_name)
            if left_key not in selected_set or right_key not in selected_set:
                continue

            pair = (
                fk.schema_name,
                fk.table_name,
                fk.column_name,
                fk.referenced_schema_name,
                fk.referenced_table_name,
                fk.referenced_column_name,
            )
            confirmed_pairs.add(pair)
            rel = RelationshipResult(
                relationship_type="declared_foreign_key",
                status="confirmed",
                left_schema=fk.schema_name,
                left_table=fk.table_name,
                left_column=fk.column_name,
                right_schema=fk.referenced_schema_name,
                right_table=fk.referenced_table_name,
                right_column=fk.referenced_column_name,
                reason="Relationship is declared by a database foreign key.",
                confidence=1.0,
            )
            results.append(rel)

        # 2. Bounded candidate discovery
        candidates = discover_bounded_candidates(
            self.database_schema,
            selected_tables,
            include_bridges=include_bridges,
        )

        for candidate in candidates:
            key = (
                candidate.left_schema,
                candidate.left_table,
                candidate.left_column,
                candidate.right_schema,
                candidate.right_table,
                candidate.right_column,
            )
            reverse = (
                candidate.right_schema,
                candidate.right_table,
                candidate.right_column,
                candidate.left_schema,
                candidate.left_table,
                candidate.left_column,
            )

            if key in confirmed_pairs or reverse in confirmed_pairs:
                continue

            # 3. Check cache first
            cached_rel = self.cache.get(
                candidate.left_schema,
                candidate.left_table,
                candidate.left_column,
                candidate.right_schema,
                candidate.right_table,
                candidate.right_column,
            )

            if cached_rel is not None:
                rel = cached_rel
            else:
                # 4. Empirical validation
                try:
                    validation: RelationshipValidation = validate_relationship(
                        candidate
                    )
                    status = validation.status
                    reason = f"{candidate.reason}; {validation.reason}"
                    match_count = validation.matching_value_count
                    left_distinct = validation.left_distinct_count
                    right_distinct = validation.right_distinct_count
                except Exception as exc:
                    status = "insufficient_data"
                    reason = f"Validation could not execute: {exc}"
                    match_count = None
                    left_distinct = None
                    right_distinct = None

                rel = RelationshipResult(
                    relationship_type="inferred",
                    status=status,
                    left_schema=candidate.left_schema,
                    left_table=candidate.left_table,
                    left_column=candidate.left_column,
                    right_schema=candidate.right_schema,
                    right_table=candidate.right_table,
                    right_column=candidate.right_column,
                    reason=reason,
                    confidence=candidate.confidence if status in {"validated", "candidate_validated"} else 0.0,
                    matching_value_count=match_count,
                    left_distinct_count=left_distinct,
                    right_distinct_count=right_distinct,
                )
                self.cache.set(rel)

            if rel.status in {"validated", "candidate_validated"}:
                self.graph.add(rel)
                results.append(rel)

        # Persist any new validations
        self.cache.save()

        return sorted(
            results,
            key=lambda r: (-r.confidence, r.relationship_type, r.left_table, r.right_table),
        )

    def get_graph(self) -> RelationshipGraph:
        """Expose the authoritative canonical relationship graph."""
        return self.graph

    def find_path(
        self,
        start: TableKey,
        target: TableKey,
    ) -> list[TableKey] | None:
        """Find the shortest relationship path between two tables."""
        return self.graph.find_shortest_path(start, target)

    def find_all_paths(
        self,
        start: TableKey,
        target: TableKey,
        max_depth: int = 3,
    ) -> list[list[TableKey]]:
        """Find all simple relationship paths between two tables."""
        return self.graph.find_all_paths(start, target, max_depth=max_depth)

    def is_connected(
        self,
        tables: set[TableKey] | list[TableKey],
    ) -> bool:
        """Check if all supplied tables belong to the same connected component."""
        return self.graph.is_connected(tables)

    def get_bridge_tables(
        self,
        start: TableKey,
        target: TableKey,
    ) -> list[TableKey]:
        """Return bridge tables connecting start and target."""
        return self.graph.get_bridge_tables(start, target)

    def detect_ambiguous_paths(
        self,
        start: TableKey,
        target: TableKey,
        max_depth: int = 3,
    ) -> list[list[TableKey]]:
        """Return all simple paths if multiple distinct paths exist between start and target."""
        return self.graph.detect_ambiguous_paths(start, target, max_depth=max_depth)


# Canonical alias
RelationshipService = RelationshipDiscoveryService
