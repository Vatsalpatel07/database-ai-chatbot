from __future__ import annotations

import re
from typing import Any

from dotenv import load_dotenv
from psycopg.rows import namedtuple_row
from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import URL

try:
    import pyodbc
except ImportError:
    pyodbc = None

from app.core.config import (
    DatabaseConfig,
    DatabaseConfigurationError,
    get_database_config,
)

load_dotenv()


class DatabaseConnectionError(RuntimeError):
    """Raised when connecting to the configured database fails."""


_ENGINES: dict[str, Engine] = {}


def get_engine(config: DatabaseConfig | None = None) -> Engine:
    """Create or retrieve a canonical SQLAlchemy 2.x Engine for PostgreSQL."""
    cfg = config or get_database_config()
    cfg.validate()

    cache_key = f"{cfg.engine}:{cfg.server}:{cfg.port}:{cfg.database}:{cfg.schema}"
    if cache_key in _ENGINES:
        return _ENGINES[cache_key]

    try:
        url = URL.create(
            drivername="postgresql+psycopg",
            username=cfg.user or None,
            password=cfg.password or None,
            host=cfg.server,
            port=cfg.port or 5432,
            database=cfg.database,
        )

        statement_timeout_ms = int(getattr(cfg, "query_timeout", None) or cfg.connection_timeout or 30) * 1000
        engine = create_engine(
            url,
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True,
            pool_recycle=3600,
            pool_timeout=cfg.connection_timeout or 30,
            connect_args={"options": f"-c search_path={cfg.schema},public -c statement_timeout={statement_timeout_ms}"},
        )
        _ENGINES[cache_key] = engine
        return engine
    except Exception as exc:
        err_msg = str(exc)
        if cfg.password:
            err_msg = err_msg.replace(cfg.password, "***")
        raise DatabaseConnectionError(
            f"Failed to create SQLAlchemy engine for '{cfg.database}' on '{cfg.server}': {err_msg}"
        ) from exc


class PostgresCursorWrapper:
    """Wraps a psycopg cursor to provide drop-in compatibility with DB-API and pyodbc.Row."""

    def __init__(self, raw_cursor: Any) -> None:
        self._cur = raw_cursor

    def execute(self, query: str, *args: Any, **kwargs: Any) -> "PostgresCursorWrapper":
        params: Any = None
        if args:
            if len(args) == 1 and isinstance(args[0], (list, tuple)):
                params = args[0]
            else:
                params = args

        # PostgreSQL doesn't have COUNT_BIG; standard COUNT returns 64-bit int
        if "COUNT_BIG" in query:
            query = query.replace("COUNT_BIG", "COUNT")

        # Translate ? parameter placeholders to %s for psycopg 3
        if "?" in query:
            query = query.replace("?", "%s")

        try:
            if params is not None:
                self._cur.execute(query, tuple(params), **kwargs)
            else:
                self._cur.execute(query, **kwargs)
            return self
        except Exception as exc:
            raise exc

    def fetchone(self) -> Any:
        return self._cur.fetchone()

    def fetchall(self) -> list[Any]:
        return self._cur.fetchall()

    @property
    def description(self) -> Any:
        return self._cur.description

    def close(self) -> None:
        self._cur.close()

    def __enter__(self) -> "PostgresCursorWrapper":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()


class PostgresConnectionWrapper:
    """Wraps an active SQLAlchemy pooled connection with DB-API cursor interface."""

    def __init__(self, raw_connection: Any) -> None:
        self._raw = raw_connection

    def cursor(self) -> PostgresCursorWrapper:
        cur = self._raw.cursor(row_factory=namedtuple_row)
        return PostgresCursorWrapper(cur)

    def commit(self) -> None:
        self._raw.commit()

    def rollback(self) -> None:
        self._raw.rollback()

    def close(self) -> None:
        self._raw.close()

    def __enter__(self) -> "PostgresConnectionWrapper":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if exc_type is not None:
            try:
                self.rollback()
            except Exception:
                pass
        self.close()


