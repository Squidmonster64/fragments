"""Server-side audio transcription for Fragments.

The browser never receives a provider key.  This module deliberately runs only
on an already-finished file; it never streams microphone audio and it does not
keep listening after the client has stopped the recorder.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import requests


class TranscriptionConfigurationError(RuntimeError):
    """Raised when the independently hosted service has no configured provider."""


class TranscriptionProviderError(RuntimeError):
    """Raised when the configured provider cannot transcribe a finished recording."""


@dataclass(frozen=True)
class TranscriptionResult:
    text: str
    provider: str
    model: str


class TranscriptionProvider(Protocol):
    def transcribe(self, audio_path: Path, mime_type: str, hint: str) -> TranscriptionResult:
        """Transcribe a complete audio file and return only the words that were heard."""


class OpenAITranscriptionProvider:
    name = "openai"

    def __init__(self, api_key: str, model: str) -> None:
        self.api_key = api_key
        self.model = model

    def transcribe(self, audio_path: Path, mime_type: str, hint: str) -> TranscriptionResult:
        if not audio_path.exists() or not audio_path.is_file():
            raise TranscriptionProviderError("The original recording could not be found.")
        try:
            with audio_path.open("rb") as audio_file:
                response = requests.post(
                    "https://api.openai.com/v1/audio/transcriptions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    data={
                        "model": self.model,
                        "response_format": "json",
                        "language": "en",
                        # The hint supplies only owner-held context such as titles and themes.
                        # It is not a replacement transcript and does not change the saved audio.
                        "prompt": hint[:1_000],
                    },
                    files={"file": (audio_path.name, audio_file, mime_type or "audio/webm")},
                    timeout=120,
                )
        except requests.RequestException as error:
            raise TranscriptionProviderError("The transcription service could not be reached. The original recording is still safe here.") from error
        if not response.ok:
            try:
                detail = response.json().get("error", {}).get("message", "")
            except ValueError:
                detail = ""
            safe_detail = str(detail).strip().replace("\n", " ")[:220]
            raise TranscriptionProviderError(f"The transcription service could not finish this recording{': ' + safe_detail if safe_detail else '.'}")
        try:
            payload = response.json()
        except ValueError as error:
            raise TranscriptionProviderError("The transcription service returned an unreadable reply.") from error
        text = str(payload.get("text", "")).strip()
        if not text:
            raise TranscriptionProviderError("No words were returned for this recording. You can still type the words yourself.")
        return TranscriptionResult(text=text, provider=self.name, model=self.model)


def configured_transcription_provider() -> TranscriptionProvider:
    """Return the selected provider without allowing keys into client-side code.

    `TRANSCRIPTION_PROVIDER` makes a later provider replacement explicit.  OpenAI
    is currently the only implementation because it is the requested default.
    """

    selected = os.getenv("TRANSCRIPTION_PROVIDER", "openai").strip().lower()
    if selected not in {"openai", ""}:
        raise TranscriptionConfigurationError(f"The selected transcription provider ({selected}) is not available yet.")
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise TranscriptionConfigurationError("Voice transcription is not set up on this server yet. The original recording is saved; type the words below or add the server key before trying again.")
    # gpt-4o-transcribe is OpenAI's gpt-transcribe family model.  Deployment may
    # override this with OPENAI_TRANSCRIPTION_MODEL without a code change.
    model = os.getenv("OPENAI_TRANSCRIPTION_MODEL", "gpt-4o-transcribe").strip() or "gpt-4o-transcribe"
    return OpenAITranscriptionProvider(api_key=api_key, model=model)


def transcribe_finished_recording(audio_path: Path, mime_type: str, hint: str) -> TranscriptionResult:
    """Transcribe an audio file only after recording has finished and been saved."""

    return configured_transcription_provider().transcribe(audio_path, mime_type, hint)
