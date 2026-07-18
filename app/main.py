from datetime import datetime
from pathlib import Path
import re
import shutil
import uuid

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .database import Base, SessionLocal, engine
from .models import Fragment

BASE_DIR = Path(__file__).resolve().parent.parent
AUDIO_DIR = BASE_DIR / "audio"
AUDIO_DIR.mkdir(parents=True, exist_ok=True)

Base.metadata.create_all(bind=engine)
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
    numbers = [int(m.group(1)) for code in codes if (m := re.fullmatch(r"F(\d+)", code))]
    return f"F{(max(numbers, default=0) + 1):03d}"


def fragment_markdown(fragment: Fragment) -> str:
    created = fragment.created_at.strftime("%Y-%m-%d")
    return f"""# {fragment.fragment_code} — {fragment.title}

**Date:** {created}  
**Status:** {fragment.status}  
**Themes:** {fragment.themes or '—'}  
**Cross References:** {fragment.cross_references or '—'}

---

## Original Dictation

{fragment.raw_transcript or '[Audio preserved; transcript not yet added.]'}

---

## Edited Version

{fragment.edited_version or '[Not yet edited.]'}

---

## Notes

{fragment.notes or ''}
"""


@app.get("/", response_class=HTMLResponse)
def home(request: Request, db: Session = Depends(get_db)):
    fragments = db.scalars(select(Fragment).order_by(Fragment.created_at.desc())).all()
    return templates.TemplateResponse("index.html", {"request": request, "fragments": fragments})


@app.post("/api/fragments")
def create_fragment(
    raw_transcript: str = Form(...),
    db: Session = Depends(get_db),
):
    text = raw_transcript.strip()
    if not text:
        raise HTTPException(400, "Fragment text cannot be empty")

    code = next_fragment_code(db)
    fragment = Fragment(
        fragment_code=code,
        title="Untitled fragment",
        raw_transcript=text,
        audio_path="",
        audio_mime_type="",
    )
    db.add(fragment)
    db.commit()
    db.refresh(fragment)
    return RedirectResponse(f"/fragments/{fragment.id}", status_code=303)


@app.get("/fragments/{fragment_id}", response_class=HTMLResponse)
def fragment_page(fragment_id: int, request: Request, db: Session = Depends(get_db)):
    fragment = db.get(Fragment, fragment_id)
    if not fragment:
        raise HTTPException(404, "Fragment not found")
    return templates.TemplateResponse("fragment.html", {"request": request, "fragment": fragment})


@app.post("/fragments/{fragment_id}")
def update_fragment(
    fragment_id: int,
    title: str = Form(...),
    status: str = Form("Draft"),
    themes: str = Form(""),
    cross_references: str = Form(""),
    raw_transcript: str = Form(""),
    edited_version: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    fragment = db.get(Fragment, fragment_id)
    if not fragment:
        raise HTTPException(404, "Fragment not found")
    fragment.title = title.strip() or "Untitled fragment"
    fragment.status = status.strip() or "Draft"
    fragment.themes = themes.strip()
    fragment.cross_references = cross_references.strip()
    fragment.raw_transcript = raw_transcript.strip()
    fragment.edited_version = edited_version.strip()
    fragment.notes = notes.strip()
    db.commit()
    return RedirectResponse(f"/fragments/{fragment_id}?saved=1", status_code=303)


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
    filename = re.sub(r"[^A-Za-z0-9 _-]", "", fragment.title).strip() or "Untitled"
    headers = {"Content-Disposition": f'attachment; filename="{fragment.fragment_code} - {filename}.md"'}
    return PlainTextResponse(fragment_markdown(fragment), headers=headers)


@app.get("/health")
def health(db: Session = Depends(get_db)):
    count = db.scalar(select(func.count()).select_from(Fragment))
    return {"ok": True, "fragments": count, "time": datetime.utcnow().isoformat() + "Z"}
