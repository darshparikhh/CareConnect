# CareConnect Backend

FastAPI + SQLAlchemy/SQLite backend hosting the Matching and Recommendation
data science engines and the appointment state machine. All records are
synthetic (Requirement 20.1).

## Layout

```
backend/
  app/
    __init__.py
    config.py          # settings + database URL resolution
    database.py        # engine, session factory, transactional session dependency
    main.py            # FastAPI app factory + health check
    models/            # SQLAlchemy declarative base + ORM models (task 2)
    services/          # registration, auth, credentials, appointments, ... (later tasks)
    engines/           # Matching_Engine, Recommendation_Engine (later tasks)
    api/               # REST routers (later tasks)
    tests/             # pytest suite + isolated SQLite fixtures
  pyproject.toml
  requirements.txt
```

## Setup

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
uvicorn app.main:app --reload
# health check: GET http://127.0.0.1:8000/health
```

## Test

```bash
pytest
```

Tests use an isolated per-test SQLite database (temp-file or in-memory) via the
fixtures in `app/tests/conftest.py`, so they never touch the development
database.
