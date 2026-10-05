from dataclasses import dataclass, field
from typing import Any

from app.core.config import DatabaseConfig, get_database_config
from app.database.connection import get_connection


@dataclass
class ColumnInfo:
    name: str
    data_type: str
    nullable: bool
    ordinal_position: int


@dataclass
class TableInfo:
    schema_name: str
    table_name: str
    columns: list[ColumnInfo] = field(default_factory=list)
    primary_key_columns: list[str] = field(default_factory=list)


@dataclass
class ForeignKeyInfo:
    constraint_name: str

    schema_name: str
    table_name: str
    column_name: str

    referenced_schema_name: str
    referenced_table_name: str
    referenced_column_name: str


@dataclass
class UniqueConstraintInfo:
    constraint_name: str
    schema_name: str
    table_name: str
    column_name: str


@dataclass(frozen=True)
class ResolvedColumn:
    schema_name: str
    table_name: str
    column_name: str
    data_type: str = ""
    nullable: bool = True


@dataclass(frozen=True)
class ColumnResolution:
    resolved: ResolvedColumn | None = None
    is_ambiguous: bool = False
    matching_tables: list[tuple[str, str]] = field(default_factory=list)
    error: str | None = None


def parse_column_reference(ref: str) -> tuple[str | None, str | None, str]:
    """
    Parse a column reference into (schema, table, column).
    Handles bracket-quoted or unquoted identifiers:
      'dbo.table_a.id' -> ('dbo', 'table_a', 'id')
      'table_a.id' -> (None, 'table_a', 'id')
      'id' -> (None, None, 'id')
      '[dbo].[table_a].[id]' -> ('dbo', 'table_a', 'id')
    """
    cleaned = str(ref).strip()
    if not cleaned:
        return (None, None, "")
    parts = [p.strip().strip('[]"') for p in cleaned.split(".") if p.strip()]
    if len(parts) >= 3:
        return (parts[0], parts[1], parts[2])
    elif len(parts) == 2:
        return (None, parts[0], parts[1])
    elif len(parts) == 1:
        return (None, None, parts[0])
    return (None, None, cleaned)


