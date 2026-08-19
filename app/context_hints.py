"""Optional, private vocabulary hints for completed Fragments recordings.

This is deliberately best-effort.  It sends no audio and no transcript to the
control service—only the current app label and a short owner-entered theme.  If
the private connection is absent or unavailable, transcription still proceeds
with Fragments' local hint.
"""

from __future__ import annotations

import os
from typing import Any

import requests


def _clean(value: Any, maximum: int = 100) -> str:
    return value.strip().replace("\n", " ")[:maximum] if isinstance(value, str) else ""


def private_context_hint(current_domain: str = "") -> str:
    url = os.getenv("TRANSCRIPTION_CONTEXT_URL", "").strip().rstrip("/")
    secret = os.getenv("FRAGMENTS_CONTEXT_SECRET", "").strip()
    if not url or not secret:
        return ""
    try:
        response = requests.get(
            url,
            params={"app": "Fragments", **({"domain": current_domain[:80]} if current_domain else {})},
            headers={"x-fragments-context-secret": secret},
            timeout=4,
        )
        if not response.ok:
            return ""
        payload = response.json()
    except (requests.RequestException, ValueError):
        return ""
    phrases = payload.get("phrases") if isinstance(payload, dict) else []
    if not isinstance(phrases, list):
        return ""
    clean_phrases: list[str] = []
    seen: set[str] = set()
    for phrase in phrases:
        cleaned = _clean(phrase)
        if cleaned and cleaned.casefold() not in seen:
            seen.add(cleaned.casefold())
            clean_phrases.append(cleaned)
        if len(clean_phrases) >= 40:
            break
    return f"Likely Australian-English personal terms: {', '.join(clean_phrases)}." if clean_phrases else ""
