from datetime import datetime
from pathlib import Path
import io
import json
import re
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, inspect, or_, select
from sqlalchemy.orm import Session

from .database import Base, SessionLocal, engine
from .models import Fragment

BASE_DIR = Path(__file__).resolve().parent.parent
AUDIO_DIR = BASE_DIR / "audio"
AUDIO_DIR.mkdir(parents=True, exist_ok=True)
STATUSES = ["Draft", "In revision", "Edited", "Final", "Archived"]
THEMES = ["Absence", "Childhood", "Family", "Grief", "Identity", "Loss", "Love", "Memory", "Place", "Relationships", "Travel"]
Base.metadata.create_all(bind=engine)


def ensure_fragment_columns() -> None:
    existing = {column["name"] for column in inspect(engine).get_columns("fragments")}
    additions = {
        "processing_state": "VARCHAR(32) NOT NULL DEFAULT 'unprocessed'",
        "processed_at": "DATETIME",
        "last_handoff_at": "DATETIME",
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


def fragment_markdown(fragment: Fragment) -> str:
    created = fragment.created_at.strftime("%Y-%m-%d")
    return f"""# {fragment.fragment_code} — {fragment.title}

**Date:** {created}  
**Status:** {fragment.status}  
**Themes:** {fragment.themes or '—'}  
**Cross References:** {fragment.cross_references or '—'}
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
        "processing_state": fragment.processing_state,
        "processed_at": fragment.processed_at.isoformat() if fragment.processed_at else "",
        "last_handoff_at": fragment.last_handoff_at.isoformat() if fragment.last_handoff_at else "",
        "created_at": fragment.created_at.isoformat() if fragment.created_at else "",
        "updated_at": fragment.updated_at.isoformat() if fragment.updated_at else "",
    }


def safe_filename(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9 _-]", "", value).strip() or "Untitled"


@app.get("/", response_class=HTMLResponse)
def home(request: Request, q: str = "", review: bool = False, db: Session = Depends(get_db)):
    query = select(Fragment)
    text = q.strip()
    if text:
        pattern = f"%{text}%"
        query = query.where(or_(Fragment.title.ilike(pattern), Fragment.raw_transcript.ilike(pattern), Fragment.edited_version.ilike(pattern), Fragment.notes.ilike(pattern), Fragment.themes.ilike(pattern)))
    if review:
        query = query.where(Fragment.status.in_(["Draft", "In revision"]))
    fragments = db.scalars(query.order_by(Fragment.updated_at.desc())).all()
    return templates.TemplateResponse("index.html", {"request": request, "fragments": fragments, "query": text, "review": review})


@app.post("/api/fragments")
def create_fragment(title: str = Form("Untitled fragment"), raw_transcript: str = Form(...), db: Session = Depends(get_db)):
    text = raw_transcript.strip()
    if not text:
        raise HTTPException(400, "Fragment text cannot be empty")
    fragment = Fragment(fragment_code=next_fragment_code(db), title=title.strip() or "Untitled fragment", status="Draft", raw_transcript=text, edited_version=text, audio_path="", audio_mime_type="")
    db.add(fragment)
    db.commit()
    db.refresh(fragment)
    return RedirectResponse(f"/fragments/{fragment.id}", status_code=303)


@app.get("/fragments/{fragment_id}", response_class=HTMLResponse)
def fragment_page(fragment_id: int, request: Request, db: Session = Depends(get_db)):
    fragment = db.get(Fragment, fragment_id)
    if not fragment:
        raise HTTPException(404, "Fragment not found")
    other_fragments = db.scalars(select(Fragment).where(Fragment.id != fragment_id).order_by(Fragment.fragment_code)).all()
    return templates.TemplateResponse("fragment.html", {"request": request, "fragment": fragment, "statuses": STATUSES, "themes": THEMES, "selected_themes": split_values(fragment.themes), "selected_refs": split_values(fragment.cross_references), "other_fragments": other_fragments})


@app.post("/fragments/{fragment_id}")
def update_fragment(fragment_id: int, title: str = Form(...), status: str = Form("Draft"), themes: list[str] = Form([]), cross_references: list[str] = Form([]), raw_transcript: str = Form(""), edited_version: str = Form(""), notes: str = Form(""), action: str = Form("save"), db: Session = Depends(get_db)):
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
    if source_changed:
        fragment.processing_state = "unprocessed"
        fragment.processed_at = None
    fragment.edited_version = edited_version.strip()
    fragment.notes = notes.strip()
    db.commit()
    if action == "export":
        return RedirectResponse(f"/fragments/{fragment_id}/export", status_code=303)
    return RedirectResponse(f"/fragments/{fragment_id}?saved=1", status_code=303)


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
