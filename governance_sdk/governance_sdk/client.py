"""Thin HTTP client for the governance_api service.

Fail-closed by design: any network error or non-2xx response is treated as a
deny, never a silent allow (see docs/HACKATHON_PLAN.md hardening #5). This is
the only thing an integrating agent's code needs to import.
"""
import os
from typing import Optional

import httpx


class GovernanceClient:
    def __init__(self, base_url: Optional[str] = None, timeout: float = 2.0):
        self.base_url = base_url or os.getenv("GOVERNANCE_API_URL", "http://localhost:8001")
        self.timeout = timeout

    def _post(self, path: str, payload: dict) -> dict:
        try:
            resp = httpx.post(f"{self.base_url}{path}", json=payload, timeout=self.timeout)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as exc:
            return {"allowed": False, "verdict": "deny", "reason": f"governance_api_unreachable: {exc}"}

    def check_tool(self, identity: dict, tool_id: str) -> dict:
        return self._post("/governance/tool-check", {"identity": identity, "tool_id": tool_id})

    def check_compliance(self, identity: dict, text: str, direction: str, pack_id: str = "hipaa") -> dict:
        return self._post(
            "/governance/compliance-check",
            {"identity": identity, "text": text, "direction": direction, "pack_id": pack_id},
        )

    def check_handoff(self, identity: dict, output_text: str, pack_id: str = "hipaa") -> dict:
        return self._post(
            "/governance/handoff-check",
            {"identity": identity, "output_text": output_text, "pack_id": pack_id},
        )
