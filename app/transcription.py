"""Server-side audio transcription for Fragments.

The browser never receives a provider key.  This module deliberately runs only
on an already-finished file; it never streams microphone audio and it does not
keep listening after the client has stopped the recorder.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import requests

logger = logging.getLogger(__name__)


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

    def _request(self, audio_path: Path, mime_type: str, hint: str, model: str) -> requests.Response:
        """Send one completed recording.  The file is reopened for every retry."""
        with audio_path.open("rb") as audio_file:
            return requests.post(
                "https://api.openai.com/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                data={
                    "model": model,
                    "response_format": "json",
                    "language": "en",
                    # The hint supplies only owner-held context such as titles and themes.
                    # It is not a replacement transcript and does not change the saved audio.
                    "prompt": hint[:1_000],
                },
                files={"file": (audio_path.name, audio_file, mime_type or "audio/webm")},
                timeout=120,
            )

    @staticmethod
    def _error_detail(response: requests.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            return ""
        if not isinstance(payload, dict):
            return ""
        error = payload.get("error")
        if isinstance(error, dict):
            return str(error.get("message", "")).strip()
        return str(payload.get("message", "")).strip()

    @staticmethod
    def _requires_whisper_fallback(response: requests.Response, detail: str, requested_model: str) -> bool:
        """Keep gpt-transcribe first, but support endpoints restricted to Whisper.

        Some compatible OpenAI gateways accept the audio API but expose only
        ``whisper-1``.  They state that restriction explicitly.  Retrying only
        for that exact condition prevents a bad recording, bad key, rate limit,
        or network error from being hidden by a second request.
        """
        if requested_model == "whisper-1" or response.status_code not in {400, 404}:
            return False
        wording = detail.casefold()
        return "whisper-1" in wording and ("only" in wording or "supported" in wording or "model" in wording)

    def transcribe(self, audio_path: Path, mime_type: str, hint: str) -> TranscriptionResult:
        if not audio_path.exists() or not audio_path.is_file():
            raise TranscriptionProviderError("The original recording could not be found.")
        selected_model = self.model
        try:
            response = self._request(audio_path, mime_type, hint, selected_model)
            detail = self._error_detail(response)
            if self._requires_whisper_fallback(response, detail, selected_model):
                selected_model = "whisper-1"
                response = self._request(audio_path, mime_type, hint, selected_model)
                detail = self._error_detail(response)
        except requests.RequestException as error:
            raise TranscriptionProviderError("The transcription service could not be reached. The original recording is still safe here.") from error
        if not response.ok:
            safe_detail = detail.replace("\n", " ")[:220]
            # Keep the full recording and secret key private, but make the
            # upstream status diagnosable in the service log.
            logger.warning(
                "Finished-recording transcription failed: status=%s model=%s detail=%s",
                response.status_code,
                selected_model,
                safe_detail or "(no JSON error detail)",
            )
            raise TranscriptionProviderError(f"The transcription service could not finish this recording{': ' + safe_detail if safe_detail else '.'}")
        try:
            payload = response.json()
        except ValueError as error:
            raise TranscriptionProviderError("The transcription service returned an unreadable reply.") from error
        text = str(payload.get("text", "")).strip()
        if not text:
            raise TranscriptionProviderError("No words were returned for this recording. You can still type the words yourself.")
        return TranscriptionResult(text=text, provider=self.name, model=selected_model)


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
