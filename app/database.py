"""Database setup for Fragments.

Local development remains deliberately simple with a project-local SQLite file.  A
managed deployment must set ``DATABASE_URL`` (or Railway's ``MYSQL_URL``) so
recordings, words, and routing reviews survive a service rebuild.
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, sessionmaker

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)


def deployment_database_url() -> str:
    configured = (os.getenv("DATABASE_URL") or os.getenv("MYSQL_URL") or "").strip()
    if not configured:
        return f"sqlite:///{DATA_DIR / 'fragments.db'}"
    # Railway supplies MySQL URLs as mysql://.  SQLAlchemy needs the explicit
    # DBAPI driver name; keep any already-explicit driver untouched.
    if configured.startswith("mysql://"):
        return f"mysql+pymysql://{configured[len('mysql://'):]}"
    return configured


DATABASE_URL = deployment_database_url()
_database = make_url(DATABASE_URL)
_engine_options: dict = {"pool_pre_ping": True}
if _database.get_backend_name() == "sqlite":
    _engine_options["connect_args"] = {"check_same_thread": False}
else:
    # Railway reconnects instances during normal deploys; recycling protects
    # long-lived web workers from keeping an already-closed MySQL connection.
    _engine_options["pool_recycle"] = 280

engine = create_engine(DATABASE_URL, **_engine_options)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass
