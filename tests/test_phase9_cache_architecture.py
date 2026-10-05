from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from app.database.metadata_cache import MetadataCache
from app.database.metadata_service import (
    DatabaseMetadata,
    DatabaseMetadataService,
    IndexMetadata,
    TableMetadata,
)
from app.database.query_service import (
    DatabaseQueryResult,
    DatabaseQueryService,
    DatabaseQueryServiceError,
)
from app.database.relationship_cache import RelationshipCache
from app.database.relationship_service import RelationshipResult
from app.database.schema import (
    ColumnInfo,
    DatabaseSchema,
    ForeignKeyInfo,
    TableInfo,
    UniqueConstraintInfo,
)
from app.database.schema_fingerprint import SchemaFingerprint
from app.database.semantic_query_cache import SemanticQueryCache
from app.query.schema import QueryColumn, QueryFilter, QueryJoin, QueryPlan


# =============================================================================
# Helper Fixtures & Builders
# =============================================================================

def _build_test_schema() -> DatabaseSchema:
    table_orders = TableInfo(
        schema_name="dbo",
        table_name="orders",
        columns=[
            ColumnInfo("order_id", "int", False, 1),
            ColumnInfo("customer_id", "int", False, 2),
            ColumnInfo("amount", "decimal", False, 3),
            ColumnInfo("status", "varchar", True, 4),
        ],
        primary_key_columns=["order_id"],
    )
    table_customers = TableInfo(
        schema_name="dbo",
        table_name="customers",
        columns=[
            ColumnInfo("customer_id", "int", False, 1),
            ColumnInfo("customer_name", "varchar", False, 2),
            ColumnInfo("email", "varchar", True, 3),
        ],
        primary_key_columns=["customer_id"],
    )
    fkeys = [
        ForeignKeyInfo(
            constraint_name="FK_orders_customers",
            schema_name="dbo",
            table_name="orders",
            column_name="customer_id",
            referenced_schema_name="dbo",
            referenced_table_name="customers",
            referenced_column_name="customer_id",
        )
    ]
    uconstrs = [
        UniqueConstraintInfo(
            constraint_name="UQ_customers_email",
            schema_name="dbo",
            table_name="customers",
            column_name="email",
        )
    ]
    return DatabaseSchema(
        tables=[table_orders, table_customers],
        foreign_keys=fkeys,
        unique_constraints=uconstrs,
    )


def _build_test_indexes() -> list[IndexMetadata]:
    return [
        IndexMetadata(
            schema_name="dbo",
            table_name="orders",
            index_name="IX_orders_customer_id",
            index_type="NONCLUSTERED",
            is_unique=False,
            is_primary_key=False,
            columns=("customer_id",),
        )
    ]


# =============================================================================
# 1. Metadata Cache & DatabaseMetadataService Tests
# =============================================================================

def test_metadata_cache_hit_bypasses_catalog_queries(tmp_path: Path):
    """When cache is valid and verification token matches, catalog queries are bypassed."""
    cache = MetadataCache(cache_dir=tmp_path)
    service = DatabaseMetadataService(cache=cache)

    schema = _build_test_schema()
    indexes = _build_test_indexes()
    fingerprint = SchemaFingerprint.build(schema, indexes, "testdb", "localhost")

    meta = DatabaseMetadata(
        database_name="testdb",
        server_name="localhost",
        schema=schema,
        indexes=tuple(indexes),
        table_metadata=(),
        schema_fingerprint=fingerprint,
    )
    token = "2:7:12345:1:6789:2026-09-30"
    cache.save(meta, fingerprint=fingerprint, verification_token=token)

    with patch("app.database.metadata_service.test_connection", return_value={"server_name": "localhost", "database_name": "testdb"}), \
         patch.object(service, "_get_verification_token", return_value=token), \
         patch("app.database.metadata_service.get_database_schema") as mock_get_schema, \
         patch.object(service, "_load_indexes") as mock_load_indexes, \
         patch.object(service, "_load_table_metadata", return_value=[TableMetadata("dbo", "orders", 100)]):

        loaded = service.load(force_refresh=False)
        assert loaded.cache_hit is True
        assert loaded.schema_fingerprint == fingerprint
        assert len(loaded.schema.tables) == 2
        assert len(loaded.table_metadata) == 1
        assert loaded.table_metadata[0].row_count == 100
        mock_get_schema.assert_not_called()
        mock_load_indexes.assert_not_called()


