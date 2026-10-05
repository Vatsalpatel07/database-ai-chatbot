from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from app.database.relationship_service import RelationshipResult


def _canonical_key(
    left_schema: str,
    left_table: str,
    left_column: str,
    right_schema: str,
    right_table: str,
    right_column: str,
) -> tuple[str, str, str, str, str, str]:
    """
    Produce a canonical ordered key for an undirected relationship candidate
    so that (A, B) and (B, A) map to the exact same cache entry.
    """
    left = (left_schema.casefold(), left_table.casefold(), left_column.casefold())
    right = (right_schema.casefold(), right_table.casefold(), right_column.casefold())
    if left <= right:
        return (*left, *right)
    return (*right, *left)


class RelationshipCache:
    """
    Persistent JSON cache for empirically validated relationships.

    Phase 5 responsibilities:
      - Key entries by server identity + database name + schema fingerprint.
      - Persist validated, rejected, and insufficient-data candidate evaluations.
      - Invalidate when the schema fingerprint changes.
      - Maintain an in-memory lookup table for zero-latency lookups during queries.
    """

    CACHE_VERSION = 1

    def __init__(
        self,
        cache_dir: str | Path | None = None,
        server_name: str | None = None,
        database_name: str | None = None,
        schema_fingerprint: str | None = None,
    ) -> None:
        base_dir = (
            Path(cache_dir)
            if cache_dir is not None
            else Path(__file__).resolve().parents[2] / "data" / "relationship_cache"
        )
        self.cache_dir = base_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.server_name = server_name or "default"
        self.database_name = database_name or "default"
        self.schema_fingerprint = schema_fingerprint or ""

        # In-memory lookup: canonical_key -> RelationshipResult
        self._entries: dict[tuple[str, str, str, str, str, str], Any] = {}
        self._dirty = False

        if self.schema_fingerprint:
            self.load()

    def _cache_path(self) -> Path:
        norm_server = (self.server_name or "default").strip().casefold()
        norm_db = (self.database_name or "default").strip().casefold()
        raw_key = f"{norm_server}|{norm_db}|{self.schema_fingerprint}".encode("utf-8")
        digest = hashlib.sha256(raw_key).hexdigest()[:24]
        return self.cache_dir / f"rel_{digest}.json"

    def clear(self) -> None:
        """Clear in-memory evaluations and delete cache file from disk."""
        self._entries.clear()
        self._dirty = False
        path = self._cache_path()
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass

    def load(self) -> bool:
        """
        Load cached relationship evaluations matching the current schema fingerprint.
        Returns True if loaded from disk, False otherwise.
        """
        from app.database.relationship_service import RelationshipResult

        if not self.schema_fingerprint:
            return False

        path = self._cache_path()
        if not path.exists():
            return False

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return False

        if not isinstance(payload, dict):
            return False

        if payload.get("cache_version") != self.CACHE_VERSION:
            return False
        if payload.get("schema_fingerprint") != self.schema_fingerprint:
            return False
        if payload.get("server_name", "").casefold() != (self.server_name or "").casefold():
            return False
        if payload.get("database_name", "").casefold() != (self.database_name or "").casefold():
            return False

        raw_relationships = payload.get("relationships", [])
        for item in raw_relationships:
            try:
                rel = RelationshipResult(
                    relationship_type=item["relationship_type"],
                    status=item["status"],
                    left_schema=item["left_schema"],
                    left_table=item["left_table"],
                    left_column=item["left_column"],
                    right_schema=item["right_schema"],
                    right_table=item["right_table"],
                    right_column=item["right_column"],
                    reason=item.get("reason", ""),
                    confidence=float(item.get("confidence", 0.0)),
                    matching_value_count=item.get("matching_value_count"),
                    left_distinct_count=item.get("left_distinct_count"),
                    right_distinct_count=item.get("right_distinct_count"),
                )
                key = _canonical_key(
                    rel.left_schema,
                    rel.left_table,
                    rel.left_column,
                    rel.right_schema,
                    rel.right_table,
                    rel.right_column,
                )
                self._entries[key] = rel
            except (KeyError, TypeError, ValueError):
                continue

        self._dirty = False
        return True

    def get(
        self,
        left_schema: str,
        left_table: str,
        left_column: str,
        right_schema: str,
        right_table: str,
        right_column: str,
    ) -> Any | None:
        """
        Look up a relationship evaluation from the in-memory cache.
        """
        key = _canonical_key(
            left_schema,
            left_table,
            left_column,
            right_schema,
            right_table,
            right_column,
        )
        return self._entries.get(key)

    def set(self, relationship: Any) -> None:
        """
        Store a relationship evaluation in memory and mark cache as dirty.
        """
        key = _canonical_key(
            relationship.left_schema,
            relationship.left_table,
            relationship.left_column,
            relationship.right_schema,
            relationship.right_table,
            relationship.right_column,
        )
        self._entries[key] = relationship
        self._dirty = True

    def save(self) -> None:
        """
        Persist in-memory relationship evaluations to disk atomically.
        """
        if not self._dirty or not self.schema_fingerprint:
            return

        path = self._cache_path()
        payload = {
            "cache_version": self.CACHE_VERSION,
            "server_name": self.server_name,
            "database_name": self.database_name,
            "schema_fingerprint": self.schema_fingerprint,
            "relationships": [
                {
                    "relationship_type": rel.relationship_type,
                    "status": rel.status,
                    "left_schema": rel.left_schema,
                    "left_table": rel.left_table,
                    "left_column": rel.left_column,
                    "right_schema": rel.right_schema,
                    "right_table": rel.right_table,
                    "right_column": rel.right_column,
                    "reason": rel.reason,
                    "confidence": rel.confidence,
                    "matching_value_count": rel.matching_value_count,
                    "left_distinct_count": rel.left_distinct_count,
                    "right_distinct_count": rel.right_distinct_count,
                }
                for rel in self._entries.values()
            ],
        }

        self._atomic_write(path, payload)
        self._dirty = False

    @staticmethod
    def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            text=True,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, path)
        finally:
            try:
                if os.path.exists(temp_name):
                    os.remove(temp_name)
            except OSError:
                pass

    def all_relationships(self) -> list[Any]:
        return list(self._entries.values())
