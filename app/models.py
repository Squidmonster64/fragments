from datetime import datetime, timezone
from sqlalchemy import DateTime, Integer, LargeBinary, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from .database import Base

class Fragment(Base):
    __tablename__ = "fragments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fragment_code: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(240), default="Untitled fragment")
    status: Mapped[str] = mapped_column(String(32), default="Draft")
    themes: Mapped[str] = mapped_column(String(500), default="")
    cross_references: Mapped[str] = mapped_column(String(500), default="")
    raw_transcript: Mapped[str] = mapped_column(Text, default="")
    edited_version: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    # What was heard or written stays separate from every later interpretation.
    audio_path: Mapped[str] = mapped_column(String(500), default="")
    audio_mime_type: Mapped[str] = mapped_column(String(100), default="audio/webm")
    # The original finished recording is stored with the durable Fragment row.
    # audio_path remains for compatibility with earlier file-backed recordings.
    audio_data: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)

    # These fields describe preservation and review only. They never create work
    # in another surface by themselves.
    memory_class: Mapped[str] = mapped_column(String(24), default="unclassified")
    memory_class_reason: Mapped[str] = mapped_column(String(500), default="")
    interpretation_json: Mapped[str] = mapped_column(Text, default="")
    routing_review_json: Mapped[str] = mapped_column(Text, default="")
    # Cross-surface links are recorded only after the owner accepts a reviewed
    # action. Their completion state governs conservative transient retention.
    linked_actions_json: Mapped[str] = mapped_column(Text, default="")
    cleanup_eligible_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cleanup_state: Mapped[str] = mapped_column(String(32), default="kept")
    interpreted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    transcription_provider: Mapped[str] = mapped_column(String(80), default="")
    transcription_model: Mapped[str] = mapped_column(String(120), default="")
    transcribed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    processing_state: Mapped[str] = mapped_column(String(32), default="unprocessed")
    processed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_handoff_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    client_capture_id: Mapped[str] = mapped_column(String(80), default="", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
