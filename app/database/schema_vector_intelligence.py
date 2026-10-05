"""
Generic Database Schema Intelligence & pgvector Semantic Schema Retrieval.

Phase 13 Step 5:
- Generic, database-agnostic schema embedding generation and storage using pgvector.
- Scoped by database identity and schema fingerprint for strict database isolation.
- Deterministic Python-generated schema descriptions (no LLM required for embeddings).
- Hybrid candidate retrieval combining deterministic matching and semantic vector similarity.
- Fail-closed: invalid or missing entities never produce hallucinated answers.
- Preserves SQL Server rollback option when pgvector is not available.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Sequence

import mmh3
import numpy as np

from app.core.config import DatabaseConfig, get_database_config
from app.database.connection import get_connection
from app.database.schema import DatabaseSchema, TableInfo, ColumnInfo
from app.database.schema_fingerprint import SchemaFingerprint
from app.database.schema_intelligence import DatabaseSchemaIntelligence

logger = logging.getLogger(__name__)


# =============================================================================
# 1. Deterministic Schema Embedding Model
# =============================================================================

class SchemaEmbeddingModel:
    """
    Deterministic, reproducible 384-dimensional embedding model for schema intelligence.

    Uses character n-grams, subword tokens, token bigrams, and signed MurmurHash3
    projections with sublinear scaling and L2 normalization.
    Requires no external APIs, network calls, or heavy neural network dependencies.
    Produces identical vectors for identical text across processes and restarts.
    """

    DIMENSION: int = 384

    def __init__(self, dimension: int = 384) -> None:
        self.dimension = dimension

    @staticmethod
    def _stem(word: str) -> str:
        word = word.lower()
        if word.endswith("ing") and len(word) > 4:
            word = word[:-3]
        elif word.endswith("ed") and len(word) > 3:
            word = word[:-2]
        elif word.endswith("tion") and len(word) > 5:
            word = word[:-4]
        elif word.endswith("registrant") or word.endswith("registration"):
            word = "regist"
        elif word.endswith("ies") and len(word) > 3:
            word = word[:-3] + "y"
        elif word.endswith("s") and not word.endswith("ss"):
            word = word[:-1]
        return word

    def _extract_features(self, text: str) -> list[str]:
        tokens = DatabaseSchemaIntelligence.tokenize(text)
        features: set[str] = set()
        stemmed: list[str] = []

        for t in tokens:
            st = self._stem(t)
            features.add(st)
            stemmed.append(st)
            # Character 3-grams for subword morphological matching
            for i in range(len(st) - 2):
                features.add("ng:" + st[i : i + 3])

        # Token bigrams for compound concepts
        for i in range(len(stemmed) - 1):
            features.add("bg:" + stemmed[i] + "_" + stemmed[i + 1])

        return sorted(list(features))

    def embed_text(self, text: str) -> list[float]:
        """Convert input text into a deterministic, unit-normalized float vector."""
        if not text or not str(text).strip():
            vec = np.zeros(self.dimension, dtype=np.float32)
            vec[0] = 1.0
            return vec.tolist()

        features = self._extract_features(text)
        if not features:
            vec = np.zeros(self.dimension, dtype=np.float32)
            vec[0] = 1.0
            return vec.tolist()

        vec = np.zeros(self.dimension, dtype=np.float32)
        for f in features:
            weight = 3.0 if f.startswith("bg:") else (0.5 if f.startswith("ng:") else 2.0)
            h = mmh3.hash(f, seed=42)
            idx = abs(h) % self.dimension
            sign = 1.0 if (h >= 0) else -1.0
            vec[idx] += sign * weight

        # Sublinear scaling: sign(x) * log(1 + |x|)
        vec = np.sign(vec) * np.log1p(np.abs(vec))

        norm = float(np.linalg.norm(vec))
        if norm > 0.0:
            vec = vec / norm
        else:
            vec[0] = 1.0

        return vec.tolist()

    def embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        return [self.embed_text(t) for t in texts]


# =============================================================================
# 2. Schema Candidate DTO
# =============================================================================

@dataclass(frozen=True)
class SchemaVectorCandidate:
    """A schema candidate retrieved via semantic vector similarity."""

    schema_name: str
    table_name: str
    column_name: str | None
    object_type: str  # "table" or "column"
    similarity: float
    metadata_text: str


# =============================================================================
# 3. Schema Vector Intelligence Service
# =============================================================================

class SchemaVectorIntelligence:
    """
    Manages pgvector-based schema intelligence storage, synchronization,
    and semantic similarity search in PostgreSQL.

    Guarantees:
    1. Database isolation: scoped strictly to database_identity.
    2. Fingerprint isolation: scoped strictly to schema_fingerprint.
    3. Idempotent storage: object_key prevents duplicate entries.
    4. Sub-millisecond query time via PostgreSQL vector operations (<=> cosine distance).
    5. Clean fallback when running on SQL Server (no-op / deterministic only).
    """

    TABLE_NAME = "public.schema_vector_intelligence"

    def __init__(
        self,
        config: DatabaseConfig | None = None,
        embedding_model: SchemaEmbeddingModel | None = None,
    ) -> None:
        self.config = config or get_database_config()
        self.embedding_model = embedding_model or SchemaEmbeddingModel()
        self._schema_ensured: bool = False

    @property
    def is_available(self) -> bool:
        """Check if vector intelligence is available on the current connection."""
        return bool(self.config and self.config.is_postgresql)

    def get_database_identity(self, config: DatabaseConfig | None = None) -> str:
        """Construct canonical database identity string (server:port/database)."""
        cfg = config or self.config
        server = (cfg.server or "localhost").strip().lower()
        port = cfg.port or 5432
        database = (cfg.database or "").strip().lower()
        return f"{server}:{port}/{database}"

    def ensure_schema_table(self) -> None:
        """Ensure pgvector extension and schema_vector_intelligence table exist."""
        if not self.is_available:
            return

        with get_connection(self.config) as conn:
            cursor = conn.cursor()
            cursor.execute("CREATE EXTENSION IF NOT EXISTS vector;")
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self.TABLE_NAME} (
                    id BIGSERIAL PRIMARY KEY,
                    database_identity VARCHAR(255) NOT NULL,
                    schema_fingerprint VARCHAR(64) NOT NULL,
                    schema_name VARCHAR(128) NOT NULL,
                    object_type VARCHAR(32) NOT NULL,
                    table_name VARCHAR(128) NOT NULL,
                    column_name VARCHAR(128),
                    metadata_text TEXT NOT NULL,
                    embedding vector({self.embedding_model.DIMENSION}) NOT NULL,
                    object_key VARCHAR(512) UNIQUE NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_schema_vec_db_fp 
                    ON {self.TABLE_NAME} (database_identity, schema_fingerprint);
                CREATE INDEX IF NOT EXISTS idx_schema_vec_obj_type 
                    ON {self.TABLE_NAME} (database_identity, schema_fingerprint, object_type);
                """
            )
            conn.commit()
            self._schema_ensured = True

    def is_indexed(
        self,
        database_identity: str | None = None,
        schema_fingerprint: str = "",
    ) -> bool:
        """Check whether embeddings for the given database identity and fingerprint exist."""
        if not self.is_available:
            return False

        self.ensure_schema_table()
        db_id = database_identity or self.get_database_identity()
        with get_connection(self.config) as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"""
                SELECT COUNT(*) FROM {self.TABLE_NAME}
                WHERE database_identity = %s AND schema_fingerprint = %s;
                """,
                (db_id, schema_fingerprint),
            )
            row = cursor.fetchone()
            count = row[0] if row else 0
            return count > 0

    @classmethod
    def generate_table_description(
        cls,
        table: TableInfo,
        schema: DatabaseSchema,
    ) -> str:
        """Construct deterministic text representation of a database table."""
        col_parts: list[str] = []
        for c in sorted(table.columns, key=lambda x: x.ordinal_position):
            roles = DatabaseSchemaIntelligence.infer_roles(c.name, c.data_type)
            roles_str = f" [{', '.join(sorted(roles))}]" if roles else ""
            nullable_str = " nullable" if c.nullable else " non-null"
            col_parts.append(f"{c.name} {c.data_type}{nullable_str}{roles_str}")

        pk_str = f" primary keys: [{', '.join(sorted(table.primary_key_columns))}]." if table.primary_key_columns else ""

        # Relationships involving this table
        fk_parts: list[str] = []
        for fk in schema.foreign_keys:
            if fk.schema_name == table.schema_name and fk.table_name == table.table_name:
                fk_parts.append(f"{fk.column_name}->{fk.referenced_schema_name}.{fk.referenced_table_name}.{fk.referenced_column_name}")
            elif fk.referenced_schema_name == table.schema_name and fk.referenced_table_name == table.table_name:
                fk_parts.append(f"referenced_by {fk.schema_name}.{fk.table_name}.{fk.column_name}")

        rel_str = f" relationships: [{', '.join(sorted(fk_parts))}]." if fk_parts else ""

        return (
            f'table "{table.table_name}" in schema "{table.schema_name}".{pk_str} '
            f"columns: [{', '.join(col_parts)}].{rel_str}"
        )

    @classmethod
    def generate_column_description(
        cls,
        table: TableInfo,
        column: ColumnInfo,
    ) -> str:
        """Construct deterministic text representation of a column."""
        roles = DatabaseSchemaIntelligence.infer_roles(column.name, column.data_type)
        roles_str = f" with semantic roles [{', '.join(sorted(roles))}]" if roles else ""
        nullable_str = "nullable" if column.nullable else "required"
        is_pk = " primary key" if column.name in table.primary_key_columns else ""

        return (
            f'column "{column.name}" ({column.data_type}, {nullable_str}{is_pk}){roles_str} '
            f'in table "{table.table_name}" (schema "{table.schema_name}").'
        )

    def index_schema(
        self,
        database_schema: DatabaseSchema,
        schema_fingerprint: str,
        force_refresh: bool = False,
        database_identity: str | None = None,
    ) -> int:
        """
        Index all tables and columns into pgvector table for the given schema fingerprint.
        Reuses existing embeddings if already indexed unless force_refresh is True.
        """
        if not self.is_available:
            return 0

        self.ensure_schema_table()
        db_id = database_identity or self.get_database_identity()

        if not force_refresh and self.is_indexed(db_id, schema_fingerprint):
            logger.debug(
                "Schema embeddings already indexed for db_id=%s, fp=%s",
                db_id,
                schema_fingerprint,
            )
            with get_connection(self.config) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    f"SELECT COUNT(*) FROM {self.TABLE_NAME} WHERE database_identity = %s AND schema_fingerprint = %s;",
                    (db_id, schema_fingerprint),
                )
                row = cursor.fetchone()
                return row[0] if row else 0

        # Build embedding objects
        entries: list[dict[str, Any]] = []

        for table in database_schema.tables:
            # 1. Table-level object
            table_desc = self.generate_table_description(table, database_schema)
            table_key = f"{db_id}:{schema_fingerprint}:{table.schema_name}:table:{table.table_name}:"
            entries.append({
                "database_identity": db_id,
                "schema_fingerprint": schema_fingerprint,
                "schema_name": table.schema_name,
                "object_type": "table",
                "table_name": table.table_name,
                "column_name": None,
                "metadata_text": table_desc,
                "object_key": table_key,
            })

            # 2. Column-level objects for columns
            for column in table.columns:
                col_desc = self.generate_column_description(table, column)
                col_key = f"{db_id}:{schema_fingerprint}:{table.schema_name}:column:{table.table_name}:{column.name}"
                entries.append({
                    "database_identity": db_id,
                    "schema_fingerprint": schema_fingerprint,
                    "schema_name": table.schema_name,
                    "object_type": "column",
                    "table_name": table.table_name,
                    "column_name": column.name,
                    "metadata_text": col_desc,
                    "object_key": col_key,
                })

        # Batch embed texts
        texts = [e["metadata_text"] for e in entries]
        embeddings = self.embedding_model.embed_batch(texts)
        for i, emb in enumerate(embeddings):
            entries[i]["embedding"] = "[" + ",".join(f"{x:.6f}" for x in emb) + "]"

        # Upsert into PostgreSQL pgvector
        with get_connection(self.config) as conn:
            cursor = conn.cursor()

            # Invalidate older fingerprints for this database identity
            cursor.execute(
                f"DELETE FROM {self.TABLE_NAME} WHERE database_identity = %s AND schema_fingerprint != %s;",
                (db_id, schema_fingerprint),
            )

            # Insert in chunks of 100
            chunk_size = 100
            for start_idx in range(0, len(entries), chunk_size):
                chunk = entries[start_idx : start_idx + chunk_size]
                values_clauses = []
                params = []
                for item in chunk:
                    values_clauses.append("(%s, %s, %s, %s, %s, %s, %s, %s::vector, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)")
                    params.extend([
                        item["database_identity"],
                        item["schema_fingerprint"],
                        item["schema_name"],
                        item["object_type"],
                        item["table_name"],
                        item["column_name"],
                        item["metadata_text"],
                        item["embedding"],
                        item["object_key"],
                    ])

                insert_sql = f"""
                INSERT INTO {self.TABLE_NAME} (
                    database_identity, schema_fingerprint, schema_name, object_type,
                    table_name, column_name, metadata_text, embedding, object_key,
                    created_at, updated_at
                ) VALUES {', '.join(values_clauses)}
                ON CONFLICT (object_key) DO UPDATE SET
                    metadata_text = EXCLUDED.metadata_text,
                    embedding = EXCLUDED.embedding,
                    updated_at = CURRENT_TIMESTAMP;
                """
                cursor.execute(insert_sql, params)

            conn.commit()

        logger.info(
            "Successfully indexed %d schema objects into pgvector for db_id=%s, fp=%s",
            len(entries),
            db_id,
            schema_fingerprint,
        )
        return len(entries)

    def search_candidates(
        self,
        query: str,
        schema_fingerprint: str,
        object_type: str | None = None,
        limit: int = 5,
        min_similarity: float = 0.05,
        database_identity: str | None = None,
    ) -> list[SchemaVectorCandidate]:
        """
        Execute semantic similarity search using pgvector cosine distance (<=>).
        Strictly isolated by database_identity and schema_fingerprint.
        """
        if not self.is_available:
            return []

        self.ensure_schema_table()
        db_id = database_identity or self.get_database_identity()

        query_vec = self.embedding_model.embed_text(query)
        vec_literal = "[" + ",".join(f"{x:.6f}" for x in query_vec) + "]"

        type_filter = "AND object_type = %s" if object_type else ""
        sql = f"""
        SELECT
            schema_name,
            table_name,
            column_name,
            object_type,
            metadata_text,
            1.0 - (embedding <=> %s::vector) AS similarity
        FROM {self.TABLE_NAME}
        WHERE database_identity = %s
          AND schema_fingerprint = %s
          {type_filter}
        ORDER BY embedding <=> %s::vector ASC
        LIMIT %s;
        """

        params: list[Any] = [vec_literal, db_id, schema_fingerprint]
        if object_type:
            params.append(object_type)
        params.extend([vec_literal, limit])

        with get_connection(self.config) as conn:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            rows = cursor.fetchall()

        candidates: list[SchemaVectorCandidate] = []
        for r in rows:
            similarity = float(getattr(r, "similarity", r[5]))
            if similarity < min_similarity:
                continue
            candidates.append(
                SchemaVectorCandidate(
                    schema_name=getattr(r, "schema_name", r[0]),
                    table_name=getattr(r, "table_name", r[1]),
                    column_name=getattr(r, "column_name", r[2]),
                    object_type=getattr(r, "object_type", r[3]),
                    similarity=similarity,
                    metadata_text=getattr(r, "metadata_text", r[4]),
                )
            )

        return candidates

    def search_tables(
        self,
        query: str,
        schema_fingerprint: str,
        limit: int = 5,
        min_similarity: float = 0.05,
        database_identity: str | None = None,
    ) -> list[SchemaVectorCandidate]:
        """Search specifically for candidate tables."""
        return self.search_candidates(
            query=query,
            schema_fingerprint=schema_fingerprint,
            object_type="table",
            limit=limit,
            min_similarity=min_similarity,
            database_identity=database_identity,
        )

    def search_columns(
        self,
        query: str,
        schema_fingerprint: str,
        limit: int = 10,
        min_similarity: float = 0.05,
        database_identity: str | None = None,
    ) -> list[SchemaVectorCandidate]:
        """Search specifically for candidate columns."""
        return self.search_candidates(
            query=query,
            schema_fingerprint=schema_fingerprint,
            object_type="column",
            limit=limit,
            min_similarity=min_similarity,
            database_identity=database_identity,
        )

    def invalidate_database(
        self,
        database_identity: str | None = None,
        schema_fingerprint: str | None = None,
    ) -> int:
        """Purge stored embeddings for a database identity or specific fingerprint."""
        if not self.is_available:
            return 0

        self.ensure_schema_table()
        db_id = database_identity or self.get_database_identity()

        with get_connection(self.config) as conn:
            cursor = conn.cursor()
            if schema_fingerprint:
                cursor.execute(
                    f"DELETE FROM {self.TABLE_NAME} WHERE database_identity = %s AND schema_fingerprint = %s;",
                    (db_id, schema_fingerprint),
                )
            else:
                cursor.execute(
                    f"DELETE FROM {self.TABLE_NAME} WHERE database_identity = %s;",
                    (db_id,),
                )
            deleted = cursor.rowcount
            conn.commit()
            return deleted
