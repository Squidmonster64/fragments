import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.main import app, get_db
from app.models import Fragment


@pytest.fixture
def auth_app(monkeypatch, tmp_path):
    monkeypatch.setenv("FRAGMENTS_AUTH_PASSPHRASE", "a long test-only private passphrase")
    monkeypatch.setenv("FRAGMENTS_COOKIE_SECURE", "false")
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(engine)

    def test_db():
        with TestingSession() as db:
            yield db

    app.dependency_overrides[get_db] = test_db
    with TestClient(app) as client:
        yield client, TestingSession
    app.dependency_overrides.clear()
    engine.dispose()


def add_fragment(Session, **overrides):
    with Session() as db:
        count = len(db.scalars(select(Fragment.id)).all())
        values = {
            "fragment_code": f"F{count + 1:03d}",
            "title": "Private fragment",
            "raw_transcript": "private words",
            "edited_version": "private words",
            "audio_path": "private.webm",
            "audio_mime_type": "audio/webm",
            "audio_data": b"private audio",
        }
        values.update(overrides)
        fragment = Fragment(**values)
        db.add(fragment)
        db.commit()
        db.refresh(fragment)
        return fragment.id


@pytest.mark.parametrize(
    ("method", "path", "kwargs", "expected"),
    [
        ("get", "/", {}, 303),
        ("get", "/fragments/1", {}, 303),
        ("get", "/api/fragments/1/retention", {}, 401),
        ("post", "/api/fragments", {"data": {"raw_transcript": "secret"}}, 401),
        ("post", "/fragments/1", {"data": {"title": "changed"}}, 303),
        ("post", "/api/fragments/1/transcribe", {}, 401),
        ("post", "/api/fragments/1/interpret", {}, 401),
        ("post", "/api/fragments/1/routing-review", {"json": {}}, 401),
        ("post", "/api/fragments/1/immediate-actions/action-1/undo", {}, 401),
        ("post", "/api/fragments/1/learned-rules/rule-1/revoke", {}, 401),
        ("post", "/api/fragments/1/action-links", {"json": {}}, 401),
        ("post", "/api/fragments/1/action-links/item-1/complete", {}, 401),
        ("delete", "/api/fragments/1/action-links/item-1", {}, 401),
        ("post", "/fragments/1/handoff", {}, 303),
        ("post", "/fragments/1/processing", {"data": {"processing_state": "processed"}}, 303),
        ("get", "/audio/1", {}, 303),
        ("get", "/fragments/1/export", {}, 303),
        ("get", "/export/backup", {}, 303),
        ("get", "/export/markdown", {}, 303),
        (
            "post",
            "/import/backup",
            {"files": {"backup": ("backup.json", b"{}", "application/json")}},
            303,
        ),
        ("post", "/fragments/1/delete", {}, 303),
        ("post", "/api/fragments/cleanup-eligible", {}, 401),
    ],
)
def test_anonymous_sensitive_routes_are_denied(auth_app, method, path, kwargs, expected):
    client, _ = auth_app
    response = getattr(client, method)(path, follow_redirects=False, **kwargs)
    assert response.status_code == expected
    assert response.headers["cache-control"] == "no-store"
    if path.startswith("/api/"):
        assert response.json() == {"detail": "Authentication required."}


def test_health_login_and_static_assets_remain_public_without_disclosure(auth_app):
    client, _ = auth_app
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json() == {"ok": True}
    assert client.get("/auth/login").status_code == 200
    assert client.get("/static/style.css").status_code == 200


def test_missing_server_passphrase_fails_closed(auth_app, monkeypatch):
    client, _ = auth_app
    monkeypatch.delenv("FRAGMENTS_AUTH_PASSPHRASE")
    assert client.get("/", follow_redirects=False).status_code == 303
    response = client.post(
        "/auth/login",
        data={"passphrase": "anything", "next": "/"},
        follow_redirects=False,
    )
    assert response.status_code == 503
    assert "anything" not in response.text


def test_authenticated_reads_writes_audio_exports_import_delete_and_cleanup_work(auth_app):
    client, Session = auth_app
    private_id = add_fragment(Session)
    cleanup_id = add_fragment(
        Session,
        title="Expired transient",
        memory_class="transient",
        linked_actions_json=json.dumps(
            [
                {
                    "target_app": "Run & Maintain",
                    "target_type": "job",
                    "target_id": "done-1",
                    "label": "Done job",
                    "state": "completed",
                    "completed_at": (
                        datetime.now(timezone.utc) - timedelta(days=31)
                    ).isoformat(),
                }
            ]
        ),
    )

    rejected = client.post(
        "/auth/login",
        data={"passphrase": "wrong", "next": "/"},
        follow_redirects=False,
    )
    assert rejected.status_code == 401
    assert "wrong" not in rejected.text

    login = client.post(
        "/auth/login",
        data={"passphrase": "a long test-only private passphrase", "next": "/"},
        follow_redirects=False,
    )
    assert login.status_code == 303
    cookie = login.headers["set-cookie"]
    assert "HttpOnly" in cookie
    assert "SameSite=strict" in cookie

    assert client.get("/").status_code == 200
    assert client.get(f"/fragments/{private_id}").status_code == 200
    assert client.get(f"/audio/{private_id}").content == b"private audio"
    assert client.get(f"/fragments/{private_id}/export").status_code == 200
    assert client.get("/export/backup").status_code == 200
    assert client.get("/export/markdown").status_code == 200

    created = client.post(
        "/api/fragments",
        data={"title": "Authenticated", "raw_transcript": "owner words"},
        follow_redirects=False,
    )
    assert created.status_code == 303

    backup = {
        "schema": "bloody-daves/fragments-backup/v1",
        "fragments": [{"title": "Imported", "raw_transcript": "restored words"}],
    }
    imported = client.post(
        "/import/backup",
        files={
            "backup": (
                "backup.json",
                json.dumps(backup).encode(),
                "application/json",
            )
        },
        follow_redirects=False,
    )
    assert imported.status_code == 303

    cleaned = client.post("/api/fragments/cleanup-eligible")
    assert cleaned.status_code == 200
    assert cleaned.json()["removed"] == ["F002"]
    with Session() as db:
        assert db.get(Fragment, cleanup_id) is None

    deleted = client.post(
        f"/fragments/{private_id}/delete", follow_redirects=False
    )
    assert deleted.status_code == 303
    with Session() as db:
        assert db.get(Fragment, private_id) is None
