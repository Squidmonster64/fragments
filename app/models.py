from datetime import datetime, timezone
from sqlalchemy import DateTime, Integer, String, Text
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
    audio_path: Mapped[str] = mapped_column(String(500))
    audio_mime_type: Mapped[str] = mapped_column(String(100), default="audio/webm")
    processing_state: Mapped[str] = mapped_column(String(32), default="unprocessed")
    processed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_handoff_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
