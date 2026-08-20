from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
created_ids = []

try:
    typed = client.post(
        "/api/fragments",
        data={"title": "Smoke test", "raw_transcript": "I need to renew my passport then remind me to call Mary tomorrow."},
        follow_redirects=False,
    )
    assert typed.status_code == 303, typed.text
    typed_id = int(typed.headers["location"].rsplit("/", 1)[-1])
    created_ids.append(typed_id)

    draft = client.post(f"/api/fragments/{typed_id}/interpret")
    assert draft.status_code == 200, draft.text
    review = draft.json()["routing_review"]
    assert review["no_changes_made"] is True
    assert {item["type"] for item in review["candidates"]} >= {"run_maintain", "reminder"}
    assert all("renew my passport" in item["title"].lower() or "call mary" in item["title"].lower() for item in review["candidates"])

    first = review["candidates"][0]
    choice = client.post(
        f"/api/fragments/{typed_id}/routing-review",
        json={"candidate_id": first["id"], "status": "accepted"},
    )
    assert choice.status_code == 200, choice.text
    assert choice.json()["message"] == "Review saved. Nothing has been added to another app."

    short_audio = client.post(
        "/api/fragments",
        data={"raw_transcript": "", "capture_mode": "voice"},
        files={"audio": ("header-only.webm", b"tiny", "audio/webm")},
    )
    assert short_audio.status_code == 422, short_audio.text

    # This fixture is intentionally not valid audio; it tests durable upload and
    # the safe downstream transcription failure after passing the header guard.
    audio = client.post(
        "/api/fragments",
        data={"raw_transcript": "", "capture_mode": "voice"},
        files={"audio": ("test.webm", b"not-a-real-recording" * 100, "audio/webm")},
    )
    assert audio.status_code == 200, audio.text
    audio_id = audio.json()["id"]
    created_ids.append(audio_id)
    transcription = client.post(f"/api/fragments/{audio_id}/transcribe")
    # The essential property is that provider failure is reviewable after the
    # original recording has been retained; the endpoint maps it to 422.
    assert transcription.status_code == 422, transcription.text
finally:
    for fragment_id in created_ids:
        client.post(f"/fragments/{fragment_id}/delete", follow_redirects=False)

print("Fragments voice and review smoke test passed")
