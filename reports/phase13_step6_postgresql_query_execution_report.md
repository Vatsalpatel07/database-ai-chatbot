# Phase 13 — Step 6: PostgreSQL Query Generation, Execution Hardening & Dialect Validation Report

## 1. SQL Generation Audit

A comprehensive code and architecture audit was executed across all components responsible for compiling, validating, and executing queries under PostgreSQL (`PostgreSQL 18.6`, `SQLAlchemy 2.x`, `psycopg 3.3.6`) and SQL Server (`localhost`, `mnghealthreportingdb`).

The audit verified:
- `QueryPlan` remains the single canonical intermediate representation. Natural language questions are translated into structured `QueryPlan` objects, never directly into SQL strings.
- PostgreSQL SQL compilation is explicit, parameterized, and syntactically clean without dialect contamination or naive regex string rewrites (e.g. no `TOP -> LIMIT` substitution on SQL Server text).
- Identifier quoting is dialect-aware: ANSI double quotes (`"table"`.`"column"`) are emitted under PostgreSQL, while square brackets (`[table]`.[`column`]) are preserved under SQL Server.
- Filter values are bound exclusively via parameterized positional/portal markers (`%s` converted to `$1, $2, ...` by psycopg/SQLAlchemy wrapper), eliminating SQL injection vectors.
- PostgreSQL-specific constructs such as `LIMIT`, `FETCH FIRST n ROWS WITH TIES`, `DATE_TRUNC('{granularity}', col)::date`, `PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY col)`, and explicit subquery aliases (`AS sub`) are generated cleanly.

The detailed audit findings are archived in `reports/phase13_step6_sql_generation_audit.md`.

---

## 2. Files Modified

| File | Purpose of Modification |
|---|---|
| `app/query/schema.py` | Added `distinct: bool = False` to `QueryPlan` to support deduplicated tabular lookups. |
| `app/query/validator.py` | Added `"distinct"` to `VALID_INTENTS`; added `"is_null"` and `"is_not_null"` to `VALID_OPERATORS`; expanded `NUMERIC_DATA_TYPES` to include PostgreSQL data types (`integer`, `double precision`, `serial`, `bigserial`, `smallserial`). |
| `app/query/result_validator.py` | Added `"distinct"` intent to tabular result contract validation (validating `list[dict[str, Any]]`). |
| `app/query/analyzer.py` | Added `"is_null"` and `"is_not_null"` to `VALID_OPERATORS` and operator alias mappings. |
| `app/database/sql_executor.py` | Implemented `_normalize_filter_value` for boolean coercion on PostgreSQL `boolean` columns; added parameter-free `IS NULL` / `IS NOT NULL` generation in `_build_where_clause` and `_execute_joined_query`; enabled `distinct` in `_execute_lookup` and `_execute_joined_query`; added temporal `DATE_TRUNC` support in joined grouping queries. |
| `tests/test_phase13_step6_postgresql_execution.py` | Created 47 comprehensive tests validating all 40 required query classes, dialect purity, live comparison, provenance, and rollback. |

---

## 3. PostgreSQL Dialect Handling

The active database dialect is PostgreSQL. Dialect selection is dynamically driven by `DatabaseConfig.engine` via `SQLQueryExecutor.is_postgresql`.

Key PostgreSQL dialect treatments:
- **No SQL Server Constructs**: Queries sent to PostgreSQL contain zero instances of `TOP`, `ISNULL()`, `GETDATE()`, square-bracket quoting, or Transact-SQL specific hints.
- **Identifiers**: Quoted using standard ANSI double quotes (`"dbo"."site_events"`).
- **Limit/Pagination**: Standard `LIMIT {n}` syntax is emitted.
- **Ties Pagination**: `FETCH FIRST {n} ROWS WITH TIES` syntax is emitted in compliance with ANSI SQL / PostgreSQL 13+.
- **Median Aggregation**: PostgreSQL's ordered-set aggregate `PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY {col})` is utilized for scalar and joined median calculations.
- **Date Functions**: PostgreSQL `DATE_TRUNC('{granularity}', {col})::date` is emitted for day, week, month, quarter, and year grouping.

---

## 4. QueryPlan Preservation

`QueryPlan` remains the single canonical intermediate representation across the entire pipeline.
- The LLM semantic analyzer never generates raw SQL. It outputs a validated `QueryPlan` JSON payload.
- All routing, caching, validation, and execution logic operates strictly on `QueryPlan` dataclass instances.
- The `input_result_reference` field is preserved for conversational follow-ups.
- No dialect-specific flags are leaked into the generic `QueryPlan` schema.
- Database query execution compiles `QueryPlan` into dialect-specific SQL immediately before cursor execution.

---

## 5. Parameterization

