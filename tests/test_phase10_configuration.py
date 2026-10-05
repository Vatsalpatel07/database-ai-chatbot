from __future__ import annotations

import os
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from app.core.config import (
    DatabaseConfig,
    DatabaseConfigurationError,
    get_database_config,
    parse_bool,
    settings,
)
from app.database.connection import (
    DatabaseConnectionError,
    get_connection,
    test_connection as run_test_connection,
)
from app.web import app


# =============================================================================
# 1. Validation & Loading Tests
# =============================================================================

def test_valid_configuration_loads_correctly():
    """Valid database configuration loads and populates all fields accurately."""
    env = {
        "DB_SERVER": "db.example.internal",
        "DB_NAME": "enterprise_db",
        "DB_DRIVER": "ODBC Driver 18 for SQL Server",
        "DB_TRUSTED_CONNECTION": "yes",
        "DB_ENCRYPT": "mandatory",
        "DB_TRUST_SERVER_CERTIFICATE": "true",
        "DB_TIMEOUT": "25",
    }
    cfg = DatabaseConfig.from_env(env)
    assert cfg.server == "db.example.internal"
    assert cfg.database == "enterprise_db"
    assert cfg.driver == "ODBC Driver 18 for SQL Server"
    assert cfg.trusted_connection is True
    assert cfg.canonical_encrypt == "yes"
    assert cfg.trust_server_certificate is True
    assert cfg.connection_timeout == 25


def test_missing_server_fails_clearly():
    """Missing or empty DB_SERVER raises a clear DatabaseConfigurationError."""
    with pytest.raises(DatabaseConfigurationError, match=r"DB_SERVER"):
        DatabaseConfig.from_env({"DB_SERVER": "", "DB_NAME": "testdb"})

    with pytest.raises(DatabaseConfigurationError, match=r"DB_SERVER"):
        DatabaseConfig.from_env({"DB_NAME": "testdb"})


def test_missing_database_fails_clearly():
    """Missing or empty DB_NAME raises a clear DatabaseConfigurationError."""
    with pytest.raises(DatabaseConfigurationError, match=r"DB_NAME"):
        DatabaseConfig.from_env({"DB_SERVER": "localhost", "DB_NAME": ""})

    with pytest.raises(DatabaseConfigurationError, match=r"DB_NAME"):
        DatabaseConfig.from_env({"DB_SERVER": "localhost"})


def test_missing_driver_fails_clearly():
    """Empty DB_DRIVER raises a clear DatabaseConfigurationError."""
    with pytest.raises(DatabaseConfigurationError, match=r"DB_DRIVER"):
        DatabaseConfig.from_env({
            "DB_SERVER": "localhost",
            "DB_NAME": "testdb",
            "DB_DRIVER": "   ",
        })


def test_invalid_boolean_fails_clearly():
    """Non-boolean string for boolean settings raises DatabaseConfigurationError."""
    with pytest.raises(DatabaseConfigurationError, match=r"Invalid boolean value for DB_TRUST_SERVER_CERTIFICATE"):
        DatabaseConfig.from_env({
            "DB_SERVER": "localhost",
            "DB_NAME": "testdb",
            "DB_TRUST_SERVER_CERTIFICATE": "unrecognized_bool",
        })

    with pytest.raises(DatabaseConfigurationError, match=r"Invalid boolean value for DB_TRUSTED_CONNECTION"):
        DatabaseConfig.from_env({
            "DB_SERVER": "localhost",
            "DB_NAME": "testdb",
            "DB_TRUSTED_CONNECTION": "maybe",
        })


def test_valid_boolean_values_parsed_correctly():
    """All standard boolean truthy and falsy representations are parsed correctly."""
    for truthy in ("true", "TRUE", "1", "yes", "YES", "y", "on", True, 1):
        assert parse_bool(truthy, "test_param") is True

    for falsy in ("false", "FALSE", "0", "no", "NO", "n", "off", False, 0):
        assert parse_bool(falsy, "test_param") is False

    with pytest.raises(DatabaseConfigurationError):
        parse_bool("invalid", "param")

    with pytest.raises(DatabaseConfigurationError):
        parse_bool(2, "param")


# =============================================================================
# 2. Authentication & Connection String Tests
# =============================================================================

