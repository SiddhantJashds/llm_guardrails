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
    # CRITICAL, verified against the installed langchain-core (docs/adr/0012):
    # BaseCallbackHandler.raise_error defaults to False, and langchain_core's
    # callback dispatcher (handle_event) SWALLOWS any exception a handler
    # raises unless this is True -- it only logs a warning and the tool/LLM
    # call proceeds anyway. Without this flag, a PermissionError raised in
    # on_tool_start is cosmetic: the denial is logged, but the tool still
    # runs. This is NOT optional for a governance handler.
    raise_error = True

    def __init__(self, identity: dict, client: Optional[GovernanceClient] = None):
        self.identity = identity
        self.client = client or GovernanceClient()

    def on_tool_start(self, serialized: dict, input_str: str, **kwargs: Any) -> None:
        tool_id = serialized.get("name", "unknown_tool")
        result = self.client.check_tool(self.identity, tool_id)
        if not result.get("allowed", False):
            raise PermissionError(f"governance denied tool '{tool_id}': {result.get('reason')}")

    def on_llm_end(self, response: Any, **kwargs: Any) -> None:
        """Outbound compliance check on every LLM turn (verified against the
        installed langchain-core: `response` is an `LLMResult`-shaped object
        with `.generations: list[list[Generation]]`; each inner item exposes
        `.text`, which is `""` on a pure tool-call turn with no text content
        -- skipped below to avoid writing an empty-string receipt per hop).

        KNOWN LIMITATION (see docs/MOCKED_VS_PRODUCTION.md): unlike the proxy
        path, this callback cannot reliably rewrite the text the agent
        actually continues with -- callbacks are observers here, not an
        interception point with a safe, version-stable way to mutate
        `response` in place and have the agent loop pick up the change. A
        `block` verdict stops the run (raises, same as a tool denial); a
        `redact`/`hash` verdict is still recorded (penalty applied, receipt
        written) but the un-redacted text is NOT swapped out of what the
        agent sees next. Use the reverse proxy path for guaranteed
        redaction of what reaches the end user.
        """
        texts = [gen.text for gens in getattr(response, "generations", []) for gen in gens if gen.text.strip()]
        if not texts:
            return
        result = self.client.check_compliance(self.identity, "\n".join(texts), direction="outbound")
        if result.get("verdict") == "block":
            raise PermissionError(f"governance blocked LLM output: {result.get('violations')}")