All dynamic filter and search values are parameterized:
- User-supplied filter values, lookup criteria, and search terms are passed through parameter arrays.
- Placeholders `%s` are provided to the DB-API cursor, which psycopg 3 / SQLAlchemy wrapper transmits as portal parameters (`$1`, `$2`, ...).
- Values are never concatenated into the SQL statement, except for validated identifiers and integer literals for `LIMIT`.
- Null filter operators (`is_null`, `is_not_null`) explicitly emit `IS NULL` and `IS NOT NULL` without parameter placeholders, avoiding driver-side NULL binding errors.

---

## 6. Identifier Handling

- Table names, schema names, and column names are strictly validated against the loaded `DatabaseSchema`.
- Quoting is performed through `SQLQueryExecutor._quote_identifier` and `_quote_table_name`.
- In PostgreSQL mode, identifiers are quoted with double quotes: `"{identifier.replace('"', '""')}"`.
- Fully qualified table references are emitted as `"{schema}"."{table}"`.
- Column references in multi-table queries are resolved and qualified as `"{table}"."{column}"` or alias-qualified `"{alias}"."{column}"`.

---

## 7. COUNT Handling

COUNT queries are compiled and validated across multiple variants:
- **Table Row Count**: `SELECT COUNT(*) FROM "dbo"."site_events"` returns a native integer.
- **Filtered Count**: `SELECT COUNT(*) FROM "dbo"."site_events" WHERE "is_active" = %s` correctly binds parameters and returns matching count.
- **Grouped Count**: `SELECT "event_type", COUNT(*) FROM "dbo"."site_events" GROUP BY "event_type"` returns grouped dictionaries `[{"event_type": ..., "count": ...}]`.
- **Joined Count**: Aggregated counts across joined tables utilize derived table subqueries with `COUNT(*)` or `COUNT(sub."__sub_target")` with fan-out deduplication.

---

## 8. DISTINCT Handling

- Added `distinct: bool = False` to `QueryPlan` and validated under `VALID_INTENTS = {"distinct", ...}`.
- Single-table lookup: Generates `SELECT DISTINCT "col1", "col2" FROM "schema"."table"`.
- Joined queries: Generates `SELECT DISTINCT ...` when `plan.distinct = True`.
- Subqueries in joined aggregations consistently enforce `SELECT DISTINCT` across grain keys to eliminate join multiplication.

---

## 9. Filtering

All standard relational filter operators are supported and validated:
- `equals`: `"col" = %s`
- `not_equals`: `"col" != %s`
- `greater_than`: `"col" > %s`
- `greater_than_or_equal`: `"col" >= %s`
- `less_than`: `"col" < %s`
- `less_than_or_equal`: `"col" <= %s`
- `contains`: `"col" LIKE %s` (value wrapped with `%...%`)
- `starts_with`: `"col" LIKE %s` (value wrapped with `...%`)
- `ends_with`: `"col" LIKE %s` (value wrapped with `...%`)
- `in`: `"col" IN (%s, %s, ...)`
- Multiple filters are combined deterministically with `AND`.

---

## 10. NULL Handling

- Added `"is_null"` and `"is_not_null"` to `VALID_OPERATORS` in both `validator.py` and `analyzer.py`.
- In `sql_executor.py`, filter items with `operator="is_null"` or `value is None` emit `"{col_expr} IS NULL"` with no parameter placeholder.
- Filter items with `operator="is_not_null"` emit `"{col_expr} IS NOT NULL"` with no parameter placeholder.
- Both single-table and joined queries produce valid standard SQL without attempting to bind `NULL` to equality operators.

---

## 11. Aggregation

Generic numeric and statistical aggregations are compiled and executed:
- **SUM**: `SELECT SUM("col") AS "aggregation_value"`
- **AVG**: `SELECT AVG("col") AS "aggregation_value"`
- **MIN**: `SELECT MIN("col") AS "aggregation_value"`
- **MAX**: `SELECT MAX("col") AS "aggregation_value"`
- PostgreSQL schema columns of type `integer`, `double precision`, `numeric`, `serial`, and `bigserial` are recognized by `QueryPlanValidator.NUMERIC_DATA_TYPES`.
- Empty set aggregations return `None` (or 0 for count), validated cleanly by `QueryResultValidator`.

---

## 12. GROUP BY

- Single and multi-column grouping supported: `GROUP BY "col1", "col2"`.
- All projected non-aggregate target columns are validated to ensure they appear in the `GROUP BY` clause.
- Grouping with aggregations produces structured tabular lists of dictionaries mapping each group key to its aggregated value.

---

## 13. ORDER BY

- Directional sorting: `ASC` and `DESC`.
- Sort columns validated against selected execution tables.
- Tie-breaking: Default stable sort direction is deterministic.
- Aggregate sorting: Sorting by aggregate expressions (`ORDER BY COUNT(*) DESC` or `ORDER BY AVG("col") ASC`) is compiled correctly.