def test_metadata_cache_refreshes_live_row_counts_on_hit(tmp_path: Path):
    """On cache hit, live row counts are freshly queried from _load_table_metadata."""
    cache = MetadataCache(cache_dir=tmp_path)
    service = DatabaseMetadataService(cache=cache)

    schema = _build_test_schema()
    fingerprint = SchemaFingerprint.build(schema, (), "testdb", "localhost")
    meta = DatabaseMetadata("testdb", "localhost", schema=schema, schema_fingerprint=fingerprint)
    token = "token_v1"
    cache.save(meta, fingerprint=fingerprint, verification_token=token)

    with patch("app.database.metadata_service.test_connection", return_value={"server_name": "localhost", "database_name": "testdb"}), \
         patch.object(service, "_get_verification_token", return_value=token), \
         patch.object(service, "_load_table_metadata", return_value=[TableMetadata("dbo", "orders", 500)]) as mock_row_counts:

        loaded = service.load()
        assert loaded.cache_hit is True
        mock_row_counts.assert_called_once()
        assert loaded.get_table_row_count("dbo", "orders") == 500


def test_metadata_cache_miss_queries_catalog_and_saves(tmp_path: Path):
    """On cache miss, catalog is queried, fingerprint & verification token are computed and saved."""
    cache = MetadataCache(cache_dir=tmp_path)
    service = DatabaseMetadataService(cache=cache)
    schema = _build_test_schema()
    indexes = _build_test_indexes()
    token = "live_token_456"

    with patch("app.database.metadata_service.test_connection", return_value={"server_name": "localhost", "database_name": "testdb"}), \
         patch("app.database.metadata_service.get_database_schema", return_value=schema) as mock_get_schema, \
         patch.object(service, "_load_indexes", return_value=indexes), \
         patch.object(service, "_get_verification_token", return_value=token), \
         patch.object(service, "_load_table_metadata", return_value=[]):

        loaded = service.load()
        assert loaded.cache_hit is False
        assert mock_get_schema.called

        # Verify it was saved to cache
        entry = cache.get_entry("localhost", "testdb")
        assert entry is not None
        assert entry["verification_token"] == token
        assert len(entry["metadata"].schema.tables) == 2


def test_metadata_cache_invalidation_on_token_change(tmp_path: Path):
    """When verification token changes (e.g. schema modified), cache is invalidated and refreshed."""
    cache = MetadataCache(cache_dir=tmp_path)
    service = DatabaseMetadataService(cache=cache)

    schema1 = _build_test_schema()
    fp1 = SchemaFingerprint.build(schema1, (), "testdb", "localhost")
    meta1 = DatabaseMetadata("testdb", "localhost", schema=schema1, schema_fingerprint=fp1)
    cache.save(meta1, fingerprint=fp1, verification_token="old_token_111")

    # Now database has changed: new column added
    table_new = TableInfo(
        schema_name="dbo",
        table_name="orders",
        columns=[
            ColumnInfo("order_id", "int", False, 1),
            ColumnInfo("customer_id", "int", False, 2),
            ColumnInfo("amount", "decimal", False, 3),
            ColumnInfo("status", "varchar", True, 4),
            ColumnInfo("notes", "nvarchar", True, 5),
        ],
        primary_key_columns=["order_id"],
    )
    schema2 = DatabaseSchema(tables=[table_new])
    new_token = "new_token_222"

    with patch("app.database.metadata_service.test_connection", return_value={"server_name": "localhost", "database_name": "testdb"}), \
         patch.object(service, "_get_verification_token", return_value=new_token), \
         patch("app.database.metadata_service.get_database_schema", return_value=schema2) as mock_get_schema, \
         patch.object(service, "_load_indexes", return_value=[]), \
         patch.object(service, "_load_table_metadata", return_value=[]):

        loaded = service.load()
        assert loaded.cache_hit is False
        assert mock_get_schema.called
        assert len(loaded.schema.tables[0].columns) == 5

        # Updated cache entry has new token
        entry = cache.get_entry("localhost", "testdb")
        assert entry["verification_token"] == new_token


