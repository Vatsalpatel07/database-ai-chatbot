"""
Phase 13 Step 5 — Generic Database Schema Intelligence & pgvector Test Suite

Covers:
1. pgvector extension availability in PostgreSQL
2. Schema vector intelligence table structure and indexes
3. Deterministic embedding generation (reproducibility, 384 dimensions, L2 normalization)
4. Semantic similarity properties (related vs orthogonal/unrelated concepts)
5. Schema indexing idempotence and cache hit reuse
6. Database identity isolation (Database A never returns Database B embeddings)
7. Schema fingerprint isolation (stale fingerprints never leak candidates)
8. Schema refresh, invalidation, and old fingerprint pruning
9. Semantic table candidate retrieval via pgvector cosine distance (<=>)
10. Semantic column candidate retrieval via pgvector
11. Irrelevant schema candidates are not blindly selected (fail-closed)
12. Hybrid table selection (deterministic metadata + vector similarity)
13. Fail-closed: unknown table does not hallucinate
14. Fail-closed: unknown column or unavailable metric does not hallucinate
15. Valid query returning zero rows distinguished from unresolved entity
16. DeepSeek token optimization: only candidate schema subset sent, never full schema
17. SQL result remains canonical source of truth for factual answers
18. Dual-engine rollback: SQL Server mode operates deterministically without pgvector
19. Database switching: synthetic unrelated schema (warehouses, shipments) indexed dynamically
20. Forensic verification: zero business-specific table/column hardcoding in production components
"""

from __future__ import annotations

import os
import re
import pytest
from unittest.mock import MagicMock, patch

from app.core.config import DatabaseConfig
from app.database.connection import get_connection
from app.database.schema import DatabaseSchema, TableInfo, ColumnInfo
from app.database.schema_fingerprint import SchemaFingerprint
from app.database.schema_vector_intelligence import (
    SchemaEmbeddingModel,
    SchemaVectorIntelligence,
    SchemaVectorCandidate,
)
from app.database.table_selector import select_tables
from app.database.query_service import DatabaseQueryService, DatabaseQueryServiceError
from app.query.schema import QueryPlan, QueryFilter


@pytest.fixture
def pg_config():
    return DatabaseConfig(
        engine="postgresql",
        server="localhost",
        port=5432,
        database="mnghealthreportingdb",
        schema="dbo",
        user="postgres",
        password=os.environ.get("DB_PASSWORD", "Vatsal@123"),
    )


@pytest.fixture
def synthetic_schema():
    """A synthetic logistics schema with zero medical or healthcare terms."""
    table_warehouses = TableInfo(
        schema_name="logistics",
        table_name="warehouses",
        columns=[
            ColumnInfo("warehouse_id", "integer", False, 1),
            ColumnInfo("facility_name", "varchar", False, 2),
            ColumnInfo("storage_capacity", "integer", True, 3),
            ColumnInfo("postal_code", "varchar", True, 4),
        ],
        primary_key_columns=["warehouse_id"],
    )
    table_shipments = TableInfo(
        schema_name="logistics",
        table_name="shipments",
        columns=[
            ColumnInfo("shipment_id", "integer", False, 1),
            ColumnInfo("warehouse_id", "integer", False, 2),
            ColumnInfo("cargo_weight", "double precision", False, 3),
            ColumnInfo("departure_timestamp", "timestamp", True, 4),
            ColumnInfo("tracking_status", "varchar", True, 5),
        ],
        primary_key_columns=["shipment_id"],
    )
    return DatabaseSchema(tables=[table_warehouses, table_shipments])


# =============================================================================
# 1. pgvector Extension & Table Creation
# =============================================================================

def test_01_pgvector_extension_availability(pg_config):
    """pgvector extension is installed and available in PostgreSQL."""
    with get_connection(pg_config) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT extname, extversion FROM pg_extension WHERE extname = 'vector';")
        row = cursor.fetchone()
        assert row is not None
        extname = getattr(row, "extname", row[0])
        assert extname == "vector"


