# Phase 13 — Step 5: Generic Database Schema Intelligence + pgvector Foundation Report

## 1. Executive Summary & Objective

In **Phase 13 — Step 5**, we designed, implemented, and verified a completely **database-agnostic, generic schema intelligence foundation** powered by PostgreSQL's `pgvector` extension.

The objective was to enable the chatbot to semantically discover and rank schema candidates (tables and columns) using vector similarity without relying on hardcoded business terms, while preserving:
1. Strict database identity and schema fingerprint isolation.
2. Deterministic entity resolution and hybrid candidate ranking.
3. Fail-closed protection against hallucination when entities or metrics are unknown.
4. DeepSeek token minimization (sending at most 5 candidate tables, never the entire 67-table database schema).
5. Seamless dual-engine fallback (`DB_ENGINE=sqlserver` and `DB_ENGINE=postgresql`).
6. 100% test pass rate across all existing baseline tests.

---

## 2. Architecture & Execution Flow

```text
User Question
    │
    ▼
FastAPI /ask/database
    │
    ▼
DatabaseOrchestrator
    │
    ▼
DatabaseQueryService
    │
    ├─► SchemaVectorIntelligence.is_indexed() ──[If stale/missing]──► SchemaVectorIntelligence.index_schema()
    │                                                                         │
    │                                                                 (pgvector: public.schema_vector_intelligence)
    │
    ▼
TableSelector.select_tables() [Hybrid Retrieval Engine]
    ├── Deterministic Lexical Match (DatabaseEntityResolver)
    └── Semantic Vector Similarity Search (SchemaVectorIntelligence <=> operator)
    │
    ▼
Candidate Schema Subset Filter (Top K <= 5 tables)
    │
    ▼
QuestionAnalyzer (DeepSeek LLM receives ONLY Candidate Schema Subset)
    │
    ▼
QueryPlan Validation (Validator & JoinValidator)
    │
    ▼
SQLQueryExecutor (PostgreSQL SQLAlchemy / SQL Server pyodbc)
    │
    ▼
ResultValidator & AnswerGenerator
    │
    ▼
Client Response (SQL is authoritative source of truth)
```

---

## 3. Existing Schema-Intelligence Components Audited

Prior to Step 5, schema discovery and candidate selection were handled by:
1. `app/database/schema_intelligence.py`: `DatabaseSchemaIntelligence` — Rule-based classification of column names and data types (identifiers, foreign keys, timestamps, metrics, names).
2. `app/database/entity_resolver.py`: `DatabaseEntityResolver` — Deterministic token overlap, exact matches, and singular/plural normalization.
3. `app/database/table_selector.py`: `select_tables` — Lexical scoring aggregating column and table matches.
4. `app/database/schema_fingerprint.py`: `SchemaFingerprint` — Structural SHA-256 hash computed over tables, columns, nullability, ordinal positions, and primary keys.
5. `app/database/metadata_cache.py`: On-disk JSON cache storing discovered schema structures.

---

## 4. Components Reused

1. `DatabaseSchemaIntelligence`: Used to enrich table and column semantic representations with inferred roles (`infer_roles`).
2. `DatabaseEntityResolver`: Used as the deterministic lexical scoring baseline in hybrid table selection.
3. `SchemaFingerprint`: Used to tag every vector embedding row, guaranteeing structural cache validity.
4. `DatabaseSchema`, `TableInfo`, `ColumnInfo`: Reused existing structural data contracts without breaking changes.
5. `get_connection`: Reused central connection management supporting PostgreSQL and SQL Server.

---

## 5. Components Modified

1. **`app/database/table_selector.py`**:
   - Updated `select_tables` signature to accept optional `vector_service: SchemaVectorIntelligence | None` and `schema_fingerprint: str | None`.
   - Implemented hybrid candidate scoring: queries `vector_service.search_tables()` when available; computes vector similarity bonus (up to +0.40 confidence score); merges lexical and semantic candidate sets; filters candidates against confidence threshold.
2. **`app/database/query_service.py`**:
   - Initialized `self.vector_service = SchemaVectorIntelligence(config=active_config)` when running on PostgreSQL.
   - Added automatic, idempotent schema indexing in `ensure_schema_indexed()` triggered on query execution.
   - Passed `self.vector_service` and `self.schema_fingerprint` to `_resolve_execution_tables()`.
   - Utilized safe `getattr(self, "vector_service", None)` to maintain 100% backward compatibility with test suites using mocked instances (`__new__`).

---

## 6. New Components Created

1. **`app/database/schema_vector_intelligence.py`**:
   - `SchemaEmbeddingModel`: 384-dimensional deterministic feature hashing embedding model.
   - `SchemaVectorCandidate`: Typed candidate dataclass representing retrieved objects, similarity scores, and metadata.
   - `SchemaVectorIntelligence`: pgvector storage, indexing, similarity search, and cache-invalidation service.