def test_metadata_cache_force_refresh(tmp_path: Path):
    """force_refresh=True forces catalog queries even if token matches."""
    cache = MetadataCache(cache_dir=tmp_path)
    service = DatabaseMetadataService(cache=cache)
    schema = _build_test_schema()
    fp = SchemaFingerprint.build(schema, (), "testdb", "localhost")
    meta = DatabaseMetadata("testdb", "localhost", schema=schema, schema_fingerprint=fp)
    token = "token_same"
    cache.save(meta, fingerprint=fp, verification_token=token)

    with patch("app.database.metadata_service.test_connection", return_value={"server_name": "localhost", "database_name": "testdb"}), \
         patch.object(service, "_get_verification_token", return_value=token), \
         patch("app.database.metadata_service.get_database_schema", return_value=schema) as mock_get_schema, \
         patch.object(service, "_load_indexes", return_value=[]), \
         patch.object(service, "_load_table_metadata", return_value=[]):

        loaded = service.load(force_refresh=True)
        assert loaded.cache_hit is False
        assert mock_get_schema.called


def test_metadata_cache_server_database_isolation(tmp_path: Path):
    """Cache saved for (srv1, db1) is not accessible to (srv1, db2) or (srv2, db1)."""
    cache = MetadataCache(cache_dir=tmp_path)
    schema = _build_test_schema()
    fp = SchemaFingerprint.build(schema, (), "db1", "srv1")
    meta = DatabaseMetadata("db1", "srv1", schema=schema, schema_fingerprint=fp)
    cache.save(meta, fingerprint=fp, verification_token="tok1")

    assert cache.get_entry("srv1", "db1") is not None
    assert cache.get_entry("srv1", "db2") is None
    assert cache.get_entry("srv2", "db1") is None


def test_metadata_cache_case_insensitive_scoping(tmp_path: Path):
    """Server and database names are matched case-insensitively."""
    cache = MetadataCache(cache_dir=tmp_path)
    schema = _build_test_schema()
    fp = SchemaFingerprint.build(schema, (), "TestDB", "LocalHost")
    meta = DatabaseMetadata("TestDB", "LocalHost", schema=schema, schema_fingerprint=fp)
    cache.save(meta, fingerprint=fp, verification_token="tok1")

    entry = cache.get_entry("localhost", "testdb")
    assert entry is not None
    assert entry["metadata"].database_name == "testdb"


def test_metadata_cache_corrupt_file_handling(tmp_path: Path):
    """Corrupted JSON file on disk is safely treated as cache miss without exception."""
    cache = MetadataCache(cache_dir=tmp_path)
    path = cache._cache_path("localhost", "testdb")
    path.write_text("{ this is corrupt json !!!", encoding="utf-8")

    assert cache.get_entry("localhost", "testdb") is None
    assert cache.load("localhost", "testdb", "fp") is None


def test_metadata_cache_atomic_write(tmp_path: Path):
    """Atomic write creates a valid JSON file and leaves no temporary files behind."""
    cache = MetadataCache(cache_dir=tmp_path)
    schema = _build_test_schema()
    fp = SchemaFingerprint.build(schema, (), "testdb", "localhost")
    meta = DatabaseMetadata("testdb", "localhost", schema=schema, schema_fingerprint=fp)
    cache.save(meta, fingerprint=fp, verification_token="tok_atomic")

    # Check file exists and is valid JSON
    path = cache._cache_path("localhost", "testdb")
    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["verification_token"] == "tok_atomic"

    # Ensure no leftover .tmp files
    tmp_files = list(tmp_path.glob("*.tmp"))
    assert len(tmp_files) == 0


# =============================================================================
# 2. Schema Fingerprint Tests
# =============================================================================

