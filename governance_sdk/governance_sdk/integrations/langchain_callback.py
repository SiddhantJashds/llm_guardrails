"""LangChain callback handler that calls the governance API on every tool call.

Gives per-tool-call granularity natively (LangChain single-agent path from
docs/HACKATHON_PLAN.md's Integration Contract, option 2). Requires
`langchain-core` in the integrating project; not a hard dependency of
governance-sdk itself.
"""
from typing import Any, Optional

from ..client import GovernanceClient

try:
    from langchain_core.callbacks import BaseCallbackHandler
except ImportError:  # pragma: no cover - integration-only dependency
    BaseCallbackHandler = object  # type: ignore


class GovernanceCallbackHandler(BaseCallbackHandler):
    def __init__(self, identity: dict, client: Optional[GovernanceClient] = None):
        self.identity = identity
        self.client = client or GovernanceClient()

    def on_tool_start(self, serialized: dict, input_str: str, **kwargs: Any) -> None:
        tool_id = serialized.get("name", "unknown_tool")
        result = self.client.check_tool(self.identity, tool_id)
        if not result.get("allowed", False):
            raise PermissionError(f"governance denied tool '{tool_id}': {result.get('reason')}")

    def on_llm_end(self, response: Any, **kwargs: Any) -> None:
        # TODO: extract completion text from `response` and run an outbound
        # compliance check via self.client.check_compliance(...).
        pass
