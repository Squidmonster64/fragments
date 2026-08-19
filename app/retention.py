"""Retention rules for Fragments.

The cleanup rule is deliberately conservative: a transient Fragment remains
unless it has at least one recorded linked action, every linked action is
explicitly marked completed, and the last completion is more than thirty days
old.  Permanent and Reference Fragments are never candidates here.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

RETENTION_DAYS = 30
TERMINAL_ACTION_STATE = "completed"


def _as_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def retention_status(memory_class: str, links: list[dict[str, Any]], now: datetime | None = None) -> dict[str, Any]:
    """Return a human-readable retention decision without making a deletion."""

    reference = now or datetime.now(timezone.utc)
    if memory_class == "permanent":
        return {"eligible": False, "eligible_at": None, "reason": "Permanent Fragments are kept indefinitely."}
    if memory_class != "transient":
        return {"eligible": False, "eligible_at": None, "reason": "Only Transient Fragments can ever be cleaned up automatically."}
    if not links:
        return {"eligible": False, "eligible_at": None, "reason": "No linked actions are recorded, so this Fragment is being kept."}
    incomplete = [link for link in links if str(link.get("state", "")).lower() != TERMINAL_ACTION_STATE]
    if incomplete:
        return {"eligible": False, "eligible_at": None, "reason": "At least one linked action is still open, so this Fragment is being kept."}
    completions = [_as_datetime(link.get("completed_at")) for link in links]
    if any(value is None for value in completions):
        return {"eligible": False, "eligible_at": None, "reason": "A linked action has no confirmed completion date, so this Fragment is being kept."}
    eligible_at = max(value for value in completions if value is not None) + timedelta(days=RETENTION_DAYS)
    if reference < eligible_at:
        return {"eligible": False, "eligible_at": eligible_at.isoformat(), "reason": f"All linked actions are done. Keep this Fragment until {eligible_at.strftime('%d %b %Y')}."}
    return {"eligible": True, "eligible_at": eligible_at.isoformat(), "reason": "All linked actions were completed more than 30 days ago."}


def normalise_link(value: Any) -> dict[str, Any] | None:
    """Accept a narrow link shape suitable for owner-reviewed cross-app actions."""

    if not isinstance(value, dict):
        return None
    target_app = str(value.get("target_app", "")).strip()[:80]
    target_type = str(value.get("target_type", "")).strip()[:80]
    target_id = str(value.get("target_id", "")).strip()[:160]
    label = str(value.get("label", "")).strip()[:250]
    state = str(value.get("state", "open")).strip().lower()
    if not target_app or not target_type or not target_id or not label or state not in {"open", "completed"}:
        return None
    completed_at = _as_datetime(value.get("completed_at"))
    if state == "completed" and not completed_at:
        return None
    return {
        "target_app": target_app,
        "target_type": target_type,
        "target_id": target_id,
        "label": label,
        "state": state,
        "completed_at": completed_at.isoformat() if completed_at else None,
    }
