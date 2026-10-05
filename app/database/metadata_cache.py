from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.database.metadata_service import DatabaseMetadata
from app.database.schema import (
    ColumnInfo,
    DatabaseSchema,
    ForeignKeyInfo,
    TableInfo,
    UniqueConstraintInfo,
)


class MetadataCache:
    """Persistent JSON cache for validated database metadata snapshots."""

    CACHE_VERSION = 1

    def __init__(self, cache_dir: str | Path | None = None) -> None:
        base_dir = Path(cache_dir) if cache_dir is not None else (
            Path(__file__).resolve().parents[2] / "data" / "metadata_cache"
        )
        self.cache_dir = base_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _cache_path(self, server_name: str, database_name: str) -> Path:
        import hashlib

        norm_server = (server_name or "").strip().casefold()
        norm_db = (database_name or "").strip().casefold()
        key = f"{norm_server}|{norm_db}".encode("utf-8")
        digest = hashlib.sha256(key).hexdigest()[:24]
        return self.cache_dir / f"metadata_{digest}.json"

    def load(
        self,
        server_name: str,
        database_name: str,
        fingerprint: str,
    ) -> "DatabaseMetadata | None":
        path = self._cache_path(server_name, database_name)

        if not path.exists():
            return None

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return None

        if not isinstance(payload, dict):
            return None

        if payload.get("cache_version") != self.CACHE_VERSION:
            return None

        if payload.get("fingerprint") != fingerprint:
            return None

        if payload.get("server_name", "").casefold() != (server_name or "").casefold():
            return None

        if payload.get("database_name", "").casefold() != (database_name or "").casefold():
            return None

        try:
            return self._deserialize_metadata(
                payload["metadata"],
                server_name=server_name,
                database_name=database_name,
            )
        except (KeyError, TypeError, ValueError):
            return None

    def get_entry(
        self,
        server_name: str,
        database_name: str,
    ) -> dict[str, Any] | None:
        """Read and validate the cached metadata entry without requiring fingerprint beforehand."""
        path = self._cache_path(server_name, database_name)

        if not path.exists():
            return None

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return None

        if not isinstance(payload, dict):
            return None

        if payload.get("cache_version") != self.CACHE_VERSION:
            return None

        if payload.get("server_name", "").casefold() != (server_name or "").casefold():
            return None

        if payload.get("database_name", "").casefold() != (database_name or "").casefold():
            return None

        try:
            metadata = self._deserialize_metadata(
                payload["metadata"],
                server_name=server_name,
                database_name=database_name,
            )
            return {
                "metadata": metadata,
                "fingerprint": str(payload.get("fingerprint", "")),
                "verification_token": str(payload.get("verification_token", "")),
            }
        except (KeyError, TypeError, ValueError):
            return None

    def save(
        self,
        metadata: "DatabaseMetadata",
        fingerprint: str,
        verification_token: str = "",
    ) -> None:
        path = self._cache_path(
            metadata.server_name,
            metadata.database_name,
        )

        payload = {
            "cache_version": self.CACHE_VERSION,
            "fingerprint": fingerprint,
            "verification_token": verification_token,
            "server_name": metadata.server_name,
            "database_name": metadata.database_name,
            "metadata": self._serialize_metadata(metadata),
        }

        self._atomic_write(path, payload)

    def clear(
        self,
        server_name: str | None = None,
        database_name: str | None = None,
    ) -> None:
        """Clear cache file for specific server/database, or all metadata cache files."""
        if server_name is not None and database_name is not None:
            path = self._cache_path(server_name, database_name)
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        else:
            for p in self.cache_dir.glob("metadata_*.json"):
                try:
                    p.unlink(missing_ok=True)
                except OSError:
                    pass

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

    @staticmethod
    def _serialize_metadata(metadata: DatabaseMetadata) -> dict[str, Any]:
        schema = metadata.schema

        return {
            "schema": {
                "tables": [
                    {
                        "schema_name": table.schema_name,
                        "table_name": table.table_name,
                        "columns": [
                            asdict(column)
                            for column in table.columns
                        ],
                        "primary_key_columns": list(
                            table.primary_key_columns
                        ),
                    }
                    for table in schema.tables
                ],
                "foreign_keys": [
                    asdict(item)
                    for item in schema.foreign_keys
                ],
                "unique_constraints": [
                    asdict(item)
                    for item in schema.unique_constraints
                ],
            },
            "indexes": [
                asdict(item)
                for item in metadata.indexes
            ],
        }

    @staticmethod
    def _deserialize_metadata(
        payload: dict[str, Any],
        *,
        server_name: str,
        database_name: str,
    ) -> "DatabaseMetadata":
        from app.database.metadata_service import DatabaseMetadata, IndexMetadata

        schema_payload = payload["schema"]

        tables = []
        for table in schema_payload["tables"]:
            tables.append(
                TableInfo(
                    schema_name=table["schema_name"],
                    table_name=table["table_name"],
                    columns=[
                        ColumnInfo(**column)
                        for column in table["columns"]
                    ],
                    primary_key_columns=list(
                        table["primary_key_columns"]
                    ),
                )
            )

        schema = DatabaseSchema(
            tables=tables,
            foreign_keys=[
                ForeignKeyInfo(**item)
                for item in schema_payload["foreign_keys"]
            ],
            unique_constraints=[
                UniqueConstraintInfo(**item)
                for item in schema_payload["unique_constraints"]
            ],
        )

        indexes = tuple(
            IndexMetadata(
                schema_name=item["schema_name"],
                table_name=item["table_name"],
                index_name=item["index_name"],
                index_type=item["index_type"],
                is_unique=bool(item["is_unique"]),
                is_primary_key=bool(item["is_primary_key"]),
                columns=tuple(item.get("columns", [])),
            )
            for item in payload["indexes"]
        )

        return DatabaseMetadata(
            database_name=database_name,
            server_name=server_name,
            table_metadata=(),
            schema=schema,
            indexes=indexes,
        )
