from __future__ import annotations

import hashlib
import json
from typing import Any

from app.database.schema import DatabaseSchema


class SchemaFingerprint:
    """Create a deterministic fingerprint for database structure.

    The fingerprint represents schema structure only. Row counts and other
    changing data statistics are intentionally excluded so normal data changes
    do not invalidate the structural metadata cache.
    """

    ALGORITHM = "sha256"
    VERSION = 1

    @classmethod
    def build(
        cls,
        schema: DatabaseSchema,
        indexes: list[Any] | tuple[Any, ...] = (),
        database_name: str = "",
        server_name: str = "",
    ) -> str:
        payload = {
            "version": cls.VERSION,
            "database_name": (database_name or "").strip().casefold(),
            "server_name": (server_name or "").strip().casefold(),
            "tables": [
                {
                    "schema": table.schema_name,
                    "table": table.table_name,
                    "columns": [
                        {
                            "name": column.name,
                            "data_type": column.data_type,
                            "nullable": column.nullable,
                            "ordinal_position": column.ordinal_position,
                        }
                        for column in sorted(
                            table.columns,
                            key=lambda item: (item.ordinal_position, item.name.casefold()),
                        )
                    ],
                    "primary_key_columns": sorted(
                        list(table.primary_key_columns)
                    ),
                }
                for table in sorted(
                    schema.tables,
                    key=lambda item: (
                        item.schema_name.casefold(),
                        item.table_name.casefold(),
                    ),
                )
            ],
            "foreign_keys": [
                {
                    "constraint_name": item.constraint_name,
                    "schema": item.schema_name,
                    "table": item.table_name,
                    "column": item.column_name,
                    "referenced_schema": item.referenced_schema_name,
                    "referenced_table": item.referenced_table_name,
                    "referenced_column": item.referenced_column_name,
                }
                for item in sorted(
                    schema.foreign_keys,
                    key=lambda value: (
                        value.schema_name.casefold(),
                        value.table_name.casefold(),
                        value.constraint_name.casefold(),
                        value.column_name.casefold(),
                        value.referenced_schema_name.casefold(),
                        value.referenced_table_name.casefold(),
                        value.referenced_column_name.casefold(),
                    ),
                )
            ],
            "unique_constraints": [
                {
                    "constraint_name": item.constraint_name,
                    "schema": item.schema_name,
                    "table": item.table_name,
                    "column": item.column_name,
                }
                for item in sorted(
                    schema.unique_constraints,
                    key=lambda value: (
                        value.schema_name.casefold(),
                        value.table_name.casefold(),
                        value.constraint_name.casefold(),
                        value.column_name.casefold(),
                    ),
                )
            ],
            "indexes": [
                {
                    "schema": item.schema_name,
                    "table": item.table_name,
                    "index_name": item.index_name,
                    "index_type": item.index_type,
                    "is_unique": item.is_unique,
                    "is_primary_key": item.is_primary_key,
                    "columns": list(item.columns),
                }
                for item in sorted(
                    indexes,
                    key=lambda value: (
                        value.schema_name.casefold(),
                        value.table_name.casefold(),
                        value.index_name.casefold(),
                    ),
                )
            ],
        }

        canonical = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")

        return hashlib.sha256(canonical).hexdigest()