2. **`tests/test_phase13_step5_pgvector.py`**:
   - 20 automated tests validating pgvector availability, embedding reproducibility, database isolation, fingerprint pruning, hybrid table selection, fail-closed handling, token optimization, SQL truthfulness, and dual-engine rollback.

---

## 7. PGVECTOR Storage Design

### Table Specification
- **Table Name**: `public.schema_vector_intelligence`
- **Schema Selection**: Stored in `public` rather than `dbo`. This design decision ensures that `dbo` contains strictly the 67 business tables of `mnghealthreportingdb`, preventing regression against Phase 13 Step 4 schema assertions (`len(schema.tables) == 67`). Because the connection wrapper sets `search_path=dbo,public`, PostgreSQL accesses this table natively.

### DDL Structure
```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS public.schema_vector_intelligence (
    id BIGSERIAL PRIMARY KEY,
    database_identity VARCHAR(255) NOT NULL,
    schema_fingerprint VARCHAR(128) NOT NULL,
    schema_name VARCHAR(128) NOT NULL,
    object_type VARCHAR(32) NOT NULL,       -- 'table' or 'column'
    table_name VARCHAR(128) NOT NULL,
    column_name VARCHAR(128) NULL,
    metadata_text TEXT NOT NULL,
    embedding vector(384) NOT NULL,
    object_key VARCHAR(512) UNIQUE NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_schema_vec_db_fp
    ON public.schema_vector_intelligence (database_identity, schema_fingerprint);

CREATE INDEX IF NOT EXISTS idx_schema_vec_lookup
    ON public.schema_vector_intelligence (database_identity, schema_fingerprint, object_type);
```

---

## 8. Embedding Model Implementation

- **Model Class**: `SchemaEmbeddingModel`
- **Dimensionality**: 384 dimensions dense float array.
- **Normalization**: $L_2$ Euclidean normalization ($||v||_2 = 1.0$).
- **Technique**: High-performance MurmurHash3 feature hashing across:
  - Full whitespace tokens and subwords (splitting snake_case and camelCase).
  - Character 3-grams for typo-resilient morphological similarity.
  - Token bigrams for phrase preservation.
  - Suffix stemming for morphological alignment.
- **Properties**:
  - 100% deterministic and reproducible across processes and runs.
  - Zero external network dependency (no OpenAI or DeepSeek API calls required for embeddings).
  - Sub-millisecond embedding latency.

---

## 9. Schema Fingerprint & Invalidation Mechanics

1. **Fingerprint Stamp**: Every indexed record carries `schema_fingerprint` computed by `SchemaFingerprint.build()`.
2. **Strict Filtering**: All semantic similarity queries filter with `WHERE database_identity = %s AND schema_fingerprint = %s`.
3. **Idempotence**: If `is_indexed(db_id, fp)` returns `True`, indexing is skipped and existing vectors are reused.
4. **Stale Pruning**: When `index_schema(..., force_refresh=True)` runs with a new fingerprint, all older records for that `database_identity` are automatically deleted:
   ```sql
   DELETE FROM public.schema_vector_intelligence
   WHERE database_identity = %s AND schema_fingerprint != %s;
   ```

---

## 10. Database Isolation Mechanism

Embeddings are partitioned by `database_identity` (formatted as `{server}:{port}/{database}`). Queries explicitly filter on this column. Consequently:
- Embeddings from `mnghealthreportingdb` are never returned for a query against `hospital_db` or `logistics_db`.
- Multi-database deployments sharing a single PostgreSQL instance remain completely isolated.

---

## 11. Deterministic vs Semantic Retrieval & Hybrid Candidate Ranking

Table selection combines deterministic lexical matching with semantic vector similarity:
1. **Deterministic Lexical Score** ($S_{lex} \in [0, 1]$): Computed by token matching across table and column names via `DatabaseEntityResolver`.
2. **Semantic Vector Score** ($S_{vec} \in [0, 1]$): Computed via pgvector cosine distance:
   ```sql
   SELECT table_name, 1.0 - (embedding <=> %s::vector) AS similarity
   FROM public.schema_vector_intelligence
   WHERE database_identity = %s AND schema_fingerprint = %s AND object_type = 'table'
   ORDER BY embedding <=> %s::vector ASC
   LIMIT %s;
   ```
3. **Hybrid Confidence Fusion**:
   $$S_{final} = \min(1.0, S_{lex} + \text{boost}(S_{vec}))$$
   where $\text{boost}(S_{vec}) = \min(0.40, S_{vec} \times 0.50)$ when $S_{vec} \ge 0.05$.
4. **Selection Threshold**: Only candidates with $S_{final} \ge 0.15$ are returned, capped at `MAX_SELECTED_TABLES` (5).

---

## 12. DeepSeek Token Optimization

Instead of injecting the full database schema (67 tables, 838 columns, ~15,000 tokens) into DeepSeek's prompt, the system passes **only the candidate schema subset** (at most 5 tables, ~500 tokens).
- Reduces prompt token consumption by >95%.
- Eliminates context confusion and hallucination across irrelevant tables.

---

## 13. Hallucination Prevention & Fail-Closed Guardrails

