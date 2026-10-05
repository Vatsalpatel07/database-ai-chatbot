# Phase 13 — Step 6: SQL Generation & Dialect Execution Audit Report

## 1. Executive Summary

This audit inspects the SQL generation, execution, QueryPlan compilation, and dialect-handling components across the codebase as the system transitions from SQL Server to PostgreSQL (PostgreSQL 18.6 with SQLAlchemy and psycopg 3).

The purpose of this audit is to identify all dialect dependencies, unsafe constructs, missing PostgreSQL type mappings, identifier quoting mechanisms, and parameterization contracts prior to applying targeted execution hardening.

---

## 2. Components Audited

1. `app/database/sql_executor.py` (`SQLQueryExecutor`): Core compiler and execution engine for single-table and multi-table queries.
2. `app/database/connection.py` (`PostgresConnectionWrapper`, `PostgresCursorWrapper`): DB-API cursor and connection wrapper translating parameter markers and executing queries via SQLAlchemy engine.
3. `app/database/query_service.py` (`DatabaseQueryService`): High-level service orchestrating table selection, QueryPlan analysis, validation, semantic cache, execution, and result validation.
4. `app/query/schema.py` (`QueryPlan`, `QueryFilter`, `QueryColumn`, `QueryJoin`): Canonical intermediate representation between natural language intent and database dialect execution.
5. `app/query/validator.py` (`QueryPlanValidator`): Schema-aware validator verifying intent, table existence, column references, data types, and operators.
6. `app/query/result_validator.py` (`QueryResultValidator`): Validates top-level result contracts (types, shapes, column lists).
7. `app/query/analyzer.py` (`QuestionAnalyzer`): DeepSeek-powered semantic question analyzer converting user questions into QueryPlans.
8. `app/database/relationship_validator.py` & `app/database/relationship_service.py`: Discovers and validates foreign key and inferred relationships.
9. `app/orchestration/database_orchestrator.py` (`DatabaseOrchestrator`): Handles deterministic routes (metadata, row statistics) and query dispatch.
10. Test suite (`tests/`): All tests verifying SQL execution, QueryPlan compilation, and dialect contracts.

---

## 3. Detailed Audit Findings

### 3.1. PostgreSQL-Specific vs SQL Server Dialect Handling
- **Identifier Quoting**:
  - `SQLQueryExecutor.quote_identifier` supports both dialects: `"` (escaped as `""`) for PostgreSQL when `is_postgresql=True`, and `[` / `]` for SQL Server when `False`.
  - `DatabaseOrchestrator._handle_database_row_statistics_request` and `relationship_validator.py` check `is_postgresql` and quote with `"` vs `[...]`.
- **Pagination & Limits**:
  - PostgreSQL uses `LIMIT {limit}` and `FETCH FIRST {limit} ROWS WITH TIES`.
  - SQL Server uses `TOP ({limit})` and `TOP ({limit}) WITH TIES`.
  - In PostgreSQL, `WITH TIES` requires an explicit `ORDER BY` clause. `SQLQueryExecutor` correctly adds a fallback `ORDER BY` if none was specified.
- **Ordered-Set Aggregates (Median)**:
  - PostgreSQL natively supports `PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY {col})`.
  - SQL Server required a window function `OVER ()` or subquery partition.
  - In PostgreSQL, scalar and grouped median execute cleanly via native `PERCENTILE_CONT`.
- **Temporal Grouping**:
  - PostgreSQL uses `DATE_TRUNC('{granularity}', {col})::date`.
  - SQL Server used `DATEFROMPARTS` or `DATEADD/DATEDIFF`.
  - PostgreSQL date truncation is implemented in `_build_group_expression` for single-table grouped aggregations. However, in `_execute_joined_query`, `group_by_granularity` was omitted.

### 3.2. Critical Dialect Deficiencies & Unsafe Constructs

#### Defect 1: Boolean Type Mismatch in PostgreSQL Filtering
- **Finding**: SQL Server stores booleans as `bit` (integer 0 or 1). PostgreSQL uses the native `boolean` type (`true` / `false`).
- **Impact**: In PostgreSQL, executing `WHERE boolean_column = 1` or `WHERE boolean_column = 0` fails with:
  ```text
  operator does not exist: boolean = integer
  HINT: No operator matches the given name and argument types.
  ```
- **Remediation**: In `SQLQueryExecutor`, when `self.is_postgresql` is True and the column's discovered data type is `boolean`, incoming filter values (`1`, `0`, `'1'`, `'0'`, `'true'`, `'false'`, `'yes'`, `'no'`) must be normalized to Python booleans (`True` or `False`) so the driver binds native PostgreSQL boolean literals.

#### Defect 2: Missing PostgreSQL Numeric Data Types in `QueryPlanValidator`
- **Finding**: In `app/query/validator.py`, `NUMERIC_DATA_TYPES` was defined solely with SQL Server types:
  ```python
  NUMERIC_DATA_TYPES = {
      "bigint", "decimal", "float", "int", "money",
      "numeric", "real", "smallint", "smallmoney", "tinyint"
  }
  ```
