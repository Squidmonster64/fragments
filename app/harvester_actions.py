"""Private, idempotent low-risk Harvester actions.

Only a clear Get List or Run & Maintain proposal reaches this module.  The
original Fragment stays in Fragments; the remote service receives a versioned
contract v1 request with provenance.  If the private service is not configured
or unavailable, the candidate remains a visible draft.
"""

from __future__ import annotations

import hashlib
import os
from datetime import datetime
from typing import Any

import requests

from app.harvester_contract import HARVESTER_CONTRACT_VERSION, build_action_request, parse_action_response
from app.interpretation import DESTRUCTIVE

ALLOWED_ROUTE_TYPES = {"get_list", "run_maintain", "reminder"}


def _configured() -> tuple[str, str] | None:
    url = os.getenv("HARVESTER_ACTION_URL", "").strip().rstrip("/")
    secret = os.getenv("FRAGMENTS_HARVESTER_SECRET", "").strip()
    return (url, secret) if url and secret else None


def _idempotency_key(fragment_identity: str, candidate: dict[str, Any]) -> str:
    """Key actions to an immutable Fragment identity, never its reusable display code."""

    source = f"{fragment_identity}|{candidate.get('type', '')}|{str(candidate.get('title', '')).strip().casefold()}"
    return f"fragment:{hashlib.sha256(source.encode('utf-8')).hexdigest()}"


def can_act_immediately(candidate: dict[str, Any]) -> bool:
    title = str(candidate.get("title", ""))
    detail = str(candidate.get("detail", ""))
    if DESTRUCTIVE.search(f"{title} {detail}"):
        return False
    return (
        candidate.get("type") in ALLOWED_ROUTE_TYPES
        and not bool(candidate.get("requires_confirmation"))
        and float(candidate.get("confidence", 0)) >= 0.8
        and bool(title.strip())
    )


def _source_type(fragment: dict[str, Any]) -> str:
    return "voice" if fragment.get("audio_path") else "typed"


def apply_clear_actions(
    fragment_code: str,
    candidates: list[dict[str, Any]],
    *,
    fragment_identity: str | None = None,
    fragment: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Apply clear low-risk candidates with a stable action identity."""

    configured = _configured()
    if not configured:
        return []
    url, secret = configured
    outcomes: list[dict[str, Any]] = []
    fragment_meta = fragment or {}
    source_created_at = fragment_meta.get("created_at")
    if isinstance(source_created_at, datetime):
        source_created_at = source_created_at.isoformat()
    source_created_at = str(source_created_at or "")
    normalized_text = str(fragment_meta.get("raw_transcript") or "").strip()
    fragment_db_id = int(fragment_meta.get("id") or 0)
    source_url = str(fragment_meta.get("source_url") or f"/fragments/{fragment_db_id}")

    for candidate in candidates:
        if not isinstance(candidate, dict) or not can_act_immediately(candidate):
            continue
        idempotency_key = _idempotency_key(fragment_identity or fragment_code, candidate)
        payload = build_action_request(
            fragment_code=fragment_code,
            fragment_db_id=fragment_db_id,
            source_created_at=source_created_at,
            source_type=_source_type(fragment_meta),
            normalized_text=normalized_text,
            candidate=candidate,
            idempotency_key=idempotency_key,
            source_url=source_url,
        )
        try:
            response = requests.post(
                f"{url}/internal/harvester/actions",
                json=payload,
                headers={"x-fragments-harvester-secret": secret},
                timeout=5,
            )
            if not response.ok:
                outcomes.append({
                    "candidate_id": candidate.get("id"),
                    "status": "not_added",
                    "message": "Could not add this yet.",
                    "contract_version": HARVESTER_CONTRACT_VERSION,
                })
                continue
            parsed = parse_action_response(response.json())
            if not parsed.get("accepted"):
                outcomes.append({
                    "candidate_id": candidate.get("id"),
                    "status": "not_added",
                    "message": parsed.get("reason") or "Could not add this yet.",
                    "contract_version": parsed.get("contract_version") or HARVESTER_CONTRACT_VERSION,
                    "provenance": {"idempotency_key": idempotency_key, "provenance_reference": parsed.get("provenance_reference")},
                })
                continue
            target_kind = (parsed.get("provenance_reference") or {}).get("targetKind", "")
            outcomes.append({
                "candidate_id": candidate.get("id"),
                "status": "acted",
                "message": parsed.get("reason") or "Added.",
                "action_id": parsed.get("action_id"),
                "target_app": "Get List" if candidate["type"] == "get_list" else "Hope Task" if candidate["type"] == "reminder" else "Run & Maintain",
                "target_type": target_kind,
                "target_id": parsed.get("resulting_entity_id"),
                "created_target": parsed.get("idempotency_outcome") == "created",
                "contract_version": parsed.get("contract_version") or HARVESTER_CONTRACT_VERSION,
                "idempotency_outcome": parsed.get("idempotency_outcome"),
                "provenance": {
                    "idempotency_key": idempotency_key,
                    "harvester_action_id": parsed.get("action_id"),
                    "resulting_entity_id": parsed.get("resulting_entity_id"),
                    "idempotency_outcome": parsed.get("idempotency_outcome"),
                    "provenance_reference": parsed.get("provenance_reference"),
                    "undo_available": parsed.get("undo_available"),
                },
            })
        except (requests.RequestException, ValueError):
            outcomes.append({
                "candidate_id": candidate.get("id"),
                "status": "not_added",
                "message": "Could not add this yet.",
                "contract_version": HARVESTER_CONTRACT_VERSION,
            })
    return outcomes


def undo_action(action_id: str) -> dict[str, Any] | None:
    configured = _configured()
    if not configured or not action_id:
        return None
    url, secret = configured
    try:
        response = requests.post(
            f"{url}/internal/harvester/actions/{action_id}/undo",
            headers={"x-fragments-harvester-secret": secret},
            timeout=5,
        )
        if not response.ok:
            return None
        payload = response.json()
        if isinstance(payload, dict) and payload.get("contractVersion") == HARVESTER_CONTRACT_VERSION:
            return payload.get("action") if isinstance(payload.get("action"), dict) else None
        return payload.get("action") if isinstance(payload, dict) else None
    except (requests.RequestException, ValueError):
        return None
