# Phase 13 Step 4: Database Connection & Infrastructure Audit Report

- **Audit Date**: 2026-10-01
- **Current Active Engine**: Microsoft SQL Server (`localhost` / `mnghealthreportingdb.dbo` via `pyodbc`)
- **Target Migration Engine**: PostgreSQL 18.6 (`localhost:5432` / `mnghealthreportingdb.dbo` via `SQLAlchemy 2.x` + `psycopg 3`)
- **Audit Scope**: Complete application source tree (`app/`) and test infrastructure (`tests/`).

---

## 1. Executive Summary

This forensic audit identifies all SQL Server-specific components, dependencies, dialect queries, identifier quotings, limit semantics, and connection lifecycles across the application. 

The audit reveals that the core business logic, query planning (`QueryPlan`), intent routing, table selection, entity resolution, result validation, and answer generation are largely database-agnostic. However, the database connectivity, catalog discovery, SQL rendering, and conversation persistence layers contain specific SQL Server dependencies that require clean, dialect-aware adaptations for PostgreSQL while maintaining full rollback/reference compatibility with SQL Server.

---

## 2. Forensic File-by-File Dependency Audit

| File | Function / Class | SQL Server Dependency | Replacement Required for PostgreSQL? | Proposed Replacement |
| :--- | :--- | :--- | :--- | :--- |
| `app/core/config.py` | `DatabaseConfig` | SQL Server ODBC keywords (`ODBC Driver 18`, `Trusted_Connection`, `Encrypt`, `TrustServerCertificate`, `UID`/`PWD`). | **Yes** | Add canonical engine selection (`DB_ENGINE=postgresql`), PostgreSQL host/port/user/password/database/schema settings, and construct `postgresql+psycopg://...` SQLAlchemy URL. Preserve SQL Server configuration for reference/rollback. |
| `app/core/config.py` | `Settings` | Exposes `db_server`, `db_name`, `db_driver`, `db_trust_server_certificate`. | **Yes** | Expose canonical engine properties (`db_engine`, `db_schema`, `db_port`, `database_url`). |
| `app/database/connection.py` | `get_connection()` | Imports `pyodbc`, creates direct pyodbc connection via ODBC connection string. | **Yes** | Implement canonical SQLAlchemy 2.x Engine using `psycopg` driver with connection pooling (`pool_pre_ping=True`, FastAPI-appropriate pool sizes). Provide a dialect-aware execution interface (`get_engine()`, `get_connection()`). |
| `app/database/connection.py` | `test_connection()` | Executes `SELECT DB_NAME(), @@SERVERNAME` on SQL Server cursor. | **Yes** | Support dialect-aware test query: for PostgreSQL, `SELECT current_database(), current_schema(), version()`. |
| `app/database/schema.py` | `get_database_schema()` (Step 2 - PKs) | Queries SQL Server catalog: `sys.tables`, `sys.schemas`, `sys.indexes`, `sys.index_columns`, `sys.columns` with `i.is_primary_key = 1`. | **Yes** | Add PostgreSQL catalog query: query `information_schema.table_constraints` and `information_schema.key_column_usage` where `constraint_type = 'PRIMARY KEY'` and `table_schema = 'dbo'`. |
| `app/database/schema.py` | `get_database_schema()` (Step 3 - FKs) | Queries SQL Server catalog: `sys.foreign_keys`, `sys.foreign_key_columns`, `sys.tables`. | **Yes** | Add PostgreSQL catalog query for foreign keys via `information_schema.table_constraints` / `referential_constraints` (returns 0 rows on both engines). |
| `app/database/schema.py` | `get_database_schema()` (Step 4 - UQs) | Queries SQL Server catalog: `sys.key_constraints kc WHERE kc.type = 'UQ'`. | **Yes** | Add PostgreSQL catalog query for unique constraints via `information_schema.table_constraints` where `constraint_type = 'UNIQUE'`. |
| `app/database/schema.py` | `parse_column_reference()` | Strips `[]` brackets: `parts = [p.strip().strip("[]") for p in cleaned.split(".")]`. | **Minor** | Update to strip both square brackets `[]` and double quotes `"`: `.strip('[]"')`. |
| `app/database/metadata_service.py` | `_get_verification_token()` | Queries `sys.tables`, `sys.columns`, `CHECKSUM_AGG(CHECKSUM(...))` and `sys.indexes`. | **Yes** | For PostgreSQL, compute verification token using PostgreSQL catalog (`COUNT(*)` from `information_schema.tables`, `information_schema.columns`, and schema statistics/pg_stat_user_tables). |
| `app/database/metadata_service.py` | `_load_indexes()` | Queries `sys.tables`, `sys.indexes`, `sys.index_columns`, `sys.columns`. | **Yes** | For PostgreSQL, query `pg_index`, `pg_class`, `pg_namespace`, and `pg_attribute` in schema `dbo`. |
| `app/database/metadata_service.py` | `_load_table_metadata()` | Queries `sys.dm_db_partition_stats` grouped by schema and table to get live row counts. | **Yes** | For PostgreSQL, query `pg_stat_user_tables` (`n_live_tup`) or dynamic authoritative row count queries in schema `dbo`. |
| `app/database/sql_executor.py` | `_quote_identifier()` | Uses square brackets: `"[" + identifier.replace("]", "]]") + "]"`. | **Yes** | Dialect-aware quoting: for PostgreSQL, use double quotes `'"' + identifier.replace('"', '""') + '"'`. |
| `app/database/sql_executor.py` | `_render_base_select()`, `_render_grouped_select()`, `_render_fanout_join_select()` | Uses `TOP ({limit}) [WITH TIES]` placed before column list. | **Yes** | For PostgreSQL, render standard SQL pagination: `LIMIT {limit}` or `ORDER BY ... FETCH FIRST {limit} ROWS WITH TIES` appended at end of query. |
| `app/database/sql_executor.py` | Database execution | Uses `with get_connection() as connection: cursor = connection.cursor(); cursor.execute(sql, *params)`. | **Yes** | Execute via canonical SQLAlchemy engine/connection with safe parameter binding (`%s` or `:param` / `text(sql)`). Normalize returned rows into consistent dict/tuple contract. |
| `app/database/relationship_validator.py` | `_quote()`, `validate_relationship()` | Uses `_quote()` with `[]` and `SELECT COUNT_BIG(*) FROM {left_table}`. | **Yes** | Use dialect-aware identifier quoting (`"` for PostgreSQL) and standard `COUNT(*)` (which returns 64-bit integer in PostgreSQL). |
| `app/conversation/conversation_memory.py` | `get_context()` | Uses `SELECT TOP (?) ... FROM dbo.chatbot_conversation WHERE session_id = ? ...`. | **Yes** | Dialect-aware query: for PostgreSQL, use `SELECT ... FROM dbo.chatbot_conversation WHERE session_id = :session_id ORDER BY created_at DESC, id DESC LIMIT :limit`. |
| `app/conversation/conversation_memory.py` | `save()` | Parameter placeholder `?` in `INSERT INTO dbo.chatbot_conversation ... VALUES (?, ?, ...)`. | **Yes** | Use SQLAlchemy / psycopg safe parameter binding (`:param` or `%s`). |
| `app/orchestration/database_orchestrator.py` | `_handle_database_row_statistics_request()` | Uses `f"[{schema_name}].[{table_name}]"` and `SELECT COUNT_BIG(*) AS row_count`. | **Yes** | Use dialect-aware identifier quoting (`"{schema}"."{table}"`) and standard `COUNT(*)`. |

