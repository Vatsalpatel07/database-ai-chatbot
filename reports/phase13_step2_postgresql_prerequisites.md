# Phase 13 — Step 2: PostgreSQL + pgvector + SQLAlchemy Prerequisite Setup Report

**Execution Date**: 2026-09-30  
**Phase**: Phase 13 (Migration Setup) — Step 2  
**Scope Status**: Prerequisites installed and verified outside application runtime. Application source code and existing SQL Server configuration remain untouched.

---

## 1. Environment & Prerequisite Summary

| Item | Requirement | Installed / Configured Value | Status |
| :--- | :--- | :--- | :---: |
| **PostgreSQL Version** | PostgreSQL 18.x on Windows x64 | **PostgreSQL 18.6** (`x86_64-windows, compiled by msvc-19.44.35228, 64-bit`) | **PASSED** |
| **pgvector Server Build** | Explicit PostgreSQL 18 Windows build | **v0.8.6 for PostgreSQL 18** (Windows x64) | **PASSED** |
| **vector.control Location** | PostgreSQL 18 extension directory | `C:\Program Files\PostgreSQL\18\data\pgvector\share\extension\vector.control` | **PASSED** |
| **vector.dll Location** | PostgreSQL 18 library directory | `C:\Program Files\PostgreSQL\18\data\pgvector\lib\vector.dll` (280,064 bytes) | **PASSED** |
| **`CREATE EXTENSION` Result** | Execute in `mnghealthreportingdb` | `CREATE EXTENSION vector;` executed successfully | **PASSED** |
| **Installed vector Extension Version**| Verify in `pg_extension` | **`0.8.6`** | **PASSED** |
| **Python SQLAlchemy Version** | SQLAlchemy 2.x | **`2.1.1`** | **PASSED** |
| **Python pgvector Version** | Python pgvector package | **`0.5.0`** | **PASSED** |
| **psycopg (psycopg 3) Version** | Modern psycopg 3 driver | **`3.3.6`** (`psycopg-binary 3.3.6`) | **PASSED** |
| **SQLAlchemy + psycopg Connection** | Connect to `mnghealthreportingdb` | Successfully connected via `postgresql+psycopg` | **PASSED** |
| **SQLAlchemy + pgvector Integration** | `VECTOR(3)` column & distance ops | Insert, retrieve, and distance calculations verified | **PASSED** |
| **Temporary Object Cleanup** | Clean up test tables | All temporary tables dropped without residue | **PASSED** |
| **Regression Check** | Full project test suite | **265 / 265 passed** (100% green) | **PASSED** |

---

## 2. Server-Side pgvector Installation Details

1. **Binary Build Acquired**:
   - Package: `vector.v0.8.6-pg18.zip` (explicitly built for PostgreSQL 18 Windows x64).
   - Upstream tag: `andreiramani/pgvector_pgsql_windows` v0.8.6 for PostgreSQL 18.
2. **PostgreSQL 18 Multi-Path Extension Configuration**:
   - Because standard programmatic installation into `C:\Program Files` without interactive UAC elevation is restricted on Windows, we utilized PostgreSQL 18's official multi-path extension configuration parameter:
     - `extension_control_path = 'C:/Program Files/PostgreSQL/18/data/pgvector/share'`
     - `dynamic_library_path = 'C:/Program Files/PostgreSQL/18/data/pgvector/lib;$libdir'`
   - Configured permanently via `ALTER SYSTEM` and applied cleanly via `pg_reload_conf()`.
3. **Database Extension Registration**:
   - Connected to `mnghealthreportingdb` using administrative role.
   - Executed: `CREATE EXTENSION IF NOT EXISTS vector;`.
   - Verified via catalog query:
     ```sql
     SELECT extname, extversion FROM pg_extension WHERE extname = 'vector';
     ```
     Returned: `('vector', '0.8.6')`.

---

## 3. Basic Vector Functionality Verification

A standalone test against `mnghealthreportingdb` verified:
- **Table Creation**: `CREATE TEMP TABLE phase13_vector_test (id integer, embedding vector(3));`
- **Insertion**: Inserted 3-dimensional floating point vectors `[1.0, 2.0, 3.0]`, `[4.0, 5.0, 6.0]`, and `[1.1, 2.1, 3.1]`.
- **Retrieval**: Vectors successfully returned and parsed as vector representations.
- **Distance Operations**:
  - Euclidean (L2) distance (`<->`): Distance between `[1.0, 2.0, 3.0]` and itself is `0.0000`; distance to `[1.1, 2.1, 3.1]` is `0.1732`.
  - Cosine distance (`<=>`): Cosine distance to `[1.1, 2.1, 3.1]` is `0.0001`.
- **Cleanup**: `DROP TABLE phase13_vector_test;` executed cleanly.

---

## 4. Python Driver & ORM Verification

### SQLAlchemy 2.x + psycopg 3
- Verified connection string construction using `URL.create(drivername="postgresql+psycopg", ...)` to safely encode any special characters in credentials.
- **Dialect**: `postgresql`
- **Driver**: `psycopg` (psycopg 3)
- Evaluated `SELECT version();` and `SELECT current_database();` (`mnghealthreportingdb`).

### SQLAlchemy + pgvector Integration
- Verified using `from pgvector.sqlalchemy import VECTOR`.
- Mapped temporary test table:
  ```python
  Table(
      "phase13_sa_vector_test",
      metadata,
      Column("id", Integer, primary_key=True),
      Column("embedding", VECTOR(3)),
      prefixes=["TEMPORARY"]
  )
  ```
- Inserted vectors using SQLAlchemy `insert()`.
- Retrieved vectors via SQLAlchemy `select()` into Python lists.
- Executed distance filtering and sorting using `temp_table.c.embedding.l2_distance(...)` and `temp_table.c.embedding.cosine_distance(...)`.
- Dropped test table without touching any existing application tables.

---

## 5. Non-Interference & Regression Check

1. **SQL Server Untouched**:
   - Microsoft SQL Server 2025 instance on `localhost` continues serving `mnghealthreportingdb`.
   - `.env` and `app/core/config.py` remain pointed at SQL Server.
   - All 67 populated tables in SQL Server retain full data integrity.
2. **Application Code Untouched**:
   - No QueryPlan, analyzer, executor, metadata service, or API files were modified.
3. **Regression Suite**:
   - Full test run: `python -m pytest -q`
   - Result: **265 passed, 1 warning in 7.07s**.

---

## 6. Stop Condition

Step 2 is **COMPLETE**. No application code has been switched to PostgreSQL, no data has been migrated, and no further steps have been started.
