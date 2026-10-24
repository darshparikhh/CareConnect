"""Application configuration.

Centralizes the small number of settings the backend needs. The database URL
defaults to a file-based SQLite database living next to the backend package so
the demo seeds from (and persists to) a single file with zero setup, matching
the design's data-store decision.
"""

from __future__ import annotations

import os
from pathlib import Path

# Directory that contains the ``backend`` package (i.e. the project's backend root).
BACKEND_ROOT = Path(__file__).resolve().parent.parent

# Default file-based SQLite database, overridable via the environment so tests
# and alternate deployments can point elsewhere.
DEFAULT_SQLITE_PATH = BACKEND_ROOT / "careconnect.db"


def get_database_url() -> str:
    """Return the configured database URL.

    Reads ``CARECONNECT_DATABASE_URL`` when set; otherwise falls back to a
    file-based SQLite database in the backend root.
    """
    override = os.environ.get("CARECONNECT_DATABASE_URL")
    if override:
        return override
    return f"sqlite:///{DEFAULT_SQLITE_PATH}"


__all__ = ["BACKEND_ROOT", "DEFAULT_SQLITE_PATH", "get_database_url"]
