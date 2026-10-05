# Database AI Chatbot

A generic Natural Language → SQL Database AI Chatbot.

The canonical active database engine is **PostgreSQL 18.x** with **pgvector 0.8.x** and **SQLAlchemy 2.x**.
Microsoft SQL Server remains fully supported as a reference and rollback engine.

The chatbot is strictly **generic and database-agnostic**: it discovers connected database schemas dynamically, indexes schema intelligence into pgvector, resolves entities without hardcoded business assumptions, and executes validated SQL queries via structured `QueryPlan` intermediate representations.

---

## Architecture

```text
Browser / API Client
  -> FastAPI (/ask/database, /health)
  -> Database Orchestrator
  -> Database Metadata Service & Semantic Cache
  -> pgvector Schema Vector Intelligence & Candidate Selection
  -> Question Analyzer (LLM / Deterministic)
  -> QueryPlan Validator (Schema & Fan-out Verification)
  -> SQL Executor (PostgreSQL / SQL Server Dialect Execution)
  -> Query Result Validator
  -> Answer Generator
  -> Conversation Memory (Isolated Session Context)
  -> Browser / API Client
```

---

## Configuration

Copy `.env.example` to `.env` and configure your database and LLM credentials:

```bash
cp .env.example .env
```

### PostgreSQL (Canonical Active Default)
```ini
DB_ENGINE=postgresql
DB_SERVER=localhost
DB_PORT=5432
DB_NAME=mnghealthreportingdb
DB_SCHEMA=dbo
DB_USER=postgres
DB_PASSWORD=your_password
DB_TIMEOUT=30
DB_QUERY_TIMEOUT=30
```

### SQL Server (Rollback / Reference)
```ini
DB_ENGINE=sqlserver
DB_SERVER=localhost
DB_NAME=mnghealthreportingdb
DB_DRIVER=ODBC Driver 18 for SQL Server
DB_TRUST_SERVER_CERTIFICATE=true
DB_TRUSTED_CONNECTION=yes
DB_ENCRYPT=mandatory
DB_TIMEOUT=30
```

---

## Installation & Setup

1. **Install dependencies:**
   ```powershell
   pip install -r requirements.txt
   ```

2. **Run tests:**
   ```powershell
   python -m pytest -q
   ```

3. **Start the application server:**
   ```powershell
   python -m uvicorn app.web:app --reload
   ```

4. **Access the application:**
   - Web UI: `http://127.0.0.1:8000/`
   - Health check: `http://127.0.0.1:8000/health`
   - Query endpoint: `POST http://127.0.0.1:8000/ask/database`

---

## Operational Features

- **Query Timeouts:** Server-enforced statement timeout (`statement_timeout=30s`) with clean connection pool recovery.
- **Result Safety:** Unbounded lookup queries capped at 5,000 rows (`MAX_LOOKUP_ROWS`) to prevent memory exhaustion.
- **Strict Isolation:** Schema fingerprints, semantic caches, relationship knowledge, and pgvector embeddings are strictly partitioned by `(database_identity, schema_fingerprint)`.
- **Database Switching:** Supports dynamic switching to distinct schemas with instant cache invalidation and zero cross-database leakage.
- **Rollback Readiness:** Full compatibility with SQL Server retained across configuration, connection, and executor layers.