---

## 3. Structural Components That Require Zero Changes

The following subsystems are completely database-agnostic and will remain untouched:
- `app/query/schema.py`: Canonical `QueryPlan` data structures.
- `app/query/analyzer.py`: Natural language understanding and semantic query plan construction.
- `app/query/validator.py`: QueryPlan structural, grain, and fan-out validation.
- `app/query/result_validator.py`: Execution result contract validation.
- `app/query/answer_generator.py`: Response synthesis.
- `app/database/entity_resolver.py`: Semantic entity resolution.
- `app/database/relationship_discovery.py`: Inferred relationship heuristics.
- `app/database/relationship_service.py`: Multi-table JOIN graph algorithms.
- `app/database/table_selector.py`: Keyword/semantic table relevance ranking.
- `app/database/semantic_query_cache.py`: Plan hashing and query result caching.

---

## 4. Planned Migration Architecture

```
                       ┌───────────────────────────────┐
                       │      app/core/config.py       │
                       │   DB_ENGINE=postgresql|mssql  │
                       └───────────────┬───────────────┘
                                       │
                       ┌───────────────▼───────────────┐
                       │  app/database/connection.py   │
                       │  SQLAlchemy 2.x Engine (PG)   │
                       │  pyodbc Connection (MSSQL)    │
                       └───────────────┬───────────────┘
                                       │
     ┌─────────────────────────────────┼─────────────────────────────────┐
     │                                 │                                 │
┌────▼────────────────────┐ ┌──────────▼───────────────┐ ┌───────────────▼───────────────┐
│ app/database/schema.py  │ │app/database/sql_executor │ │app/conversation/conversation_ │
│  Dialect-Aware Catalog  │ │  LIMIT / FETCH WITH TIES │ │          memory.py            │
│  information_schema.    │ │   Double-Quote Ident     │ │  Dialect-Aware SQL & Binding  │
│  table_constraints (PG) │ │   SQLAlchemy Execution   │ │                               │
└─────────────────────────┘ └──────────────────────────┘ └───────────────────────────────┘
```
