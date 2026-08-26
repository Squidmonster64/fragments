from app.capture_engine import capture_idempotency_key, engine_owns_run_maintain


def test_idempotency_key_is_stable_for_the_same_fragment():
    first = capture_idempotency_key("5:2026-08-26T00:00:00+00:00")
    retry = capture_idempotency_key("5:2026-08-26T00:00:00+00:00")
    other = capture_idempotency_key("5:2026-08-26T00:00:01+00:00")
    assert first == retry
    assert first != other
    assert first.startswith("capture-engine:")


def test_engine_owns_run_maintain_only_when_accepted():
    assert engine_owns_run_maintain({"accepted": True, "applied": []}) is True
    assert engine_owns_run_maintain({"accepted": False}) is False
    assert engine_owns_run_maintain(None) is False


if __name__ == "__main__":
    test_idempotency_key_is_stable_for_the_same_fragment()
    test_engine_owns_run_maintain_only_when_accepted()
    print("Capture Engine client checks passed")
