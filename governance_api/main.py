"""governance_api: authority engine + compliance engine + receipts + REST API.

Run: `uvicorn main:app --port 8001` from inside this directory (routes/ and
authority/compliance/receipts import each other as top-level packages, so run
from here rather than the repo root).
"""
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

sys.path.append(str(Path(__file__).resolve().parents[1]))  # allow `import shared`
from shared.db import Base, engine  # noqa: E402

from detectors import ner  # noqa: E402
from routes import governance, dashboard, admin  # noqa: E402

Base.metadata.create_all(bind=engine)
ner.load_model()  # fail-closed: refuse to start without the NER model (or GUARDRAILS_NER_DISABLED=1)

app = FastAPI(title="governance-api")

# The dashboard (dashboard/*.html, served from a different port) fetches this
# API directly from the browser -- that's a cross-origin request, and without
# this middleware the browser blocks it by default (curl/httpx smoke tests
# never catch this, only a real browser enforces CORS). Wildcard is fine here
# specifically because there's no session cookie/auth to leak (see
# docs/adr/0005-user-identity-no-auth.md) -- a production deployment with real
# auth should restrict this to the dashboard's actual origin instead.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(governance.router)
app.include_router(dashboard.router)
app.include_router(admin.router)


@app.get("/healthz")
def healthz():
    return {"status": "ok"}
