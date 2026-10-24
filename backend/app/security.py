"""Shared password hashing and session-token signing primitives.

This module is dependency-free (stdlib only) so both the Auth_Service and the
Registration_Service (task 6) agree on a single password scheme and a single
session-token format. Keeping these here avoids a circular dependency between
the two services and guarantees that a password hashed at registration time
verifies at sign-in time.

Password hashing uses PBKDF2-HMAC-SHA256 with a per-password random salt. The
stored hash is a self-describing string::

    pbkdf2_sha256$<iterations>$<salt_hex>$<hash_hex>

so the parameters travel with the hash and verification never needs external
configuration. This is pragmatic for a hackathon while still salting and
stretching (never storing plaintext).

Session tokens are stateless, signed payloads::

    <payload_b64url>.<signature_b64url>

where the payload is compact JSON carrying the subject id and role, and the
signature is an HMAC-SHA256 over the payload keyed by the app secret. The token
is tamper-evident: any change to the payload invalidates the signature, so a
caller cannot forge or elevate a role. This is intentionally simple (no
expiry/refresh machinery) to fit the demo while still enforcing integrity
server-side rather than trusting the client.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
from typing import Optional, Tuple

# --- Password hashing ------------------------------------------------------

_ALGORITHM = "pbkdf2_sha256"
_DEFAULT_ITERATIONS = 200_000
_SALT_BYTES = 16


def hash_password(password: str, *, iterations: int = _DEFAULT_ITERATIONS) -> str:
    """Hash a plaintext password into a self-describing, salted digest.

    The returned string embeds the algorithm, iteration count, salt, and digest
    so :func:`verify_password` needs nothing but the stored value to check a
    candidate. A fresh random salt is generated per call, so hashing the same
    password twice yields different strings.
    """
    if not isinstance(password, str):
        raise TypeError("password must be a string")
    salt = secrets.token_bytes(_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, iterations
    )
    return "{algo}${iters}${salt}${digest}".format(
        algo=_ALGORITHM,
        iters=iterations,
        salt=salt.hex(),
        digest=digest.hex(),
    )


def verify_password(password: str, stored: Optional[str]) -> bool:
    """Return True if ``password`` matches the ``stored`` hashed value.

    Parses the stored self-describing hash, recomputes the digest with the same
    salt and iterations, and compares in constant time. Any malformed or empty
    stored value (and any mismatch) returns False rather than raising, so
    authentication failures are uniform and do not leak which part failed.
    """
    if not stored or not isinstance(stored, str):
        return False
    try:
        algo, iters_str, salt_hex, digest_hex = stored.split("$")
    except ValueError:
        return False
    if algo != _ALGORITHM:
        return False
    try:
        iterations = int(iters_str)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
    except ValueError:
        return False
    candidate = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, iterations
    )
    return hmac.compare_digest(candidate, expected)


# --- Session token signing -------------------------------------------------

_SECRET_ENV = "CARECONNECT_SECRET_KEY"
# A stable default so the demo works with zero configuration. Production/real
# deployments should override via the environment.
_DEFAULT_SECRET = "careconnect-dev-secret-change-me"


def _get_secret() -> bytes:
    return os.environ.get(_SECRET_ENV, _DEFAULT_SECRET).encode("utf-8")


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def sign_session_token(subject_id: int, role: str) -> str:
    """Create a signed, stateless session token carrying id and role.

    The payload is tamper-evident via an HMAC signature keyed by the app
    secret; altering the role or id invalidates the token.
    """
    payload = {"sub": int(subject_id), "role": str(role)}
    payload_bytes = json.dumps(
        payload, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    payload_b64 = _b64url_encode(payload_bytes)
    signature = hmac.new(
        _get_secret(), payload_b64.encode("ascii"), hashlib.sha256
    ).digest()
    return f"{payload_b64}.{_b64url_encode(signature)}"


def verify_session_token(token: Optional[str]) -> Optional[Tuple[int, str]]:
    """Validate a signed session token.

    Returns ``(subject_id, role)`` when the signature is valid and the payload
    is well formed, otherwise ``None``. Returning ``None`` (rather than raising)
    lets callers treat any malformed/forged/missing token as simply
    unauthenticated.
    """
    if not token or not isinstance(token, str) or "." not in token:
        return None
    payload_b64, _, signature_b64 = token.partition(".")
    expected_sig = hmac.new(
        _get_secret(), payload_b64.encode("ascii"), hashlib.sha256
    ).digest()
    try:
        provided_sig = _b64url_decode(signature_b64)
    except (ValueError, TypeError):
        return None
    if not hmac.compare_digest(expected_sig, provided_sig):
        return None
    try:
        payload = json.loads(_b64url_decode(payload_b64).decode("utf-8"))
        return int(payload["sub"]), str(payload["role"])
    except (ValueError, TypeError, KeyError):
        return None


__all__ = [
    "hash_password",
    "verify_password",
    "sign_session_token",
    "verify_session_token",
]