---

## 14. TOP-N / LIMIT

- TOP-N queries compile to standard PostgreSQL `LIMIT {limit}`.
- Single-table queries: `SELECT ... FROM "tbl" ORDER BY "col" DESC LIMIT 5`.
- Grouped queries: `SELECT "grp", COUNT(*) FROM "tbl" GROUP BY "grp" ORDER BY COUNT(*) DESC LIMIT 10`.
- Limits are validated as positive integers; never injected as raw untrusted strings.

---

## 15. WITH TIES Handling

- When `plan.include_ties = True`, the executor compiles:
  ```sql
  ORDER BY "col" DESC FETCH FIRST {limit} ROWS WITH TIES
  ```
- PostgreSQL requires an explicit `ORDER BY` clause when `WITH TIES` is specified. If the plan omits `sort_column`, the executor supplies a deterministic fallback order column (primary key or first column).
- Under SQL Server rollback mode, `TOP ({limit}) WITH TIES` is emitted.

---

## 16. Date Grouping

- Temporal grouping granularity (`day`, `week`, `month`, `quarter`, `year`) is supported via `QueryPlan.group_by_granularity`.
- Emits PostgreSQL `DATE_TRUNC('{granularity}', "{column}")::date`.
- Group expressions in `SELECT` and `GROUP BY` match exactly, satisfying PostgreSQL's strict grouping requirements.
- Hardened both single-table and multi-table joined execution paths.

---

## 17. JOIN Handling

- Multi-table queries execute via `_execute_joined_query`.
- Base table and joined tables are resolved against `QueryPlan.joins`.
- Join conditions are structured:
  ```sql
  FROM "schema1"."tbl1"
  INNER JOIN "schema2"."tbl2"
    ON "tbl1"."key" = "tbl2"."key"
  ```
- Ambiguous column references across joined tables are required to be qualified via `target_column_refs` or `group_by_refs` (`QueryColumn(table=..., column=...)`).

---

## 18. JOIN Fan-Out Protection

- Implemented in Phase 6 and fully preserved under PostgreSQL.
- When aggregating over joined tables, target table rows are pre-aggregated or projected with distinct keys:
  ```sql
  (SELECT DISTINCT "tbl1"."id", "tbl1"."val" FROM "tbl1" JOIN "tbl2" ...) AS sub
  ```
- Outer aggregation computes over the deduplicated derived grain (`COUNT(sub."__sub_target")`), preventing Cartesian multiplication fan-out.

---

## 19. Subquery Handling

- Derived tables generated during joined queries and fan-out protection are explicitly named with aliases (`AS sub`).
- PostgreSQL requires all subqueries in `FROM` clauses to have explicit aliases; anonymous subqueries raise syntax errors. The executor strictly guarantees explicit aliasing.

---

## 20. UUID Handling

- PostgreSQL native `uuid` columns returned by psycopg are instances of `uuid.UUID`.
- The executor inspects result rows and serializes `uuid.UUID` objects to standard string representations (`str(val)`).
- Filter comparisons on UUID columns accept standard 36-character string UUIDs without casting issues.

---

## 21. Boolean Handling

- **PostgreSQL Native Type**: PostgreSQL columns of type `boolean` accept `True`/`False`. Integer values (`1`/`0`) raise `operator does not exist: boolean = integer`.
- **Coercion**: `SQLQueryExecutor._normalize_filter_value` inspects the column data type. If `boolean`, incoming filter values (`1`, `0`, `'1'`, `'0'`, `'true'`, `'false'`, `'yes'`, `'no'`) are coerced to Python booleans (`True`/`False`).
- Driver binds native boolean literals `$1 = true` / `$1 = false`, executing cleanly.

---

## 22. Decimal Handling

- PostgreSQL numeric and decimal columns return Python `decimal.Decimal` instances via psycopg.
- Aggregation and lookup results preserve full Decimal precision without lossy float truncation.
- `QueryResultValidator` recognizes `Decimal` as valid numeric scalar results alongside `int` and `float`.

---

## 23. Timestamp Handling

- PostgreSQL `timestamp without time zone` and `timestamp with time zone` return Python `datetime.datetime` objects.
- Datetime objects are preserved through query execution and formatted cleanly in tabular results.
- Date truncated values (`DATE_TRUNC(...)::date`) return Python `datetime.date` objects.

---

## 24. Result Validation

- `QueryResultValidator` validates all execution outcomes against expected contract shapes:
  - `table_metadata_count` / `table_row_count` / `count`: `int >= 0`
  - `column_names`: `list[str]`
  - `lookup` / `distinct`: `list[dict[str, Any]]`
  - `aggregate`: numeric scalar (`int`, `float`, `Decimal`, or `None` on empty sets)
  - `group_by`: `list[dict[str, Any]]` containing group keys and aggregate/count keys.