def test_windows_authentication_configuration():
    """Windows Authentication (Trusted_Connection=yes) constructs correct connection string without credentials."""
    cfg = DatabaseConfig(
        server="localhost",
        database="testdb",
        trusted_connection=True,
    )
    cs = cfg.connection_string
    assert "Trusted_Connection=yes" in cs
    assert "UID=" not in cs
    assert "PWD=" not in cs


def test_trusted_connection_handling():
    """Trusted connection handles SQL auth cleanly and rejects incompatible settings."""
    # SQL Auth valid case
    cfg_sql = DatabaseConfig(
        server="localhost",
        database="testdb",
        trusted_connection=False,
        user="sql_admin",
        password="P@ssw0rdSecure!",
    )
    cs = cfg_sql.connection_string
    assert "UID=sql_admin" in cs
    assert "PWD=P@ssw0rdSecure!" in cs
    assert "Trusted_Connection=yes" not in cs

    # Incompatible settings: user supplied with Windows Auth
    with pytest.raises(DatabaseConfigurationError, match=r"Incompatible authentication settings"):
        DatabaseConfig(
            server="localhost",
            database="testdb",
            trusted_connection=True,
            user="sql_admin",
        )

    # Missing user when SQL auth is chosen
    with pytest.raises(DatabaseConfigurationError, match=r"Missing required database user"):
        DatabaseConfig(
            server="localhost",
            database="testdb",
            trusted_connection=False,
            user=None,
        )


def test_encrypt_handling():
    """Encrypt configurations (mandatory, optional, strict) map accurately."""
    cfg_man = DatabaseConfig(server="s", database="d", encrypt="mandatory")
    assert "Encrypt=yes" in cfg_man.connection_string

    cfg_opt = DatabaseConfig(server="s", database="d", encrypt="optional")
    assert "Encrypt=no" in cfg_opt.connection_string

    cfg_strict = DatabaseConfig(server="s", database="d", encrypt="strict")
    assert "Encrypt=strict" in cfg_strict.connection_string

    with pytest.raises(DatabaseConfigurationError, match=r"Invalid encryption setting"):
        DatabaseConfig(server="s", database="d", encrypt="unsupported_encrypt")


def test_trust_server_certificate_handling():
    """TrustServerCertificate setting properly populates yes or no in connection string."""
    cfg_trust = DatabaseConfig(server="s", database="d", trust_server_certificate=True)
    assert "TrustServerCertificate=yes" in cfg_trust.connection_string

    cfg_no_trust = DatabaseConfig(server="s", database="d", trust_server_certificate=False)
    assert "TrustServerCertificate=no" in cfg_no_trust.connection_string


# =============================================================================
# 3. Safety, Fallback & Security Tests
# =============================================================================

def test_no_fallback_to_old_database():
    """When DB_NAME is missing, system fails strictly without falling back to any default database."""
    with pytest.raises(DatabaseConfigurationError):
        DatabaseConfig.from_env({"DB_SERVER": "localhost"})


def test_no_hardcoded_salesdb_fallback():
    """Setting legacy SalesDB database is strictly rejected and prevented."""
    with pytest.raises(DatabaseConfigurationError, match=r"legacy fallback database cannot be used"):
        DatabaseConfig.from_env({"DB_SERVER": "localhost", "DB_NAME": "SalesDB"})

    with pytest.raises(DatabaseConfigurationError, match=r"legacy fallback database cannot be used"):
        DatabaseConfig.from_env({"DB_SERVER": "localhost", "DB_NAME": "salesdb"})


def test_environment_overrides_defaults_correctly():
    """Environment variables correctly override optional configuration defaults."""
    env = {
        "DB_SERVER": "custom-server",
        "DB_NAME": "custom-db",
        "DB_DRIVER": "ODBC Driver 17 for SQL Server",
        "DB_TIMEOUT": "60",
    }
    cfg = DatabaseConfig.from_env(env)
    assert cfg.server == "custom-server"
    assert cfg.database == "custom-db"
    assert cfg.driver == "ODBC Driver 17 for SQL Server"
    assert cfg.connection_timeout == 60