@dataclass
class DatabaseSchema:
    tables: list[TableInfo] = field(default_factory=list)
    foreign_keys: list[ForeignKeyInfo] = field(default_factory=list)
    unique_constraints: list[UniqueConstraintInfo] = field(default_factory=list)

    def get_table(
        self,
        schema_name: str | None,
        table_name: str,
    ) -> TableInfo | None:
        table_lower = table_name.lower() if table_name else ""
        if not table_lower:
            return None

        if schema_name:
            schema_lower = schema_name.lower()
            for table in self.tables:
                if (
                    table.schema_name.lower() == schema_lower
                    and table.table_name.lower() == table_lower
                ):
                    return table
            return None

        matching = [t for t in self.tables if t.table_name.lower() == table_lower]
        if len(matching) == 1:
            return matching[0]
        return None

    def find_tables_with_column(self, column_name: str) -> list[TableInfo]:
        col_lower = column_name.lower()
        return [
            table for table in self.tables
            if any(c.name.lower() == col_lower for c in table.columns)
        ]

    def resolve_column(
        self,
        column_ref: str,
        explicit_refs: list[Any] | None = None,
        prefer_table: tuple[str, str] | None = None,
    ) -> ColumnResolution:
        schema_part, table_part, col_name = parse_column_reference(column_ref)
        if not col_name:
            return ColumnResolution(error="Column reference cannot be empty.")

        # 1. Match against explicit references (e.g. target_column_refs, group_by_refs)
        if explicit_refs:
            for ref in explicit_refs:
                ref_col = getattr(ref, "column", None)
                if not ref_col or str(ref_col).lower() != col_name.lower():
                    continue

                ref_table = getattr(ref, "table", None)
                ref_schema = getattr(ref, "schema", None)

                if table_part and ref_table and str(ref_table).lower() != table_part.lower():
                    continue
                if schema_part and ref_schema and str(ref_schema).lower() != schema_part.lower():
                    continue

                matched_table = self.get_table(ref_schema, ref_table) if ref_table else None
                if matched_table is None and ref_table:
                    candidates = [t for t in self.tables if t.table_name.lower() == str(ref_table).lower()]
                    if len(candidates) == 1:
                        matched_table = candidates[0]

                if matched_table is not None:
                    col_info = next((c for c in matched_table.columns if c.name.lower() == col_name.lower()), None)
                    if col_info is not None:
                        return ColumnResolution(
                            resolved=ResolvedColumn(
                                schema_name=matched_table.schema_name,
                                table_name=matched_table.table_name,
                                column_name=col_info.name,
                                data_type=col_info.data_type,
                                nullable=col_info.nullable,
                            )
                        )
                    else:
                        return ColumnResolution(
                            error=f"Column '{col_name}' does not exist on table '{matched_table.schema_name}.{matched_table.table_name}'."
                        )
                elif ref_schema and ref_table:
                    return ColumnResolution(
                        error=f"Table '{ref_schema}.{ref_table}' does not exist."
                    )
                elif ref_table:
                    return ColumnResolution(
                        error=f"Table '{ref_table}' does not exist."
                    )

        # 2. Schema-qualified reference (schema.table.column)
        if schema_part and table_part:
            table = self.get_table(schema_part, table_part)
            if table is None:
                return ColumnResolution(error=f"Table '{schema_part}.{table_part}' does not exist.")
            col_info = next((c for c in table.columns if c.name.lower() == col_name.lower()), None)
            if col_info is None:
                return ColumnResolution(error=f"Column '{col_name}' does not exist on table '{schema_part}.{table_part}'.")
            return ColumnResolution(
                resolved=ResolvedColumn(
                    schema_name=table.schema_name,
                    table_name=table.table_name,
                    column_name=col_info.name,
                    data_type=col_info.data_type,
                    nullable=col_info.nullable,
                )
            )

        # 3. Table-qualified reference (table.column)
        if table_part:
            matching_tables = [t for t in self.tables if t.table_name.lower() == table_part.lower()]
            if not matching_tables:
                return ColumnResolution(error=f"Table '{table_part}' does not exist.")

            tables_with_col = [
                (t, next(c for c in t.columns if c.name.lower() == col_name.lower()))
                for t in matching_tables
                if any(c.name.lower() == col_name.lower() for c in t.columns)
            ]
            if not tables_with_col:
                return ColumnResolution(error=f"Column '{col_name}' does not exist on table '{table_part}'.")
            if len(tables_with_col) > 1:
                return ColumnResolution(
                    is_ambiguous=True,
                    matching_tables=[(t.schema_name, t.table_name) for t, _ in tables_with_col],
                    error=f"Column '{col_name}' on table '{table_part}' is ambiguous across multiple schemas: "
                          + ", ".join(sorted(f"{t.schema_name}.{t.table_name}" for t, _ in tables_with_col)),
                )
            table, col_info = tables_with_col[0]
            return ColumnResolution(
                resolved=ResolvedColumn(
                    schema_name=table.schema_name,
                    table_name=table.table_name,
                    column_name=col_info.name,
                    data_type=col_info.data_type,
                    nullable=col_info.nullable,
                )
            )

        # 4. Unqualified reference (column)
        tables_with_col = [
            (t, next(c for c in t.columns if c.name.lower() == col_name.lower()))
            for t in self.tables
            if any(c.name.lower() == col_name.lower() for c in t.columns)
        ]
        if not tables_with_col:
            return ColumnResolution(error=f"Column does not exist: {col_name}")

        if len(tables_with_col) == 1:
            table, col_info = tables_with_col[0]
            return ColumnResolution(
                resolved=ResolvedColumn(
                    schema_name=table.schema_name,
                    table_name=table.table_name,
                    column_name=col_info.name,
                    data_type=col_info.data_type,
                    nullable=col_info.nullable,
                )
            )

        # More than one table contains this column
        if prefer_table is not None:
            pref_matches = [
                (t, c) for t, c in tables_with_col
                if (t.schema_name.lower(), t.table_name.lower()) == (prefer_table[0].lower(), prefer_table[1].lower())
            ]
            if len(pref_matches) == 1:
                table, col_info = pref_matches[0]
                return ColumnResolution(
                    resolved=ResolvedColumn(
                        schema_name=table.schema_name,
                        table_name=table.table_name,
                        column_name=col_info.name,
                        data_type=col_info.data_type,
                        nullable=col_info.nullable,
                    )
                )

        table_names = [f"{t.schema_name}.{t.table_name}" for t, _ in tables_with_col]
        return ColumnResolution(
            is_ambiguous=True,
            matching_tables=[(t.schema_name, t.table_name) for t, _ in tables_with_col],
            error=f"Column '{col_name}' is ambiguous across multiple selected tables: {', '.join(sorted(table_names))}."
        )


