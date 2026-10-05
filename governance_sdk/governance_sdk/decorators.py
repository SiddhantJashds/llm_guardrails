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


def _new_or_changed_text(state, output) -> str:
    """Stringify only what THIS node actually added/changed, not state
    carried over from upstream nodes.

    LangGraph nodes conventionally return a partial update that gets merged
    into cumulative state (`{**state, "my_field": ...}` is the idiom used
    throughout this repo's own examples) -- so `output` almost always still
    contains every key prior nodes set. Stringifying the whole thing (the
    original, literal `str(output)`) means once ANY node leaks PHI into
    state, every node downstream of it gets re-penalized forever for a leak
    it didn't cause and has no way to avoid -- confirmed by actually running
    a 3-node graph (docs/adr/0012): the 3rd node's own output had no PHI at
    all, yet it still took the same -20 hit the 2nd node already took, for
    carrying the 2nd node's leaked SSN forward in `state`.

    Falls back to `str(output)` whole-cloth for a non-dict state/output
    shape (e.g. a plain string node) -- the diffing only applies when both
    sides are dicts to compare key-by-key.
    """
    if isinstance(output, dict) and isinstance(state, dict):
        changed = {k: v for k, v in output.items() if state.get(k) != v}
        return str(changed) if changed else ""
    return str(output)


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
            output_text = _new_or_changed_text(state, output)
            if not output_text:
                return output  # this node changed nothing -- nothing new to evaluate
            result = _client.check_handoff(identity, output_text, pack_id)
            if not result.get("allowed", False):
                raise PermissionError(f"governance blocked handoff: {result.get('reason')}")
            return output

        return wrapper

    return decorator