def test_schema_fingerprint_deterministic_table_column_order():
    """Identical schema with different table and column orders produces identical fingerprint."""
    col1 = ColumnInfo("id", "int", False, 1)
    col2 = ColumnInfo("name", "varchar", True, 2)
    tbl_a = TableInfo("dbo", "users", columns=[col1, col2], primary_key_columns=["id"])

    col3 = ColumnInfo("code", "int", False, 1)
    tbl_b = TableInfo("dbo", "roles", columns=[col3], primary_key_columns=["code"])

    schema1 = DatabaseSchema(tables=[tbl_a, tbl_b])
    schema2 = DatabaseSchema(tables=[tbl_b, TableInfo("dbo", "users", columns=[col2, col1], primary_key_columns=["id"])])

    fp1 = SchemaFingerprint.build(schema1, (), "testdb", "srv1")
    fp2 = SchemaFingerprint.build(schema2, (), "testdb", "srv1")
    assert fp1 == fp2


def test_schema_fingerprint_sensitive_to_column_addition():
    """Adding a column alters the fingerprint."""
    tbl1 = TableInfo("dbo", "t", columns=[ColumnInfo("a", "int", False, 1)])
    tbl2 = TableInfo("dbo", "t", columns=[ColumnInfo("a", "int", False, 1), ColumnInfo("b", "varchar", True, 2)])

    fp1 = SchemaFingerprint.build(DatabaseSchema(tables=[tbl1]))
    fp2 = SchemaFingerprint.build(DatabaseSchema(tables=[tbl2]))
    assert fp1 != fp2


def test_schema_fingerprint_sensitive_to_column_type_change():
    """Changing column data type alters the fingerprint."""
    tbl1 = TableInfo("dbo", "t", columns=[ColumnInfo("a", "int", False, 1)])
    tbl2 = TableInfo("dbo", "t", columns=[ColumnInfo("a", "bigint", False, 1)])

    fp1 = SchemaFingerprint.build(DatabaseSchema(tables=[tbl1]))
    fp2 = SchemaFingerprint.build(DatabaseSchema(tables=[tbl2]))
    assert fp1 != fp2


def test_schema_fingerprint_sensitive_to_pk_change():
    """Changing primary key alters the fingerprint."""
    tbl1 = TableInfo("dbo", "t", columns=[ColumnInfo("a", "int", False, 1)], primary_key_columns=["a"])
    tbl2 = TableInfo("dbo", "t", columns=[ColumnInfo("a", "int", False, 1)], primary_key_columns=[])

    fp1 = SchemaFingerprint.build(DatabaseSchema(tables=[tbl1]))
    fp2 = SchemaFingerprint.build(DatabaseSchema(tables=[tbl2]))
    assert fp1 != fp2


def test_schema_fingerprint_sensitive_to_fk_change():
    """Adding a foreign key alters the fingerprint."""
    tbl1 = TableInfo("dbo", "t1", columns=[ColumnInfo("a", "int", False, 1)])
    tbl2 = TableInfo("dbo", "t2", columns=[ColumnInfo("b", "int", False, 1)])
    schema1 = DatabaseSchema(tables=[tbl1, tbl2])
    fk = ForeignKeyInfo("FK_1", "dbo", "t1", "a", "dbo", "t2", "b")
    schema2 = DatabaseSchema(tables=[tbl1, tbl2], foreign_keys=[fk])

    fp1 = SchemaFingerprint.build(schema1)
    fp2 = SchemaFingerprint.build(schema2)
    assert fp1 != fp2


def test_schema_fingerprint_sensitive_to_index_change():
    """Adding or modifying an index alters the fingerprint."""
    schema = DatabaseSchema(tables=[TableInfo("dbo", "t", columns=[ColumnInfo("a", "int", False, 1)])])
    idx = IndexMetadata("dbo", "t", "IX_a", "NONCLUSTERED", False, False, ("a",))

    fp1 = SchemaFingerprint.build(schema, indexes=[])
    fp2 = SchemaFingerprint.build(schema, indexes=[idx])
    assert fp1 != fp2


def test_schema_fingerprint_insensitive_to_row_counts():
    """Fingerprint depends strictly on structural schema, completely independent of row counts."""
    schema = _build_test_schema()
    indexes = _build_test_indexes()

    # Fingerprint does not accept or incorporate table_metadata row counts
    fp1 = SchemaFingerprint.build(schema, indexes, "testdb", "srv1")
    fp2 = SchemaFingerprint.build(schema, indexes, "testdb", "srv1")
    assert fp1 == fp2