def get_connection(config: DatabaseConfig | None = None) -> Any:
    """Create a connection to the configured database (PostgreSQL via SQLAlchemy or SQL Server via pyodbc)."""
    cfg = config or get_database_config()
    cfg.validate()

    if cfg.is_postgresql:
        try:
            engine = get_engine(cfg)
            raw_conn = engine.raw_connection()
            return PostgresConnectionWrapper(raw_conn)
        except Exception as exc:
            err_msg = str(exc)
            if cfg.password:
                err_msg = err_msg.replace(cfg.password, "***")
            raise DatabaseConnectionError(
                f"Failed to connect to PostgreSQL database '{cfg.database}' on server '{cfg.server}:{cfg.port}': {err_msg}"
            ) from exc
    else:
        # SQL Server via pyodbc
        try:
            import pyodbc

            return pyodbc.connect(cfg.connection_string, timeout=cfg.connection_timeout)
        except Exception as exc:
            err_msg = str(exc)
            if cfg.password:
                err_msg = err_msg.replace(cfg.password, "***")
            raise DatabaseConnectionError(
                f"Failed to connect to SQL Server database '{cfg.database}' on server '{cfg.server}': {err_msg}"
            ) from exc


def test_connection(config: DatabaseConfig | None = None) -> dict[str, Any]:
    """Test the database connection and return canonical database and server information."""
    cfg = config or get_database_config()
    with get_connection(cfg) as connection:
        cursor = connection.cursor()

        if cfg.is_postgresql:
            cursor.execute(
                """
                SELECT
                    current_database() AS database_name,
                    COALESCE(inet_server_addr()::text, %s) AS server_name,
                    current_schema() AS schema_name
                """,
                (cfg.server,),
            )
            row = cursor.fetchone()
            active_db = row.database_name if hasattr(row, "database_name") else row[0]
            server_ip = row.server_name if hasattr(row, "server_name") else row[1]
            schema_name = row.schema_name if hasattr(row, "schema_name") else row[2]

            if active_db and cfg.database and active_db.casefold() != cfg.database.casefold():
                raise DatabaseConnectionError(
                    f"Connected to database '{active_db}', but configured database is '{cfg.database}'."
                )

            return {
                "database_name": active_db or cfg.database,
                "server_name": cfg.server,
                "instance_name": f"PostgreSQL {server_ip or cfg.server}:{cfg.port}",
                "schema_name": schema_name or cfg.schema,
            }
        else:
            cursor.execute(
                """
                SELECT
                    DB_NAME() AS database_name,
                    @@SERVERNAME AS server_name
                """
            )
            row = cursor.fetchone()
            active_db = row.database_name if hasattr(row, "database_name") else row[0]
            server_name = row.server_name if hasattr(row, "server_name") else row[1]

            if active_db and cfg.database and active_db.casefold() != cfg.database.casefold():
                raise DatabaseConnectionError(
                    f"Connected to database '{active_db}', but configured database is '{cfg.database}'."
                )

            return {
                "database_name": active_db or cfg.database,
                "server_name": cfg.server,
                "instance_name": (server_name if row else None) or cfg.server,
            }


def dispose_engine(config: DatabaseConfig | None = None) -> None:
    """Dispose and remove a specific cached SQLAlchemy engine."""
    cfg = config or get_database_config()
    cache_key = f"{cfg.engine}:{cfg.server}:{cfg.port}:{cfg.database}:{cfg.schema}"
    engine = _ENGINES.pop(cache_key, None)
    if engine is not None:
        try:
            engine.dispose()
        except Exception:
            pass


def dispose_all_engines() -> None:
    """Dispose and clear all cached SQLAlchemy engines on shutdown or test reset."""
    for engine in list(_ENGINES.values()):
        try:
            engine.dispose()
        except Exception:
            pass
    _ENGINES.clear()


__all__ = [
    "DatabaseConfig",
    "DatabaseConfigurationError",
    "DatabaseConnectionError",
    "PostgresConnectionWrapper",
    "PostgresCursorWrapper",
    "dispose_all_engines",
    "dispose_engine",
    "get_connection",
    "get_database_config",
    "get_engine",
    "test_connection",
]