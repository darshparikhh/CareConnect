"""Application configuration.

Centralizes the small number of settings the backend needs. The database URL
defaults to a file-based SQLite database living next to the backend package so
the demo seeds from (and persists to) a single file with zero setup, matching
the design's data-store decision. In a cloud deployment (Vercel / Render) a
hosted Postgres URL is supplied via the environment and takes precedence.
"""
from __future__ import annotations
import os
from pathlib import Path
# Directory that contains the ``backend`` package (i.e. the project's backend root).
BACKEND_ROOT = Path(__file__).resolve().parent.parent
# Default file-based SQLite database, overridable via the environment so tests
# and alternate deployments can point elsewhere.
DEFAULT_SQLITE_PATH = BACKEND_ROOT / "careconnect.db"
def _normalize_postgres_url(url: str) -> str:
    """Rewrite bare Postgres URLs to use the psycopg v3 driver.

    Render, Vercel Postgres, and most managed Postgres providers hand out URLs
    with the ``postgres://`` or ``postgresql://`` scheme. SQLAlchemy needs an
    explicit driver, so when no ``+driver`` is present we rewrite the scheme to
    ``postgresql+psycopg://`` (psycopg v3). URLs that already name a driver
    (e.g. ``postgresql+asyncpg://``) are left untouched.
    """
    for prefix in ("postgresql://", "postgres://"):
        if url.startswith(prefix):
            # Only rewrite when the scheme carries no explicit "+driver".
            scheme, sep, rest = url.partition("://")
            if "+" not in scheme:
                return f"postgresql+psycopg://{rest}"
            return url
    return url
def get_database_url() -> str:
    """Return the configured database URL.

    Environment precedence:
    1. ``DATABASE_URL`` — Render's standard injected connection string.
    2. ``POSTGRES_URL`` — Vercel Postgres's standard injected connection
       string (Vercel also injects ``POSTGRES_PRISMA_URL`` et al.).
    3. ``CARECONNECT_DATABASE_URL`` — app-specific override.
    4. A file-based SQLite database in the backend root (local/dev default).

    If the resolved URL is a bare Postgres URL (``postgres://`` or
    ``postgresql://`` with no ``+driver``), its scheme is rewritten to
    ``postgresql+psycopg://`` so SQLAlchemy uses psycopg v3.
    """
    override = (
        os.environ.get("DATABASE_URL")
        or os.environ.get("POSTGRES_URL")
        or os.environ.get("CARECONNECT_DATABASE_URL")
    )
    if override:
        return _normalize_postgres_url(override)
    return f"sqlite:///{DEFAULT_SQLITE_PATH}"
__all__ = ["BACKEND_ROOT", "DEFAULT_SQLITE_PATH", "get_database_url"]
