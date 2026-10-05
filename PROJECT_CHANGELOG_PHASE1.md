# Phase 1 Integration — Production Structure

This package is the latest uploaded SQL Server chatbot project with the Phase 1 structural changes integrated into the same codebase.

## What changed

- Added `app/api/routes/` for HTTP route separation:
  - `database.py`
  - `frontend.py`
  - `health.py`
- Added `app/core/` for application configuration and logging:
  - `config.py`
  - `logging.py`
- Added `app/orchestration/database_orchestrator.py` as the application-level orchestration boundary.
- Simplified `app/web.py` to application creation and router registration.
- Kept the existing database/query/LLM implementation intact.
- Kept the existing frontend intact.
- Removed obsolete Excel-only runtime dependencies from `requirements.txt`.
- Added `.env.example` for configuration documentation.
- Excluded `.env`, backup CSS/JS files, Python caches, and compiled files from this production package.

## Important

The existing SQL Server database configuration is intentionally not packaged as `.env`.
Create/copy a local `.env` using `.env.example` and keep secrets out of source control.

## Runtime

Install dependencies once:

```powershell
pip install -r requirements.txt
```

Run:

```powershell
python -m uvicorn app.web:app --reload
```

Health check:

```text
http://127.0.0.1:8000/health
```

Database API:

```text
POST /ask/database
```

No query-planning behavior was intentionally redesigned in this phase. The purpose of this change is to establish a stable production structure before adding semantic caching, stronger schema intelligence, relationship inference, and deterministic orchestration improvements in later phases.
