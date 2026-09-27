"""The "thin wrapper" integration surface: decorators, not a rewrite of the
caller's agent code (per the kickoff transcript's explicit ask).
"""
import functools
from typing import Callable

from .client import GovernanceClient

_client = GovernanceClient()


def governed_tool(tool_id: str, identity_fn: Callable[..., dict]):
    """Wrap a tool function with a pre-call authority check.

    `identity_fn(*args, **kwargs) -> dict` extracts the IdentityEnvelope from
    the wrapped call's context. Identity must come from trusted context
    (session/framework state), never from the tool's own arguments -- an
    injected `agent_id` in a tool argument must have no effect.
    """

    def decorator(fn: Callable):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            identity = identity_fn(*args, **kwargs)
            result = _client.check_tool(identity, tool_id)
            if not result.get("allowed", False):
                raise PermissionError(f"governance denied tool '{tool_id}': {result.get('reason')}")
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def governed_node(identity_fn: Callable[..., dict], pack_id: str = "hipaa"):
    """Wrap a single LangGraph node so its output is checked before the
    handoff to the next node.

    This is the concrete answer to "post_model_hook only fires at the whole-
    graph level, not per node" -- we intercept at the node boundary instead,
    so every agent-to-agent handoff is independently evaluated.
    """

    def decorator(fn: Callable):
        @functools.wraps(fn)
        def wrapper(state, *args, **kwargs):
            identity = identity_fn(state, *args, **kwargs)
            output = fn(state, *args, **kwargs)
            output_text = str(output)  # TODO: extract the actual text field(s) from `output`
            result = _client.check_handoff(identity, output_text, pack_id)
            if not result.get("allowed", False):
                raise PermissionError(f"governance blocked handoff: {result.get('reason')}")
            return output

        return wrapper

    return decorator
