"""Review-only personal language handling for Fragments.

This follows the useful shape of the existing segmentation work without any
health-specific rules: original words stay intact, the readable normalisation
is separate, individual clauses can yield several candidates, and uncertainty
becomes one short question instead of a silent guess.  It has no I/O and makes
no cross-surface changes.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

MEMORY_CLASSES = {"permanent", "reference", "transient", "unclassified"}
ROUTE_TYPES = {"reminder", "run_maintain", "shitlist", "decision", "fieldbook"}

PERMANENT_WORDS = re.compile(
    r"\b(?:when i was|i remember|remember when|my mum|my dad|my father|my mother|grandma|grandmother|grandfather|childhood|story|memoir|legacy|funeral|died|passed away|birth|born|family history)\b",
    re.IGNORECASE,
)
REFERENCE_WORDS = re.compile(
    r"\b(?:idea|note|reference|research|recipe|book|article|website|link|place|person|contact|quote|mantra|keep this|save this|worth knowing)\b",
    re.IGNORECASE,
)
TRANSIENT_WORDS = re.compile(
    r"\b(?:remind me|remember to|don't let me forget|need to|i need to|todo|to do|call|email|buy|pick up|pay|book|renew|fix|clean|service|check|organise|schedule)\b",
    re.IGNORECASE,
)


def normalise_text(original_text: str) -> str:
    value = re.sub(r"\s+", " ", original_text.replace("\u2019", "'"))
    return value.strip()


def split_clauses(normalised_text: str) -> list[str]:
    """Split on clear speech boundaries without chopping a personal story apart."""

    if not normalised_text:
        return []
    pieces = re.split(
        r"(?:[\n.;]+|\s+\b(?:then|also|and then)\b\s+|,\s*(?:and\s+)?(?=(?:remind me|remember to|don't let me forget|i need to|need to|i should|fix|clean|service|renew|save|keep|decide)\b))",
        normalised_text,
        flags=re.IGNORECASE,
    )
    return [piece.strip(" ,:-") for piece in pieces if piece.strip(" ,:-")]


def _title_from_clause(clause: str) -> str:
    cleaned = re.sub(r"^(?:please\s+)?(?:remind me to|remember to|don't let me forget to|i need to|need to|i should|put|add|save|keep)\s+", "", clause, flags=re.IGNORECASE).strip(" .")
    return (cleaned or clause).strip()[:250]


def _candidate(route_type: str, clause: str, confidence: float, requires_confirmation: bool = False) -> dict[str, Any]:
    return {
        "id": str(uuid4()),
        "type": route_type,
        "title": _title_from_clause(clause),
        "detail": clause.strip(),
        "raw_span": clause.strip(),
        "confidence": round(confidence, 2),
        "requires_confirmation": requires_confirmation,
        "status": "proposed",
        "destination": {
            "reminder": "Daybook",
            "run_maintain": "Run & Maintain",
            "shitlist": "Shitlist",
            "decision": "Decisions",
            "fieldbook": "Fieldbook",
        }[route_type],
    }


def _extract_candidates(clauses: list[str]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for clause in clauses:
        lower = clause.lower()
        found: list[dict[str, Any]] = []
        if re.search(r"\b(?:remind me|remember to|don't let me forget|at \d{1,2}(?::\d{2})?\s*(?:am|pm)?|tomorrow|next \w+|on \w+day)\b", lower):
            # Time-like language still needs review until a date/time parser and the
            # owner confirm it.  Never manufacture a due time from a vague phrase.
            found.append(_candidate("reminder", clause, 0.76, True))
        if re.search(r"\b(?:fix|clean|service|maintain|maintenance|repair|replace|inspect|renew|insurance|licence|license|passport|registration|rego|tax)\b", lower):
            found.append(_candidate("run_maintain", clause, 0.78, False))
        if re.search(r"\b(?:decide|decision|i chose|i choose|we chose|we're going with|going with|instead of|rather than)\b", lower):
            found.append(_candidate("decision", clause, 0.72, True))
        if re.search(r"\b(?:save|keep|reference|bookmark|website|link|pdf|photo|article|book|place|person|quote|mantra)\b", lower):
            found.append(_candidate("fieldbook", clause, 0.7, False))
        if re.search(r"\b(?:need to|i need to|i should|todo|to do|call|email|buy|pick up|pay|book|organise)\b", lower) and not any(item["type"] in {"reminder", "run_maintain"} for item in found):
            found.append(_candidate("shitlist", clause, 0.66, False))
        for item in found:
            key = (item["type"], item["title"].casefold())
            if key not in seen:
                candidates.append(item)
                seen.add(key)
    return candidates[:8]


def classify_memory(original_text: str, candidates: list[dict[str, Any]]) -> tuple[str, str]:
    """Return the retention class; permanent always wins for mixed material."""

    if PERMANENT_WORDS.search(original_text):
        return "permanent", "It contains story, family, memory, or legacy language, so it stays permanently."
    if REFERENCE_WORDS.search(original_text):
        return "reference", "It looks useful to keep as a note, idea, or source."
    if TRANSIENT_WORDS.search(original_text) or candidates:
        return "transient", "It mainly sounds like short-lived work or a request."
    return "reference", "It is safest to keep this as a reference until you choose otherwise."


def clarification_questions(clauses: list[str], candidates: list[dict[str, Any]]) -> list[str]:
    questions: list[str] = []
    for candidate in candidates:
        if candidate["type"] == "reminder" and candidate["requires_confirmation"]:
            questions.append(f"When should I remind you about “{candidate['title']}”? ")
        elif candidate["type"] == "decision" and candidate["requires_confirmation"]:
            questions.append(f"Is “{candidate['title']}” a decision to keep, or just something you are considering?")
    if not candidates and any(re.search(r"\b(?:maybe|might|could|perhaps|someday)\b", clause, re.IGNORECASE) for clause in clauses):
        questions.append("Should I keep this as a reference, or put it on the Shitlist?")
    # One short question at a time is a deliberate interaction rule.
    return questions[:1]


def interpret_fragment(original_text: str) -> dict[str, Any]:
    """Produce a reviewable, no-write interpretation for one saved fragment."""

    normalised = normalise_text(original_text)
    clauses = split_clauses(normalised)
    candidates = _extract_candidates(clauses)
    memory_class, memory_class_reason = classify_memory(original_text, candidates)
    confidence = 0.92 if not candidates else round(sum(item["confidence"] for item in candidates) / len(candidates), 2)
    return {
        "schema": "bloody-daves/fragment-interpretation/v1",
        "original_text": original_text,
        "normalised_text": normalised,
        "clauses": clauses,
        "memory_class": memory_class,
        "memory_class_reason": memory_class_reason,
        "candidates": candidates,
        "clarifications": clarification_questions(clauses, candidates),
        "confidence": confidence,
        "interpreted_at": datetime.now(timezone.utc).isoformat(),
        "review_state": "draft",
        "no_changes_made": True,
    }


def valid_memory_class(value: str) -> bool:
    return value in MEMORY_CLASSES


def valid_route_type(value: str) -> bool:
    return value in ROUTE_TYPES
