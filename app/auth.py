"""Small, server-only authentication helpers for the single-owner app."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import time

COOKIE_NAME = "fragments_session"
DEFAULT_SESSION_AGE = 7 * 24 * 60 * 60
MINIMUM_PASSPHRASE_LENGTH = 20


def configured_passphrase() -> str:
    return os.getenv("FRAGMENTS_AUTH_PASSPHRASE", "").strip()


def auth_is_configured() -> bool:
    return len(configured_passphrase()) >= MINIMUM_PASSPHRASE_LENGTH


def cookie_secure() -> bool:
    return os.getenv("FRAGMENTS_COOKIE_SECURE", "true").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def session_max_age() -> int:
    try:
        value = int(os.getenv("FRAGMENTS_SESSION_MAX_AGE", str(DEFAULT_SESSION_AGE)))
    except ValueError:
        return DEFAULT_SESSION_AGE
    return value if 300 <= value <= 30 * 24 * 60 * 60 else DEFAULT_SESSION_AGE


def passphrase_matches(candidate: str) -> bool:
    configured = configured_passphrase()
    return bool(configured) and hmac.compare_digest(
        hashlib.sha256(candidate.encode("utf-8")).digest(),
        hashlib.sha256(configured.encode("utf-8")).digest(),
    )


def _signing_key() -> bytes:
    # Domain separation prevents the configured passphrase from being used
    # directly as an HMAC key.
    return hashlib.sha256(
        b"bloody-daves/fragments/session/v1\0"
        + configured_passphrase().encode("utf-8")
    ).digest()


def issue_session(now: int | None = None) -> str:
    if not auth_is_configured():
        raise RuntimeError("Fragments authentication is not configured")
    issued_at = int(time.time()) if now is None else now
    payload = f"v1.{issued_at}.{secrets.token_urlsafe(24)}".encode("ascii")
    signature = hmac.new(_signing_key(), payload, hashlib.sha256).digest()
    encoded_signature = base64.urlsafe_b64encode(signature).rstrip(b"=")
    return f"{payload.decode('ascii')}.{encoded_signature.decode('ascii')}"


def valid_session(token: str | None, now: int | None = None) -> bool:
    if not token or not auth_is_configured():
        return False
    try:
        version, issued_text, nonce, encoded_signature = token.split(".", 3)
        issued_at = int(issued_text)
        signature = base64.urlsafe_b64decode(
            encoded_signature + "=" * (-len(encoded_signature) % 4)
        )
    except (ValueError, TypeError):
        return False
    if version != "v1" or not nonce:
        return False
    current_time = int(time.time()) if now is None else now
    if issued_at > current_time + 60 or current_time - issued_at > session_max_age():
        return False
    payload = f"{version}.{issued_text}.{nonce}".encode("ascii")
    expected = hmac.new(_signing_key(), payload, hashlib.sha256).digest()
    return hmac.compare_digest(signature, expected)
