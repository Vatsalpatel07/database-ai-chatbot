from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.query.schema import (
    QueryColumn,
    QueryFilter,
    QueryJoin,
    QueryPlan,
)


class SemanticQueryCache:
    """
    Persistent cache for validated QueryPlans.

    Phase 4 responsibilities:
      - canonicalize common natural-language query wording
      - key entries by database identity + schema fingerprint
      - persist validated QueryPlans, never final answers
      - tolerate missing/corrupt cache files
      - support safe invalidation through cache versioning

    The cache does not cache SQL results. Every cache hit still executes
    against the current SQL Server data.
    """

    CACHE_VERSION = 1

    def __init__(self, cache_dir: str | Path = "data/query_cache") -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def normalize_question(cls, question: str) -> str:
        """
        Create a deterministic, domain-independent canonical wording.

        This deliberately performs only conservative transformations.
        It does not attempt to infer entities, columns, relationships,
        filters, or aggregation semantics.
        """

        text = (question or "").strip().casefold()

        if not text:
            return ""

        # Normalize common count-question paraphrases.
        replacements = (
            (r"\bwhat\s+is\s+the\s+total\s+number\s+of\b", "count"),
            (r"\bwhat\s+is\s+the\s+number\s+of\b", "count"),
            (r"\bwhat\s+is\s+the\s+count\s+of\b", "count"),
            (r"\btotal\s+number\s+of\b", "count"),
            (r"\btotal\s+count\s+of\b", "count"),
            (r"\bnumber\s+of\b", "count"),
            (r"\bno\.?\s+of\b", "count"),
            (r"\bhow\s+many\b", "count"),
            (r"\bcount\s+of\b", "count"),
        )

        for pattern, replacement in replacements:
            text = re.sub(pattern, replacement, text)

        # Remove conversational filler only where it does not carry query
        # semantics.
        text = re.sub(
            r"\b(?:please|kindly|could\s+you|can\s+you|would\s+you)\b",
            " ",
            text,
        )

        # Command verbs do not change the meaning of a retrieval/count
        # request. Keep this conservative and only remove them at the start.
        text = re.sub(
            r"^(?:give|show|list|display|return|provide)\s+(?:me\s+)?",
            "",
            text,
        )

        # Normalize punctuation and whitespace.
        text = re.sub(r"[^\w\s]", " ", text)
        text = re.sub(r"\s+", " ", text).strip()

        # These phrases are usually grammatical wrappers around a count
        # request and do not alter the requested entity.
        text = re.sub(r"\b(?:are|is)\s+there\b", " ", text)
        text = re.sub(r"\bthere\s+(?:are|is)\b", " ", text)
        text = re.sub(r"\s+", " ", text).strip()

        return text

    @classmethod
    def build_key(
        cls,
        *,
        question: str,
        server_name: str,
        database_name: str,
        schema_fingerprint: str,
    ) -> str:
        normalized = cls.normalize_question(question)

        payload = {
            "cache_version": cls.CACHE_VERSION,
            "server_name": (server_name or "").strip().casefold(),
            "database_name": (database_name or "").strip().casefold(),
            "schema_fingerprint": (schema_fingerprint or "").strip(),
            "normalized_question": normalized,
        }

        serialized = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )

        return hashlib.sha256(
            serialized.encode("utf-8")
        ).hexdigest()

    def _path(self, key: str) -> Path:
        return self.cache_dir / f"{key}.json"

    def get(
        self,
        *,
        question: str,
        server_name: str,
        database_name: str,
        schema_fingerprint: str,
    ) -> QueryPlan | None:
        key = self.build_key(
            question=question,
            server_name=server_name,
            database_name=database_name,
            schema_fingerprint=schema_fingerprint,
        )

        path = self._path(key)

        if not path.exists():
            return None

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))

            if not isinstance(payload, dict):
                return None

            if payload.get("cache_version") != self.CACHE_VERSION:
                return None

            if payload.get("server_name", "").casefold() != (server_name or "").casefold():
                return None

            if payload.get("database_name", "").casefold() != (database_name or "").casefold():
                return None

            if payload.get("schema_fingerprint") != schema_fingerprint:
                return None

            plan_dict = payload.get("plan")
            if not isinstance(plan_dict, dict):
                return None

            return self._plan_from_dict(plan_dict)

        except (
            OSError,
            ValueError,
            TypeError,
            KeyError,
            json.JSONDecodeError,
        ):
            return None

    def set(
        self,
        *,
        question: str,
        server_name: str,
        database_name: str,
        schema_fingerprint: str,
        plan: QueryPlan,
    ) -> None:
        key = self.build_key(
            question=question,
            server_name=server_name,
            database_name=database_name,
            schema_fingerprint=schema_fingerprint,
        )

        payload = {
            "cache_version": self.CACHE_VERSION,
            "server_name": server_name,
            "database_name": database_name,
            "schema_fingerprint": schema_fingerprint,
            "normalized_question": self.normalize_question(question),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "plan": asdict(plan),
        }

        path = self._path(key)
        self._atomic_write(path, payload)

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
                json.dump(
                    payload,
                    handle,
                    ensure_ascii=False,
                    indent=2,
                    default=str,
                )
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, path)
        finally:
            try:
                if os.path.exists(temp_name):
                    os.remove(temp_name)
            except OSError:
                pass

    def delete(
        self,
        *,
        question: str,
        server_name: str,
        database_name: str,
        schema_fingerprint: str,
    ) -> None:
        key = self.build_key(
            question=question,
            server_name=server_name,
            database_name=database_name,
            schema_fingerprint=schema_fingerprint,
        )

        try:
            self._path(key).unlink(missing_ok=True)
        except OSError:
            pass

    def clear(self) -> None:
        """Clear all cached query plan files."""
        for p in self.cache_dir.glob("*.json"):
            try:
                p.unlink(missing_ok=True)
            except OSError:
                pass

    @staticmethod
    def _plan_from_dict(payload: dict[str, Any]) -> QueryPlan | None:
        if not isinstance(payload, dict):
            return None
        if "intent" not in payload:
            return None

        try:
            filters = [
                QueryFilter(**item)
                for item in payload.get("filters", [])
                if isinstance(item, dict)
            ]

            having_filters = [
                QueryFilter(**item)
                for item in payload.get("having_filters", [])
                if isinstance(item, dict)
            ]

            target_column_refs = [
                QueryColumn(**item)
                for item in payload.get("target_column_refs", [])
                if isinstance(item, dict)
            ]

            group_by_refs = [
                QueryColumn(**item)
                for item in payload.get("group_by_refs", [])
                if isinstance(item, dict)
            ]

            joins = [
                QueryJoin(**item)
                for item in payload.get("joins", [])
                if isinstance(item, dict)
            ]

            return QueryPlan(
                intent=str(payload["intent"]),
                target_columns=list(payload.get("target_columns", [])),
                filters=filters,
                having_filters=having_filters,
                group_by=list(payload.get("group_by", [])),
                aggregation=payload.get("aggregation"),
                sort_column=payload.get("sort_column"),
                sort_direction=payload.get("sort_direction"),
                limit=payload.get("limit"),
                include_ties=bool(payload.get("include_ties", False)),
                input_result_reference=payload.get("input_result_reference"),
                explanation=str(payload.get("explanation", "")),
                confidence=float(payload.get("confidence", 0.0)),
                joins=joins,
                target_column_refs=target_column_refs,
                group_by_refs=group_by_refs,
                group_by_granularity=payload.get("group_by_granularity"),
                require_all_filter_values=bool(
                    payload.get("require_all_filter_values", False)
                ),
            )
        except Exception:
            return None
