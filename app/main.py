from datetime import datetime, timezone
from pathlib import Path
import io
import json
import re
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, inspect, or_, select
from sqlalchemy.orm import Session

from .database import Base, SessionLocal, engine
from .interpretation import interpret_fragment, valid_memory_class
from .models import Fragment
from .transcription import TranscriptionConfigurationError, TranscriptionProviderError, transcribe_finished_recording

BASE_DIR = Path(__file__).resolve().parent.parent
AUDIO_DIR = BASE_DIR / "audio"
AUDIO_DIR.mkdir(parents=True, exist_ok=True)
STATUSES = ["Draft", "In revision", "Edited", "Final", "Archived"]
THEMES = ["Absence", "Childhood", "Family", "Grief", "Identity", "Loss", "Love", "Memory", "Place", "Relationships", "Travel"]
MEMORY_CLASSES = ["permanent", "reference", "transient", "unclassified"]
ROUTING_REVIEW_STATUSES = {"proposed", "accepted", "edited", "rejected"}
Base.metadata.create_all(bind=engine)


def ensure_fragment_columns() -> None:
    existing = {column["name"] for column in inspect(engine).get_columns("fragments")}
    additions = {
        "processing_state": "VARCHAR(32) NOT NULL DEFAULT 'unprocessed'",
        "processed_at": "DATETIME",
        "last_handoff_at": "DATETIME",
        "memory_class": "VARCHAR(24) NOT NULL DEFAULT 'unclassified'",
        "memory_class_reason": "VARCHAR(500) NOT NULL DEFAULT ''",
        # Nullable for older rows during a live upgrade; new ORM records always
        # begin with empty review data and are normalised by json_object().
        "interpretation_json": "TEXT",
        "routing_review_json": "TEXT",
        "interpreted_at": "DATETIME",
        "transcription_provider": "VARCHAR(80) NOT NULL DEFAULT ''",
        "transcription_model": "VARCHAR(120) NOT NULL DEFAULT ''",
        "transcribed_at": "DATETIME",
    }
    with engine.begin() as connection:
        for name, definition in additions.items():
            if name not in existing:
                connection.exec_driver_sql(f"ALTER TABLE fragments ADD COLUMN {name} {definition}")


