"""Versioned Harvester action contract (v1)."""

from __future__ import annotations

from typing import Any

HARVESTER_CONTRACT_VERSION = "v1"
ORIGINATING_APP = "fragments"


def build_action_request(
    *,
    fragment_code: str,
    fragment_db_id: int,
    source_created_at: str,
    source_type: str,
    normalized_text: str,
    candidate: dict[str, Any],
    idempotency_key: str,
    source_url: str,
    provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    domains = metadata.get("domains") if isinstance(metadata.get("domains"), list) else []
    return {
        "contractVersion": HARVESTER_CONTRACT_VERSION,
        "fragmentId": fragment_code,
        "sourceCreatedAt": source_created_at,
        "sourceType": source_type,
        "normalizedText": normalized_text,
        "intent": candidate["type"],
        "proposedAction": {
            "title": str(candidate.get("title", "")).strip(),
            "detail": str(candidate.get("detail", "")).strip(),
            "domains": domains,
        },
        "idempotencyKey": idempotency_key,
        "originatingApp": ORIGINATING_APP,
        "provenance": {
            "fragmentDbId": fragment_db_id,
            "sourceUrl": source_url,
            "candidateId": candidate.get("id"),
            "confidence": candidate.get("confidence"),
            **(provenance or {}),
        },
    }


def parse_action_response(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("contractVersion") == HARVESTER_CONTRACT_VERSION:
        return {
            "accepted": bool(payload.get("accepted")),
            "action_id": payload.get("actionId"),
            "resulting_entity_id": payload.get("resultingEntityId"),
            "idempotency_outcome": payload.get("idempotencyOutcome"),
            "reason": payload.get("reason") or payload.get("error"),
            "provenance_reference": payload.get("provenanceReference"),
            "undo_available": bool(payload.get("undoAvailable")),
            "contract_version": HARVESTER_CONTRACT_VERSION,
        }

    action = payload.get("action") if isinstance(payload.get("action"), dict) else {}
    duplicate = bool(payload.get("duplicate"))
    return {
        "accepted": bool(action.get("id")),
        "action_id": action.get("id"),
        "resulting_entity_id": action.get("targetId"),
        "idempotency_outcome": "duplicate" if duplicate else "created",
        "reason": action.get("summary"),
        "provenance_reference": {
            "actionId": action.get("id"),
            "sourceFragmentId": action.get("sourceFragmentId"),
            "idempotencyKey": action.get("idempotencyKey"),
            "targetKind": action.get("targetKind"),
            "targetId": action.get("targetId"),
        },
        "undo_available": action.get("status") == "active" and bool(action.get("createdTarget")),
        "contract_version": None,
    }
