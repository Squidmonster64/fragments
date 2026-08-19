"""Visible, reversible Harvester learning from explicit user corrections only."""

from __future__ import annotations

import os
from typing import Any

import requests


def _configured() -> tuple[str, str] | None:
    url = os.getenv("HARVESTER_ACTION_URL", "").strip().rstrip("/")
    secret = os.getenv("FRAGMENTS_HARVESTER_SECRET", "").strip()
    return (url, secret) if url and secret else None


def learn_explicit_rules(fragment_code: str, source_text: str) -> dict[str, Any]:
    """Ask the private service to learn direct generalisations, never guesses."""

    configured = _configured()
    if not configured or not source_text.strip():
        return {"rules": [], "clarification": None}
    url, secret = configured
    try:
        response = requests.post(
            f"{url}/internal/harvester/rules/learn",
            json={"fragmentId": fragment_code, "sourceText": source_text},
            headers={"x-fragments-harvester-secret": secret},
            timeout=5,
        )
        if not response.ok:
            return {"rules": [], "clarification": None}
        payload = response.json()
        return payload if isinstance(payload, dict) else {"rules": [], "clarification": None}
    except (requests.RequestException, ValueError):
        return {"rules": [], "clarification": None}


def revoke_learned_rule(rule_id: str) -> bool:
    configured = _configured()
    if not configured or not rule_id:
        return False
    url, secret = configured
    try:
        response = requests.post(f"{url}/internal/harvester/rules/{rule_id}/revoke", headers={"x-fragments-harvester-secret": secret}, timeout=5)
        return response.ok
    except requests.RequestException:
        return False