ensure_fragment_columns()
app = FastAPI(title="Fragments")
app.mount("/static", StaticFiles(directory=BASE_DIR / "app" / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "app" / "templates")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def next_fragment_code(db: Session) -> str:
    codes = db.scalars(select(Fragment.fragment_code)).all()
    numbers = [int(match.group(1)) for code in codes if (match := re.fullmatch(r"F(\d+)", code))]
    return f"F{(max(numbers, default=0) + 1):03d}"


def split_values(value: str) -> set[str]:
    return {item.strip() for item in value.split(",") if item.strip()}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def json_object(value: str) -> dict:
    try:
        parsed = json.loads(value) if value else {}
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def interpretation_for(fragment: Fragment) -> dict:
    return json_object(fragment.interpretation_json)


def review_for(fragment: Fragment) -> dict:
    return json_object(fragment.routing_review_json)


def audio_extension(mime_type: str, filename: str) -> str:
    suffix = Path(filename or "").suffix.lower()
    if suffix in {".webm", ".m4a", ".mp4", ".ogg", ".wav", ".mp3", ".aac"}:
        return suffix
    if "mp4" in mime_type or "m4a" in mime_type:
        return ".m4a"
    if "ogg" in mime_type:
        return ".ogg"
    if "wav" in mime_type:
        return ".wav"
    return ".webm"


async def save_finished_audio(audio: UploadFile | None, fragment_code: str) -> tuple[str, str]:
    if not audio or not audio.filename:
        return "", ""
    payload = await audio.read()
    if not payload:
        raise HTTPException(400, "The recording was empty. Please try again or type the words instead.")
    if len(payload) > 80 * 1024 * 1024:
        raise HTTPException(413, "That recording is too large to save here. Please make a shorter fragment.")
    mime_type = (audio.content_type or "audio/webm").strip()[:100]
    filename = f"{fragment_code}-{uuid4().hex}{audio_extension(mime_type, audio.filename)}"
    (AUDIO_DIR / filename).write_bytes(payload)
    return filename, mime_type


def transcription_hint(fragment: Fragment) -> str:
    parts = ["Personal Australian-English dictation."]
    if fragment.title and fragment.title != "Untitled fragment":
        parts.append(f"Title: {fragment.title}.")
    if fragment.themes:
        parts.append(f"Themes: {fragment.themes}.")
    return " ".join(parts)


def fragment_markdown(fragment: Fragment) -> str:
    created = fragment.created_at.strftime("%Y-%m-%d")
    return f"""# {fragment.fragment_code} — {fragment.title}

**Date:** {created}  
**Status:** {fragment.status}  
**Themes:** {fragment.themes or '—'}  
**Cross References:** {fragment.cross_references or '—'}
**Memory:** {fragment.memory_class or 'unclassified'}
**Memory note:** {fragment.memory_class_reason or '—'}
**Processing:** {fragment.processing_state or 'unprocessed'}

---

## Original Dictation

{fragment.raw_transcript or '[Original text not yet added.]'}

---

## Edited Version

{fragment.edited_version or '[Not yet edited.]'}

---

## Notes

{fragment.notes or ''}
"""


def fragment_payload(fragment: Fragment) -> dict:
    return {
        "fragment_code": fragment.fragment_code,
        "title": fragment.title,
        "status": fragment.status,
        "themes": fragment.themes,
        "cross_references": fragment.cross_references,
        "raw_transcript": fragment.raw_transcript,
        "edited_version": fragment.edited_version,
        "notes": fragment.notes,
        "audio_path": fragment.audio_path,
        "audio_mime_type": fragment.audio_mime_type,
        "memory_class": fragment.memory_class,
        "memory_class_reason": fragment.memory_class_reason,
        "interpretation": interpretation_for(fragment),
        "routing_review": review_for(fragment),
        "interpreted_at": fragment.interpreted_at.isoformat() if fragment.interpreted_at else "",
        "transcription_provider": fragment.transcription_provider,
        "transcription_model": fragment.transcription_model,
        "transcribed_at": fragment.transcribed_at.isoformat() if fragment.transcribed_at else "",
        "processing_state": fragment.processing_state,
        "processed_at": fragment.processed_at.isoformat() if fragment.processed_at else "",
        "last_handoff_at": fragment.last_handoff_at.isoformat() if fragment.last_handoff_at else "",
        "created_at": fragment.created_at.isoformat() if fragment.created_at else "",
        "updated_at": fragment.updated_at.isoformat() if fragment.updated_at else "",
    }


def safe_filename(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9 _-]", "", value).strip() or "Untitled"


@app.get("/", response_class=HTMLResponse)
def home(request: Request, q: str = "", review: bool = False, memory: str = "", db: Session = Depends(get_db)):
    query = select(Fragment)
    text = q.strip()
    selected_memory = memory.strip().lower()
    if text:
        pattern = f"%{text}%"
        query = query.where(or_(Fragment.title.ilike(pattern), Fragment.raw_transcript.ilike(pattern), Fragment.edited_version.ilike(pattern), Fragment.notes.ilike(pattern), Fragment.themes.ilike(pattern)))
    if review:
        query = query.where(Fragment.status.in_(["Draft", "In revision"]))
    if selected_memory in MEMORY_CLASSES:
        query = query.where(Fragment.memory_class == selected_memory)
    fragments = db.scalars(query.order_by(Fragment.updated_at.desc())).all()
    return templates.TemplateResponse("index.html", {"request": request, "fragments": fragments, "query": text, "review": review, "memory": selected_memory, "memory_classes": MEMORY_CLASSES})


@app.post("/api/fragments")
async def create_fragment(
    title: str = Form("Untitled fragment"),
    raw_transcript: str = Form(""),
    audio: UploadFile | None = File(None),
    capture_mode: str = Form(""),
    db: Session = Depends(get_db),
):
    text = raw_transcript.strip()
    if not text and (not audio or not audio.filename):
        raise HTTPException(400, "Write something or record a fragment before saving it.")
    fragment_code = next_fragment_code(db)
    audio_path, audio_mime_type = await save_finished_audio(audio, fragment_code)
    fragment = Fragment(
        fragment_code=fragment_code,
        title=title.strip() or "Untitled fragment",
        status="Draft",
        raw_transcript=text,
        edited_version=text,
        audio_path=audio_path,
        audio_mime_type=audio_mime_type,
        processing_state="awaiting_transcription" if audio_path else "unprocessed",
    )
    db.add(fragment)
    db.commit()
    db.refresh(fragment)
    if capture_mode == "voice":
        return {"id": fragment.id, "url": f"/fragments/{fragment.id}", "transcription_pending": bool(audio_path)}
    return RedirectResponse(f"/fragments/{fragment.id}", status_code=303)


@app.get("/fragments/{fragment_id}", response_class=HTMLResponse)
def fragment_page(fragment_id: int, request: Request, db: Session = Depends(get_db)):
    fragment = db.get(Fragment, fragment_id)
    if not fragment:
        raise HTTPException(404, "Fragment not found")
    other_fragments = db.scalars(select(Fragment).where(Fragment.id != fragment_id).order_by(Fragment.fragment_code)).all()
    return templates.TemplateResponse(
        "fragment.html",
        {
            "request": request,
            "fragment": fragment,
            "statuses": STATUSES,
            "themes": THEMES,
            "memory_classes": MEMORY_CLASSES,
            "selected_themes": split_values(fragment.themes),
            "selected_refs": split_values(fragment.cross_references),
            "other_fragments": other_fragments,
            "interpretation": interpretation_for(fragment),
            "routing_review": review_for(fragment),
        },
    )


@app.post("/fragments/{fragment_id}")
def update_fragment(
    fragment_id: int,
    title: str = Form(...),
    status: str = Form("Draft"),
    themes: list[str] = Form([]),
    cross_references: list[str] = Form([]),
    raw_transcript: str = Form(""),
    edited_version: str = Form(""),
    notes: str = Form(""),
    memory_class: str = Form("unclassified"),
    action: str = Form("save"),
    db: Session = Depends(get_db),
):
    fragment = db.get(Fragment, fragment_id)
    if not fragment:
        raise HTTPException(404, "Fragment not found")
    new_raw_transcript = raw_transcript.strip()
    source_changed = new_raw_transcript != fragment.raw_transcript
    fragment.title = title.strip() or "Untitled fragment"
    fragment.status = status if status in STATUSES else "Draft"
    fragment.themes = ", ".join(theme for theme in THEMES if theme in themes)
    valid_codes = set(db.scalars(select(Fragment.fragment_code).where(Fragment.id != fragment_id)).all())
    fragment.cross_references = ", ".join(code for code in cross_references if code in valid_codes)
    fragment.raw_transcript = new_raw_transcript
    fragment.edited_version = edited_version.strip()
    fragment.notes = notes.strip()
    if source_changed:
        fragment.processing_state = "unprocessed"
        fragment.processed_at = None
        fragment.interpretation_json = ""
        fragment.routing_review_json = ""
        fragment.interpreted_at = None
        fragment.memory_class = "unclassified"
        fragment.memory_class_reason = "The original words changed. Review the memory class again."
    elif valid_memory_class(memory_class):
        fragment.memory_class = memory_class
        fragment.memory_class_reason = "Set by you."
    db.commit()
    if action == "export":
        return RedirectResponse(f"/fragments/{fragment_id}/export", status_code=303)
    return RedirectResponse(f"/fragments/{fragment_id}?saved=1", status_code=303)


@app.post("/api/fragments/{fragment_id}/transcribe")
def transcribe_fragment(fragment_id: int, db: Session = Depends(get_db)):
    fragment = db.get(Fragment, fragment_id)
    if not fragment:
        raise HTTPException(404, "Fragment not found")
    if not fragment.audio_path:
        raise HTTPException(400, "There is no saved recording to transcribe. You can type the words instead.")
    audio_path = AUDIO_DIR / fragment.audio_path
    try:
        result = transcribe_finished_recording(audio_path, fragment.audio_mime_type, transcription_hint(fragment))
    except TranscriptionConfigurationError as error:
        raise HTTPException(503, str(error)) from error
    except TranscriptionProviderError as error:
        raise HTTPException(502, str(error)) from error
    previous_text = fragment.raw_transcript.strip()
    fragment.raw_transcript = result.text
    if not fragment.edited_version.strip() or fragment.edited_version.strip() == previous_text:
        fragment.edited_version = result.text
    fragment.transcription_provider = result.provider
    fragment.transcription_model = result.model
    fragment.transcribed_at = utc_now()
    fragment.processing_state = "transcribed"
    fragment.interpretation_json = ""
    fragment.routing_review_json = ""
    fragment.interpreted_at = None
    fragment.memory_class = "unclassified"
    fragment.memory_class_reason = "The recording has been transcribed. Review what was heard before deciding what it means."
    db.commit()
    return {
        "fragment": fragment_payload(fragment),
        "message": "The recording is saved. These are the words that were heard; interpretation comes next only if you ask for it.",
    }


@app.post("/api/fragments/{fragment_id}/interpret")
def interpret_saved_fragment(fragment_id: int, db: Session = Depends(get_db)):
    fragment = db.get(Fragment, fragment_id)
    if not fragment:
        raise HTTPException(404, "Fragment not found")
    original_text = fragment.raw_transcript.strip()
    if not original_text:
        raise HTTPException(400, "There are no saved words to interpret yet. Transcribe the finished recording or type the words first.")
    draft = interpret_fragment(original_text)
    classified_as = draft["memory_class"]
    # A prior or mixed-content Permanent call always wins over a less durable
    # automatic suggestion. The owner can still choose a different class later.
    if fragment.memory_class == "permanent" or classified_as == "permanent":
        fragment.memory_class = "permanent"
        fragment.memory_class_reason = draft["memory_class_reason"] if classified_as == "permanent" else fragment.memory_class_reason or "Kept permanently by you."
    else:
        fragment.memory_class = classified_as
        fragment.memory_class_reason = draft["memory_class_reason"]
    review = {
        "schema": "bloody-daves/fragment-routing-review/v1",
        "fragment_id": fragment.id,
        "source_fragment_code": fragment.fragment_code,
        "candidates": draft["candidates"],
        "clarifications": draft["clarifications"],
        "state": "review",
        "no_changes_made": True,
        "updated_at": utc_now().isoformat(),
    }
    fragment.interpretation_json = json.dumps(draft)
    fragment.routing_review_json = json.dumps(review)
    fragment.interpreted_at = utc_now()
    fragment.processing_state = "ready_for_review"
    db.commit()
    return {
        "fragment": fragment_payload(fragment),
        "interpretation": draft,
        "routing_review": review,
        "message": "These are suggestions only. Nothing has been added anywhere yet.",
    }


@app.post("/api/fragments/{fragment_id}/routing-review")
async def update_routing_review(fragment_id: int, request: Request, db: Session = Depends(get_db)):
    fragment = db.get(Fragment, fragment_id)
    if not fragment:
        raise HTTPException(404, "Fragment not found")
    review = review_for(fragment)
    candidates = review.get("candidates") if isinstance(review.get("candidates"), list) else []
    if not candidates:
        raise HTTPException(400, "There is no routing draft to review yet.")
    try:
        body = await request.json()
    except json.JSONDecodeError as error:
        raise HTTPException(400, "The review choice could not be read.") from error
    candidate_id = str(body.get("candidate_id", "")).strip()
    status = str(body.get("status", "")).strip().lower()
    if status not in ROUTING_REVIEW_STATUSES or not candidate_id:
        raise HTTPException(400, "Choose one suggested item and a valid review state.")
    selected = next((item for item in candidates if isinstance(item, dict) and item.get("id") == candidate_id), None)
    if not selected:
        raise HTTPException(404, "That suggested item is no longer in this review.")
    selected["status"] = status
    if status == "edited":
        title = str(body.get("title", selected.get("title", ""))).strip()[:250]
        detail = str(body.get("detail", selected.get("detail", ""))).strip()[:4_000]
        if not title:
            raise HTTPException(400, "Give the edited suggestion a short title.")
        selected["title"] = title
        selected["detail"] = detail
    review["candidates"] = candidates
    review["updated_at"] = utc_now().isoformat()
    review["no_changes_made"] = True
    fragment.routing_review_json = json.dumps(review)
    db.commit()
    return {"routing_review": review, "message": "Review saved. Nothing has been added to another app."}


@app.post("/fragments/{fragment_id}/handoff")
def export_harvest_handoff(fragment_id: int, db: Session = Depends(get_db)):
    fragment = db.get(Fragment, fragment_id)
    if not fragment:
        raise HTTPException(404, "Fragment not found")
    fragment.processing_state = "handed_off"
    fragment.last_handoff_at = datetime.utcnow()
    db.commit()
    payload = {
        "schema": "bloody-daves/fragment-handoff/v1",
        "created_at": datetime.utcnow().isoformat() + "Z",
        "source": {"app": "fragments", "id": fragment.fragment_code, "url": f"/fragments/{fragment.id}"},
        "fragment": {"code": fragment.fragment_code, "title": fragment.title, "raw_text": fragment.raw_transcript, "captured_at": fragment.created_at.isoformat() if fragment.created_at else ""},
        "review": {"processing_state": "handed_off", "instruction": "Import or paste this file into Structure's Harvester only when you want a reviewed proposal. The original fragment remains unchanged."},
    }
    headers = {"Content-Disposition": f'attachment; filename="{fragment.fragment_code}-harvester-handoff.json"'}
    return Response(json.dumps(payload, indent=2), media_type="application/json", headers=headers)


@app.post("/fragments/{fragment_id}/processing")
def set_processing_state(fragment_id: int, processing_state: str = Form(...), db: Session = Depends(get_db)):
    fragment = db.get(Fragment, fragment_id)
    if not fragment:
        raise HTTPException(404, "Fragment not found")
    if processing_state not in {"unprocessed", "handed_off", "processed"}:
        raise HTTPException(400, "Unknown processing state")
    fragment.processing_state = processing_state
    fragment.processed_at = datetime.utcnow() if processing_state == "processed" else None
    db.commit()
    return RedirectResponse(f"/fragments/{fragment.id}?processing={processing_state}", status_code=303)


@app.post("/fragments/{fragment_id}/delete")
def delete_fragment(fragment_id: int, db: Session = Depends(get_db)):
    fragment = db.get(Fragment, fragment_id)
    if not fragment:
        raise HTTPException(404, "Fragment not found")
    if fragment.audio_path:
        audio_path = AUDIO_DIR / fragment.audio_path
        if audio_path.exists():
            audio_path.unlink()
    db.delete(fragment)
    db.commit()
    return RedirectResponse("/?deleted=1", status_code=303)


@app.get("/audio/{fragment_id}")
def get_audio(fragment_id: int, db: Session = Depends(get_db)):
    fragment = db.get(Fragment, fragment_id)
    if not fragment:
        raise HTTPException(404, "Fragment not found")
    path = AUDIO_DIR / fragment.audio_path
    if not path.exists():
        raise HTTPException(404, "Audio file missing")
    return FileResponse(path, media_type=fragment.audio_mime_type, filename=path.name)


@app.get("/fragments/{fragment_id}/export", response_class=PlainTextResponse)
def export_fragment(fragment_id: int, db: Session = Depends(get_db)):
    fragment = db.get(Fragment, fragment_id)
    if not fragment:
        raise HTTPException(404, "Fragment not found")
    headers = {"Content-Disposition": f'attachment; filename="{fragment.fragment_code} - {safe_filename(fragment.title)}.md"'}
    return PlainTextResponse(fragment_markdown(fragment), headers=headers)


@app.get("/export/backup")
def export_backup(db: Session = Depends(get_db)):
    fragments = db.scalars(select(Fragment).order_by(Fragment.fragment_code)).all()
    payload = {"schema": "bloody-daves/fragments-backup/v1", "exported_at": datetime.utcnow().isoformat() + "Z", "fragments": [fragment_payload(fragment) for fragment in fragments]}
    headers = {"Content-Disposition": 'attachment; filename="bloody-daves-fragments-backup.json"'}
    return Response(json.dumps(payload, indent=2), media_type="application/json", headers=headers)


@app.get("/export/markdown")
def export_markdown_bundle(db: Session = Depends(get_db)):
    fragments = db.scalars(select(Fragment).order_by(Fragment.fragment_code)).all()
    archive = io.BytesIO()
    with ZipFile(archive, "w", ZIP_DEFLATED) as bundle:
        for fragment in fragments:
            bundle.writestr(f"{fragment.fragment_code} - {safe_filename(fragment.title)}.md", fragment_markdown(fragment))
    headers = {"Content-Disposition": 'attachment; filename="bloody-daves-fragments-markdown.zip"'}
    return Response(archive.getvalue(), media_type="application/zip", headers=headers)


@app.post("/import/backup")
async def import_backup(backup: UploadFile = File(...), db: Session = Depends(get_db)):
    try:
        payload = json.loads((await backup.read()).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise HTTPException(400, "The backup could not be read as JSON") from error
    if payload.get("schema") != "bloody-daves/fragments-backup/v1" or not isinstance(payload.get("fragments"), list):
        raise HTTPException(400, "This file is not a compatible Fragments backup")
    imported = 0
    for record in payload["fragments"]:
        if not isinstance(record, dict) or not str(record.get("raw_transcript", "")).strip():
            continue
        fragment = Fragment(
            fragment_code=next_fragment_code(db),
            title=str(record.get("title", "Untitled fragment")).strip()[:240] or "Untitled fragment",
            status=str(record.get("status", "Draft")) if str(record.get("status", "Draft")) in STATUSES else "Draft",
            themes=str(record.get("themes", ""))[:500],
            cross_references="",
            raw_transcript=str(record.get("raw_transcript", "")).strip(),
            edited_version=str(record.get("edited_version", record.get("raw_transcript", ""))).strip(),
            notes=str(record.get("notes", "")).strip(),
            processing_state=str(record.get("processing_state", "unprocessed")) if str(record.get("processing_state", "unprocessed")) in {"unprocessed", "handed_off", "processed"} else "unprocessed",
            audio_path="",
            audio_mime_type="",
        )
        db.add(fragment)
        db.flush()
        imported += 1
    db.commit()
    return RedirectResponse(f"/?imported={imported}", status_code=303)


@app.get("/health")
def health(db: Session = Depends(get_db)):
    count = db.scalar(select(func.count()).select_from(Fragment))
    return {"ok": True, "fragments": count, "time": datetime.utcnow().isoformat() + "Z"}
