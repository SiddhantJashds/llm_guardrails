"""Shared test fixtures for data_pipeline.

Points DATABASE_URL at a throwaway SQLite file BEFORE anything that imports
`shared.db` (directly or via user_profile_job.py) gets imported -- same
reasoning as governance_api/tests/conftest.py. `shared.db`'s engine is a
process-global singleton bound at first import, so whichever test directory
collects first in a combined `pytest` run from the repo root determines the
actual file in use for BOTH directories for that run -- harmless either way,
since every test here (like governance_api's) resets the schema itself via
the autouse `reset_db` fixture below, so no test depends on which file won.
"""
import os
import sys
from pathlib import Path

_TEST_DB_PATH = Path(__file__).resolve().parent / "_test_data_pipeline.db"
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_TEST_DB_PATH}")

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))  # allow `import shared`
sys.path.insert(0, str(_REPO_ROOT / "data_pipeline" / "aggregation"))  # allow `import user_profile_job`

import pytest
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
