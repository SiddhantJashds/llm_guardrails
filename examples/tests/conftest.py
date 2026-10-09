"""Fixtures for the examples' tests.

`demo_http` runs the REAL governance_api in-process (no socket, no API key),
seeded like `scripts/init_db.py` seeds a live one (so `sql_query_tool` has its
real 75 threshold, not the unseeded 60 fallback). Same env-var-before-import
rule and `setdefault` as the other test conftests (see governance_sdk/tests/).
"""
import os
import sys
from pathlib import Path

_EXAMPLES_DIR = Path(__file__).resolve().parents[1]
_REPO_ROOT = _EXAMPLES_DIR.parent
os.environ.setdefault("DATABASE_URL", f"sqlite:///{Path(__file__).resolve().parent / '_test_examples.db'}")
os.environ.setdefault("RECEIPT_SIGNING_SECRET", "test-signing-secret")

# examples/ isn't a package (the scripts run as `uv run examples/x.py`), so make
# its sibling modules importable the same way that run puts them on sys.path.
sys.path.insert(0, str(_EXAMPLES_DIR))
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "governance_api"))  # allow `import main` (governance_api's app)
sys.path.insert(0, str(_REPO_ROOT / "scripts"))  # allow `import init_db`

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from shared.db import Base, engine  # noqa: E402


@pytest.fixture
def demo_http():
    import init_db
    import main  # governance_api/main.py

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    init_db.main()
    return TestClient(main.app)
