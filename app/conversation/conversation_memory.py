from __future__ import annotations

import json
import uuid
from typing import Any

from app.database.connection import get_connection


class ConversationMemoryError(Exception):
    """Raised when conversation memory cannot be read or written."""


class ConversationMemory:
    """
    Persistent conversation memory for database-chat sessions.

    Stores only the verified result context required by the query
    analyzer for follow-up questions.
    """

    MAX_CONTEXT_TURNS = 5
    MAX_RESULT_ROWS = 100
    MAX_DISTINCT_VALUES = 1000

    def __init__(self, config: Any | None = None) -> None:
        self.config = config

    @property
    def schema(self) -> str:
        if self.config is not None:
            return getattr(self.config, "schema", "dbo") or "dbo"
        try:
            from app.core.config import get_database_config
            return get_database_config().schema or "dbo"
        except Exception:
            return "dbo"

    @property
    def is_postgresql(self) -> bool:
        if self.config is not None:
            return getattr(self.config, "is_postgresql", False)
        try:
            from app.core.config import DatabaseConfig
            return DatabaseConfig.from_env().is_postgresql
        except Exception:
            return False

    def ensure_table(self) -> None:
        """Ensure chatbot_conversation table exists in the configured database/schema."""
        if not self.is_postgresql:
            return
        try:
            with get_connection(self.config) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS {self.schema}.chatbot_conversation (
                        id BIGSERIAL PRIMARY KEY,
                        session_id VARCHAR(255) NOT NULL,
                        reference_id VARCHAR(255) NOT NULL,
                        question TEXT NOT NULL,
                        result_columns TEXT,
                        result_data TEXT,
                        query_context TEXT,
                        created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_{self.schema}_chat_conv_session 
                        ON {self.schema}.chatbot_conversation (session_id);
                    """
                )
                conn.commit()
        except Exception:
            pass

    def get_context(self, session_id: str | None) -> dict[str, Any]:
        """
        Return recent conversation context for a session.

        The returned structure is intentionally compatible with the
        existing analyzer's conversation-context handling and includes
        structured query context (plan, tables) when available.
        """

        session_id = (session_id or "").strip()

        if not session_id:
            return {}

        connection = None

        try:
            connection = get_connection(self.config)
            cursor = connection.cursor()

            if self.is_postgresql:
                try:
                    cursor.execute(
                        f"""
                        SELECT
                            reference_id,
                            question,
                            result_columns,
                            result_data,
                            query_context
                        FROM {self.schema}.chatbot_conversation
                        WHERE session_id = ?
                        ORDER BY created_at DESC, id DESC
                        LIMIT ?
                        """,
                        session_id,
                        self.MAX_CONTEXT_TURNS,
                    )
                    has_query_context_col = True
                except Exception:
                    if connection is not None and hasattr(connection, "rollback"):
                        connection.rollback()
                    cursor.execute(
                        f"""
                        SELECT
                            reference_id,
                            question,
                            result_columns,
                            result_data
                        FROM {self.schema}.chatbot_conversation
                        WHERE session_id = ?
                        ORDER BY created_at DESC, id DESC
                        LIMIT ?
                        """,
                        session_id,
                        self.MAX_CONTEXT_TURNS,
                    )
                    has_query_context_col = False
            else:
                try:
                    cursor.execute(
                        f"""
                        SELECT TOP (?)
                            reference_id,
                            question,
                            result_columns,
                            result_data,
                            query_context
                        FROM {self.schema}.chatbot_conversation
                        WHERE session_id = ?
                        ORDER BY created_at DESC, id DESC
                        """,
                        self.MAX_CONTEXT_TURNS,
                        session_id,
                    )
                    has_query_context_col = True
                except Exception:
                    cursor.execute(
                        f"""
                        SELECT TOP (?)
                            reference_id,
                            question,
                            result_columns,
                            result_data
                        FROM {self.schema}.chatbot_conversation
                        WHERE session_id = ?
                        ORDER BY created_at DESC, id DESC
                        """,
                        self.MAX_CONTEXT_TURNS,
                        session_id,
                    )
                    has_query_context_col = False

            rows = cursor.fetchall()

            history: list[dict[str, Any]] = []

            for row in reversed(rows):
                entry: dict[str, Any] = {
                    "reference_id": str(row.reference_id if hasattr(row, "reference_id") else row[0]),
                    "question": row.question if hasattr(row, "question") else row[1],
                    "columns": self._load_json(
                        row.result_columns if hasattr(row, "result_columns") else row[2],
                        default=[],
                    ),
                    "data": self._load_json(
                        row.result_data if hasattr(row, "result_data") else row[3],
                        default=None,
                    ),
                }

                qc_raw = None
                if has_query_context_col:
                    qc_raw = getattr(row, "query_context", None)
                    if qc_raw is None and len(row) > 4:
                        qc_raw = row[4]

                qc = self._load_json(qc_raw, default=None)
                if qc and isinstance(qc, dict):
                    entry["query_context"] = qc
                    entry["plan"] = qc.get("plan")
                    entry["tables"] = qc.get("tables", [])
                else:
                    entry["query_context"] = None
                    entry["plan"] = None
                    entry["tables"] = []

                history.append(entry)

            if not history:
                return {}

            return {
                "history": history,
            }

        except Exception as exc:
            err_str = str(exc).lower()
            if "does not exist" in err_str or "undefinedtable" in err_str or "invalid object name" in err_str:
                return {}
            raise ConversationMemoryError(
                f"Failed to load conversation memory: {exc}"
            ) from exc

        finally:
            if connection is not None:
                connection.close()

    def save(
        self,
        session_id: str | None,
        question: str,
        result: Any,
        plan: Any | None = None,
        tables: list[Any] | None = None,
        query_context: dict[str, Any] | None = None,
    ) -> str | None:
        """
        Store the verified query result and structured query context for a session.

        Returns the generated reference ID.
        """

        session_id = (session_id or "").strip()
        question = (question or "").strip()

        if not session_id or not question:
            return None

        reference_id = str(uuid.uuid4())

        columns, data = self._prepare_result(result)

        # Build minimum structured query context
        qc_dict = dict(query_context) if query_context else {}
        if plan is not None and "plan" not in qc_dict:
            qc_dict["plan"] = self._serialize_plan(plan)
        if tables is not None and "tables" not in qc_dict:
            qc_dict["tables"] = self._serialize_tables(tables)
        if "is_scalar" not in qc_dict:
            qc_dict["is_scalar"] = self._is_scalar_result(result)

        qc_json = json.dumps(qc_dict, ensure_ascii=False, default=str) if qc_dict else None

        connection = None

        try:
            connection = get_connection(self.config)
            cursor = connection.cursor()

            try:
                cursor.execute(
                    f"""
                    INSERT INTO {self.schema}.chatbot_conversation (
                        session_id,
                        reference_id,
                        question,
                        result_columns,
                        result_data,
                        query_context
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    session_id,
                    reference_id,
                    question,
                    json.dumps(
                        columns,
                        ensure_ascii=False,
                        default=str,
                    ),
                    json.dumps(
                        data,
                        ensure_ascii=False,
                        default=str,
                    ),
                    qc_json,
                )
            except Exception:
                if connection is not None and hasattr(connection, "rollback"):
                    connection.rollback()
                try:
                    cursor.execute(
                        f"""
                        INSERT INTO {self.schema}.chatbot_conversation (
                            session_id,
                            reference_id,
                            question,
                            result_columns,
                            result_data
                        )
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        session_id,
                        reference_id,
                        question,
                        json.dumps(
                            columns,
                            ensure_ascii=False,
                            default=str,
                        ),
                        json.dumps(
                            data,
                            ensure_ascii=False,
                            default=str,
                        ),
                    )
                except Exception as inner_exc:
                    if connection is not None and hasattr(connection, "rollback"):
                        connection.rollback()
                    # Table might not exist yet in newly connected database/schema
                    if self.is_postgresql:
                        self.ensure_table()
                        cursor.execute(
                            f"""
                            INSERT INTO {self.schema}.chatbot_conversation (
                                session_id,
                                reference_id,
                                question,
                                result_columns,
                                result_data,
                                query_context
                            )
                            VALUES (?, ?, ?, ?, ?, ?)
                            """,
                            session_id,
                            reference_id,
                            question,
                            json.dumps(columns, ensure_ascii=False, default=str),
                            json.dumps(data, ensure_ascii=False, default=str),
                            qc_json,
                        )
                    else:
                        raise inner_exc

            connection.commit()

            return reference_id

        except Exception as exc:
            if connection is not None:
                connection.rollback()

            raise ConversationMemoryError(
                f"Failed to save conversation memory: {exc}"
            ) from exc

        finally:
            if connection is not None:
                connection.close()

    @staticmethod
    def _is_scalar_result(result: Any) -> bool:
        if result is None:
            return True
        if isinstance(result, (int, float, str, bool)):
            return True
        if isinstance(result, list):
            if not result:
                return False
            return not all(isinstance(item, dict) for item in result)
        return False

    @staticmethod
    def _serialize_plan(plan: Any) -> dict[str, Any]:
        if plan is None:
            return {}
        return {
            "intent": getattr(plan, "intent", None),
            "target_columns": list(getattr(plan, "target_columns", []) or []),
            "filters": [
                {
                    "column": getattr(f, "column", None),
                    "operator": getattr(f, "operator", None),
                    "value": getattr(f, "value", None),
                }
                for f in getattr(plan, "filters", []) or []
                if f is not None
            ],
            "having_filters": [
                {
                    "column": getattr(f, "column", None),
                    "operator": getattr(f, "operator", None),
                    "value": getattr(f, "value", None),
                }
                for f in getattr(plan, "having_filters", []) or []
                if f is not None
            ],
            "group_by": list(getattr(plan, "group_by", []) or []),
            "group_by_granularity": getattr(plan, "group_by_granularity", None),
            "aggregation": getattr(plan, "aggregation", None),
            "inner_aggregation": getattr(plan, "inner_aggregation", None),
            "sort_column": getattr(plan, "sort_column", None),
            "sort_direction": getattr(plan, "sort_direction", None),
            "limit": getattr(plan, "limit", None),
            "include_ties": getattr(plan, "include_ties", False),
            "require_all_filter_values": getattr(plan, "require_all_filter_values", False),
            "joins": [
                {
                    "left_schema": getattr(j, "left_schema", ""),
                    "left_table": getattr(j, "left_table", ""),
                    "left_column": getattr(j, "left_column", ""),
                    "right_schema": getattr(j, "right_schema", ""),
                    "right_table": getattr(j, "right_table", ""),
                    "right_column": getattr(j, "right_column", ""),
                    "join_type": getattr(j, "join_type", "inner"),
                }
                for j in getattr(plan, "joins", []) or []
                if j is not None
            ],
            "target_column_refs": [
                {
                    "schema": getattr(r, "schema", None),
                    "table": getattr(r, "table", None),
                    "column": getattr(r, "column", ""),
                }
                for r in getattr(plan, "target_column_refs", []) or []
                if r is not None
            ],
            "group_by_refs": [
                {
                    "schema": getattr(r, "schema", None),
                    "table": getattr(r, "table", None),
                    "column": getattr(r, "column", ""),
                }
                for r in getattr(plan, "group_by_refs", []) or []
                if r is not None
            ],
        }

    @staticmethod
    def _serialize_tables(tables: list[Any]) -> list[dict[str, Any]]:
        result = []
        if not tables:
            return result
        for t in tables:
            if hasattr(t, "schema_name") and hasattr(t, "table_name"):
                col_defs = []
                for col in getattr(t, "columns", []) or []:
                    col_defs.append({
                        "name": getattr(col, "name", ""),
                        "data_type": getattr(col, "data_type", ""),
                        "nullable": getattr(col, "nullable", True),
                        "ordinal_position": getattr(col, "ordinal_position", 0),
                    })
                entry_dict: dict[str, Any] = {
                    "schema": t.schema_name,
                    "table": t.table_name,
                }
                if col_defs:
                    entry_dict["columns"] = col_defs
                if getattr(t, "primary_key_columns", None):
                    entry_dict["primary_key_columns"] = list(t.primary_key_columns)
                result.append(entry_dict)
            elif isinstance(t, dict):
                result.append({
                    "schema": t.get("schema", ""),
                    "table": t.get("table", ""),
                    "columns": t.get("columns", []),
                    "primary_key_columns": t.get("primary_key_columns", []),
                })
            elif isinstance(t, (list, tuple)) and len(t) == 2:
                result.append({"schema": str(t[0]), "table": str(t[1])})
        return result

    def _prepare_result(
        self,
        result: Any,
    ) -> tuple[list[str], Any]:
        """
        Convert a verified query result into bounded conversation context.

        Single-column results preserve distinct values so that follow-up
        operations have access to the complete value set without retaining
        unnecessary duplicate rows.

        Multi-column results remain bounded by MAX_RESULT_ROWS.
        """

        if result is None:
            return [], None

        if isinstance(result, dict):
            return list(result.keys()), result

        if isinstance(result, list):
            if not result:
                return [], []

            if all(isinstance(item, dict) for item in result):
                columns = self._collect_columns(result)

                if len(columns) == 1:
                    column = columns[0]

                    distinct_rows: list[dict[str, Any]] = []
                    seen_values: set[str] = set()

                    for row in result:
                        value = row.get(column)

                        value_key = json.dumps(
                            value,
                            ensure_ascii=False,
                            default=str,
                        )

                        if value_key in seen_values:
                            continue

                        seen_values.add(value_key)
                        distinct_rows.append(
                            {column: value}
                        )

                        if len(distinct_rows) >= self.MAX_DISTINCT_VALUES:
                            break

                    return columns, distinct_rows

                return (
                    columns,
                    result[: self.MAX_RESULT_ROWS],
                )

            return [], result[: self.MAX_RESULT_ROWS]

        return [], result

    @staticmethod
    def _collect_columns(
        rows: list[dict[str, Any]],
    ) -> list[str]:
        columns: list[str] = []
        seen: set[str] = set()

        for row in rows:
            for key in row.keys():
                column = str(key)

                if column not in seen:
                    seen.add(column)
                    columns.append(column)

        return columns

    @staticmethod
    def _load_json(
        value: Any,
        default: Any,
    ) -> Any:
        if value is None:
            return default

        if isinstance(value, (dict, list)):
            return value

        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return default
