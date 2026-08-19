# Fragments web app

A phone-first voice capture app that preserves the original recording before any editing.

## What it does

- One large **red** microphone button: tap once to record, then tap the **black Stop** button once to finish. There is no press-and-hold mode.
- Saves the finished original audio before requesting a transcript. The microphone and the optional browser preview stop immediately when Stop is tapped.
- Transcribes the saved finished recording on the server with OpenAI’s `gpt-4o-transcribe` by default. Browser recognition is only a rough on-screen preview and is never saved as the authoritative transcript.
- Keeps **what was heard** (the original transcript) separate from **what it might mean** (a review-only interpretation draft).
- Keeps original dictation and edited version in separate SQL fields.
- Classifies material as Permanent, Reference, Transient, or Unclassified. Permanent wins for mixed story-and-action material and is never eligible for automatic cleanup.
- Splits one spoken Fragment into multiple reviewable possible routes—Daybook reminder, Run & Maintain, Shitlist, Decisions, or Fieldbook—without writing anything into those surfaces automatically.
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

- `data/fragments.db` (or the independently managed SQL database used in production)
- `audio/`

Do not deploy without a durable volume or object storage for `audio/`. The database only points to each recording; it is not a substitute for the original file.

## Database

The starter uses SQLite, which is a real SQL database and is enough for one author. For hosted multi-device use, replace `DATABASE_URL` in `app/database.py` with PostgreSQL and add its driver.

## Preservation rule

The audio is saved as a separate file. The database points to it. Editing a transcript never modifies or deletes the recording.

## Server-only transcription setup

Set these environment variables on the hosted Fragments service. **Never put the key in browser JavaScript, source files, or a PWA manifest.**

```text
OPENAI_API_KEY=...
TRANSCRIPTION_PROVIDER=openai
OPENAI_TRANSCRIPTION_MODEL=gpt-4o-transcribe
```

`TRANSCRIPTION_PROVIDER` exists so a different server-side provider can be added later without changing the capture screen or the stored Fragment format. Until a key is configured, a recording is still saved safely and the owner can type the words; transcription simply reports that it is not ready.

## Review and routing safety

The interpretation endpoint is intentionally local and review-only. It preserves the original text, keeps normalised clauses separate, suggests multiple possible routes, gives one short clarification when an important detail is uncertain, and records accept/change/reject choices. It does **not** create a task, reminder, decision, or external record. Future cross-surface actions must remain explicit, owner-reviewed steps.
