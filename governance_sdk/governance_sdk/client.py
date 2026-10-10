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
        except Exception as exc:
            # Broad on purpose (hardening #5: deny on error): this must hold
            # for transport errors from ANY httpx major (the venv has both
            # httpx 0.x and httpx2 2.x, whose error hierarchies don't overlap)
            # as well as errors the in-process TestClient re-raises, not just
            # the httpx.HTTPError real network calls produce.
            return {"allowed": False, "verdict": "deny", "reason": f"governance_api_unreachable: {exc}"}

    def check_tool(self, identity: dict, tool_id: str, tool_args: dict = None, declared_tools: list = None) -> dict:
        payload = {"identity": identity, "tool_id": tool_id}
        if tool_args is not None:
            payload["tool_args"] = tool_args  # recipient / consent / identifier checks
        if declared_tools is not None:
            payload["declared_tools"] = list(declared_tools)  # out-of-scope calls are denied
        return self._post("/governance/tool-check", payload)

    def check_compliance(
        self, identity: dict, text: str, direction: str, pack_id: str = "hipaa", apply_score: bool = True,
        restore_to_sender: bool = None, pass_sender_keys: bool = None,
    ) -> dict:
        payload = {"identity": identity, "text": text, "direction": direction, "pack_id": pack_id, "apply_score": apply_score}
        if restore_to_sender is not None:
            payload["restore_to_sender"] = restore_to_sender  # this text was typed by the end user
        if pass_sender_keys is not None:
            payload["pass_sender_keys"] = pass_sender_keys  # their own name/email/MRN reach the model
        return self._post("/governance/compliance-check", payload)

    def check_handoff(self, identity: dict, output_text: str, pack_id: str = "hipaa") -> dict:
        return self._post(
            "/governance/handoff-check",
            {"identity": identity, "output_text": output_text, "pack_id": pack_id},
        )