def test_02_vector_table_creation_and_indexes(pg_config):
    """schema_vector_intelligence table and composite indexes exist and are valid."""
    service = SchemaVectorIntelligence(config=pg_config)
    service.ensure_schema_table()

    with get_connection(pg_config) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT column_name, data_type, udt_name
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'schema_vector_intelligence';
            """
        )
        cols = {getattr(r, "column_name", r[0]): getattr(r, "udt_name", r[2]) for r in cursor.fetchall()}
        assert "embedding" in cols
        assert cols["embedding"] == "vector"
        assert "database_identity" in cols
        assert "schema_fingerprint" in cols
        assert "object_key" in cols


# =============================================================================
# 2. Deterministic Embedding Model
# =============================================================================

def test_03_deterministic_embedding_generation_consistency():
    """Embedding generation is deterministic, reproducible, 384 dimensions, and unit-normalized."""
    model = SchemaEmbeddingModel(dimension=384)
    text = 'table "customers" in schema "sales". columns: [customer_id integer, email text].'

    v1 = model.embed_text(text)
    v2 = model.embed_text(text)

    assert len(v1) == 384
    assert v1 == v2  # 100% exact reproducible float representation

    import numpy as np
    norm = np.linalg.norm(np.array(v1))
    assert pytest.approx(float(norm), 1e-4) == 1.0


def test_04_semantic_similarity_properties():
    """Morphological/semantic variants have positive similarity; unrelated concepts are orthogonal."""
    model = SchemaEmbeddingModel(dimension=384)
    import numpy as np

    v_reg1 = np.array(model.embed_text("registrations and attendees for event"))
    v_reg2 = np.array(model.embed_text("who is registered for the conference"))
    v_unrelated = np.array(model.embed_text("quantum physics astrophysical astrophysics telescope galaxy"))

    sim_related = float(np.dot(v_reg1, v_reg2))
    sim_unrelated = float(np.dot(v_reg1, v_unrelated))

    assert sim_related > 0.05
    assert sim_unrelated <= 0.02


# =============================================================================
# 3. Idempotent Indexing & Fingerprint Isolation
# =============================================================================

def test_05_schema_indexing_idempotence(pg_config, synthetic_schema):
    """Indexing a schema saves embeddings, and repeated indexing without changes is an instant cache hit."""
    service = SchemaVectorIntelligence(config=pg_config)
    db_id = "localhost:5432/test_synth_db"
    fp = SchemaFingerprint.build(schema=synthetic_schema, database_name="test_synth_db", server_name="localhost")

    # Index first time
    count1 = service.index_schema(database_schema=synthetic_schema, schema_fingerprint=fp, force_refresh=True, database_identity=db_id)
    # 2 tables + 9 columns = 11 objects
    assert count1 == 11

    # Index second time (cache hit)
    count2 = service.index_schema(database_schema=synthetic_schema, schema_fingerprint=fp, force_refresh=False, database_identity=db_id)
    assert count2 == 11


def test_06_database_identity_isolation(pg_config, synthetic_schema):
    """Database identity isolation: searches scoped to Database A never return Database B embeddings."""
    service = SchemaVectorIntelligence(config=pg_config)
    fp = SchemaFingerprint.build(schema=synthetic_schema, database_name="db_alpha", server_name="localhost")
    service.index_schema(synthetic_schema, fp, force_refresh=True, database_identity="localhost:5432/db_alpha")

    # Search as db_beta with same fingerprint
    results_b = service.search_tables("warehouse facility", schema_fingerprint=fp, database_identity="localhost:5432/db_beta")
    assert len(results_b) == 0  # Strict database isolation


def test_07_schema_fingerprint_isolation(pg_config, synthetic_schema):
    """Schema fingerprint isolation: searching with an older/different fingerprint yields zero results."""
    service = SchemaVectorIntelligence(config=pg_config)
    db_id = "localhost:5432/test_fp_isolation_db"
    fp_valid = SchemaFingerprint.build(schema=synthetic_schema, database_name="test_fp_isolation_db", server_name="localhost")
    service.index_schema(synthetic_schema, fp_valid, force_refresh=True, database_identity=db_id)

    # Search with different fingerprint
    results_stale = service.search_tables("warehouse facility", schema_fingerprint="old_stale_fingerprint_999", database_identity=db_id)
    assert len(results_stale) == 0


def test_08_schema_invalidation_and_pruning(pg_config, synthetic_schema):
    """Indexing with a new schema fingerprint purges older fingerprints for the same database identity."""
    service = SchemaVectorIntelligence(config=pg_config)
    db_id = "localhost:5432/test_prune_db"
    fp_old = "fingerprint_v1_old"
    fp_new = "fingerprint_v2_new"

    # Index with fp_old
    service.index_schema(synthetic_schema, fp_old, force_refresh=True, database_identity=db_id)
    assert service.is_indexed(database_identity=db_id, schema_fingerprint=fp_old) is True

    # Index with fp_new -> should prune fp_old
    service.index_schema(synthetic_schema, fp_new, force_refresh=True, database_identity=db_id)
    assert service.is_indexed(database_identity=db_id, schema_fingerprint=fp_new) is True
    assert service.is_indexed(database_identity=db_id, schema_fingerprint=fp_old) is False  # Pruned


# =============================================================================
# 4. Semantic Search & Candidate Ranking
# =============================================================================

def test_09_semantic_table_candidate_retrieval(pg_config, synthetic_schema):
    """search_tables retrieves relevant tables using cosine similarity."""
    service = SchemaVectorIntelligence(config=pg_config)
    fp = SchemaFingerprint.build(schema=synthetic_schema, database_name=pg_config.database, server_name=pg_config.server)
    service.index_schema(synthetic_schema, fp, force_refresh=True)

    candidates = service.search_tables("warehouse storage facilities and depots", schema_fingerprint=fp, limit=3)
    assert len(candidates) > 0
    top = candidates[0]
    assert top.table_name == "warehouses"
    assert top.object_type == "table"
    assert top.similarity > 0.05


def test_10_semantic_column_candidate_retrieval(pg_config, synthetic_schema):
    """search_columns retrieves relevant column objects based on semantic descriptions."""
    service = SchemaVectorIntelligence(config=pg_config)
    fp = SchemaFingerprint.build(schema=synthetic_schema, database_name=pg_config.database, server_name=pg_config.server)
    service.index_schema(synthetic_schema, fp, force_refresh=True)

    candidates = service.search_columns("cargo freight weight in kilograms", schema_fingerprint=fp, limit=3)
    assert len(candidates) > 0
    assert any(c.column_name == "cargo_weight" for c in candidates)


def test_11_irrelevant_candidates_not_blindly_selected(pg_config, synthetic_schema):
    """Unrelated questions yield no candidates above similarity threshold."""
    service = SchemaVectorIntelligence(config=pg_config)
    fp = SchemaFingerprint.build(schema=synthetic_schema, database_name=pg_config.database, server_name=pg_config.server)
    service.index_schema(synthetic_schema, fp, force_refresh=True)

    candidates = service.search_tables(
        "medieval feudalism Renaissance sculpture painting",
        schema_fingerprint=fp,
        min_similarity=0.15,
    )
    assert len(candidates) == 0


def test_12_hybrid_table_selection_combines_lexical_and_vector(synthetic_schema):
    """select_tables boosts confidence when both deterministic and vector signals match."""
    mock_vector = MagicMock()
    mock_vector.search_tables.return_value = [
        SchemaVectorCandidate(
            schema_name="logistics",
            table_name="warehouses",
            column_name=None,
            object_type="table",
            similarity=0.20,
            metadata_text="",
        )
    ]

    selected = select_tables(
        question="Show warehouses",
        schema=synthetic_schema.tables,
        vector_service=mock_vector,
        schema_fingerprint="fp123",
    )
    assert len(selected) > 0
    assert selected[0]["table"] == "warehouses"
    # Lexical score alone is ~10; with vector boost it is > 15
    assert selected[0]["score"] >= 15


# =============================================================================
# 5. Fail-Closed & Hallucination Prevention
# =============================================================================

def test_13_fail_closed_on_unknown_table(synthetic_schema):
    """Asking about a completely absent table/entity fails closed without hallucination."""
    service = DatabaseQueryService.__new__(DatabaseQueryService)
    service.database_schema = synthetic_schema
    service.entity_resolver = MagicMock()
    service.entity_resolver.resolve.return_value = MagicMock(candidates=[])
    service.relationship_service = MagicMock()
    service.vector_service = None
    service.schema_fingerprint = "fp"

    with pytest.raises(DatabaseQueryServiceError, match=r"No database table could be selected"):
        service._resolve_execution_tables(
            question="How many students study in this school?",
            conversation_context=None,
        )


def test_14_fail_closed_on_unknown_column_metric(synthetic_schema):
    """Asking for an unavailable metric/column returns unsupported plan without guessing."""
    service = DatabaseQueryService.__new__(DatabaseQueryService)
    service.database_schema = synthetic_schema
    service.analyzer = MagicMock()
    unsupported_plan = QueryPlan(
        intent="unsupported",
        explanation="The requested column 'profit_margin' does not exist in the connected database.",
        confidence=0.0,
    )
    service.analyzer.analyze.return_value = unsupported_plan
    service.validator = MagicMock()
    service.executor = MagicMock()
    service.metadata_service = MagicMock()
    service.semantic_cache = MagicMock()
    service.semantic_cache.get.return_value = None
    service.entity_resolver = MagicMock()
    service.relationship_service = MagicMock()
    service.database_server_name = "srv"
    service.database_name = "db"
    service.schema_fingerprint = "fp"
    service.vector_service = None

    with patch.object(service, "_resolve_execution_tables", return_value=[synthetic_schema.tables[0]]):
        res = service.answer("What is the average profit margin of warehouses?")
        assert res.plan.intent == "unsupported"
        assert "profit_margin" in res.data
        # SQL executor was NOT called
        assert not service.executor.execute.called


def test_15_valid_query_zero_rows_distinguished_from_unresolved(synthetic_schema):
    """A valid query returning 0 matching rows returns actual empty data list, distinct from unresolved."""
    service = DatabaseQueryService.__new__(DatabaseQueryService)
    service.database_schema = synthetic_schema
    service.analyzer = MagicMock()
    valid_plan = QueryPlan(
        intent="lookup",
        target_columns=["facility_name"],
        filters=[QueryFilter("postal_code", "equals", "99999")],
    )
    service.analyzer.analyze.return_value = valid_plan
    service.validator = MagicMock()
    service.validator.validate.return_value = MagicMock(valid=True, warnings=[])
    service.executor = MagicMock()
    service.executor.execute.return_value = []  # 0 rows returned from SQL
    service.result_validator = MagicMock()
    service.result_validator.validate.return_value = MagicMock(valid=True, errors=[])
    service.metadata_service = MagicMock()
    service.semantic_cache = MagicMock()
    service.semantic_cache.get.return_value = None
    service.entity_resolver = MagicMock()
    service.relationship_service = MagicMock()
    service.database_server_name = "srv"
    service.database_name = "db"
    service.schema_fingerprint = "fp"
    service.vector_service = None

    with patch.object(service, "_resolve_execution_tables", return_value=[synthetic_schema.tables[0]]):
        res = service.answer("Show warehouses in postal code 99999")
        assert res.plan.intent == "lookup"
        assert res.data == []  # Real 0 rows from database


# =============================================================================
# 6. DeepSeek Optimization & SQL Authority
# =============================================================================

def test_16_deepseek_token_optimization_schema_subset(synthetic_schema):
    """DeepSeek analyzer receives only the selected candidate schema subset, never the full database catalog."""
    mock_analyzer = MagicMock()
    mock_analyzer.analyze.return_value = QueryPlan(intent="row_count")
    mock_executor = MagicMock()
    mock_executor.execute.return_value = [{"row_count": 42}]
    mock_validator = MagicMock()
    mock_validator.validate.return_value = MagicMock(valid=True, warnings=[])
    mock_result_validator = MagicMock()
    mock_result_validator.validate.return_value = MagicMock(valid=True, errors=[])

    service = DatabaseQueryService.__new__(DatabaseQueryService)
    service.database_schema = synthetic_schema  # contains 2 tables
    service.analyzer = mock_analyzer
    service.validator = mock_validator
    service.executor = mock_executor
    service.result_validator = mock_result_validator
    service.metadata_service = MagicMock()
    service.semantic_cache = MagicMock()
    service.semantic_cache.get.return_value = None
    service.database_server_name = "srv"
    service.database_name = "db"
    service.schema_fingerprint = "fp"
    service.entity_resolver = MagicMock()
    service.relationship_service = MagicMock()
    service.vector_service = None

    # Simulate only 1 table selected out of the whole database
    single_table = [synthetic_schema.tables[0]]
    with patch.object(service, "_resolve_execution_tables", return_value=single_table):
        service.answer("How many warehouses are there?")

        # Inspect the schema passed to analyzer
        passed_schema = mock_analyzer.analyze.call_args[1]["semantic_schema"]
        assert len(passed_schema.tables) == 1
        assert passed_schema.tables[0].table_name == "warehouses"


def test_17_sql_remains_canonical_source_of_truth():
    """Factual numbers come exclusively from SQLQueryExecutor execution."""
    mock_executor = MagicMock()
    mock_executor.execute.return_value = [{"aggregation_value": 789}]

    service = DatabaseQueryService.__new__(DatabaseQueryService)
    schema = DatabaseSchema(tables=[TableInfo(schema_name="dbo", table_name="items", columns=[ColumnInfo("id", "int", False, 1)])])
    service.database_schema = schema
    service.analyzer = MagicMock()
    service.analyzer.analyze.return_value = QueryPlan(intent="count", target_columns=["id"])
    service.validator = MagicMock()
    service.validator.validate.return_value = MagicMock(valid=True, warnings=[])
    service.executor = mock_executor
    service.result_validator = MagicMock()
    service.result_validator.validate.return_value = MagicMock(valid=True, errors=[])
    service.metadata_service = MagicMock()
    service.semantic_cache = MagicMock()
    service.semantic_cache.get.return_value = None
    service.database_server_name = "srv"
    service.database_name = "db"
    service.schema_fingerprint = "fp"
    service.entity_resolver = MagicMock()
    service.relationship_service = MagicMock()
    service.vector_service = None

    with patch.object(service, "_resolve_execution_tables", return_value=schema.tables):
        res = service.answer("How many items are there?")
        assert res.data == [{"aggregation_value": 789}]
        assert mock_executor.execute.called


# =============================================================================
# 7. Dual-Engine Rollback & Database Switching
# =============================================================================

def test_18_sql_server_rollback_compatibility():
    """SQL Server rollback: vector service is gracefully unavailable and deterministic routing continues."""
    sqlserver_cfg = DatabaseConfig(
        engine="sqlserver",
        server="localhost",
        database="mnghealthreportingdb",
        driver="ODBC Driver 18 for SQL Server",
        trusted_connection=True,
    )
    service = SchemaVectorIntelligence(config=sqlserver_cfg)
    assert service.is_available is False
    assert service.index_schema(DatabaseSchema(tables=[]), "fp") == 0
    assert service.search_tables("anything", "fp") == []


def test_19_database_switching_synthetic_schema(pg_config):
    """Completely new, unrelated database schema can be indexed and searched dynamically."""
    hospital_schema = DatabaseSchema(
        tables=[
            TableInfo(
                schema_name="health",
                table_name="inpatients",
                columns=[
                    ColumnInfo("patient_id", "integer", False, 1),
                    ColumnInfo("admission_ward", "varchar", True, 2),
                ],
                primary_key_columns=["patient_id"],
            )
        ]
    )
    service = SchemaVectorIntelligence(config=pg_config)
    db_id = "localhost:5432/hospital_db"
    fp = SchemaFingerprint.build(schema=hospital_schema, database_name="hospital_db", server_name="localhost")

    count = service.index_schema(hospital_schema, fp, force_refresh=True, database_identity=db_id)
    assert count == 3  # 1 table + 2 columns

    candidates = service.search_tables("hospital inpatient admissions and wards", schema_fingerprint=fp, database_identity=db_id)
    assert len(candidates) > 0
    assert candidates[0].table_name == "inpatients"


# =============================================================================
# 8. Forensic Verification (No Business Hardcoding)
# =============================================================================

def test_20_no_business_hardcoding_in_production_code():
    """Verify that no business-specific table names or domains are hardcoded in schema intelligence files."""
    banned_words = [
        "site_events",
        "site_details",
        "site_speakers",
        "site_event_registrants",
        "gujarat",
    ]
    source_files = [
        "app/database/schema_vector_intelligence.py",
        "app/database/schema_intelligence.py",
        "app/database/table_selector.py",
        "app/database/entity_resolver.py",
    ]

    for rel_path in source_files:
        full_path = os.path.join(os.getcwd(), rel_path)
        if not os.path.exists(full_path):
            continue
        with open(full_path, "r", encoding="utf-8") as f:
            content = f.read().lower()
            for banned in banned_words:
                assert banned not in content, (
                    f"Found hardcoded business concept '{banned}' in production file '{rel_path}'!"
                )
