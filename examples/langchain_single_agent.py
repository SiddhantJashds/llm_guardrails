"""LangChain single-agent reference flow, governed via callback handler
(docs/HACKATHON_PLAN.md Integration Contract, option 2; SWE#1 Day1 #6).

This is a REAL, runnable agent -- no API key, no network call. It uses a
deterministic `ScriptedChatModel` (a minimal `BaseChatModel` that returns
pre-scripted messages in order and implements `bind_tools` as a no-op) in
place of a real provider, since this file's job is to verify the governance
wiring against the actually-installed LangChain version, not to demo a real
model's behavior. Swap `ScriptedChatModel` for `ChatOpenAI` (or any real
chat model) to run this against a live provider -- nothing else changes.

Verified against langchain==1.4.3 / langchain-core==1.6.6 (docs/adr/0012):
the old `langchain.agents.AgentExecutor` / `create_tool_calling_agent` API
this file used to reference as a TODO no longer exists in installed
LangChain 1.x -- `langchain.agents.create_agent` (built on LangGraph
internally) replaced it. Callbacks are now passed at invoke time via
`config={"callbacks": [...]}`, not the agent constructor.

Run: `python examples/langchain_single_agent.py` from the repo root, with
`governance_api` running on :8001 (`cd governance_api && uvicorn main:app
--port 8001`) -- or see `governance_sdk/tests/test_langchain_integration.py`
for a version that runs the real governance_api in-process, no server needed.
"""
import sys
from pathlib import Path
from typing import List

sys.path.append(str(Path(__file__).resolve().parents[1]))

from shared.identity import new_session_id, new_agent_id  # noqa: E402
from governance_sdk.governance_sdk.integrations.langchain_callback import GovernanceCallbackHandler  # noqa: E402

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool
from langchain.agents import create_agent


class ScriptedChatModel(BaseChatModel):
    """Deterministic stand-in for a real chat model -- see module docstring."""

    responses: List[AIMessage] = []

    def __init__(self, responses, **kwargs):
        super().__init__(**kwargs)
        object.__setattr__(self, "responses", list(responses))
        object.__setattr__(self, "_calls", [])

    @property
    def _llm_type(self) -> str:
        return "scripted-chat-model"

    def bind_tools(self, tools, **kwargs):
        return self  # the script already "knows" what to call; no real binding needed

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        self._calls.append(messages)
        return ChatResult(generations=[ChatGeneration(message=self.responses[len(self._calls) - 1])])


@tool
def lookup_patient(query: str) -> str:
    """Look up a patient record by query."""
    # Deliberately returns PHI (phone + name), to also exercise the outbound
    # compliance check once it reaches the model's final answer below.
    return "Patient John Smith, phone 555-123-4567"


def build_governed_agent(user_id: str = "demo_user"):
    identity = {
        "user_id": user_id,
        "session_id": new_session_id(),
        "agent_id": new_agent_id("sql_agent"),
        "parent_agent_id": None,
    }
    callback = GovernanceCallbackHandler(identity=identity)

    # The scripted model's two turns: call the tool, then answer using its
    # (PHI-containing) result -- this is what `on_llm_end` catches below.
    model = ScriptedChatModel(
        responses=[
            AIMessage(content="", tool_calls=[{"name": "lookup_patient", "args": {"query": "123"}, "id": "call_1"}]),
            AIMessage(content="Found: Patient John Smith, phone 555-123-4567"),
        ]
    )
    agent = create_agent(model, tools=[lookup_patient])
    return agent, identity, callback


def run_demo() -> None:
    agent, identity, callback = build_governed_agent()
    print(f"identity: {identity}")

    result = agent.invoke(
        {"messages": [HumanMessage(content="find patient 123")]},
        config={"callbacks": [callback]},
    )
    print(f"final answer (as the agent itself saw it): {result['messages'][-1].content}")
    print(
        "note: the outbound compliance check above ran and was recorded (see "
        "governance_api's receipts for this session_id) -- but per "
        "GovernanceCallbackHandler.on_llm_end's docstring, redaction is NOT "
        "applied back onto what the agent/end-user sees via this path. Use "
        "the reverse proxy (examples/chat_interface.py) for guaranteed "
        "redaction of the final text."
    )


if __name__ == "__main__":
    run_demo()
