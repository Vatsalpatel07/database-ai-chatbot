from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote_plus

from dotenv import load_dotenv

load_dotenv()


class DatabaseConfigurationError(ValueError):
    """Raised when database configuration is missing, malformed, or invalid."""


def parse_bool(value: Any, param_name: str) -> bool:
    """Parse a boolean value deterministically from string, int, or bool.

    Accepts:
      Truthy: True, 1, 'true', '1', 'yes', 'y', 'on'
      Falsy: False, 0, 'false', '0', 'no', 'n', 'off'
    Raises:
      DatabaseConfigurationError if the value cannot be parsed as a boolean.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        if value == 1:
            return True
        if value == 0:
            return False
        raise DatabaseConfigurationError(
            f"Invalid boolean value for {param_name}: '{value}'. Must be 1 (true) or 0 (false)."
        )
    if isinstance(value, str):
        cleaned = value.strip().casefold()
        if cleaned in ("true", "1", "yes", "y", "on"):
            return True
        if cleaned in ("false", "0", "no", "n", "off"):
            return False
        raise DatabaseConfigurationError(
            f"Invalid boolean value for {param_name}: '{value}'. Must be 'true' or 'false'."
        )
    raise DatabaseConfigurationError(
        f"Invalid boolean value for {param_name}: {type(value).__name__}. Must be a boolean or string."
    )


@dataclass(frozen=True)
class DatabaseConfig:
    """Canonical database connection configuration."""

    server: str
    database: str
    driver: str = "ODBC Driver 18 for SQL Server"
    trusted_connection: bool = True
    encrypt: str = "mandatory"
    trust_server_certificate: bool = True
    connection_timeout: int = 30
    user: str | None = None
    password: str | None = None
    engine: str = "sqlserver"
    port: int | None = None
    schema: str = "dbo"
    query_timeout: int = 30

    def __post_init__(self) -> None:
        # Normalize engine
        eng = (self.engine or "sqlserver").strip().casefold()
        if eng in ("postgres", "postgresql"):
            object.__setattr__(self, "engine", "postgresql")
            if self.port is None:
                object.__setattr__(self, "port", 5432)
            if self.driver == "ODBC Driver 18 for SQL Server":
                object.__setattr__(self, "driver", "psycopg")
            if self.trusted_connection and not self.user:
                # In PostgreSQL, trusted_connection is not applicable in the ODBC sense
                object.__setattr__(self, "trusted_connection", False)
        elif eng in ("sqlserver", "mssql", "mssql+pyodbc"):
            object.__setattr__(self, "engine", "sqlserver")
            if self.port is None:
                object.__setattr__(self, "port", 1433)
        else:
            raise DatabaseConfigurationError(
                f"Unsupported database engine '{self.engine}'. Must be 'postgresql' or 'sqlserver'."
            )

        self.validate()

    @property
    def is_postgresql(self) -> bool:
        return self.engine == "postgresql"

    @property
    def is_sql_server(self) -> bool:
        return self.engine == "sqlserver"

    def validate(self) -> None:
        """Validate that all database configuration settings are complete and compatible."""
        # 1. Server validation
        if not self.server or not str(self.server).strip():
            raise DatabaseConfigurationError(
                "Missing required database configuration: DB_SERVER is not set."
            )

        # 2. Database validation (strict - no silent fallback!)
        if not self.database or not str(self.database).strip():
            raise DatabaseConfigurationError(
                "Missing required database configuration: DB_NAME is not set."
            )

        # Check for banned legacy fallback databases
        if str(self.database).strip().casefold() in ("salesdb",):
            raise DatabaseConfigurationError(
                f"Configured database '{self.database}' is invalid: legacy fallback database cannot be used."
            )

        # 3. Timeout validation
        if self.connection_timeout is not None:
            try:
                t = int(self.connection_timeout)
                if t < 0:
                    raise ValueError()
            except (ValueError, TypeError):
                raise DatabaseConfigurationError(
                    f"Invalid connection timeout: '{self.connection_timeout}'. Must be a non-negative integer."
                )

        if self.query_timeout is not None:
            try:
                qt = int(self.query_timeout)
                if qt < 0:
                    raise ValueError()
            except (ValueError, TypeError):
                raise DatabaseConfigurationError(
                    f"Invalid query timeout: '{self.query_timeout}'. Must be a non-negative integer."
                )

        # 4. Engine-specific validation
        if self.is_postgresql:
            if not self.schema or not str(self.schema).strip():
                raise DatabaseConfigurationError(
                    "Missing required schema for PostgreSQL: DB_SCHEMA is not set."
                )
            if self.port is not None:
                try:
                    p = int(self.port)
                    if p <= 0 or p > 65535:
                        raise ValueError()
                except (ValueError, TypeError):
                    raise DatabaseConfigurationError(
                        f"Invalid port: '{self.port}'. Must be an integer between 1 and 65535."
                    )
        else:
            # SQL Server specific validation
            if not self.driver or not str(self.driver).strip():
                raise DatabaseConfigurationError(
                    "Missing required database configuration: DB_DRIVER is not set."
                )

            e = str(self.encrypt).strip().casefold()
            if e not in ("mandatory", "optional", "strict", "yes", "no"):
                raise DatabaseConfigurationError(
                    f"Invalid encryption setting for DB_ENCRYPT: '{self.encrypt}'. "
                    "Must be 'mandatory', 'optional', 'strict', 'yes', or 'no'."
                )

            if self.trusted_connection:
                if self.user or self.password:
                    raise DatabaseConfigurationError(
                        "Incompatible authentication settings: DB_USER / DB_PASSWORD cannot be used "
                        "when Trusted_Connection=yes (Windows Authentication)."
                    )
            else:
                if not self.user or not str(self.user).strip():
                    raise DatabaseConfigurationError(
                        "Missing required database user (DB_USER) when Windows Authentication "
                        "(Trusted_Connection) is disabled."
                    )

    @property
    def canonical_encrypt(self) -> str:
        """Map encrypt setting to standard SQL Server ODBC driver keyword."""
        e = str(self.encrypt).strip().casefold()
        if e in ("mandatory", "yes", "true", "1"):
            return "yes"
        if e in ("optional", "no", "false", "0"):
            return "no"
        return e

    @property
    def database_url(self) -> str:
        """Return SQLAlchemy database connection URL."""
        if self.is_postgresql:
            from sqlalchemy.engine import URL

            return URL.create(
                drivername="postgresql+psycopg",
                username=self.user or None,
                password=self.password or None,
                host=self.server,
                port=self.port or 5432,
                database=self.database,
            ).render_as_string(hide_password=False)
        return self.connection_string

    @property
    def safe_database_url(self) -> str:
        """Return SQLAlchemy database URL with masked password."""
        if self.is_postgresql:
            from sqlalchemy.engine import URL

            return URL.create(
                drivername="postgresql+psycopg",
                username=self.user or None,
                password=self.password or None,
                host=self.server,
                port=self.port or 5432,
                database=self.database,
            ).render_as_string(hide_password=True)
        return self.safe_connection_string

    @property
    def connection_string(self) -> str:
        """Construct the safe SQL Server ODBC connection string."""
        clean_driver = self.driver.strip().strip("{}")
        parts = [
            f"DRIVER={{{clean_driver}}}",
            f"SERVER={self.server.strip()}",
            f"DATABASE={self.database.strip()}",
        ]

        if self.trusted_connection:
            parts.append("Trusted_Connection=yes")
        else:
            parts.append(f"UID={self.user}")
            parts.append(f"PWD={self.password or ''}")

        parts.append(f"Encrypt={self.canonical_encrypt}")
        parts.append(
            f"TrustServerCertificate={'yes' if self.trust_server_certificate else 'no'}"
        )

        if self.connection_timeout is not None:
            parts.append(f"Timeout={int(self.connection_timeout)}")

        return ";".join(parts) + ";"

    @property
    def safe_connection_string(self) -> str:
        """Return connection string with passwords redacted for logging/diagnostics."""
        if not self.trusted_connection and self.password:
            cs = self.connection_string
            return cs.replace(f"PWD={self.password}", "PWD=***")
        return self.connection_string

    def __repr__(self) -> str:
        pwd_repr = "'***'" if self.password else "None"
        return (
            f"DatabaseConfig(engine={self.engine!r}, server={self.server!r}, "
            f"port={self.port!r}, database={self.database!r}, schema={self.schema!r}, "
            f"driver={self.driver!r}, trusted_connection={self.trusted_connection!r}, "
            f"encrypt={self.encrypt!r}, trust_server_certificate={self.trust_server_certificate!r}, "
            f"connection_timeout={self.connection_timeout!r}, query_timeout={self.query_timeout!r}, "
            f"user={self.user!r}, password={pwd_repr})"
        )

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "DatabaseConfig":
        """Load database configuration from environment variables or custom dict."""
        lookup = env if env is not None else os.environ

        server = (
            lookup.get("DB_SERVER")
            or lookup.get("SQL_SERVER")
            or lookup.get("POSTGRES_HOST")
            or lookup.get("SERVER")
            or ""
        )

        database = (
            lookup.get("DB_NAME")
            or lookup.get("DATABASE_NAME")
            or lookup.get("POSTGRES_DB")
            or lookup.get("DATABASE")
            or ""
        )

        raw_engine = lookup.get("DB_ENGINE") or lookup.get("DATABASE_ENGINE") or ""
        driver = lookup.get("DB_DRIVER") or lookup.get("DRIVER") or ""

        if raw_engine:
            eng = raw_engine.strip().casefold()
            if eng in ("postgres", "postgresql"):
                engine = "postgresql"
            elif eng in ("sqlserver", "mssql", "mssql+pyodbc"):
                engine = "sqlserver"
            else:
                raise DatabaseConfigurationError(
                    f"Unsupported DB_ENGINE: '{raw_engine}'. Must be 'postgresql' or 'sqlserver'."
                )
        else:
            # If DB_ENGINE is not set, infer engine
            if driver and ("odbc" in driver.casefold() or "sql server" in driver.casefold()):
                engine = "sqlserver"
            elif driver and ("psycopg" in driver.casefold() or "postgres" in driver.casefold()):
                engine = "postgresql"
            elif lookup.get("POSTGRES_DB") or lookup.get("POSTGRES_PORT"):
                engine = "postgresql"
            elif env is None:
                # Default to os.environ DB_ENGINE if present, else sqlserver for backward compatibility
                active_env_engine = os.environ.get("DB_ENGINE", "").strip().casefold()
                engine = "postgresql" if active_env_engine == "postgresql" else "sqlserver"
            else:
                engine = "sqlserver"

        if not driver:
            driver = "psycopg" if engine == "postgresql" else "ODBC Driver 18 for SQL Server"

        raw_port = lookup.get("DB_PORT") or lookup.get("POSTGRES_PORT") or lookup.get("PORT")
        port = int(raw_port) if raw_port else (5432 if engine == "postgresql" else 1433)

        schema = lookup.get("DB_SCHEMA") or lookup.get("SCHEMA") or "dbo"

        raw_trusted = (
            lookup.get("DB_TRUSTED_CONNECTION")
            or lookup.get("Trusted_Connection")
            or lookup.get("TRUSTED_CONNECTION")
            or ("no" if engine == "postgresql" else "yes")
        )
        trusted_connection = parse_bool(raw_trusted, "DB_TRUSTED_CONNECTION")

        raw_encrypt = (
            lookup.get("DB_ENCRYPT")
            or lookup.get("Encrypt")
            or lookup.get("ENCRYPT")
            or "mandatory"
        )

        raw_trust_cert = (
            lookup.get("DB_TRUST_SERVER_CERTIFICATE")
            or lookup.get("TrustServerCertificate")
            or lookup.get("TRUST_SERVER_CERTIFICATE")
            or "true"
        )
        trust_server_certificate = parse_bool(
            raw_trust_cert, "DB_TRUST_SERVER_CERTIFICATE"
        )

        raw_timeout = (
            lookup.get("DB_TIMEOUT")
            or lookup.get("DB_CONNECTION_TIMEOUT")
            or lookup.get("Connection_Timeout")
            or "30"
        )
        try:
            connection_timeout = int(raw_timeout) if raw_timeout else 30
        except (ValueError, TypeError):
            raise DatabaseConfigurationError(
                f"Invalid connection timeout: '{raw_timeout}'. Must be a non-negative integer."
            )

        raw_query_timeout = (
            lookup.get("DB_QUERY_TIMEOUT")
            or lookup.get("QUERY_TIMEOUT")
            or lookup.get("STATEMENT_TIMEOUT")
            or str(connection_timeout)
        )
        try:
            query_timeout = int(raw_query_timeout) if raw_query_timeout else 30
        except (ValueError, TypeError):
            raise DatabaseConfigurationError(
                f"Invalid query timeout: '{raw_query_timeout}'. Must be a non-negative integer."
            )

        if engine == "postgresql":
            user = (
                lookup.get("DB_USER")
                or lookup.get("POSTGRES_USER")
                or lookup.get("UID")
                or None
            )
            password = (
                lookup.get("DB_PASSWORD")
                or lookup.get("POSTGRES_PASSWORD")
                or lookup.get("PWD")
                or None
            )
        else:
            if trusted_connection:
                user = None
                password = None
            else:
                user = (
                    lookup.get("DB_USER")
                    or lookup.get("SQLSERVER_USER")
                    or lookup.get("UID")
                    or None
                )
                password = (
                    lookup.get("DB_PASSWORD")
                    or lookup.get("SQLSERVER_PASSWORD")
                    or lookup.get("PWD")
                    or None
                )

        return cls(
            server=server,
            database=database,
            driver=driver,
            trusted_connection=trusted_connection,
            encrypt=raw_encrypt,
            trust_server_certificate=trust_server_certificate,
            connection_timeout=connection_timeout,
            user=user,
            password=password,
            engine=engine,
            port=port,
            schema=schema,
            query_timeout=query_timeout,
        )


def get_database_config(env: dict[str, str] | None = None) -> DatabaseConfig:
    """Get canonical database configuration from environment."""
    return DatabaseConfig.from_env(env=env)


@dataclass(frozen=True)
class Settings:
    """Application configuration loaded from environment variables."""

    @property
    def app_name(self) -> str:
        return os.getenv("APP_NAME", "Database AI Chatbot")

    @property
    def deepseek_model(self) -> str:
        return os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")

    @property
    def max_selected_tables(self) -> int:
        return int(os.getenv("MAX_SELECTED_TABLES", "5"))

    @property
    def db_engine(self) -> str:
        return get_database_config().engine

    @property
    def db_server(self) -> str:
        return get_database_config().server

    @property
    def db_port(self) -> int | None:
        return get_database_config().port

    @property
    def db_name(self) -> str:
        return get_database_config().database

    @property
    def db_schema(self) -> str:
        return get_database_config().schema

    @property
    def db_driver(self) -> str:
        return get_database_config().driver

    @property
    def db_trust_server_certificate(self) -> bool:
        return get_database_config().trust_server_certificate

    @property
    def database_config(self) -> DatabaseConfig:
        return get_database_config()


settings = Settings()

__all__ = [
    "DatabaseConfig",
    "DatabaseConfigurationError",
    "Settings",
    "get_database_config",
    "parse_bool",
    "settings",
]
