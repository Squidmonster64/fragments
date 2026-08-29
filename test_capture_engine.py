from pathlib import Path
from unittest.mock import patch

import requests

from app.capture_engine import capture_idempotency_key, engine_owns_run_maintain, submit_capture


ROOT = Path(__file__).resolve().parent


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


def test_submit_capture_skips_when_unconfigured():
    with patch("app.capture_engine._configured", return_value=None):
        assert submit_capture(
            fragment_code="FR-1",
            fragment_identity="1:2026-08-26T00:00:00+00:00",
            raw_text="I need to trim the hedge at the back of the pool.",
        ) is None


def test_submit_capture_fail_soft_when_engine_is_down():
    with patch("app.capture_engine._configured", return_value=("https://minutes.hope-johnstone.com", "secret")):
        with patch("app.capture_engine.requests.post", side_effect=requests.RequestException("down")):
            result = submit_capture(
                fragment_code="FR-1",
                fragment_identity="1:2026-08-26T00:00:00+00:00",
                raw_text="I need to trim the hedge at the back of the pool.",
            )
    assert result is not None
    assert result["accepted"] is False
    assert result["discarded"] is False


def test_submit_capture_fail_soft_on_http_error():
    response = requests.Response()
    response.status_code = 503
    with patch("app.capture_engine._configured", return_value=("https://minutes.hope-johnstone.com", "secret")):
        with patch("app.capture_engine.requests.post", return_value=response):
            result = submit_capture(
                fragment_code="FR-1",
                fragment_identity="1:2026-08-26T00:00:00+00:00",
                raw_text="I need to trim the hedge at the back of the pool.",
            )
    assert result is not None
    assert result["accepted"] is False
    assert result["discarded"] is False


def test_capture_ui_is_one_login_and_routes_before_synced():
    outbox = (ROOT / "app/static/captureOutbox.js").read_text()
    logic = (ROOT / "app/static/captureOutboxLogic.mjs").read_text()
    css = (ROOT / "app/static/fragments-recovery.css").read_text()

    # The actual form class used by the recovered capture UI must be bound to
    # the durable outbox rather than bypassing it with a direct form submit.
    assert "form.fragments-typed" in outbox

    # A capture is not considered synced until the existing interpret endpoint
    # has run, which is the point that hands the preserved source to the single
    # Hope Task Capture Engine.
    assert "/interpret" in outbox
    assert "routeCapture" in logic
    assert "route_failed" in logic
    assert "Captured and routed" in logic

    # The obsolete second passphrase panel is not part of the human capture
    # flow. Fragments owner auth remains the only user-facing login.
    assert "#live-sync { display: none !important; }" in css


if __name__ == "__main__":
    test_idempotency_key_is_stable_for_the_same_fragment()
    test_engine_owns_run_maintain_only_when_accepted()
    test_submit_capture_skips_when_unconfigured()
    test_submit_capture_fail_soft_when_engine_is_down()
    test_submit_capture_fail_soft_on_http_error()
    test_capture_ui_is_one_login_and_routes_before_synced()
    print("Capture Engine client checks passed")