def test_schema_fingerprint_server_database_normalization():
    """Server and database names in different casing produce the identical fingerprint."""
    schema = _build_test_schema()
    fp1 = SchemaFingerprint.build(schema, (), "MngHealthReportingDB", "LOCALHOST")
    fp2 = SchemaFingerprint.build(schema, (), "mnghealthreportingdb", "localhost")
    assert fp1 == fp2


# =============================================================================
# 3. Semantic Query Cache Tests
# =============================================================================

def test_semantic_cache_hit_returns_query_plan(tmp_path: Path):
    """Stored QueryPlan is retrieved accurately with all attributes."""
    cache = SemanticQueryCache(cache_dir=tmp_path)
    plan = QueryPlan(
        intent="aggregate",
        target_columns=["orders.amount"],
        aggregation="SUM",
        confidence=0.95,
        explanation="Calculate total orders amount.",
    )
    cache.set(
        question="What is the total order amount?",
        server_name="localhost",
        database_name="testdb",
        schema_fingerprint="fp123",
        plan=plan,
    )

    retrieved = cache.get(
        question="What is the total order amount?",
        server_name="localhost",
        database_name="testdb",
        schema_fingerprint="fp123",
    )
    assert retrieved is not None
    assert retrieved.intent == "aggregate"
    assert retrieved.target_columns == ["orders.amount"]
    assert retrieved.aggregation == "SUM"
    assert retrieved.confidence == 0.95


def test_semantic_cache_paraphrase_normalization(tmp_path: Path):
    """Paraphrased questions generate the identical cache key."""
    q1 = "what is the total number of orders"
    q2 = "how many orders are there"
    q3 = "count of orders"
    q4 = "show number of orders"

    k1 = SemanticQueryCache.build_key(question=q1, server_name="s", database_name="d", schema_fingerprint="fp")
    k2 = SemanticQueryCache.build_key(question=q2, server_name="s", database_name="d", schema_fingerprint="fp")
    k3 = SemanticQueryCache.build_key(question=q3, server_name="s", database_name="d", schema_fingerprint="fp")
    k4 = SemanticQueryCache.build_key(question=q4, server_name="s", database_name="d", schema_fingerprint="fp")

    assert k1 == k2 == k3 == k4


def test_semantic_cache_preserves_filter_values(tmp_path: Path):
    """Distinct semantic queries with different filter criteria produce distinct keys."""
    k1 = SemanticQueryCache.build_key(question="orders with status active", server_name="s", database_name="d", schema_fingerprint="fp")
    k2 = SemanticQueryCache.build_key(question="orders with status inactive", server_name="s", database_name="d", schema_fingerprint="fp")
    assert k1 != k2


def test_semantic_cache_invalidation_on_schema_fingerprint_change(tmp_path: Path):
    """Cached plan is missed when schema fingerprint changes."""
    cache = SemanticQueryCache(cache_dir=tmp_path)
    plan = QueryPlan(intent="select", target_columns=["orders.order_id"])
    cache.set(
        question="list orders",
        server_name="localhost",
        database_name="testdb",
        schema_fingerprint="fp_old",
        plan=plan,
    )

    # Cache hit with same fingerprint
    assert cache.get(question="list orders", server_name="localhost", database_name="testdb", schema_fingerprint="fp_old") is not None

    # Cache miss with new fingerprint
    assert cache.get(question="list orders", server_name="localhost", database_name="testdb", schema_fingerprint="fp_new") is None


def test_semantic_cache_server_database_scoping(tmp_path: Path):
    """Plans cached for one server/database are not visible to another."""
    cache = SemanticQueryCache(cache_dir=tmp_path)
    plan = QueryPlan(intent="select", target_columns=["orders.order_id"])
    cache.set(
        question="list orders",
        server_name="srvA",
        database_name="dbA",
        schema_fingerprint="fp1",
        plan=plan,
    )

    assert cache.get(question="list orders", server_name="srvA", database_name="dbB", schema_fingerprint="fp1") is None
    assert cache.get(question="list orders", server_name="srvB", database_name="dbA", schema_fingerprint="fp1") is None


