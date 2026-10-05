from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.config import DatabaseConfig, get_database_config
from app.database.connection import get_connection, test_connection
from app.database.metadata_cache import MetadataCache
from app.database.schema import DatabaseSchema, get_database_schema
from app.database.schema_fingerprint import SchemaFingerprint


@dataclass(frozen=True)
class IndexMetadata:
    """Metadata for one SQL Server index."""

    schema_name: str
    table_name: str
    index_name: str
    index_type: str
    is_unique: bool
    is_primary_key: bool
    columns: tuple[str, ...] = ()


@dataclass(frozen=True)
class TableMetadata:
    """Runtime metadata associated with one database table."""

    schema_name: str
    table_name: str
    row_count: int


@dataclass(frozen=True)
class DatabaseMetadata:
    """Complete metadata snapshot used by application services."""

    database_name: str
    server_name: str
    schema: DatabaseSchema
    indexes: tuple[IndexMetadata, ...] = ()
    table_metadata: tuple[TableMetadata, ...] = ()
    schema_fingerprint: str = ""
    cache_hit: bool = False

    @property
    def tables(self):
        return self.schema.tables

    @property
    def foreign_keys(self):
        return self.schema.foreign_keys

    @property
    def unique_constraints(self):
        return self.schema.unique_constraints

    def get_table(self, schema_name: str, table_name: str):
        return self.schema.get_table(schema_name, table_name)

    def get_table_row_count(
        self,
        schema_name: str,
        table_name: str,
    ) -> int | None:
        key = (schema_name, table_name)
        for item in self.table_metadata:
            if (item.schema_name, item.table_name) == key:
                return item.row_count
        return None


