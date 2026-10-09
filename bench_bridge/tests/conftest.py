"""Shared fixtures for bench_bridge tests.

Same pattern as the other test conftests: env vars before imports,
throwaway SQLite file, per-test schema reset. Both FastAPI apps run
in-process via TestClient -- no sockets, no ports, no upstream LLM.

The bridge's `gov` client is rewired to the in-process governance_api app
(a TestClient injected into GovernanceClient), so hook -> governance calls
never leave the process. The bridge TestClient is used WITHOUT a context
manager, so its startup event (threshold seeding against a live :8001)
never runs here -- tests seed thresholds explicitly through the
governance app's admin API when they need non-default values.
"""
import importlib.util
import os
import sys
from pathlib import Path

_TESTS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _TESTS_DIR.parents[1]
_TEST_DB_PATH = _TESTS_DIR / "_test_bench_bridge.db"
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_TEST_DB_PATH}")
os.environ.setdefault("RECEIPT_SIGNING_SECRET", "test-signing-secret")

sys.path.insert(0, str(_REPO_ROOT))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from shared.db import Base, engine  # noqa: E402


def _load_bridge_main():
    # bench_bridge/main.py is a top-level `main` module just like
    # governance_api/main.py -- and pytest's own sys.path insertion would let
    # one shadow the other. Import both by path under unique names so module
    # resolution here is deterministic, not sys.path-order-dependent.
    spec = importlib.util.spec_from_file_location(
        "bench_bridge_main", _REPO_ROOT / "bench_bridge" / "main.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_governance_app():
    # governance_api/main.py expects to run from inside governance_api/ (its
    # sibling packages import as top-level names), so its directory must be
    # on sys.path for the exec below. Left in place afterwards on purpose:
    # it pins `import main` to the governance_api app for every other test
    # directory's lazy `from main import app` in combined runs.
    if str(_REPO_ROOT / "governance_api") not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT / "governance_api"))
    spec = importlib.util.spec_from_file_location(
        "bench_governance_main", _REPO_ROOT / "governance_api" / "main.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.app


@pytest.fixture(autouse=True)
def reset_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield


@pytest.fixture
def gov_client():
    return TestClient(_load_governance_app())


@pytest.fixture
def bridge_client(gov_client):
    from governance_sdk.governance_sdk.client import GovernanceClient  # noqa: E402

    bridge = _load_bridge_main()
    bridge.gov = GovernanceClient(client=gov_client)
    return TestClient(bridge.app)