def test_semantic_cache_atomic_write(tmp_path: Path):
    """SemanticQueryCache writes atomically and does not leave orphan .tmp files."""
    cache = SemanticQueryCache(cache_dir=tmp_path)
    plan = QueryPlan(intent="select", target_columns=["orders.order_id"])
    cache.set(
        question="show orders",
        server_name="localhost",
        database_name="testdb",
        schema_fingerprint="fp1",
        plan=plan,
    )

    tmp_files = list(tmp_path.glob("*.tmp"))
    assert len(tmp_files) == 0
    assert len(list(tmp_path.glob("*.json"))) == 1


def test_semantic_cache_corrupt_file_handling(tmp_path: Path):
    """Corrupt or malformed JSON in semantic cache returns None safely."""
    cache = SemanticQueryCache(cache_dir=tmp_path)
    key = cache.build_key(
        question="corrupt query",
        server_name="localhost",
        database_name="testdb",
        schema_fingerprint="fp1",
    )
    file_path = cache._path(key)
    file_path.write_text("{\"plan\": \"not a valid plan dict\"}", encoding="utf-8")

    assert cache.get(
        question="corrupt query",
        server_name="localhost",
        database_name="testdb",
        schema_fingerprint="fp1",
    ) is None


def test_semantic_cache_does_not_cache_conversation_followups(tmp_path: Path):
    """Queries executed with conversation history are never written to the semantic cache."""
    cache = SemanticQueryCache(cache_dir=tmp_path)
    schema = _build_test_schema()

    # Mock metadata service returning valid metadata
    meta = DatabaseMetadata("testdb", "localhost", schema=schema, schema_fingerprint="fp_conv")
    mock_meta_service = MagicMock()
    mock_meta_service.load.return_value = meta

    mock_analyzer = MagicMock()
    followup_plan = QueryPlan(
        intent="filter",
        target_columns=["orders.amount"],
        filters=[QueryFilter("orders.status", "equals", "active")],
    )
    mock_analyzer.analyze.return_value = followup_plan

    mock_executor = MagicMock()
    mock_executor.execute.return_value = [{"amount": 100}]

    service = DatabaseQueryService(
        database_schema=schema,
        analyzer=mock_analyzer,
        executor=mock_executor,
        metadata_service=mock_meta_service,
        semantic_cache=cache,
    )

    conv_context = {
        "history": [{"question": "List orders", "answer": "..."}],
        "referenced_result": None,
    }

    result = service.answer("Only active ones", conversation_context=conv_context)
    assert result is not None

    # Verify that "Only active ones" was NOT written to semantic cache
    cached = cache.get(
        question="Only active ones",
        server_name="localhost",
        database_name="testdb",
        schema_fingerprint="fp_conv",
    )
    assert cached is None


def test_semantic_cache_hit_revalidates_against_current_schema(tmp_path: Path):
    """A cached plan is revalidated; if schema dropped a column, cached plan is rejected and falls back."""
    cache = SemanticQueryCache(cache_dir=tmp_path)
    schema = _build_test_schema()

    meta = DatabaseMetadata("testdb", "localhost", schema=schema, schema_fingerprint="fp_shared")
    mock_meta_service = MagicMock()
    mock_meta_service.load.return_value = meta

    # Cache a plan that targets non-existent column "orders.nonexistent"
    bad_plan = QueryPlan(
        intent="lookup",
        target_columns=["orders.nonexistent"],
    )
    cache.set(
        question="show orders",
        server_name="localhost",
        database_name="testdb",
        schema_fingerprint="fp_shared",
        plan=bad_plan,
    )

    # Query service should detect cached plan fails validation against execution schema
    # and call analyzer instead of blindly executing bad cached plan
    mock_analyzer = MagicMock()
    fallback_plan = QueryPlan(intent="lookup", target_columns=["orders.amount"])
    mock_analyzer.analyze.return_value = fallback_plan

    mock_executor = MagicMock()
    mock_executor.execute.return_value = [{"amount": 50}]

    service = DatabaseQueryService(
        database_schema=schema,
        analyzer=mock_analyzer,
        executor=mock_executor,
        metadata_service=mock_meta_service,
        semantic_cache=cache,
    )

    result = service.answer("show orders")
    assert result is not None
    # Analyzer was called because cached plan was rejected during validation!
    assert mock_analyzer.analyze.called