class DatabaseMetadataService:
    """Load database metadata with structural fingerprint-based caching.

    Phase 3 responsibilities:
      - create a deterministic schema fingerprint
      - reuse cached structural metadata when the fingerprint matches
      - refresh live row counts on every load
      - persist metadata atomically
      - expose whether the current load was a cache hit

    The semantic query cache is deliberately not implemented here. That is
    the responsibility of official Phase 4.
    """

    def __init__(
        self,
        cache: MetadataCache | None = None,
        config: DatabaseConfig | None = None,
    ) -> None:
        self.cache = cache or MetadataCache()
        self.config = config

    def _get_verification_token(self, config: DatabaseConfig | None = None) -> str | None:
        """Fast sub-millisecond verification of schema integrity."""
        cfg = config or self.config or get_database_config()
        try:
            connection = get_connection(cfg)
            try:
                cursor = connection.cursor()
                if cfg.is_postgresql:
                    cursor.execute(
                        """
                        SELECT
                            (SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = %s) AS tbl_cnt,
                            (SELECT COUNT(*) FROM information_schema.columns WHERE table_schema = %s) AS col_cnt,
                            (SELECT COUNT(*) FROM pg_index i JOIN pg_class c ON c.oid = i.indrelid JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = %s) AS idx_cnt;
                        """,
                        (cfg.schema, cfg.schema, cfg.schema),
                    )
                else:
                    cursor.execute(
                        """
                        SELECT
                            (SELECT COUNT(*) FROM sys.tables) AS tbl_cnt,
                            (SELECT COUNT(*) FROM sys.columns) AS col_cnt,
                            (SELECT CHECKSUM_AGG(CHECKSUM(object_id, column_id, system_type_id, max_length, precision, scale, is_nullable)) FROM sys.columns) AS col_chk,
                            (SELECT COUNT(*) FROM sys.indexes) AS idx_cnt,
                            (SELECT CHECKSUM_AGG(CHECKSUM(object_id, index_id, name, type, is_unique, is_primary_key)) FROM sys.indexes) AS idx_chk,
                            (SELECT MAX(modify_date) FROM sys.objects WHERE type IN ('U', 'PK', 'F', 'UQ')) AS max_modify;
                        """
                    )
                row = cursor.fetchone()
                if row is None:
                    return None
                return ":".join(str(item) for item in row)
            finally:
                connection.close()
        except Exception:
            return None

    def load(self, force_refresh: bool = False, config: DatabaseConfig | None = None) -> DatabaseMetadata:
        cfg = config or self.config or get_database_config()
        connection_info = test_connection(cfg)
        database_name = connection_info["database_name"]
        server_name = connection_info["server_name"]

        # Fast path: check verification token without querying INFORMATION_SCHEMA
        if not force_refresh:
            cached_entry = self.cache.get_entry(
                server_name=server_name,
                database_name=database_name,
            )
            if cached_entry is not None:
                cached_token = cached_entry.get("verification_token", "")
                if cached_token:
                    live_token = self._get_verification_token(cfg)
                    if live_token is not None and live_token == cached_token:
                        cached_meta: DatabaseMetadata = cached_entry["metadata"]
                        table_metadata = self._load_table_metadata(cfg)
                        return DatabaseMetadata(
                            database_name=database_name,
                            server_name=server_name,
                            schema=cached_meta.schema,
                            indexes=cached_meta.indexes,
                            table_metadata=tuple(table_metadata),
                            schema_fingerprint=cached_entry["fingerprint"],
                            cache_hit=True,
                        )

        # Slow path: schema discovery needed (first run, token mismatch, or forced refresh)
        schema = get_database_schema(cfg)
        if not schema.tables:
            raise ValueError("Database contains no tables.")

        indexes = self._load_indexes(cfg)
        fingerprint = SchemaFingerprint.build(
            schema=schema,
            indexes=indexes,
            database_name=database_name,
            server_name=server_name,
        )

        verification_token = self._get_verification_token(cfg) or ""

        cached = None
        if not force_refresh:
            cached = self.cache.load(
                server_name=server_name,
                database_name=database_name,
                fingerprint=fingerprint,
            )

        if cached is not None:
            structural_schema = cached.schema
            structural_indexes = cached.indexes
            cache_hit = True
        else:
            structural_schema = schema
            structural_indexes = tuple(indexes)
            cache_hit = False

            structural_metadata = DatabaseMetadata(
                database_name=database_name,
                server_name=server_name,
                schema=structural_schema,
                indexes=structural_indexes,
                table_metadata=(),
                schema_fingerprint=fingerprint,
                cache_hit=False,
            )
            self.cache.save(
                metadata=structural_metadata,
                fingerprint=fingerprint,
                verification_token=verification_token,
            )

        # Row counts are deliberately live. They describe current data and
        # therefore must never come from the structural schema cache.
        table_metadata = self._load_table_metadata(cfg)

        return DatabaseMetadata(
            database_name=database_name,
            server_name=server_name,
            schema=structural_schema,
            indexes=structural_indexes,
            table_metadata=tuple(table_metadata),
            schema_fingerprint=fingerprint,
            cache_hit=cache_hit,
        )

    def _load_indexes(self, config: DatabaseConfig | None = None) -> list[IndexMetadata]:
        cfg = config or get_database_config()
        connection = get_connection(cfg)
        try:
            cursor = connection.cursor()
            if cfg.is_postgresql:
                cursor.execute(
                    """
                    SELECT
                        n.nspname AS schema_name,
                        t.relname AS table_name,
                        i.relname AS index_name,
                        am.amname AS index_type,
                        ix.indisunique AS is_unique,
                        ix.indisprimary AS is_primary_key,
                        a.attname AS column_name,
                        pos.n AS key_ordinal
                    FROM pg_class t
                    JOIN pg_index ix ON t.oid = ix.indrelid
                    JOIN pg_class i ON i.oid = ix.indexrelid
                    JOIN pg_namespace n ON n.oid = t.relnamespace
                    JOIN pg_am am ON i.relam = am.oid
                    CROSS JOIN LATERAL unnest(ix.indkey) WITH ORDINALITY AS pos(attnum, n)
                    JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = pos.attnum
                    WHERE n.nspname = %s
                    ORDER BY n.nspname, t.relname, i.relname, pos.n;
                    """,
                    (cfg.schema,),
                )
            else:
                cursor.execute(
                    """
                    SELECT
                        s.name AS schema_name,
                        t.name AS table_name,
                        i.name AS index_name,
                        i.type_desc AS index_type,
                        i.is_unique,
                        i.is_primary_key,
                        c.name AS column_name,
                        ic.key_ordinal,
                        ic.index_column_id
                    FROM sys.tables AS t
                    INNER JOIN sys.schemas AS s
                        ON s.schema_id = t.schema_id
                    INNER JOIN sys.indexes AS i
                        ON i.object_id = t.object_id
                    INNER JOIN sys.index_columns AS ic
                        ON ic.object_id = i.object_id
                        AND ic.index_id = i.index_id
                    INNER JOIN sys.columns AS c
                        ON c.object_id = ic.object_id
                        AND c.column_id = ic.column_id
                    WHERE i.index_id > 0
                        AND i.is_hypothetical = 0
                    ORDER BY
                        s.name,
                        t.name,
                        i.index_id,
                        ic.key_ordinal,
                        ic.index_column_id
                    """
                )

            grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
            for row in cursor.fetchall():
                schema_name = getattr(row, "schema_name", None) if hasattr(row, "schema_name") else row[0]
                table_name = getattr(row, "table_name", None) if hasattr(row, "table_name") else row[1]
                index_name = getattr(row, "index_name", None) if hasattr(row, "index_name") else row[2]
                index_type = getattr(row, "index_type", None) if hasattr(row, "index_type") else row[3]
                is_unique = getattr(row, "is_unique", None) if hasattr(row, "is_unique") else row[4]
                is_primary_key = getattr(row, "is_primary_key", None) if hasattr(row, "is_primary_key") else row[5]
                column_name = getattr(row, "column_name", None) if hasattr(row, "column_name") else row[6]

                key = (
                    schema_name,
                    table_name,
                    index_name,
                )
                item = grouped.setdefault(
                    key,
                    {
                        "schema_name": schema_name,
                        "table_name": table_name,
                        "index_name": index_name,
                        "index_type": index_type,
                        "is_unique": bool(is_unique),
                        "is_primary_key": bool(is_primary_key),
                        "columns": [],
                    },
                )
                item["columns"].append(column_name)

            return [
                IndexMetadata(
                    schema_name=item["schema_name"],
                    table_name=item["table_name"],
                    index_name=item["index_name"],
                    index_type=item["index_type"],
                    is_unique=item["is_unique"],
                    is_primary_key=item["is_primary_key"],
                    columns=tuple(item["columns"]),
                )
                for item in grouped.values()
            ]
        finally:
            connection.close()

    def _load_table_metadata(self, config: DatabaseConfig | None = None) -> list[TableMetadata]:
        cfg = config or get_database_config()
        connection = get_connection(cfg)
        try:
            cursor = connection.cursor()
            if cfg.is_postgresql:
                cursor.execute(
                    """
                    SELECT
                        schemaname AS schema_name,
                        relname AS table_name,
                        n_live_tup AS row_count
                    FROM pg_stat_user_tables
                    WHERE schemaname = %s
                    ORDER BY schemaname, relname;
                    """,
                    (cfg.schema,),
                )
            else:
                cursor.execute(
                    """
                    SELECT
                        s.name AS schema_name,
                        t.name AS table_name,
                        SUM(p.row_count) AS row_count
                    FROM sys.tables AS t
                    INNER JOIN sys.schemas AS s
                        ON s.schema_id = t.schema_id
                    INNER JOIN sys.dm_db_partition_stats AS p
                        ON p.object_id = t.object_id
                        AND p.index_id IN (0, 1)
                    GROUP BY
                        s.name,
                        t.name
                    ORDER BY
                        s.name,
                        t.name
                    """
                )

            return [
                TableMetadata(
                    schema_name=getattr(row, "schema_name", None) if hasattr(row, "schema_name") else row[0],
                    table_name=getattr(row, "table_name", None) if hasattr(row, "table_name") else row[1],
                    row_count=int((getattr(row, "row_count", None) if hasattr(row, "row_count") else row[2]) or 0),
                )
                for row in cursor.fetchall()
            ]
        finally:
            connection.close()