def test_connection_string_construction():
    """Connection string construction safely sanitizes driver braces and formats parameters."""
    # Driver without curly braces
    cfg1 = DatabaseConfig(server="srv", database="db", driver="ODBC Driver 18 for SQL Server")
    assert "DRIVER={ODBC Driver 18 for SQL Server};" in cfg1.connection_string

    # Driver already having curly braces
    cfg2 = DatabaseConfig(server="srv", database="db", driver="{ODBC Driver 18 for SQL Server}")
    assert "DRIVER={ODBC Driver 18 for SQL Server};" in cfg2.connection_string
    assert "{{ODBC" not in cfg2.connection_string


def test_credentials_not_exposed_in_errors_or_logging():
    """Passwords are redacted in repr, safe_connection_string, and error messages."""
    cfg = DatabaseConfig(
        server="srv",
        database="db",
        trusted_connection=False,
        user="testuser",
        password="SuperSecretPassword!",
    )
    # repr masking
    repr_str = repr(cfg)
    assert "SuperSecretPassword!" not in repr_str
    assert "'***'" in repr_str

    # safe_connection_string masking
    safe_cs = cfg.safe_connection_string
    assert "SuperSecretPassword!" not in safe_cs
    assert "PWD=***" in safe_cs

    # Error wrapping in get_connection does not expose password
    with patch("pyodbc.connect", side_effect=Exception("ODBC network error: server unreachable")):
        with pytest.raises(DatabaseConnectionError) as exc_info:
            get_connection(cfg)
        assert "SuperSecretPassword!" not in str(exc_info.value)


# =============================================================================
# 4. Identity & Infrastructure Integration Tests
# =============================================================================

def test_cache_identity_uses_canonical_server_database():
    """test_connection returns the canonical configured server and active database."""
    cfg = DatabaseConfig(server="localhost", database="mnghealthreportingdb")

    mock_row = MagicMock()
    mock_row.database_name = "mnghealthreportingdb"
    mock_row.server_name = "PHYSICAL-MACHINE-XYZ"

    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = mock_row

    mock_connection = MagicMock()
    mock_connection.cursor.return_value = mock_cursor
    mock_connection.__enter__.return_value = mock_connection
    mock_connection.__exit__.return_value = False

    with patch("pyodbc.connect", return_value=mock_connection):
        result = run_test_connection(cfg)
        assert result["server_name"] == "localhost"
        assert result["database_name"] == "mnghealthreportingdb"
        assert result["instance_name"] == "PHYSICAL-MACHINE-XYZ"


def test_imports_do_not_require_live_sql_connection():
    """Importing core modules and web app does not initiate any database queries."""
    with patch("pyodbc.connect") as mock_connect:
        import app.core.config
        import app.database.connection
        import app.orchestration.database_orchestrator
        import app.web
        mock_connect.assert_not_called()


def test_health_endpoint_behavior_remains_valid():
    """FastAPI GET /health endpoint returns 200 OK and valid status."""
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_invalid_configuration_does_not_trigger_database_queries():
    """Invalid configuration raises an exception before any database connection attempt is made."""
    with patch("pyodbc.connect") as mock_connect:
        with pytest.raises(DatabaseConfigurationError):
            get_connection(DatabaseConfig(server="", database="testdb"))
        mock_connect.assert_not_called()


def test_current_mnghealthreportingdb_configuration_accepted():
    """The current environment configuration for mnghealthreportingdb is accepted cleanly."""
    env = {
        "DB_SERVER": "localhost",
        "DB_NAME": "mnghealthreportingdb",
        "DB_DRIVER": "ODBC Driver 18 for SQL Server",
        "DB_TRUST_SERVER_CERTIFICATE": "true",
        "DB_TRUSTED_CONNECTION": "yes",
        "DB_ENCRYPT": "mandatory",
        "DB_TIMEOUT": "30",
    }
    cfg = DatabaseConfig.from_env(env)
    assert cfg.server == "localhost"
    assert cfg.database == "mnghealthreportingdb"
    assert cfg.trusted_connection is True
    assert cfg.canonical_encrypt == "yes"
    assert cfg.trust_server_certificate is True
    assert "DATABASE=mnghealthreportingdb" in cfg.connection_string
    assert "Trusted_Connection=yes" in cfg.connection_string
    assert "Encrypt=yes" in cfg.connection_string
