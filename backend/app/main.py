"""FastAPI application entrypoint for CareConnect.

Wires the application surface: the app instance, a startup hook that ensures the
database schema exists, CORS for the Vite dev server, a health check, and the
role-scoped routers. The auth and registration routers (task 17.1) are
registered here; the patient/volunteer/clinician domain routers (tasks
17.2-17.4) are added as they land.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api import auth_router, patient_router, registration_router
from app.api import volunteer_router
from app.api import clinician_router
from app.database import init_db

# The Vite dev server origin the React SPA (task 18+) runs on. CORS is opened to
# this origin so the browser-based frontend can call the API cross-origin during
# development, including sending the session cookie / Authorization header.
FRONTEND_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Ensure tables exist before serving requests. Importing model modules in
    # later tasks registers them on the shared metadata picked up here.
    init_db()
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

    # Allow the Vite dev-server SPA to call the API cross-origin.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=FRONTEND_ORIGINS,
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
