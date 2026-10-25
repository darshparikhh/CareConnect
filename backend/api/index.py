"""Vercel serverless entrypoint for the CareConnect FastAPI backend.

@vercel/python runs this module as a serverless function and uses the
module-level ``app`` as the ASGI application. It adds this file's directory
(``backend/api``) to ``sys.path``, but the FastAPI app lives in the ``app``
package one level up (``backend/app``), so we insert the backend root
(``backend/``) onto ``sys.path`` *before* importing, so ``from app.main import
app`` resolves the ``app`` package rather than failing or shadowing.
"""
from __future__ import annotations
import sys
from pathlib import Path

# ``backend/`` — the directory that contains the ``app`` package.
BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.main import app  # noqa: E402  (import after sys.path setup)

__all__ = ["app"]
