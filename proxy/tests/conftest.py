"""Fixtures for the proxy's tests: the REAL governance_api app in-process (via
ASGITransport) plus a stubbed upstream LLM -- no sockets, no API key.

`proxy/main.py` and `governance_api/main.py` are both named `main`, so the
proxy is loaded by file path under a different module name.
"""
import importlib.util
import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TEST_DB_PATH = Path(__file__).resolve().parent / "_test_proxy.db"
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_TEST_DB_PATH}")
os.environ.setdefault("RECEIPT_SIGNING_SECRET", "test-signing-secret")

sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "governance_api"))

import httpx
import pytest
from fastapi.testclient import TestClient
from shared.db import Base, engine


@pytest.fixture(autouse=True)
def reset_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield


@pytest.fixture
def proxy_client(monkeypatch):
    """Returns (TestClient for the proxy, list of bodies the stub upstream received).
    Set `upstream_reply` on the returned client's `.state` via the `reply` helper."""
    import main as governance_main  # governance_api's app

    spec = importlib.util.spec_from_file_location("proxy_main", _REPO_ROOT / "proxy" / "main.py")
    proxy_main = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(proxy_main)

    upstream_requests = []
    reply = {"content": "ok"}

    override = {}

    def upstream(request: httpx.Request) -> httpx.Response:
        import json
        if "fn" in override:
            return override["fn"](request)
        upstream_requests.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"index": 0, "message": {"role": "assistant", "content": reply["content"]}}]})

    governance_transport = httpx.ASGITransport(app=governance_main.app)
    upstream_transport = httpx.MockTransport(upstream)

    class Router(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            if request.url.host == "upstream.test":
                return await upstream_transport.handle_async_request(request)
            return await governance_transport.handle_async_request(request)

    real_client = httpx.AsyncClient
    monkeypatch.setattr(proxy_main, "UPSTREAM_LLM_BASE_URL", "http://upstream.test/v1")
    monkeypatch.setattr(proxy_main, "GOVERNANCE_API_URL", "http://governance.test")
    monkeypatch.setattr(proxy_main.httpx, "AsyncClient", lambda **kw: real_client(transport=Router(), **kw))

    client = TestClient(proxy_main.app)
    client.upstream_requests = upstream_requests
    client.upstream_reply = reply
    client.set_upstream = lambda fn: override.update(fn=fn)
    return client
