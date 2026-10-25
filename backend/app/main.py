"""FastAPI application entrypoint for CareConnect.

Wires the application surface: the app instance, a startup hook that ensures the
database schema exists, CORS for the Vite dev server, a health check, and the
role-scoped routers. The auth and registration routers (task 17.1) are
registered here; the patient/volunteer/clinician domain routers (tasks
17.2-17.4) are added as they land.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api import auth_router, patient_router, registration_router
from app.api import volunteer_router
from app.api import clinician_router
from app.database import init_db, session_scope

# The Vite dev server origin the React SPA (task 18+) runs on. CORS is opened to
# this origin so the browser-based frontend can call the API cross-origin during
# development, including sending the session cookie / Authorization header.
# Local dev origins (Vite). Production is cross-origin: the Vercel-hosted SPA
# calls this Render-hosted API, so the deployed frontend's origin must be
# allowed too. Set FRONTEND_ORIGIN on Render to your exact Vercel URL (e.g.
# https://care-connect-xyz.vercel.app); any *.vercel.app origin is also allowed
# via FRONTEND_ORIGIN_REGEX so preview deployments work without reconfiguring.
FRONTEND_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]
_env_origin = os.environ.get("FRONTEND_ORIGIN")
if _env_origin:
    FRONTEND_ORIGINS.append(_env_origin.rstrip("/"))

# Allow every Vercel deployment domain (production + previews) by default; an
# explicit regex can override via FRONTEND_ORIGIN_REGEX.
FRONTEND_ORIGIN_REGEX = os.environ.get(
    "FRONTEND_ORIGIN_REGEX", r"https://.*\.vercel\.app"
)


logger = logging.getLogger(__name__)


def init_and_seed() -> None:
    """Create tables and seed demo data if the database is empty (idempotent).

    This runs at app-creation time (not only in the lifespan hook) so the schema
    always exists regardless of HOW the app is started: uvicorn (local), a bare
    import by a serverless handler (Vercel), or a TestClient without a lifespan
    context. Creating tables is a no-op when they already exist, and seeding
    only happens when there are zero Patient rows, so repeated calls are safe.
    """
    init_db()
    try:
        from sqlalchemy import select

        from app.models.people import Patient
        from app.seed import seed as seed_demo_data
        from app.services.insurance import verify_insurance

        with session_scope() as session:
            already_seeded = (
                session.execute(select(Patient.id).limit(1)).first() is not None
            )
            if not already_seeded:
                result = seed_demo_data(session)
                verify_insurance(session, result.boston_patient)
                logger.info("Auto-seeded demo data into an empty database.")
    except Exception:  # noqa: BLE001 - never let seeding crash startup
        logger.exception("Auto-seed failed; continuing without it.")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Belt-and-suspenders: ensure schema + seed on startup too. Safe/idempotent.
    init_and_seed()
    yield


def create_app() -> FastAPI:
    """Application factory so tests can build isolated app instances."""
    app = FastAPI(
        title="CareConnect",
        version=__version__,
        description=(
            "Backend API for CareConnect: coordinates at-home preventive care "
            "across Patient, Volunteer, and Clinician roles."
        ),
        lifespan=lifespan,
    )

    # Guarantee the schema exists (and demo data is seeded) as soon as the app
    # is created, covering serverless/import and TestClient startup paths.
    init_and_seed()

    # Allow the Vite dev-server SPA to call the API cross-origin.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=FRONTEND_ORIGINS,
        allow_origin_regex=FRONTEND_ORIGIN_REGEX,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health", tags=["system"])
    def health() -> dict[str, str]:
        """Liveness probe."""
        return {"status": "ok", "version": __version__}

    # Public auth + registration routes (task 17.1). Role-gated domain routers
    # (tasks 17.2-17.4) register here as they are implemented.
    app.include_router(auth_router)
    app.include_router(registration_router)
    app.include_router(patient_router)
    app.include_router(volunteer_router)
    app.include_router(clinician_router)

    return app


app = create_app()

__all__ = ["app", "create_app"]
