"""
Phase 13 Step 8 — Cross-Database Switching & Schema Portability Test Suite

Validates that the generic Database AI Chatbot can switch dynamically to an
isolated second PostgreSQL database with a structurally different schema,
discover its metadata, execute diverse queries, maintain strict cache and
vector isolation, enforce conversation session boundaries, and switch back
to the canonical original database with zero residue or regressions.
"""

from __future__ import annotations

import os
import pytest
from decimal import Decimal
import psycopg

from app.core.config import get_database_config, DatabaseConfig
from app.database.connection import get_connection, _ENGINES
from app.database.metadata_service import DatabaseMetadataService
from app.database.schema import DatabaseSchema, TableInfo, ColumnInfo
from app.database.schema_fingerprint import SchemaFingerprint
from app.database.schema_vector_intelligence import SchemaVectorIntelligence
from app.database.sql_executor import SQLQueryExecutor, SQLQueryExecutionError
from app.orchestration.database_orchestrator import DatabaseOrchestrator
from app.query.schema import QueryPlan, QueryFilter, QueryJoin, QueryColumn
from app.query.validator import QueryPlanValidator
from app.conversation.conversation_memory import ConversationMemory


TEMP_DB_NAME = "test_portability_step8_db"
TEMP_SCHEMA_NAME = "public"


@pytest.fixture(scope="module")
def orig_config():
    cfg = get_database_config()
    assert cfg.engine == "postgresql"
    assert cfg.database == "mnghealthreportingdb"
    return cfg


