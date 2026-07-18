# Fragments web app

A phone-first voice capture app that preserves the original recording before any editing.

## What it does

- One large microphone button: tap to record, tap again to save.
- Stores the original audio file permanently.
- Stores a raw browser-generated transcript when supported.
- Keeps original dictation and edited version in separate SQL fields.
- Assigns sequential fragment IDs (`F001`, `F002`, ...).
- Supports title, status, themes, cross-references and notes.
- Exports each fragment as Markdown.
- Installable as a simple PWA from a phone browser.

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000`.

## Phone use

Microphone recording requires HTTPS except on localhost. For actual phone use, deploy this app behind HTTPS on a service such as Render, Railway, Fly.io or a small VPS. Persistent storage must include both:

- `data/fragments.db`
- `audio/`

## Database

The starter uses SQLite, which is a real SQL database and is enough for one author. For hosted multi-device use, replace `DATABASE_URL` in `app/database.py` with PostgreSQL and add its driver.

## Preservation rule

The audio is saved as a separate file. The database points to it. Editing a transcript never modifies or deletes the recording.

## Important limitation

Live transcription uses the browser's Speech Recognition API when available. The audio is still preserved when transcription is unavailable or inaccurate. A server-side transcription provider can be added later without changing the data model.
