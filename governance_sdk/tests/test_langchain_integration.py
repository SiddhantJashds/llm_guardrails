"""SWE#1 Day1 #6: one real LangChain single-agent flow, one real tool, HIPAA
pack, full loop verified -- against the REAL governance_api (in-process, no
server needed) and a real `langchain.agents.create_agent` tool-calling loop
(docs/adr/0012). The "model" is a deterministic scripted stand-in (no API
key/network) -- what's being verified is the governance wiring, not any
particular provider's behavior.
"""
from typing import List

import pytest
from langchain.agents import create_agent
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool

from governance_sdk.governance_sdk.client import GovernanceClient
from governance_sdk.governance_sdk.integrations.langchain_callback import GovernanceCallbackHandler


class ScriptedChatModel(BaseChatModel):
    """Deterministic stand-in for a real chat model: returns the next
    pre-scripted message on each call. `bind_tools` is a no-op -- the script
    already "knows" what to call, no real tool-schema binding needed."""

    responses: List[AIMessage] = []

    def __init__(self, responses, **kwargs):
        super().__init__(**kwargs)
        object.__setattr__(self, "responses", list(responses))
        object.__setattr__(self, "_calls", [])

    @property
    def _llm_type(self) -> str:
        return "scripted-chat-model"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        self._calls.append(messages)
        return ChatResult(generations=[ChatGeneration(message=self.responses[len(self._calls) - 1])])


@tool
def lookup_patient(query: str) -> str:
    """Look up a patient record by query."""
    return "Patient John Smith, phone 555-123-4567"


@tool
def lookup_clean(query: str) -> str:
    """Look up something with no PHI in the result."""
    return "no sensitive data here"


def _make_agent(responses, tools):
    return create_agent(ScriptedChatModel(responses=responses), tools=tools)


def _identity(agent_id="lc_agent", parent_agent_id=None):
    return {"user_id": "u1", "session_id": "s1", "agent_id": agent_id, "parent_agent_id": parent_agent_id}


class _Recorder(BaseCallbackHandler):
    """Confirms the tool actually ran (or didn't) -- not just that no
    exception surfaced, since a swallowed exception looks identical to
    success from the outside (this is exactly the bug docs/adr/0012 found)."""

    def __init__(self):
        self.tool_started = False

    def on_tool_start(self, serialized, input_str, **kwargs):
        self.tool_started = True


def test_full_loop_benign_tool_call_allowed_and_clean_output_not_penalized(governance_app_client):
    client = GovernanceClient(client=governance_app_client)
    identity = _identity("benign_agent")
    handler = GovernanceCallbackHandler(identity=identity, client=client)
    recorder = _Recorder()

    agent = _make_agent(
        responses=[
            AIMessage(content="", tool_calls=[{"name": "lookup_clean", "args": {"query": "x"}, "id": "c1"}]),
            AIMessage(content="no sensitive data here"),
        ],
        tools=[lookup_clean],
    )
    result = agent.invoke({"messages": [HumanMessage(content="look up x")]}, config={"callbacks": [handler, recorder]})

    assert recorder.tool_started is True
    assert result["messages"][-1].content == "no sensitive data here"
    score = client.check_tool(identity, "sql_query_tool")
    assert score["current_score"] == 100.0


def test_full_loop_phi_in_final_answer_is_caught_and_costs_score(governance_app_client):
    client = GovernanceClient(client=governance_app_client)
    identity = _identity("phi_agent")
    handler = GovernanceCallbackHandler(identity=identity, client=client)

    agent = _make_agent(
        responses=[
            AIMessage(content="", tool_calls=[{"name": "lookup_patient", "args": {"query": "123"}, "id": "c1"}]),
            AIMessage(content="Found: Patient John Smith, phone 555-123-4567"),
        ],
        tools=[lookup_patient],
    )
    agent.invoke({"messages": [HumanMessage(content="find patient 123")]}, config={"callbacks": [handler]})

    score = client.check_tool(identity, "sql_query_tool")
    assert score["current_score"] == 80.0  # one real violation, full phi_in_output penalty


def test_full_loop_denied_tool_call_actually_stops_the_tool_from_running(governance_app_client):
    # The critical regression this guards against (docs/adr/0012): LangChain's
    # callback dispatcher silently swallows an exception raised in
    # on_tool_start UNLESS the handler sets raise_error=True. Without that,
    # the tool runs anyway and this whole governance mechanism is cosmetic.
    client = GovernanceClient(client=governance_app_client)
    identity = _identity("degraded_agent")
    for _ in range(3):  # 100 -> 80 -> 60 -> 40, below the 60.0 default threshold
        client.check_compliance(identity, "SSN: 123-45-6789", direction="outbound")
    pre_check = client.check_tool(identity, "sql_query_tool")
    assert pre_check["allowed"] is False

    ran = {"value": False}

    @tool
    def tracked_tool(query: str) -> str:
        """A tool that records whether it actually executed."""
        ran["value"] = True
        return "should never get here"

    handler = GovernanceCallbackHandler(identity=identity, client=client)
    agent = _make_agent(
        responses=[AIMessage(content="", tool_calls=[{"name": "tracked_tool", "args": {"query": "x"}, "id": "c1"}])],
        tools=[tracked_tool],
    )

    with pytest.raises(PermissionError, match="governance denied tool"):
        agent.invoke({"messages": [HumanMessage(content="do it")]}, config={"callbacks": [handler]})

    assert ran["value"] is False, "the tool executed despite a denial -- raise_error=True regressed"


def test_governance_callback_handler_sets_raise_error():
    # The one-line fix that makes the test above actually mean something --
    # pinned directly, so a future refactor can't silently drop it.
    assert GovernanceCallbackHandler.raise_error is True