def get_database_schema(config: DatabaseConfig | None = None) -> DatabaseSchema:
    """
    Load the complete database structure and relationship metadata.
    """
    cfg = config or get_database_config()
    connection = get_connection(cfg)

    try:
        cursor = connection.cursor()

        # ---------------------------------------------------------
        # 1. Columns
        # ---------------------------------------------------------
        tables: dict[tuple[str, str], TableInfo] = {}

        if cfg.is_postgresql:
            cursor.execute(
                """
                SELECT
                    table_schema AS "TABLE_SCHEMA",
                    table_name AS "TABLE_NAME",
                    column_name AS "COLUMN_NAME",
                    data_type AS "DATA_TYPE",
                    is_nullable AS "IS_NULLABLE",
                    ordinal_position AS "ORDINAL_POSITION"
                FROM information_schema.columns
                WHERE table_schema = %s
                ORDER BY
                    table_schema,
                    table_name,
                    ordinal_position
                """,
                (cfg.schema,),
            )
        else:
            cursor.execute(
                """
                SELECT
                    TABLE_SCHEMA,
                    TABLE_NAME,
                    COLUMN_NAME,
                    DATA_TYPE,
                    IS_NULLABLE,
                    ORDINAL_POSITION
                FROM INFORMATION_SCHEMA.COLUMNS
                ORDER BY
                    TABLE_SCHEMA,
                    TABLE_NAME,
                    ORDINAL_POSITION
                """
            )

        for row in cursor.fetchall():
            schema_name = getattr(row, "TABLE_SCHEMA", None) if hasattr(row, "TABLE_SCHEMA") else row[0]
            table_name = getattr(row, "TABLE_NAME", None) if hasattr(row, "TABLE_NAME") else row[1]
            col_name = getattr(row, "COLUMN_NAME", None) if hasattr(row, "COLUMN_NAME") else row[2]
            data_type = getattr(row, "DATA_TYPE", None) if hasattr(row, "DATA_TYPE") else row[3]
            is_nullable = getattr(row, "IS_NULLABLE", None) if hasattr(row, "IS_NULLABLE") else row[4]
            ord_pos = getattr(row, "ORDINAL_POSITION", None) if hasattr(row, "ORDINAL_POSITION") else row[5]

            table_key = (
                schema_name,
                table_name,
            )

            if table_key not in tables:
                tables[table_key] = TableInfo(
                    schema_name=schema_name,
                    table_name=table_name,
                )

            tables[table_key].columns.append(
                ColumnInfo(
                    name=col_name,
                    data_type=data_type,
                    nullable=is_nullable == "YES",
                    ordinal_position=int(ord_pos),
                )
            )

        # ---------------------------------------------------------
        # 2. Primary keys
        # ---------------------------------------------------------
        if cfg.is_postgresql:
            cursor.execute(
                """
                SELECT
                    tc.table_schema AS schema_name,
                    tc.table_name AS table_name,
                    kcu.column_name AS column_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                    ON tc.constraint_name = kcu.constraint_name
                    AND tc.table_schema = kcu.table_schema
                WHERE tc.table_schema = %s
                    AND tc.constraint_type = 'PRIMARY KEY'
                ORDER BY
                    tc.table_schema,
                    tc.table_name,
                    kcu.ordinal_position
                """,
                (cfg.schema,),
            )
        else:
            cursor.execute(
                """
                SELECT
                    s.name AS schema_name,
                    t.name AS table_name,
                    c.name AS column_name
                FROM sys.tables t
                INNER JOIN sys.schemas s
                    ON s.schema_id = t.schema_id
                INNER JOIN sys.indexes i
                    ON i.object_id = t.object_id
                    AND i.is_primary_key = 1
                INNER JOIN sys.index_columns ic
                    ON ic.object_id = i.object_id
                    AND ic.index_id = i.index_id
                INNER JOIN sys.columns c
                    ON c.object_id = ic.object_id
                    AND c.column_id = ic.column_id
                ORDER BY
                    s.name,
                    t.name,
                    ic.key_ordinal
                """
            )

        for row in cursor.fetchall():
            s_name = getattr(row, "schema_name", None) if hasattr(row, "schema_name") else row[0]
            t_name = getattr(row, "table_name", None) if hasattr(row, "table_name") else row[1]
            c_name = getattr(row, "column_name", None) if hasattr(row, "column_name") else row[2]

            table = tables.get((s_name, t_name))
            if table is not None:
                table.primary_key_columns.append(c_name)

        # ---------------------------------------------------------
        # 3. Foreign keys
        # ---------------------------------------------------------
        foreign_keys: list[ForeignKeyInfo] = []

        if cfg.is_postgresql:
            cursor.execute(
                """
                SELECT
                    tc.constraint_name,
                    tc.table_schema AS schema_name,
                    tc.table_name AS table_name,
                    kcu.column_name AS column_name,
                    ccu.table_schema AS referenced_schema_name,
                    ccu.table_name AS referenced_table_name,
                    ccu.column_name AS referenced_column_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                    ON tc.constraint_name = kcu.constraint_name
                    AND tc.table_schema = kcu.table_schema
                JOIN information_schema.constraint_column_usage ccu
                    ON ccu.constraint_name = tc.constraint_name
                    AND ccu.table_schema = tc.table_schema
                WHERE tc.table_schema = %s
                    AND tc.constraint_type = 'FOREIGN KEY'
                ORDER BY
                    tc.table_schema,
                    tc.table_name,
                    tc.constraint_name,
                    kcu.ordinal_position
                """,
                (cfg.schema,),
            )
        else:
            cursor.execute(
                """
                SELECT
                    fk.name AS constraint_name,

                    s.name AS schema_name,
                    t.name AS table_name,
                    c.name AS column_name,

                    rs.name AS referenced_schema_name,
                    rt.name AS referenced_table_name,
                    rc.name AS referenced_column_name

                FROM sys.foreign_key_columns fkc

                INNER JOIN sys.foreign_keys fk
                    ON fk.object_id = fkc.constraint_object_id

                INNER JOIN sys.tables t
                    ON t.object_id = fkc.parent_object_id

                INNER JOIN sys.schemas s
                    ON s.schema_id = t.schema_id

                INNER JOIN sys.columns c
                    ON c.object_id = fkc.parent_object_id
                    AND c.column_id = fkc.parent_column_id

                INNER JOIN sys.tables rt
                    ON rt.object_id = fkc.referenced_object_id

                INNER JOIN sys.schemas rs
                    ON rs.schema_id = rt.schema_id

                INNER JOIN sys.columns rc
                    ON rc.object_id = fkc.referenced_object_id
                    AND rc.column_id = fkc.referenced_column_id

                ORDER BY
                    s.name,
                    t.name,
                    fk.name,
                    fkc.constraint_column_id
                """
            )

        for row in cursor.fetchall():
            foreign_keys.append(
                ForeignKeyInfo(
                    constraint_name=getattr(row, "constraint_name", None) if hasattr(row, "constraint_name") else row[0],
                    schema_name=getattr(row, "schema_name", None) if hasattr(row, "schema_name") else row[1],
                    table_name=getattr(row, "table_name", None) if hasattr(row, "table_name") else row[2],
                    column_name=getattr(row, "column_name", None) if hasattr(row, "column_name") else row[3],
                    referenced_schema_name=getattr(row, "referenced_schema_name", None) if hasattr(row, "referenced_schema_name") else row[4],
                    referenced_table_name=getattr(row, "referenced_table_name", None) if hasattr(row, "referenced_table_name") else row[5],
                    referenced_column_name=getattr(row, "referenced_column_name", None) if hasattr(row, "referenced_column_name") else row[6],
                )
            )

        # ---------------------------------------------------------
        # 4. Unique constraints
        # ---------------------------------------------------------
        unique_constraints: list[UniqueConstraintInfo] = []

        if cfg.is_postgresql:
            cursor.execute(
                """
                SELECT
                    tc.constraint_name,
                    tc.table_schema AS schema_name,
                    tc.table_name AS table_name,
                    kcu.column_name AS column_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                    ON tc.constraint_name = kcu.constraint_name
                    AND tc.table_schema = kcu.table_schema
                WHERE tc.table_schema = %s
                    AND tc.constraint_type = 'UNIQUE'
                ORDER BY
                    tc.table_schema,
                    tc.table_name,
                    tc.constraint_name,
                    kcu.ordinal_position
                """,
                (cfg.schema,),
            )
        else:
            cursor.execute(
                """
                SELECT
                    kc.name AS constraint_name,
                    s.name AS schema_name,
                    t.name AS table_name,
                    c.name AS column_name

                FROM sys.key_constraints kc

                INNER JOIN sys.tables t
                    ON t.object_id = kc.parent_object_id

                INNER JOIN sys.schemas s
                    ON s.schema_id = t.schema_id

                INNER JOIN sys.index_columns ic
                    ON ic.object_id = kc.parent_object_id
                    AND ic.index_id = kc.unique_index_id

                INNER JOIN sys.columns c
                    ON c.object_id = ic.object_id
                    AND c.column_id = ic.column_id

                WHERE kc.type = 'UQ'

                ORDER BY
                    s.name,
                    t.name,
                    kc.name,
                    ic.key_ordinal
                """
            )

        for row in cursor.fetchall():
            unique_constraints.append(
                UniqueConstraintInfo(
                    constraint_name=getattr(row, "constraint_name", None) if hasattr(row, "constraint_name") else row[0],
                    schema_name=getattr(row, "schema_name", None) if hasattr(row, "schema_name") else row[1],
                    table_name=getattr(row, "table_name", None) if hasattr(row, "table_name") else row[2],
                    column_name=getattr(row, "column_name", None) if hasattr(row, "column_name") else row[3],
                )
            )

        return DatabaseSchema(
            tables=list(tables.values()),
            foreign_keys=foreign_keys,
            unique_constraints=unique_constraints,
        )

    finally:
        connection.close()


# -------------------------------------------------------------
# Backward compatibility
# -------------------------------------------------------------

def get_schema(config: DatabaseConfig | None = None) -> list[TableInfo]:
    """
    Existing callers can continue using get_schema().
    """

    return get_database_schema(config).tables


def schema_to_dict(
    schema: list[TableInfo],
) -> list[dict[str, Any]]:
    """
    Convert table schema into JSON-friendly dictionaries.
    """

    return [
        {
            "schema": table.schema_name,
            "table": table.table_name,
            "columns": [
                {
                    "name": column.name,
                    "data_type": column.data_type,
                    "nullable": column.nullable,
                    "ordinal_position": column.ordinal_position,
                }
                for column in table.columns
            ],
            "primary_key_columns": table.primary_key_columns,
        }
        for table in schema
    ]