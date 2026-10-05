"""Shared test fixtures for governance_api.

Points DATABASE_URL at a throwaway SQLite file BEFORE anything under
governance_api/ or shared/ gets imported -- shared/db.py reads that env var
at import time, so this has to happen first, at module scope, before the
`from main import app` below.

Uses `setdefault`, not a plain assignment: `shared.db`'s engine is a
process-global singleton bound at first import, so in a combined `pytest`
run from the repo root (now also collecting data_pipeline/tests), whichever
test directory's conftest runs first wins for the WHOLE run -- harmless
either way (every test here resets the schema itself, see `reset_db` below),
but `setdefault` keeps this file from clobbering a value data_pipeline/tests'
conftest already set, and vice versa, so neither ordering can break the other.
"""
import os
import sys
from pathlib import Path

_TEST_DB_PATH = Path(__file__).resolve().parent / "_test_governance.db"
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_TEST_DB_PATH}")
os.environ.setdefault("RECEIPT_SIGNING_SECRET", "test-signing-secret")

# Mirrors the sys.path setup main.py/routes/*.py do themselves (they assume
# being run via `cd governance_api && uvicorn main:app`) so `import main`,
# `import authority...` etc. resolve the same way here as in production.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # governance_api/
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root

import pytest
from fastapi.testclient import TestClient

from shared.db import Base, SessionLocal, engine


@pytest.fixture(autouse=True)
def reset_db():
    """Every test starts against empty tables -- tests must not depend on
    ordering or leak state into each other."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield


@pytest.fixture
def db_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client():
    from main import app  # imported lazily so the env vars above are set first

    return TestClient(app)


def make_identity(user_id="u1", session_id="sess1", agent_id="agent1", parent_agent_id=None):
    return {"user_id": user_id, "session_id": session_id, "agent_id": agent_id, "parent_agent_id": parent_agent_id}
