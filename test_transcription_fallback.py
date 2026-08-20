from pathlib import Path
from tempfile import TemporaryDirectory

from app.transcription import OpenAITranscriptionProvider
import app.transcription as transcription


class Response:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.ok = status_code < 400

    def json(self):
        return self._payload


calls = []


def fake_post(*_args, **kwargs):
    model = kwargs["data"]["model"]
    calls.append(model)
    if model == "gpt-4o-transcribe":
        return Response(400, {"error": {"message": "Only whisper-1 model is supported for audio transcriptions"}})
    return Response(200, {"text": "Test words from a finished recording."})


with TemporaryDirectory() as directory:
    path = Path(directory) / "fragment.webm"
    path.write_bytes(b"test-audio")
    original_post = transcription.requests.post
    transcription.requests.post = fake_post
    try:
        provider = OpenAITranscriptionProvider("test-key", "gpt-4o-transcribe")
        result = provider.transcribe(path, "audio/webm", "Australian English")
    finally:
        transcription.requests.post = original_post

assert calls == ["gpt-4o-transcribe", "whisper-1"], calls
assert result.text == "Test words from a finished recording."
assert result.model == "whisper-1"
print("fallback regression check passed")
