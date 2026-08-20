from app.database import Base, SessionLocal, engine
from app.models import Fragment
from app.main import get_audio

Base.metadata.create_all(bind=engine)
with SessionLocal() as db:
    fragment = Fragment(
        fragment_code="AUDIO-TEST",
        title="Durable audio test",
        audio_path="missing-after-deploy.webm",
        audio_mime_type="audio/webm",
        audio_data=b"original-recording-bytes",
    )
    db.add(fragment)
    db.commit()
    db.refresh(fragment)
    response = get_audio(fragment.id, db)
    assert response.body == b"original-recording-bytes"
    assert response.media_type == "audio/webm"
    db.delete(fragment)
    db.commit()

print("durable audio regression check passed")
