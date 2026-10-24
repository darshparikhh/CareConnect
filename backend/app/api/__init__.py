"""REST API routers for CareConnect.

Each router is a thin HTTP surface over a service: it validates input with the
Pydantic schemas in :mod:`app.api.schemas`, wires auth/session dependencies and
error mapping from :mod:`app.api.deps`, and delegates all rules to the services.

Routers wired so far (task 17.1):

* :data:`auth_router` — sign-in and current-session (R4).
* :data:`registration_router` — patient/volunteer/clinician sign-up (R1-R3).

The patient/volunteer/clinician domain routers (tasks 17.2-17.4) follow the
same pattern and are added here as they land.
"""

from app.api.auth import router as auth_router
from app.api.clinician import router as clinician_router
from app.api.patient import router as patient_router
from app.api.registration import router as registration_router
from app.api.volunteer import router as volunteer_router

__all__ = [
    "auth_router",
    "registration_router",
    "patient_router",
    "volunteer_router",
    "clinician_router",
]
