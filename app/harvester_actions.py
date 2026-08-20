"""Private, idempotent low-risk Harvester actions.

Only a clear Get List or Run & Maintain proposal reaches this module.  The
original Fragment stays in Fragments; the remote service receives a short title,
a source code, and an idempotency key—not the transcript.  If the private
service is not configured or unavailable, the candidate remains a visible draft.
"""

from __future__ import annotations

import hashlib
import os
from typing import Any

import requests

ALLOWED_ROUTE_TYPES = {"get_list", "run_maintain"}


def _configured() -> tuple[str, str] | None:
    url = os.getenv("HARVESTER_ACTION_URL", "").strip().rstrip("/")
    secret = os.getenv("FRAGMENTS_HARVESTER_SECRET", "").strip()
    return (url, secret) if url and secret else None


def _idempotency_key(fragment_identity: str, candidate: dict[str, Any]) -> str:
    """Key actions to an immutable Fragment identity, never its reusable display code."""

    source = f"{fragment_identity}|{candidate.get('type', '')}|{str(candidate.get('title', '')).strip().casefold()}"
    return f"fragment:{hashlib.sha256(source.encode('utf-8')).hexdigest()}"


def can_act_immediately(candidate: dict[str, Any]) -> bool:
    return (
        candidate.get("type") in ALLOWED_ROUTE_TYPES
        and not bool(candidate.get("requires_confirmation"))
        and float(candidate.get("confidence", 0)) >= 0.8
        and bool(str(candidate.get("title", "")).strip())
    )


def apply_clear_actions(fragment_code: str, candidates: list[dict[str, Any]], *, fragment_identity: str | None = None) -> list[dict[str, Any]]:
    """Apply clear low-risk candidates with a stable action identity.

    ``fragment_code`` stays human-readable in the destination provenance.  The
    optional identity is used only for idempotency, preventing a new Fragment
    from replaying an old action if a deleted display code is later reused.
    """

    configured = _configured()
    if not configured:
        return []
    url, secret = configured
    outcomes: list[dict[str, Any]] = []
    for candidate in candidates:
        if not isinstance(candidate, dict) or not can_act_immediately(candidate):
            continue
        metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
        payload = {
            "idempotencyKey": _idempotency_key(fragment_identity or fragment_code, candidate),
            "sourceFragmentId": fragment_code,
            "routeType": candidate["type"],
            "title": str(candidate["title"]).strip(),
            "detail": str(candidate.get("detail", "")).strip(),
            "domains": metadata.get("domains", []) if isinstance(metadata.get("domains"), list) else [],
        }
        try:
            response = requests.post(f"{url}/internal/harvester/actions", json=payload, headers={"x-fragments-harvester-secret": secret}, timeout=5)
            if not response.ok:
                outcomes.append({"candidate_id": candidate.get("id"), "status": "not_added", "message": "Could not add this yet."})
                continue
            action = response.json().get("action", {})
            outcomes.append({
                "candidate_id": candidate.get("id"), "status": "acted", "message": action.get("summary", "Added."),
                "action_id": action.get("id"), "target_app": "Get List" if candidate["type"] == "get_list" else "Run & Maintain",
                "target_type": action.get("targetKind", ""), "target_id": action.get("targetId", ""), "created_target": bool(action.get("createdTarget")),
            })
        except (requests.RequestException, ValueError):
            outcomes.append({"candidate_id": candidate.get("id"), "status": "not_added", "message": "Could not add this yet."})
    return outcomes


def undo_action(action_id: str) -> dict[str, Any] | None:
    configured = _configured()
    if not configured or not action_id:
        return None
    url, secret = configured
    try:
        response = requests.post(f"{url}/internal/harvester/actions/{action_id}/undo", headers={"x-fragments-harvester-secret": secret}, timeout=5)
        if not response.ok:
            return None
        payload = response.json()
        return payload.get("action") if isinstance(payload, dict) else None
    except (requests.RequestException, ValueError):
        return None
