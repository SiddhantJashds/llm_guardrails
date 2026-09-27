# Integration Contract

This is the document handed to the other three hackathon teams (deliverable #7 in the problem statement) so their reference use cases — LangGraph multi-agent, LangChain single-agent, chat interface, RAG interface — can plug into this governance runtime. See [docs/adr/0002](adr/0002-no-post-model-hook-lock-in.md) for why this isn't built around `post_model_hook`.

## The identity envelope

Every decision this runtime makes is attributed to one of these four fields (`shared/identity.py`, `shared/schemas.py`):

```json
{
  "user_id": "caller-supplied string, no auth (docs/adr/0005)",
  "session_id": "minted by the proxy/gateway, one per conversation/run",
  "agent_id": "minted per agent instance; stable across that agent's calls within a session",
  "parent_agent_id": "set when one agent delegates to another; null for the root agent"
}
```

**Rule that matters for every integration:** these four fields are set by *your* trusted wrapper/orchestration code, never parsed out of a prompt, completion, or tool argument. An LLM's output claiming `"agent_id": "supervisor_agent"` must have zero effect on the real envelope — see the hardening section in [docs/HACKATHON_PLAN.md](../HACKATHON_PLAN.md). If your framework doesn't give you a natural place to construct this envelope, `governance_sdk`'s helpers (`shared.identity.new_session_id()` / `new_agent_id()`) will mint IDs for you.

## Three attachment points — pick the one that matches your framework

### 1. Single LLM call (chat interface, RAG interface)

Point your OpenAI-compatible client's `base_url` at the proxy instead of the real provider:

```python
import httpx

resp = httpx.post(
    "http://<proxy-host>:8000/v1/chat/completions",
    json={"model": "gpt-4o-mini", "messages": [...]},
    headers={
        "x-user-id": user_id,          # required
        "x-session-id": session_id,    # optional; minted if omitted
        "x-agent-id": agent_id,        # optional; minted if omitted
        "x-request-unredacted": "false",  # optional; see docs/adr/0003
    },
)
```

That's the entire integration — inbound/outbound compliance checks happen inside the proxy. See `examples/chat_interface.py` and `examples/rag_interface.py`.

For RAG specifically: retrieved document text is just more untrusted input. Concatenate it into the prompt as usual and send the whole thing through the proxy exactly like a chat message — the inbound check treats it identically, and a leaked PHI/PII identifier from a retrieved document gets caught the same way a user-typed one would.

### 2. LangChain single-agent

Register `GovernanceCallbackHandler` (`governance_sdk/governance_sdk/integrations/langchain_callback.py`) on your agent executor:

```python
from governance_sdk.governance_sdk.integrations.langchain_callback import GovernanceCallbackHandler

identity = {"user_id": user_id, "session_id": session_id, "agent_id": agent_id, "parent_agent_id": None}
callback = GovernanceCallbackHandler(identity=identity)

agent_executor = AgentExecutor(agent=agent, tools=tools, callbacks=[callback])
```

Every `on_tool_start` triggers a `/governance/tool-check` before the tool actually runs; a denial raises `PermissionError` before the tool executes. See `examples/langchain_single_agent.py`.

### 3. LangGraph multi-agent

Wrap each node with `@governed_node` (`governance_sdk/governance_sdk/decorators.py`) rather than relying on the graph-level `post_model_hook`:

```python
from governance_sdk.governance_sdk.decorators import governed_node

def identity_fn(state):
    return {"user_id": state["user_id"], "session_id": session_id, "agent_id": "sql_agent", "parent_agent_id": "orchestrator"}

@governed_node(identity_fn=identity_fn, pack_id="hipaa")
def sql_agent_node(state: dict) -> dict:
    ...
```

Each node's output is checked via `/governance/handoff-check` before the graph moves to the next node — this is what makes "every agent-to-agent handoff independently evaluated" (objective #4) actually true regardless of what graph-level hooks your LangGraph version exposes. See `examples/langgraph_multi_agent.py`.

For tool calls *inside* a node (not the node-to-node handoff itself), wrap the tool function with `@governed_tool(tool_id, identity_fn)` the same way as the LangChain path.

## What you get back

Every `/governance/*` call returns a `receipt_id` — the hash-chained, signed audit record (`governance_api/receipts/writer.py`). You don't need to do anything with it; it's already written. If you want to show it in your own UI, `GET /dashboard/session/{session_id}` returns the full per-agent breakdown.

## Fail-closed

If the governance API is unreachable, slow, or errors, every integration path here denies/blocks rather than silently allowing the call through (`governance_sdk`'s `GovernanceClient._post`, the proxy's `_fail_closed`). Don't build retry-and-allow logic on top of this — a failure here is supposed to stop the action, not degrade gracefully into an unguarded one.