1. **Unknown Table / Entity**: If candidate tables fail to meet the confidence threshold ($< 0.15$), the system raises `DatabaseQueryServiceError` ("Unable to resolve any relevant tables"), refusing to hallucinate answers.
2. **Unknown Column / Metric**: If the requested metric or attribute does not exist in the candidate tables, the validator aborts execution before generating invalid SQL.
3. **Zero-Result Distinction**: When a query resolves validly and executes valid SQL that returns zero rows, the system returns `data: []` with successful execution status, clearly distinguished from an unresolved entity failure.
4. **SQL as Canonical Truth**: Factual numbers and metrics are derived strictly from `SQLQueryExecutor` query results; LLMs are never permitted to invent numbers.

---

## 14. Dual-Engine Rollback & Database-Agnostic Verification

1. **SQL Server Compatibility**: When `DB_ENGINE=sqlserver`, `SchemaVectorIntelligence.is_available` evaluates to `False`. The system falls back cleanly to deterministic lexical table resolution without throwing errors.
2. **No Hardcoded Business Concepts**: Verified via forensic scan across `app/database/schema_vector_intelligence.py`, `app/database/table_selector.py`, and `app/database/entity_resolver.py`. No business tables (`site_events`, `site_details`, `site_speakers`) or regional domains (`gujarat`, etc.) exist in production logic.
3. **Synthetic Database Switching**: Verified by dynamically indexing and searching an unrelated synthetic hospital schema (`inpatients`, `admission_ward`) on the fly.

---

## 15. Test Suite & Verification Results

### Test Execution Summary
- **Baseline Tests (Phases 0 through 13 Step 4)**: 285 tests passed.
- **Phase 13 Step 5 Tests (`tests/test_phase13_step5_pgvector.py`)**: 20 tests passed.
- **Total Test Suite**: **305 / 305 tests passed** (100% green).
- **Execution Time**: ~4.6 seconds.

### Step 5 Test Breakdown (`tests/test_phase13_step5_pgvector.py`)
1. `test_01_pgvector_extension_availability`: pgvector extension verified in PostgreSQL 18.6.
2. `test_02_vector_table_creation_and_indexes`: Schema vector table & composite indexes verified.
3. `test_03_deterministic_embedding_generation_consistency`: 384-dim embedding reproducibility and $L_2$ norm verified.
4. `test_04_semantic_similarity_properties`: Related vs orthogonal similarity separation verified.
5. `test_05_schema_indexing_idempotence`: Idempotent indexing and cache hit reuse verified.
6. `test_06_database_identity_isolation`: Cross-database isolation verified.
7. `test_07_schema_fingerprint_isolation`: Stale fingerprint candidate rejection verified.
8. `test_08_schema_invalidation_and_pruning`: Old fingerprint purging verified.
9. `test_09_semantic_table_candidate_retrieval`: Cosine distance table candidate retrieval verified.
10. `test_10_semantic_column_candidate_retrieval`: Column candidate retrieval verified.
11. `test_11_irrelevant_candidates_not_blindly_selected`: Fail-closed on unrelated queries verified.
12. `test_12_hybrid_table_selection_combines_lexical_and_vector`: Hybrid confidence scoring verified.
13. `test_13_fail_closed_on_unknown_table`: Unknown entity rejection without hallucination verified.
14. `test_14_fail_closed_on_unknown_column_metric`: Unknown metric rejection verified.
15. `test_15_valid_query_zero_rows_distinguished_from_unresolved`: Valid 0-row execution distinguished from resolution failure.
16. `test_16_deepseek_token_optimization_schema_subset`: DeepSeek schema subset token reduction verified.
17. `test_17_sql_remains_canonical_source_of_truth`: SQL execution as factual truth verified.
18. `test_18_sql_server_rollback_compatibility`: Dual-engine SQL Server rollback verified.
19. `test_19_database_switching_synthetic_schema`: Synthetic database schema dynamic indexing verified.
20. `test_20_no_business_hardcoding_in_production_code`: Forensic audit against business hardcoding verified.

---

## 16. Known Limitations

1. **Embedding Feature Model**: The embedded model is a deterministic n-gram and subword hashing model. While fast, reproducible, and zero-cost, it does not possess deep contextual semantics of large external neural embedding models (e.g. `text-embedding-3-small`). If desired in later phases, an external embedding adapter can be plugged in without changing the vector table schema.
2. **Vector Table Schema Location**: The table resides in `public` while business tables reside in `dbo`. This is intentional to isolate business schema discovery from infrastructure tables.

---

## 17. Remaining Work (Phase 13 Step 6+)

1. **Phase 13 Step 6**: PostgreSQL Query Generation & Execution Hardening:
   - Verification of PostgreSQL-specific SQL syntax (e.g., `LIMIT` vs `TOP`, `ILIKE`, date truncation).
   - Relationship JOIN path execution validation against PostgreSQL dialect.
2. **Phase 13 Step 7**: End-to-end conversation flow and regression validation under PostgreSQL.