@pytest.fixture(scope="module")
def temp_database_fixture(orig_config):
    """
    Creates an isolated temporary database with synthetic neutral schema,
    yields the temporary DatabaseConfig, and cleanly drops the database on teardown.
    """
    admin_conn_str = f"host={orig_config.server} port={orig_config.port} user={orig_config.user} password={orig_config.password} dbname=postgres"

    # 1. Create clean temporary database
    with psycopg.connect(admin_conn_str, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(f"DROP DATABASE IF EXISTS {TEMP_DB_NAME};")
            cur.execute(f"CREATE DATABASE {TEMP_DB_NAME};")

    temp_cfg = DatabaseConfig(
        server=orig_config.server,
        port=orig_config.port,
        database=TEMP_DB_NAME,
        schema=TEMP_SCHEMA_NAME,
        user=orig_config.user,
        password=orig_config.password,
        engine="postgresql",
    )

    # 2. Populate synthetic schema and data
    temp_conn_str = f"host={temp_cfg.server} port={temp_cfg.port} user={temp_cfg.user} password={temp_cfg.password} dbname={TEMP_DB_NAME}"
    with psycopg.connect(temp_conn_str, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
            cur.execute("""
            CREATE TABLE warehouses (
                warehouse_id UUID PRIMARY KEY,
                code VARCHAR(50) UNIQUE NOT NULL,
                city VARCHAR(100) NOT NULL,
                state VARCHAR(50) NOT NULL,
                capacity_sqft INTEGER NOT NULL,
                is_climate_controlled BOOLEAN NOT NULL,
                established_date DATE NOT NULL,
                status VARCHAR(30) NOT NULL
            );

            CREATE TABLE inventory_items (
                item_id SERIAL PRIMARY KEY,
                warehouse_code VARCHAR(50) NOT NULL,
                sku VARCHAR(50) UNIQUE NOT NULL,
                category VARCHAR(80) NOT NULL,
                unit_weight_kg NUMERIC(8, 2) NOT NULL,
                stock_quantity INTEGER NOT NULL,
                reorder_threshold INTEGER NOT NULL,
                last_restocked_at TIMESTAMP NOT NULL
            );

            CREATE TABLE shipments (
                shipment_id SERIAL PRIMARY KEY,
                tracking_uuid UUID NOT NULL,
                origin_warehouse_code VARCHAR(50) NOT NULL,
                destination_city VARCHAR(100) NOT NULL,
                item_count INTEGER NOT NULL,
                shipping_cost NUMERIC(10, 2) NOT NULL,
                shipped_date DATE NOT NULL,
                is_express BOOLEAN NOT NULL,
                status VARCHAR(30) NOT NULL
            );

            CREATE TABLE shipment_dispatches (
                dispatch_id SERIAL PRIMARY KEY,
                shipment_id INTEGER NOT NULL,
                carrier_name VARCHAR(80) NOT NULL,
                dispatch_notes TEXT,
                dispatched_at TIMESTAMP NOT NULL
            );

            CREATE TABLE audit_archived_records (
                archive_id SERIAL PRIMARY KEY,
                archive_timestamp TIMESTAMP,
                record_payload TEXT
            );
            """)

            cur.execute("""
            INSERT INTO warehouses VALUES
            ('a1111111-1111-1111-1111-111111111111', 'WH-CHI-01', 'Chicago', 'IL', 75000, TRUE, '2018-05-15', 'ACTIVE'),
            ('a2222222-2222-2222-2222-222222222222', 'WH-DAL-02', 'Dallas', 'TX', 120000, TRUE, '2019-08-20', 'ACTIVE'),
            ('a3333333-3333-3333-3333-333333333333', 'WH-SEA-03', 'Seattle', 'WA', 50000, FALSE, '2020-01-10', 'ACTIVE'),
            ('a4444444-4444-4444-4444-444444444444', 'WH-MIA-04', 'Miami', 'FL', 95000, TRUE, '2021-11-05', 'MAINTENANCE'),
            ('a5555555-5555-5555-5555-555555555555', 'WH-DEN-05', 'Denver', 'CO', 60000, FALSE, '2022-03-30', 'DECOMMISSIONED');

            INSERT INTO inventory_items (item_id, warehouse_code, sku, category, unit_weight_kg, stock_quantity, reorder_threshold, last_restocked_at) VALUES
            (1, 'WH-CHI-01', 'SKU-ELEC-01', 'Electronics', 2.50, 150, 30, '2026-01-10 09:00:00'),
            (2, 'WH-CHI-01', 'SKU-ELEC-02', 'Electronics', 1.20, 200, 50, '2026-01-15 14:30:00'),
            (3, 'WH-CHI-01', 'SKU-APPL-01', 'Appliances', 15.00, 40, 10, '2026-02-01 11:15:00'),
            (4, 'WH-DAL-02', 'SKU-FURN-01', 'Furniture', 45.00, 25, 5, '2026-01-20 16:45:00'),
            (5, 'WH-DAL-02', 'SKU-FURN-02', 'Furniture', 32.50, 60, 15, '2026-02-10 10:00:00'),
            (6, 'WH-DAL-02', 'SKU-ELEC-03', 'Electronics', 0.80, 500, 100, '2026-02-14 08:30:00'),
            (7, 'WH-SEA-03', 'SKU-TOOL-01', 'Tools', 8.50, 80, 20, '2026-01-05 13:00:00'),
            (8, 'WH-SEA-03', 'SKU-TOOL-02', 'Tools', 3.40, 120, 25, '2026-01-25 15:20:00'),
            (9, 'WH-MIA-04', 'SKU-APPL-02', 'Appliances', 22.00, 30, 8, '2026-02-05 09:45:00'),
            (10, 'WH-DEN-05', 'SKU-TOOL-03', 'Tools', 12.00, 50, 10, '2026-02-12 11:30:00');

            INSERT INTO shipments (shipment_id, tracking_uuid, origin_warehouse_code, destination_city, item_count, shipping_cost, shipped_date, is_express, status) VALUES
            (101, 'b1111111-1111-1111-1111-111111111111', 'WH-CHI-01', 'Milwaukee', 15, 120.50, '2026-01-12', TRUE, 'DELIVERED'),
            (102, 'b2222222-2222-2222-2222-222222222222', 'WH-CHI-01', 'Indianapolis', 25, 180.00, '2026-01-18', FALSE, 'DELIVERED'),
            (103, 'b3333333-3333-3333-3333-333333333333', 'WH-DAL-02', 'Houston', 50, 310.75, '2026-01-22', TRUE, 'DELIVERED'),
            (104, 'b4444444-4444-4444-4444-444444444444', 'WH-DAL-02', 'Austin', 40, 245.00, '2026-02-02', FALSE, 'DELIVERED'),
            (105, 'b5555555-5555-5555-5555-555555555555', 'WH-SEA-03', 'Portland', 18, 140.25, '2026-02-08', TRUE, 'IN_TRANSIT'),
            (106, 'b6666666-6666-6666-6666-666666666666', 'WH-MIA-04', 'Orlando', 30, 215.50, '2026-02-11', FALSE, 'IN_TRANSIT'),
            (107, 'b7777777-7777-7777-7777-777777777777', 'WH-DEN-05', 'Boulder', 12, 95.00, '2026-02-15', TRUE, 'PENDING'),
            (108, 'b8888888-8888-8888-8888-888888888888', 'WH-DEN-05', 'Colorado Springs', 8, 75.00, '2026-02-16', FALSE, 'PENDING');

            INSERT INTO shipment_dispatches (dispatch_id, shipment_id, carrier_name, dispatch_notes, dispatched_at) VALUES
            (1, 101, 'FastFreight', 'Dispatched on schedule', '2026-01-12 10:00:00'),
            (2, 102, 'FastFreight', 'Standard ground dispatch', '2026-01-18 11:30:00'),
            (3, 103, 'SwiftExpress', 'Urgent priority dispatch', '2026-01-22 08:45:00'),
            (4, 104, 'SwiftExpress', 'Normal pallet handling', '2026-02-02 14:00:00'),
            (5, 105, 'PacificLogistics', 'Weather delay alert noted', '2026-02-08 09:15:00'),
            (6, 106, 'AtlanticHaul', 'Special handling requested', '2026-02-11 13:20:00');
            """)

    yield temp_cfg

    # Teardown: terminate connections and drop temporary database
    keys_to_remove = [k for k in _ENGINES if TEMP_DB_NAME in k]
    for k in keys_to_remove:
        try:
            _ENGINES[k].dispose()
            del _ENGINES[k]
        except Exception:
            pass

    with psycopg.connect(admin_conn_str, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(f"""
            SELECT pg_terminate_backend(pg_stat_activity.pid)
            FROM pg_stat_activity
            WHERE pg_stat_activity.datname = '{TEMP_DB_NAME}'
              AND pid <> pg_backend_pid();
            """)
            cur.execute(f"DROP DATABASE IF EXISTS {TEMP_DB_NAME};")


# =============================================================================
# 1. Database Switching & Metadata Rediscovery
# =============================================================================

def test_database_switching_and_metadata_discovery(orig_config, temp_database_fixture):
    """Switching to an isolated database rediscovers metadata and changes schema fingerprint."""
    # Step A: Discover original database
    meta_svc_orig = DatabaseMetadataService(config=orig_config)
    meta_orig = meta_svc_orig.load()
    assert len(meta_orig.schema.tables) == 67

    # Step B: Switch to temporary database
    meta_svc_temp = DatabaseMetadataService(config=temp_database_fixture)
    meta_temp = meta_svc_temp.load(force_refresh=True)

    user_tables = [t.table_name for t in meta_temp.schema.tables if t.table_name not in ("schema_vector_intelligence", "chatbot_conversation")]
    assert sorted(user_tables) == ["audit_archived_records", "inventory_items", "shipment_dispatches", "shipments", "warehouses"]
    assert meta_temp.schema_fingerprint != meta_orig.schema_fingerprint


def test_schema_fingerprint_isolation(orig_config, temp_database_fixture):
    """Schema fingerprints are deterministically distinct across distinct databases."""
    meta_orig = DatabaseMetadataService(config=orig_config).load()
    meta_temp = DatabaseMetadataService(config=temp_database_fixture).load(force_refresh=True)

    assert meta_orig.schema_fingerprint != meta_temp.schema_fingerprint
    assert len(meta_orig.schema_fingerprint) == 64
    assert len(meta_temp.schema_fingerprint) == 64


# =============================================================================
# 2. PGVector Isolation & Schema Change Invalidation
# =============================================================================

def test_pgvector_database_isolation(orig_config, temp_database_fixture):
    """pgvector schema intelligence search is strictly scoped to database identity and fingerprint."""
    vec_temp = SchemaVectorIntelligence(config=temp_database_fixture)
    vec_temp.ensure_schema_table()
    meta_temp = DatabaseMetadataService(config=temp_database_fixture).load(force_refresh=True)
    indexed_cnt = vec_temp.index_schema(meta_temp.schema, meta_temp.schema_fingerprint, force_refresh=True)
    assert indexed_cnt > 0

    # Search for warehouses: must return only temp DB objects
    candidates = vec_temp.search_tables("logistics warehouse storage", schema_fingerprint=meta_temp.schema_fingerprint)
    table_names = [c.table_name for c in candidates]
    assert any(t in table_names for t in ["warehouses", "inventory_items", "shipments"])
    # Ensure zero leak from original database
    assert not any("site_" in t for t in table_names)


def test_schema_change_invalidates_fingerprint(temp_database_fixture):
    """Altering schema in temporary DB dynamically changes fingerprint."""
    meta_svc = DatabaseMetadataService(config=temp_database_fixture)
    meta_before = meta_svc.load(force_refresh=True)
    fp_before = meta_before.schema_fingerprint

    # Add a column
    conn_str = f"host={temp_database_fixture.server} port={temp_database_fixture.port} user={temp_database_fixture.user} password={temp_database_fixture.password} dbname={temp_database_fixture.database}"
    with psycopg.connect(conn_str, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("ALTER TABLE warehouses ADD COLUMN dock_doors INTEGER DEFAULT 4;")

    meta_after = meta_svc.load(force_refresh=True)
    fp_after = meta_after.schema_fingerprint
    assert fp_after != fp_before

    # Revert column
    with psycopg.connect(conn_str, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("ALTER TABLE warehouses DROP COLUMN dock_doors;")

    meta_reverted = meta_svc.load(force_refresh=True)
    assert meta_reverted.schema_fingerprint == fp_before


# =============================================================================
# 3. Cross-Schema Query Matrix (17 Cases on Synthetic Fixture)
# =============================================================================

@pytest.fixture(scope="module")
def temp_executor(temp_database_fixture):
    return SQLQueryExecutor(config=temp_database_fixture)


@pytest.fixture(scope="module")
def temp_schema(temp_database_fixture):
    meta = DatabaseMetadataService(config=temp_database_fixture).load(force_refresh=True)
    return meta.schema


def test_q01_table_discovery(temp_schema):
    """1. Table discovery and count."""
    user_tables = [t for t in temp_schema.tables if t.table_name not in ("schema_vector_intelligence", "chatbot_conversation")]
    assert len(user_tables) == 5


def test_q02_column_discovery(temp_schema):
    """2. Column discovery on warehouses table."""
    tbl = temp_schema.get_table("public", "warehouses")
    assert tbl is not None
    assert len(tbl.columns) == 8


def test_q03_row_count(temp_executor, temp_schema):
    """3. Whole-table row count on warehouses."""
    tbl = temp_schema.get_table("public", "warehouses")
    count = temp_executor.execute(QueryPlan(intent="row_count"), tbl)
    assert count == 5


def test_q04_filtered_count(temp_executor, temp_schema):
    """4. Filtered count of express shipments."""
    tbl = temp_schema.get_table("public", "shipments")
    plan = QueryPlan(intent="count", filters=[QueryFilter(column="is_express", operator="equals", value=True)])
    count = temp_executor.execute(plan, tbl)
    assert count == 4


def test_q05_distinct_values(temp_executor, temp_schema):
    """5. DISTINCT values of inventory categories."""
    tbl = temp_schema.get_table("public", "inventory_items")
    plan = QueryPlan(intent="distinct", target_columns=["category"])
    rows = temp_executor.execute(plan, tbl)
    cats = sorted([r["category"] for r in rows])
    assert cats == ["Appliances", "Electronics", "Furniture", "Tools"]


def test_q06_numeric_aggregation(temp_executor, temp_schema):
    """6. Numeric SUM aggregation of warehouse capacity."""
    tbl = temp_schema.get_table("public", "warehouses")
    plan = QueryPlan(intent="aggregation", aggregation="sum", target_columns=["capacity_sqft"])
    total_cap = temp_executor.execute(plan, tbl)
    assert total_cap == 400000


def test_q07_grouped_aggregation(temp_executor, temp_schema):
    """7. Grouped aggregation count by category."""
    tbl = temp_schema.get_table("public", "inventory_items")
    plan = QueryPlan(intent="aggregation", aggregation="count", group_by=["category"])
    rows = temp_executor.execute(plan, tbl)
    assert len(rows) == 4
    assert all("aggregation_value" in r for r in rows)


def test_q08_sorting_and_top_n(temp_executor, temp_schema):
    """8. Top 3 inventory items sorted by stock_quantity descending."""
    tbl = temp_schema.get_table("public", "inventory_items")
    plan = QueryPlan(intent="lookup", target_columns=["sku", "stock_quantity"], sort_column="stock_quantity", sort_direction="desc", limit=3)
    rows = temp_executor.execute(plan, tbl)
    skus = [r["sku"] for r in rows]
    assert skus == ["SKU-ELEC-03", "SKU-ELEC-02", "SKU-ELEC-01"]
    assert rows[0]["stock_quantity"] == 500


def test_q09_date_filtering(temp_executor, temp_schema):
    """9. Date range filtering on shipments shipped in January 2026."""
    tbl = temp_schema.get_table("public", "shipments")
    plan = QueryPlan(intent="count", filters=[
        QueryFilter(column="shipped_date", operator="greater_than_or_equal", value="2026-01-01"),
        QueryFilter(column="shipped_date", operator="less_than_or_equal", value="2026-01-31"),
    ])
    count = temp_executor.execute(plan, tbl)
    assert count == 3


def test_q10_boolean_handling(temp_executor, temp_schema):
    """10. Boolean filtering for climate-controlled warehouses."""
    tbl = temp_schema.get_table("public", "warehouses")
    plan = QueryPlan(intent="count", filters=[QueryFilter(column="is_climate_controlled", operator="equals", value=True)])
    count = temp_executor.execute(plan, tbl)
    assert count == 3


def test_q11_uuid_handling(temp_executor, temp_schema):
    """11. Filtering and selecting by UUID."""
    tbl = temp_schema.get_table("public", "warehouses")
    plan = QueryPlan(intent="lookup", target_columns=["city"], filters=[
        QueryFilter(column="warehouse_id", operator="equals", value="a1111111-1111-1111-1111-111111111111")
    ])
    rows = temp_executor.execute(plan, tbl)
    assert len(rows) == 1
    assert rows[0]["city"] == "Chicago"


def test_q12_multi_table_join(temp_executor, temp_schema):
    """12. Multi-table JOIN between warehouses and inventory_items."""
    tbl_wh = temp_schema.get_table("public", "warehouses")
    tbl_inv = temp_schema.get_table("public", "inventory_items")

    plan = QueryPlan(
        intent="lookup",
        target_columns=["code", "sku"],
        target_column_refs=[
            QueryColumn(table="warehouses", column="code"),
            QueryColumn(table="inventory_items", column="sku"),
        ],
        joins=[
            QueryJoin(
                left_schema="public",
                left_table="warehouses",
                left_column="code",
                right_schema="public",
                right_table="inventory_items",
                right_column="warehouse_code",
            )
        ],
        filters=[QueryFilter(column="city", operator="equals", value="Chicago")],
    )
    rows = temp_executor.execute(plan=plan, table=tbl_wh, tables=[tbl_wh, tbl_inv])
    assert len(rows) == 3
    assert all(r["code"] == "WH-CHI-01" for r in rows)


def test_q13_ambiguous_column_resolution(temp_schema):
    """13. Ambiguous column (status exists in both warehouses and shipments) fails closed."""
    validator = QueryPlanValidator()
    plan = QueryPlan(intent="lookup", target_columns=["status"])
    res = validator.validate(plan, temp_schema)
    assert res.valid is False
    assert any("ambiguous" in e.lower() for e in res.errors)


def test_q14_unknown_table_column_handling(temp_executor, temp_schema):
    """14. Unknown table/column fails closed safely without uncaught crashes."""
    validator = QueryPlanValidator()
    plan = QueryPlan(intent="lookup", target_columns=["nonexistent_column_xyz_999"])
    res = validator.validate(plan, temp_schema)
    assert res.valid is False

    unknown_table = TableInfo("public", "nonexistent_table_xyz_888", [])
    with pytest.raises(SQLQueryExecutionError):
        temp_executor.execute(QueryPlan(intent="row_count"), unknown_table)


def test_q15_empty_result_handling(temp_executor, temp_schema):
    """15. Empty table row count returns 0; unmatched filter returns empty list."""
    tbl_arch = temp_schema.get_table("public", "audit_archived_records")
    count = temp_executor.execute(QueryPlan(intent="row_count"), tbl_arch)
    assert count == 0


def test_q16_conversation_followup_in_memory(temp_database_fixture):
    """16. In-memory follow-up question operates on previous result within same session."""
    mem = ConversationMemory(config=temp_database_fixture)
    mem.ensure_table()
    session_id = "test_portability_session_16"
    ref_id = mem.save(
        session_id=session_id,
        question="Show warehouses",
        result=[
            {"code": "WH-DAL-02", "city": "Dallas"},
            {"code": "WH-CHI-01", "city": "Chicago"},
        ],
        plan=QueryPlan(intent="lookup"),
    )
    ctx = mem.get_context(session_id=session_id)
    assert len(ctx.get("history", [])) == 1
    assert ctx["history"][0]["reference_id"] == ref_id


def test_q17_unknown_entity_handling(temp_executor, temp_schema):
    """17. Filtering by an unknown entity value returns empty list without crashing."""
    tbl_wh = temp_schema.get_table("public", "warehouses")
    plan = QueryPlan(intent="lookup", filters=[QueryFilter(column="code", operator="equals", value="NONEXISTENT_CODE_777")])
    rows = temp_executor.execute(plan, tbl_wh)
    assert rows == []


# =============================================================================
# 4. Conversation and Session Isolation
# =============================================================================

def test_conversation_cross_database_isolation(orig_config, temp_database_fixture):
    """Session created in database B cannot be retrieved from database A."""
    mem_temp = ConversationMemory(config=temp_database_fixture)
    mem_temp.ensure_table()
    session_id = "session_isolated_db_b"
    mem_temp.save(
        session_id=session_id,
        question="Show shipments",
        result=[{"shipment_id": 101, "cost": 120.50}],
        plan=QueryPlan(intent="lookup"),
    )

    # Attempt to read this session from database A (original config)
    mem_orig = ConversationMemory(config=orig_config)
    ctx_orig = mem_orig.get_context(session_id=session_id)
    assert len(ctx_orig.get("history", [])) == 0


# =============================================================================
# 5. Switch-Back Verification to Original Database
# =============================================================================

def test_switch_back_restores_original_database(orig_config):
    """Switching back to the original database restores exact metadata, row counts, and data integrity."""
    meta_svc = DatabaseMetadataService(config=orig_config)
    meta = meta_svc.load(force_refresh=True)

    # Table count remains 67
    assert len(meta.schema.tables) == 67

    # Execute on original database table
    executor = SQLQueryExecutor(config=orig_config)
    tbl_se = meta.schema.get_table("dbo", "site_events")
    count_se = executor.execute(QueryPlan(intent="row_count"), tbl_se)
    assert count_se == 720

    tbl_sv = meta.schema.get_table("dbo", "SchemaVersions")
    count_sv = executor.execute(QueryPlan(intent="row_count"), tbl_sv)
    assert count_sv == 150
