"""Submit a preserved capture to the single Hope Task Capture Engine.

Fragments remains the capture owner. Interpretation and owner writes happen
in Hope Task. If the private service is not configured or unavailable, the
local review draft still stands — captures are never discarded.
"""

from __future__ import annotations

import hashlib
import os
from datetime import datetime
from typing import Any

import requests

CONTRACT_VERSION = "1.0"


def _configured() -> tuple[str, str] | None:
    url = os.getenv("HARVESTER_ACTION_URL", "").strip().rstrip("/")
    secret = os.getenv("FRAGMENTS_HARVESTER_SECRET", "").strip()
    return (url, secret) if url and secret else None


def capture_idempotency_key(fragment_identity: str) -> str:
    digest = hashlib.sha256(fragment_identity.encode("utf-8")).hexdigest()
    return f"capture-engine:{digest}"


def engine_owns_run_maintain(result: dict[str, Any] | None) -> bool:
    """When the engine ran, it owns task / Run & Maintain classification."""

    return isinstance(result, dict) and result.get("accepted") is True


def submit_capture(
    *,
    fragment_code: str,
    fragment_identity: str,
    raw_text: str,
    source_type: str = "fragments",
    captured_at: str = "",
) -> dict[str, Any] | None:
    configured = _configured()
    if not configured or not raw_text.strip():
        return None
    url, secret = configured
    payload = {
        "contract_version": CONTRACT_VERSION,
        "capture_id": fragment_code[:160],
        "raw_text": raw_text[:12_000],
        "idempotency_key": capture_idempotency_key(fragment_identity)[:300],
        "originating_app": "fragments",
        "source_type": source_type,
        "captured_at": captured_at,
    }
    try:
        response = requests.post(
            f"{url}/internal/canonical/capture-engine",
            json=payload,
            headers={"x-fragments-harvester-secret": secret},
            timeout=8,
        )
        if not response.ok:
            return {
                "accepted": False,
                "discarded": False,
                "status": "unavailable",
                "message": "Capture Engine could not apply this yet. The fragment is still here.",
            }
        body = response.json()
        if not isinstance(body, dict):
            return None
        body.setdefault("discarded", False)
        body.setdefault("accepted", True)
        return body
    except (requests.RequestException, ValueError):
        return {
            "accepted": False,
            "discarded": False,
            "status": "unavailable",
            "message": "Capture Engine could not apply this yet. The fragment is still here.",
        }


def source_created_at(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value or "")
