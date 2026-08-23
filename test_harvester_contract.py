from app.harvester_contract import HARVESTER_CONTRACT_VERSION, build_action_request, parse_action_response


def test_build_action_request_includes_v1_fields():
    request = build_action_request(
        fragment_code="F014",
        fragment_db_id=14,
        source_created_at="2026-08-23T10:00:00+00:00",
        source_type="voice",
        normalized_text="Buy carrots on the way home.",
        candidate={
            "id": "cand-1",
            "type": "get_list",
            "title": "Carrots",
            "detail": "On the way home",
            "confidence": 0.91,
            "metadata": {"domains": ["food"]},
        },
        idempotency_key="fragment:abc123",
        source_url="/fragments/14",
    )
    assert request["contractVersion"] == HARVESTER_CONTRACT_VERSION
    assert request["fragmentId"] == "F014"
    assert request["sourceCreatedAt"] == "2026-08-23T10:00:00+00:00"
    assert request["sourceType"] == "voice"
    assert request["normalizedText"] == "Buy carrots on the way home."
    assert request["intent"] == "get_list"
    assert request["proposedAction"]["title"] == "Carrots"
    assert request["idempotencyKey"] == "fragment:abc123"
    assert request["originatingApp"] == "fragments"
    assert request["provenance"]["fragmentDbId"] == 14
    assert request["provenance"]["candidateId"] == "cand-1"


def test_parse_action_response_v1():
    parsed = parse_action_response(
        {
            "contractVersion": "v1",
            "accepted": True,
            "actionId": "act-1",
            "resultingEntityId": "entry-1",
            "idempotencyOutcome": "created",
            "reason": "Added to Get List: Carrots",
            "provenanceReference": {
                "actionId": "act-1",
                "sourceFragmentId": "F014",
                "idempotencyKey": "fragment:abc123",
                "targetKind": "get_list_entry",
                "targetId": "entry-1",
            },
            "undoAvailable": True,
        }
    )
    assert parsed["accepted"] is True
    assert parsed["action_id"] == "act-1"
    assert parsed["resulting_entity_id"] == "entry-1"
    assert parsed["idempotency_outcome"] == "created"
    assert parsed["provenance_reference"]["targetId"] == "entry-1"


def test_parse_action_response_legacy_duplicate_prevention():
    parsed = parse_action_response(
        {
            "duplicate": True,
            "action": {
                "id": "act-1",
                "targetId": "entry-1",
                "targetKind": "get_list_entry",
                "sourceFragmentId": "F014",
                "idempotencyKey": "fragment:abc123",
                "summary": "Already on Get List: Carrots",
                "status": "active",
                "createdTarget": False,
            },
        }
    )
    assert parsed["accepted"] is True
    assert parsed["idempotency_outcome"] == "duplicate"
    assert parsed["resulting_entity_id"] == "entry-1"