- **Impact**: In PostgreSQL, standard integer columns have `data_type="integer"`, and floating point columns have `data_type="double precision"`. If a user asks for `SUM` or `AVERAGE` on an `"integer"` column, `validator.py` rejects it with:
  `"Aggregation 'sum' requires a numeric column, but '...' has SQL Server data type 'integer'."`
- **Remediation**: Add `"integer"`, `"double precision"`, `"serial"`, `"bigserial"`, and `"smallserial"` to `NUMERIC_DATA_TYPES` in `app/query/validator.py`.

#### Defect 3: Lack of Explicit NULL Operators (`IS NULL`, `IS NOT NULL`)
- **Finding**: `_build_where_clause` only checks `equals`, `not_equals`, `greater_than`, etc. If a filter requests a NULL check or has `value=None`, it produces `column = ?` (evaluating to `column = NULL` in SQL).
- **Impact**: In SQL, `column = NULL` always evaluates to UNKNOWN/False, silently returning 0 rows even when NULL values exist.
- **Remediation**:
  1. Add support for `is_null` and `is_not_null` operators in `_build_where_clause` and `_execute_joined_query`.
  2. If `operator == "equals"` and `value is None`, emit `f"{quoted_column} IS NULL"`.
  3. If `operator == "not_equals"` and `value is None`, emit `f"{quoted_column} IS NOT NULL"`.
  4. Allow `is_null` and `is_not_null` in `QueryPlanValidator.VALID_OPERATORS` and `QuestionAnalyzer.OPERATOR_ALIASES`.

#### Defect 4: Missing Generic `DISTINCT` Query Support
- **Finding**: `QueryPlan` had no explicit `distinct` boolean field. When users ask distinct questions ("What statuses exist?", "List unique regions"), `_execute_lookup` generated `SELECT *` or `SELECT col`, returning duplicate rows.
- **Remediation**: Add optional `distinct: bool = False` to `QueryPlan` (and support `intent == "distinct"`). Emit `SELECT DISTINCT ...` in `_execute_lookup` and `_execute_joined_query`. Allow `intent == "distinct"` in `QueryPlanValidator` and `QueryResultValidator`.

#### Defect 5: Temporal Grouping Missing in Joined Queries
- **Finding**: While `_execute_grouped_aggregation` applies `_build_group_expression` (`DATE_TRUNC`), `_execute_joined_query` did not apply `plan.group_by_granularity`.
- **Remediation**: Apply `_build_group_expression` to grouping columns in `_execute_joined_query` when `plan.group_by_granularity` is present.

### 3.3. Parameterization & SQL Injection Protection
- **Status**: Verified safe. All user-supplied filter values are passed through parameter markers (`?` converted to `%s` by `PostgresCursorWrapper`) and passed as tuples to `psycopg`. No user string, date, or number is interpolated into SQL.
- All table and column names are validated against `TableInfo` and `ColumnInfo` discovered from database schema metadata before quoting and emission.

### 3.4. Result Contract & Type Handling
- **Decimal**: Returned by PostgreSQL for `numeric`/`decimal` aggregates. `QueryResultValidator.NUMERIC_TYPES` already includes `Decimal`, preserving full mathematical precision without arbitrary float coercion.
- **UUID**: PostgreSQL `uuid` objects are converted to `str` during row dictionary building in `_execute_lookup` and `_execute_joined_query`, ensuring JSON serialization compatibility.
- **Dates / Timestamps**: Python `datetime.date` and `datetime.datetime` objects are preserved and handled natively.
- **Row Counts / Empty Results**: Valid queries returning zero rows return `[]` or count `0` without triggering error handlers.

---

## 4. Remediation Plan for Step 6

1. **`app/database/sql_executor.py`**:
   - Add boolean value normalization for PostgreSQL boolean columns.
   - Add `is_null` and `is_not_null` operator handling.
   - Handle `value is None` with `IS NULL` / `IS NOT NULL`.
   - Add `SELECT DISTINCT` support for `plan.distinct` or `intent == "distinct"`.
   - Apply `group_by_granularity` (`DATE_TRUNC`) in `_execute_joined_query`.
2. **`app/query/schema.py`**:
   - Add `distinct: bool = False` to `QueryPlan`.
3. **`app/query/validator.py`**:
   - Add PostgreSQL numeric types (`"integer"`, `"double precision"`, `"serial"`, `"bigserial"`, `"smallserial"`) to `NUMERIC_DATA_TYPES`.
   - Add `"distinct"` to `VALID_INTENTS`.
   - Add `"is_null"` and `"is_not_null"` to `VALID_OPERATORS`.
4. **`app/query/result_validator.py`**:
   - Support `intent == "distinct"` as a tabular result.
5. **`app/query/analyzer.py`**:
   - Add `"is_null"`, `"is not null"` aliases to `OPERATOR_ALIASES`.
6. **Tests (`tests/test_phase13_step6_postgresql_execution.py`)**:
   - Implement comprehensive tests covering all 40 required query classes from Section 40, SQL golden tests, dialect tests, live comparison, and hallucination rejection.