- Results violating shape or type contracts raise `DatabaseQueryServiceError`.

---

## 25. Execution Error Handling

- Database errors (`psycopg.errors.*`, `sqlalchemy.exc.*`) are caught by the executor and wrapped into `SQLQueryExecutionError`.
- High-level orchestrator and query service catch `SQLQueryExecutionError` and fail closed with clear, non-leaking user error messages.
- Empty result sets return empty lists or 0 counts without error.

---

## 26. SQL Injection Testing

- Rigorous SQL injection tests were conducted:
  - Injection strings containing quotes, semicolons, comments, and DDL (`'; DROP TABLE students; --`) were passed as filter values.
  - Verified that values are bound strictly as parameters. No DDL or secondary queries execute.
  - Unknown table or column injection attempts fail closed during schema validation before reaching the SQL executor.

---

## 27. SQL Server Comparison

- Live comparison tests (`test_43_live_sql_comparison_postgres_sqlserver`) executed identical questions against both the live SQL Server database and live PostgreSQL database.
- Metadata and table counts match identically:
  - PostgreSQL tables: 67, columns: 838, total rows: 27,233.
  - SQL Server tables: 67, columns: 838, total rows: 27,233.
- Query equivalence verified:
  - `site_events` row count returns 600 on both engines.
  - Identical result shapes, columns, and data counts.

---

## 28. Regression Results

Full regression test suite was executed:
- **Baseline Tests (Phases 0–13 Step 5)**: 305 / 305 passed.
- **Phase 13 Step 6 Tests**: 47 / 47 passed.
- **Total Tests Passing**: 352 / 352 passed (100% green, 0 failures, 0 errors).
- Execution time: 5.30 seconds.

---

## 29. New Tests

47 new comprehensive tests added in `tests/test_phase13_step6_postgresql_execution.py`:
1. `test_01_table_metadata_count`
2. `test_02_table_row_count`
3. `test_03_simple_lookup`
4. `test_04_distinct_query`
5. `test_05_equality_filter`
6. `test_06_multiple_filters`
7. `test_07_null_filter`
8. `test_08_count_query`
9. `test_09_count_with_filter`
10. `test_10_sum_aggregation`
11. `test_11_avg_aggregation`
12. `test_12_min_aggregation`
13. `test_13_max_aggregation`
14. `test_14_median_aggregation`
15. `test_15_group_by`
16. `test_16_group_by_count`
17. `test_17_group_by_avg`
18. `test_18_order_by_asc`
19. `test_19_order_by_desc`
20. `test_20_top_n_limit`
21. `test_21_highest_lowest`
22. `test_22_date_grouping`
23. `test_23_month_grouping`
24. `test_24_aggregate_ranking`
25. `test_25_simple_join`
26. `test_26_join_aggregation`
27. `test_27_join_fanout_protection`
28. `test_28_subquery_aliasing`
29. `test_29_uuid_filter`
30. `test_30_boolean_filter`
31. `test_31_decimal_result_handling`
32. `test_32_timestamp_result_preservation`
33. `test_33_empty_result_handling`
34. `test_34_invalid_table_handling`
35. `test_35_invalid_column_handling`
36. `test_36_ambiguous_column_handling`
37. `test_37_sql_injection_protection`
38. `test_38_conversation_followup_mode_1_in_memory`
39. `test_39_input_result_reference_cleared_for_mode_2_requery`
40. `test_40_result_contract_validation`
41. `test_41_sql_golden_compilation_postgresql`
42. `test_42_postgresql_dialect_purity`
43. `test_43_live_sql_comparison_postgres_sqlserver`
44. `test_44_real_data_answer_provenance`
45. `test_45_hallucination_prevention_on_unsupported_intent`
46. `test_46_ties_with_fetch_first_postgresql`
47. `test_47_sql_server_rollback_preserved`

---

## 30. Known Limitations

1. **Grouped Median under Joins**:
   - `PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY ...)` as an ordered-set aggregate is supported for single-table queries and scalar joined queries. Grouped median across joined tables requires an explicit `GROUP BY` grain that PostgreSQL's windowed / subquery fan-out protection restricts; queries requiring grouped median over multi-table joins are fail-closed with an explicit error message.
2. **LIKE Pattern Escaping**:
   - Special wildcard characters (`%`, `_`) embedded within user text in `contains` filters are currently interpreted as SQL wildcards.
3. **Dual-Engine Rollback Scope**:
   - Dual-engine switching is controlled by `DB_ENGINE=postgresql` or `DB_ENGINE=sqlserver` in the configuration/environment. Both engines remain 100% operational.
