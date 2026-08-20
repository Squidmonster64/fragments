"""Review-only personal language handling for Fragments.

The module follows the agreed routing shape: preserve the raw words, normalise
and segment them, make deterministic low-risk observations, surface a small
review draft, and ask one short material question when necessary.  It performs
no I/O and never writes to another Bloody Dave surface.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

MEMORY_CLASSES = {"permanent", "reference", "transient", "unclassified"}
ROUTE_TYPES = {
    "ask_ai", "get_list", "reminder", "daybook", "weekly_review",
    "run_maintain", "shitlist", "holding", "opportunity", "decision",
    "fieldbook", "stolen_minutes",
}

PERMANENT_WORDS = re.compile(
    r"\b(?:when i was|i remember|remember when|my mum|my dad|my father|my mother|grandma|grandmother|grandfather|childhood|story|memoir|legacy|funeral|died|passed away|birth|born|family history|lay me to rest|my peace|love the warm|book material)\b",
    re.IGNORECASE,
)
REFERENCE_WORDS = re.compile(
    r"\b(?:idea|note|reference|research|recipe|article|website|link|place|person|contact|quote|mantra|keep this|save this|worth knowing|weekly review|this isn't working|change tack|changed my mind|reflection)\b",
    re.IGNORECASE,
)
TRANSIENT_WORDS = re.compile(
    r"\b(?:remind me|remember to|don't let me forget|need to|i need to|todo|to do|call|email|buy|pick up|pay|book|renew|fix|clean|service|check|organise|schedule|running out|grab)\b",
    re.IGNORECASE,
)
QUESTION_START = re.compile(r"^(?:what|where|when|why|how|who|is|are|can|could|would|will|do|does|did|have|has)\b", re.IGNORECASE)
PURCHASE = re.compile(r"\b(?:buy|get|pick up|grab)\s+(?:some\s+)?(?P<item>.+?)(?:\s+(?:tomorrow|today|this week|on \w+day|at \d)|$)", re.IGNORECASE)
PLACE_REMINDER = re.compile(r"\b(?:when i get home|when i get to work|next time i(?:'m| am) at the boat|when i arrive in (?P<place>[A-Za-z][A-Za-z -]{1,60}))\b", re.IGNORECASE)
FUTURE_LANGUAGE = re.compile(r"\b(?:tomorrow|next \w+|this \w+|on \w+day|monday|tuesday|wednesday|thursday|friday|saturday|sunday|at \d{1,2}(?::\d{2})?\s*(?:am|pm)?)\b", re.IGNORECASE)
MAINTENANCE_WORDS = re.compile(r"\b(?:fix|clean|service|maintain|maintenance|repair|replace|inspect|renew|insurance|licence|license|passport|registration|rego|tax|broken|dirty|filthy|needs servicing|running low|needs checking|due|expired|damaged|not working|empty tank|is out|look low)\b", re.IGNORECASE)
IDEA_WORDS = re.compile(r"\b(?:great idea|idea for|possible|opportunity|could build|might build|want to write|book)\b", re.IGNORECASE)
DEFERRED_CRAP = re.compile(r"\b(?:sort|cancel|deal with|clean out|dripping|shelf|garage|subscription|paperwork)\b", re.IGNORECASE)
REFLECTION = re.compile(r"\b(?:i didn't|i did not|i feel|i'm tired|i am tired|need a break|warm sun|fresh[- ]cut grass)\b", re.IGNORECASE)
CHANGE_SIGNAL = re.compile(r"\b(?:this isn't working|this is not working|change tack|change the plan|scrap (?:this|that)|changed my mind|bad idea|do it differently)\b", re.IGNORECASE)
DECISION_WORDS = re.compile(r"\b(?:i've decided|i have decided|we've decided|we have decided|i decided|we decided|i'm going with|we're going with|i choose|we choose)\b", re.IGNORECASE)
WEEKLY_REVIEW = re.compile(r"\b(?:weekly review|bring this up|bring it up)\b", re.IGNORECASE)

DESTINATIONS = {
    "ask_ai": "Ask AI", "get_list": "Get List", "reminder": "Reminder",
    "daybook": "Daybook", "weekly_review": "Weekly Review",
    "run_maintain": "Run & Maintain", "shitlist": "Shitlist",
    "holding": "Holding", "opportunity": "Opportunities",
    "decision": "Decisions", "fieldbook": "Fieldbook", "stolen_minutes": "Stolen Minutes",
}


def normalise_text(original_text: str) -> str:
    return re.sub(r"\s+", " ", original_text.replace("\u2019", "'")).strip()


def split_clauses(normalised_text: str) -> list[str]:
    """Split clear compound instructions without breaking ordinary storytelling."""

    if not normalised_text:
        return []
    pieces = re.split(
        r"(?:[\n.;]+|\s+\b(?:then|also|and then)\b\s+|,\s*(?:and\s+)?(?=(?:remind me|remember to|don't let me forget|i need to|need to|i should|fix|clean|service|renew|save|keep|decide|buy|get|pick up|grab)\b))",
        normalised_text,
        flags=re.IGNORECASE,
    )
    return [piece.strip(" ,:—-\t") for piece in pieces if piece.strip(" ,:—-\t")]


def _clean_title(value: str) -> str:
    value = re.sub(r"\s+", " ", value).strip(" .,:;—-")
    return value[:250] or "Untitled suggestion"


def _title_from_clause(clause: str) -> str:
    cleaned = re.sub(r"^(?:please\s+)?(?:remind me to|remember to|don't let me forget to|i need to|need to|i should|put|add|save|keep)\s+", "", clause, flags=re.IGNORECASE)
    return _clean_title(cleaned or clause)


def _purchase_title(clause: str) -> str:
    match = PURCHASE.search(clause)
    if not match:
        return _title_from_clause(clause)
    item = re.split(r"\b(?:actually|sorry|but)\b", match.group("item"), flags=re.IGNORECASE)[0]
    return _clean_title(item).capitalize()


def _maintenance_title(clause: str) -> str:
    lower = clause.lower()
    if "headlight" in lower and ("out" in lower or "not working" in lower):
        subject = "car headlight" if "car" in lower else "headlight"
        return f"Fix {subject}"
    if "office windows" in lower and ("dirty" in lower or "filthy" in lower):
        return "Clean office windows"
    if "tyre" in lower and "low" in lower:
        return "Check tyre pressures"
    if "vacuum" in lower and ("empty" in lower or "tank" in lower):
        return "Check vacuum cleaner — empty tank alert"
    cleaned = re.sub(r"^(?:the|my|our)\s+", "", clause, flags=re.IGNORECASE)
    action_match = re.search(r"\b(fix|clean|service|repair|replace|inspect|renew|check)\b", cleaned, re.IGNORECASE)
    if action_match:
        return _clean_title(cleaned[action_match.start():]).capitalize()
    return _clean_title(cleaned).capitalize()


def _candidate(route_type: str, clause: str, confidence: float, *, title: str | None = None, requires_confirmation: bool = False, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "id": str(uuid4()), "type": route_type, "title": title or _title_from_clause(clause),
        "detail": clause.strip(), "raw_span": clause.strip(), "confidence": round(confidence, 2),
        "requires_confirmation": requires_confirmation, "status": "proposed",
        "destination": DESTINATIONS[route_type], "metadata": metadata or {},
    }


def _corrected_clause(clause: str) -> tuple[str, bool]:
    """Use a spoken correction as the proposed value while retaining raw_span."""

    correction = re.search(r"\b(?:actually|sorry)\b(?:\s+(?:make that|i meant))?\s+(?P<final>[A-Za-z][A-Za-z0-9 '\-]{1,120})$", clause, re.IGNORECASE)
    if not correction:
        return clause, False
    before = clause[:correction.start()]
    final = correction.group("final").strip(" .")
    action = re.search(r"\b(buy|get|pick up|grab|remind me|call)\b", before, re.IGNORECASE)
    return (f"{action.group(1)} {final}" if action else final), True


def _is_question(clause: str) -> bool:
    return clause.strip().endswith("?") or bool(QUESTION_START.match(clause.strip()))


def _extract_candidates(clauses: list[str]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for raw_clause in clauses:
        clause, corrected = _corrected_clause(raw_clause)
        lower = clause.lower()
        found: list[dict[str, Any]] = []
        if _is_question(clause):
            found.append(_candidate("ask_ai", raw_clause, 0.9, title="Answer this question", metadata={"question": clause, "correction_applied": corrected}))
        else:
            purchase = PURCHASE.search(clause)
            if purchase:
                found.append(_candidate("get_list", raw_clause, 0.9, title=_purchase_title(clause), metadata={"correction_applied": corrected}))
            place = PLACE_REMINDER.search(clause)
            explicit_reminder = re.search(r"\b(?:remind me|remember to|don't let me forget)\b", lower)
            dated_action = bool(FUTURE_LANGUAGE.search(clause) and re.search(r"\b(?:call|email|pay|renew|book|pick up|buy|fix|clean|check)\b", lower))
            if explicit_reminder or dated_action:
                found.append(_candidate("reminder", raw_clause, 0.8, title=_title_from_clause(clause), requires_confirmation=not bool(place), metadata={"location_trigger": place.group(0) if place else None, "has_future_language": bool(FUTURE_LANGUAGE.search(clause)), "correction_applied": corrected}))
            if MAINTENANCE_WORDS.search(clause):
                found.append(_candidate("run_maintain", raw_clause, 0.82, title=_maintenance_title(clause), metadata={"implied_action": not bool(re.search(r"\b(?:fix|clean|service|repair|replace|inspect|renew|check)\b", lower)), "correction_applied": corrected}))
            if WEEKLY_REVIEW.search(clause):
                found.append(_candidate("weekly_review", raw_clause, 0.86, title="Bring this to Weekly Review"))
            elif CHANGE_SIGNAL.search(clause):
                found.append(_candidate("daybook", raw_clause, 0.63, title="Review today’s plan change", requires_confirmation=True, metadata={"change_signal": True}))
            if DECISION_WORDS.search(clause):
                # A clear decision can mention a house, tax or a repair; that
                # context is part of the decision, not a second maintenance job.
                found = [item for item in found if item["type"] != "run_maintain"]
                found.append(_candidate("decision", raw_clause, 0.84, title=_title_from_clause(clause), requires_confirmation=False))
            elif IDEA_WORDS.search(clause):
                found.append(_candidate("opportunity", raw_clause, 0.72, title=_title_from_clause(clause), requires_confirmation=True))
            if re.search(r"\b(?:save|keep|reference|bookmark|website|link|pdf|photo|article|quote|mantra)\b", lower):
                found.append(_candidate("fieldbook", raw_clause, 0.72, title=_title_from_clause(clause)))
            if re.search(r"\b(?:start timing|start the timer|time this)\b", lower):
                found.append(_candidate("stolen_minutes", raw_clause, 0.9, title="Start Stolen Minutes"))
            if re.fullmatch(r"(?:stop|stop timing|stop the timer)[.! ]*", lower):
                found.append(_candidate("stolen_minutes", raw_clause, 0.82, title="Stop Stolen Minutes", requires_confirmation=True))
            if REFLECTION.search(clause) and not found:
                found.append(_candidate("daybook", raw_clause, 0.7, title="Add to today’s review", metadata={"reflection": True}))
            if re.search(r"\b(?:wouldn't mind|would not mind|maybe|might|could|someday|later)\b", lower) and not found:
                found.append(_candidate("holding", raw_clause, 0.68, title=_title_from_clause(clause)))
            if (re.search(r"\b(?:need to|i need to|i should|todo|to do|organise)\b", lower) or DEFERRED_CRAP.search(clause)) and not WEEKLY_REVIEW.search(" ".join(clauses)) and not any(item["type"] in {"reminder", "run_maintain", "get_list", "ask_ai", "weekly_review"} for item in found):
                found.append(_candidate("shitlist", raw_clause, 0.68, title=_title_from_clause(clause)))
        for item in found:
            key = (item["type"], item["title"].casefold())
            if key not in seen:
                candidates.append(item)
                seen.add(key)
    return candidates[:10]


def classify_memory(original_text: str, candidates: list[dict[str, Any]]) -> tuple[str, str]:
    """Return the retention class; permanent always wins for mixed material."""

    if PERMANENT_WORDS.search(original_text) or (IDEA_WORDS.search(original_text) and "book" in original_text.lower()):
        return "permanent", "It contains story, family, reflection, legacy material, or a book idea, so it stays permanently."
    if candidates and all(item["type"] == "ask_ai" for item in candidates):
        return "reference", "It is a question for retrieval, not new work to create."
    if REFERENCE_WORDS.search(original_text) or any(item["type"] in {"weekly_review", "daybook", "opportunity", "holding", "fieldbook"} for item in candidates):
        return "reference", "It is useful context, a reflection, or something worth keeping for later review."
    if TRANSIENT_WORDS.search(original_text) or any(item["type"] not in {"ask_ai"} for item in candidates):
        return "transient", "It mainly exists to create or perform short-lived work."
    return "reference", "It is safest to keep this as a reference until you choose otherwise."


def clarification_questions(clauses: list[str], candidates: list[dict[str, Any]]) -> list[str]:
    questions: list[str] = []
    for candidate in candidates:
        if candidate["type"] == "reminder" and candidate["requires_confirmation"]:
            questions.append(f"When should I remind you about “{candidate['title']}”?")
        elif candidate["type"] == "daybook" and candidate["requires_confirmation"]:
            questions.append("Which plan are you changing tack on?")
        elif candidate["type"] == "opportunity" and candidate["requires_confirmation"]:
            questions.append(f"Should I keep “{candidate['title']}” as an Opportunity or in Holding?")
    if not candidates and any(re.search(r"\b(?:maybe|might|could|perhaps|someday)\b", clause, re.IGNORECASE) for clause in clauses):
        questions.append("Should I keep this as a reference, or put it in Holding?")
    return questions[:1]


def interpret_fragment(original_text: str) -> dict[str, Any]:
    """Produce a reviewable, no-write Harvester interpretation for one Fragment."""

    normalised = normalise_text(original_text)
    clauses = split_clauses(normalised)
    candidates = _extract_candidates(clauses)
    memory_class, memory_class_reason = classify_memory(original_text, candidates)
    confidence = 0.92 if not candidates else round(sum(item["confidence"] for item in candidates) / len(candidates), 2)
    return {
        "schema": "bloody-daves/fragment-interpretation/v2",
        "original_text": original_text, "normalised_text": normalised, "clauses": clauses,
        "memory_class": memory_class, "memory_class_reason": memory_class_reason,
        "candidates": candidates, "clarifications": clarification_questions(clauses, candidates),
        "confidence": confidence, "interpreted_at": datetime.now(timezone.utc).isoformat(),
        "review_state": "draft", "no_changes_made": True,
    }


def valid_memory_class(value: str) -> bool:
    return value in MEMORY_CLASSES


def valid_route_type(value: str) -> bool:
    return value in ROUTE_TYPES
