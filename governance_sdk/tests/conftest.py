"""Shared fixtures for governance_sdk's integration tests.

These run the REAL governance_api FastAPI app in-process via
`fastapi.testclient.TestClient` (an httpx.Client subclass -- confirmed, see
docs/adr/0012) -- no real socket/port, no real LLM, no API key. That's the
whole point: this is what SWE#1 Day1 #6 / Day2 #7's "full loop ... verified"
actually means, repeatable in CI rather than only verified once by hand.

Same env-var-before-import ordering rule as the other test conftests (see
governance_api/tests/conftest.py and data_pipeline/tests/conftest.py) --
`setdefault`, not a plain assignment, so this can't clobber (or be clobbered
by) whichever of the three test directories' conftest happens to import
`shared.db` first in a combined `pytest` run from the repo root.
"""
import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TEST_DB_PATH = Path(__file__).resolve().parent / "_test_governance_sdk.db"
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_TEST_DB_PATH}")
os.environ.setdefault("RECEIPT_SIGNING_SECRET", "test-signing-secret")

sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "governance_api"))  # allow `import main` (governance_api's app)

import pytest
from fastapi.testclient import TestClient
from shared.db import Base, engine


@pytest.fixture(autouse=True)
def reset_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield


@pytest.fixture
def governance_app_client():
    """A TestClient for the real governance_api app -- pass this to
    `GovernanceClient(client=...)`, or wrap it in a `GovernanceClient` and
    monkeypatch it onto `decorators._client`, to point the SDK at a real
    (in-process) governance decision pipeline instead of needing a running
    `uvicorn` process. (Not `httpx.Client(transport=httpx.ASGITransport(...))`
    -- that transport is async-only, incompatible with a sync Client/the
    SDK's sync `_post`; TestClient already handles that bridging.)"""
    import main  # governance_api/main.py -- imported lazily so DATABASE_URL above is set first

    return TestClient(main.app)
