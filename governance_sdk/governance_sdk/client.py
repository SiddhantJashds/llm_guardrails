"""Thin HTTP client for the governance_api service.

Fail-closed by design: any network error or non-2xx response is treated as a
deny, never a silent allow (see docs/HACKATHON_PLAN.md hardening #5). This is
the only thing an integrating agent's code needs to import.
"""
import os
from typing import Optional

import httpx


class GovernanceClient:
    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: float = 2.0,
        client: Optional[httpx.Client] = None,
    ):
        self.base_url = base_url or os.getenv("GOVERNANCE_API_URL", "http://localhost:8001")
        self.timeout = timeout
        # Real usage (the default): a fresh httpx.post per call, as before --
        # zero behavior change. `client` is for tests only: pass a
        # fastapi.testclient.TestClient(governance_api_app) to exercise the
        # real FastAPI app in-process, no real socket/port needed (see
        # governance_sdk/tests/). NOT httpx.Client(transport=ASGITransport):
        # that transport is async-only and doesn't work with a sync Client
        # (confirmed -- raises AttributeError on .handle_request).
        self._client = client

    def _post(self, path: str, payload: dict) -> dict:
        try:
            if self._client is not None:
                # No `timeout=` here: TestClient (unlike a real httpx.Client)
                # warns this is deprecated on its .post() -- its own
                # construction-time timeout is enough for tests.
                resp = self._client.post(path, json=payload)
            else:
                resp = httpx.post(f"{self.base_url}{path}", json=payload, timeout=self.timeout)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as exc:
            return {"allowed": False, "verdict": "deny", "reason": f"governance_api_unreachable: {exc}"}

    def check_tool(self, identity: dict, tool_id: str) -> dict:
        return self._post("/governance/tool-check", {"identity": identity, "tool_id": tool_id})

    def check_compliance(
        self, identity: dict, text: str, direction: str, pack_id: str = "hipaa", apply_score: bool = True
    ) -> dict:
        return self._post(
            "/governance/compliance-check",
            {"identity": identity, "text": text, "direction": direction, "pack_id": pack_id, "apply_score": apply_score},
        )

    def check_handoff(self, identity: dict, output_text: str, pack_id: str = "hipaa") -> dict:
        return self._post(
            "/governance/handoff-check",
            {"identity": identity, "output_text": output_text, "pack_id": pack_id},
        )
