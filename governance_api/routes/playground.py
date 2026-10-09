"""Test-console bridge to the GuardRailBench sample apps (multi-agent,
single agent with tools, RAG chatbot).

The browser can't call the bench app directly (it serves no CORS headers and
lives in another repo we don't modify), so the dashboard's test console posts
here and this forwards server-side. The bench app's own hooks then route
every prompt, completion and tool call through bench_bridge -> this API, so
the resulting session shows up in the dashboard like any other.
"""
import os

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/playground", tags=["playground"])

# app -> (bench endpoint, name of the text field it expects)
BENCH_APPS = {
    "multi_agent": ("/run-agent", "message"),
    "single_agent": ("/run-single-agent", "message"),
    "rag": ("/ask", "question"),
}


def bench_app_url() -> str:
    return os.getenv("BENCH_APP_URL", "http://localhost:8000").rstrip("/")


class BenchRunRequest(BaseModel):
    user_id: str
    message: str


@router.get("/bench/health")
def bench_health():
    url = bench_app_url()
    try:
        resp = httpx.get(f"{url}/health", timeout=2.0)
        body = resp.json() if resp.status_code == 200 else {}
    except (httpx.HTTPError, ValueError):
        body = {}
    # The proxy also listens on :8000 in normal mode; only the bench app
    # answers /health with an edition, so that's what "available" means.
    return {"available": body.get("status") == "ok" and "edition" in body, "url": url, "edition": body.get("edition")}


@router.post("/bench/{app}")
def run_bench_app(app: str, req: BenchRunRequest):
    if app not in BENCH_APPS:
        raise HTTPException(status_code=404, detail=f"Unknown app '{app}'. Available: {', '.join(BENCH_APPS)}.")
    path, field = BENCH_APPS[app]
    url = bench_app_url()
    try:
        resp = httpx.post(f"{url}{path}", json={"user_id": req.user_id, field: req.message}, timeout=180.0)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"The GuardRailBench app is not reachable at {url} ({exc.__class__.__name__}).")
    if resp.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"The GuardRailBench app returned HTTP {resp.status_code}.")
    try:
        return resp.json()
    except ValueError:
        raise HTTPException(status_code=502, detail="The GuardRailBench app returned a response that isn't JSON.")
