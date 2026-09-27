"""Single shared DB connection used by both the proxy and governance_api.

Defaults to a local SQLite file so the team can run everything with zero
external setup; set DATABASE_URL to point at Postgres for anything beyond a
laptop demo (see docker-compose.yml).
"""
import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# Anchored to the repo root (parent of this `shared/` dir), not the process's
# cwd -- proxy/ and governance_api/ are each run with `cd <service> && uvicorn
# ...`, so a cwd-relative default would silently give every service its own
# separate SQLite file.
_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_SQLITE_PATH = _REPO_ROOT / "governance.db"

DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{_DEFAULT_SQLITE_PATH}")

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """FastAPI dependency: yields a request-scoped session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