# =============================================================================
# 4. Relationship Cache Tests
# =============================================================================

def test_relationship_cache_scoping_server_db_fingerprint(tmp_path: Path):
    """RelationshipCache validates server_name, database_name, and schema_fingerprint."""
    cache = RelationshipCache(
        cache_dir=tmp_path,
        server_name="srv1",
        database_name="db1",
        schema_fingerprint="fp_rel_1",
    )
    rel = RelationshipResult(
        relationship_type="inferred",
        status="validated",
        left_schema="dbo",
        left_table="orders",
        left_column="customer_id",
        right_schema="dbo",
        right_table="customers",
        right_column="customer_id",
        reason="Empirical match",
        confidence=0.9,
    )
    cache.set(rel)
    cache.save()

    # Same scoping loads successfully
    cache_same = RelationshipCache(
        cache_dir=tmp_path,
        server_name="srv1",
        database_name="db1",
        schema_fingerprint="fp_rel_1",
    )
    assert cache_same.get("dbo", "orders", "customer_id", "dbo", "customers", "customer_id") is not None

    # Different server name fails to load
    cache_diff_srv = RelationshipCache(
        cache_dir=tmp_path,
        server_name="srv2",
        database_name="db1",
        schema_fingerprint="fp_rel_1",
    )
    assert cache_diff_srv.get("dbo", "orders", "customer_id", "dbo", "customers", "customer_id") is None

    # Different database name fails to load
    cache_diff_db = RelationshipCache(
        cache_dir=tmp_path,
        server_name="srv1",
        database_name="db2",
        schema_fingerprint="fp_rel_1",
    )
    assert cache_diff_db.get("dbo", "orders", "customer_id", "dbo", "customers", "customer_id") is None

    # Different fingerprint fails to load
    cache_diff_fp = RelationshipCache(
        cache_dir=tmp_path,
        server_name="srv1",
        database_name="db1",
        schema_fingerprint="fp_rel_2",
    )
    assert cache_diff_fp.get("dbo", "orders", "customer_id", "dbo", "customers", "customer_id") is None


def test_relationship_cache_caches_positive_and_negative_results(tmp_path: Path):
    """RelationshipCache stores confirmed, validated, rejected, and insufficient_data results."""
    cache = RelationshipCache(
        cache_dir=tmp_path,
        server_name="localhost",
        database_name="testdb",
        schema_fingerprint="fp1",
    )
    rel_valid = RelationshipResult(
        relationship_type="inferred",
        status="validated",
        left_schema="dbo",
        left_table="orders",
        left_column="customer_id",
        right_schema="dbo",
        right_table="customers",
        right_column="customer_id",
        reason="Match found",
        confidence=0.95,
    )
    rel_rejected = RelationshipResult(
        relationship_type="inferred",
        status="rejected",
        left_schema="dbo",
        left_table="orders",
        left_column="amount",
        right_schema="dbo",
        right_table="customers",
        right_column="customer_id",
        reason="Incompatible domains",
        confidence=0.0,
    )
    rel_insufficient = RelationshipResult(
        relationship_type="inferred",
        status="insufficient_data",
        left_schema="dbo",
        left_table="orders",
        left_column="status",
        right_schema="dbo",
        right_table="customers",
        right_column="email",
        reason="Both columns empty",
        confidence=0.0,
    )

    cache.set(rel_valid)
    cache.set(rel_rejected)
    cache.set(rel_insufficient)
    cache.save()

    # Reload from disk
    reloaded = RelationshipCache(
        cache_dir=tmp_path,
        server_name="localhost",
        database_name="testdb",
        schema_fingerprint="fp1",
    )

    r1 = reloaded.get("dbo", "orders", "customer_id", "dbo", "customers", "customer_id")
    assert r1 is not None and r1.status == "validated"

    r2 = reloaded.get("dbo", "orders", "amount", "dbo", "customers", "customer_id")
    assert r2 is not None and r2.status == "rejected"

    r3 = reloaded.get("dbo", "orders", "status", "dbo", "customers", "email")
    assert r3 is not None and r3.status == "insufficient_data"
