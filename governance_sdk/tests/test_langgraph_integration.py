"""SWE#1 Day2 #7: `@governed_node` / `wrap_graph_nodes` verified against the
installed LangGraph API (docs/adr/0012), against the REAL governance_api
(in-process, no server needed). No LLM involved -- plain Python node
functions, since what's being verified is the governance wrapping at the
node boundary, not any model's behavior.
"""
from langgraph.graph import END, START, StateGraph

from governance_sdk.governance_sdk import decorators as decorators_mod
from governance_sdk.governance_sdk.client import GovernanceClient
from governance_sdk.governance_sdk.decorators import governed_node
from governance_sdk.governance_sdk.integrations.langgraph_wrapper import wrap_graph_nodes


def _identity(agent_id, parent_agent_id=None):
    return {"user_id": "u1", "session_id": "s1", "agent_id": agent_id, "parent_agent_id": parent_agent_id}


def _use_real_client(monkeypatch, governance_app_client):
    """`governed_node`/`governed_tool` read a module-level singleton client
    (unlike GovernanceCallbackHandler, which takes one in its constructor) --
    swap it for the duration of one test, restored automatically after."""
    monkeypatch.setattr(decorators_mod, "_client", GovernanceClient(client=governance_app_client))


def test_governed_node_decorator_at_definition_time_allows_clean_output(governance_app_client, monkeypatch):
    _use_real_client(monkeypatch, governance_app_client)

    @governed_node(identity_fn=lambda state: _identity("clean_node_agent"))
    def clean_node(state: dict) -> dict:
        return {**state, "result": "nothing sensitive"}

    graph = StateGraph(dict)
    graph.add_node("n", clean_node)
    graph.add_edge(START, "n")
    graph.add_edge("n", END)

    result = graph.compile().invoke({})
    assert result["result"] == "nothing sensitive"

    client = GovernanceClient(client=governance_app_client)
    assert client.check_tool(_identity("clean_node_agent"), "sql_query_tool")["current_score"] == 100.0


def test_governed_node_decorator_at_definition_time_penalizes_a_real_leak(governance_app_client, monkeypatch):
    _use_real_client(monkeypatch, governance_app_client)

    @governed_node(identity_fn=lambda state: _identity("leaky_node_agent"))
    def leaky_node(state: dict) -> dict:
        return {**state, "result": "SSN: 123-45-6789"}

    graph = StateGraph(dict)
    graph.add_node("n", leaky_node)
    graph.add_edge(START, "n")
    graph.add_edge("n", END)

    graph.compile().invoke({})

    client = GovernanceClient(client=governance_app_client)
    assert client.check_tool(_identity("leaky_node_agent"), "sql_query_tool")["current_score"] == 80.0


def test_downstream_node_is_not_repenalized_for_carrying_an_upstream_leak(governance_app_client, monkeypatch):
    # The real bug this regression-guards (docs/adr/0012): a LangGraph node's
    # "output" is the FULL merged state, including everything prior nodes
    # already set. The original `str(output)` implementation would re-check
    # (and re-penalize) node_b for node_a's leak forever, even though node_b
    # added nothing itself.
    _use_real_client(monkeypatch, governance_app_client)

    @governed_node(identity_fn=lambda state: _identity("node_a_agent"))
    def node_a(state: dict) -> dict:
        return {**state, "leak": "SSN: 123-45-6789"}

    @governed_node(identity_fn=lambda state: _identity("node_b_agent", parent_agent_id="node_a_agent"))
    def node_b(state: dict) -> dict:
        return {**state, "clean_addition": "nothing sensitive"}  # doesn't touch `leak` at all

    graph = StateGraph(dict)
    graph.add_node("a", node_a)
    graph.add_node("b", node_b)
    graph.add_edge(START, "a")
    graph.add_edge("a", "b")
    graph.add_edge("b", END)

    result = graph.compile().invoke({})
    assert result["leak"] == "SSN: 123-45-6789"  # still carried in state, as LangGraph's merge semantics dictate

    client = GovernanceClient(client=governance_app_client)
    node_a_state = client.check_tool(_identity("node_a_agent"), "sql_query_tool")
    node_b_state = client.check_tool(_identity("node_b_agent"), "sql_query_tool")
    assert node_a_state["current_score"] == 80.0  # node_a: one real violation, penalized once
    assert node_b_state["current_score"] == 80.0  # node_b: delegation-capped at its parent's score, NOT penalized


def test_wrap_graph_nodes_retrofits_an_undecorated_node_correctly(governance_app_client, monkeypatch):
    # The actual bug found (docs/adr/0012): `.runnable` is a RunnableCallable,
    # not directly callable -- the original code assigned a plain wrapped
    # function straight to it, which breaks the moment the compiled graph
    # actually runs. Verified here against the installed langgraph version,
    # through a REAL compiled-and-invoked graph (not just a direct call).
    _use_real_client(monkeypatch, governance_app_client)

    def undecorated_node(state: dict) -> dict:
        return {**state, "leak": "SSN: 123-45-6789"}

    graph = StateGraph(dict)
    graph.add_node("n", undecorated_node)
    graph.add_edge(START, "n")
    graph.add_edge("n", END)

    wrap_graph_nodes(graph, ["n"], lambda state: _identity("retrofit_agent"))
    result = graph.compile().invoke({})
    assert result["leak"] == "SSN: 123-45-6789"

    client = GovernanceClient(client=governance_app_client)
    assert client.check_tool(_identity("retrofit_agent"), "sql_query_tool")["current_score"] == 80.0


def test_governed_node_skips_the_check_entirely_when_nothing_changed(governance_app_client, monkeypatch):
    calls = []
    real_post = GovernanceClient._post

    def spy_post(self, path, payload):
        calls.append(path)
        return real_post(self, path, payload)

    monkeypatch.setattr(GovernanceClient, "_post", spy_post)
    _use_real_client(monkeypatch, governance_app_client)

    @governed_node(identity_fn=lambda state: _identity("noop_agent"))
    def noop_node(state: dict) -> dict:
        return dict(state)  # returns an identical copy -- nothing new or changed

    graph = StateGraph(dict)
    graph.add_node("n", noop_node)
    graph.add_edge(START, "n")
    graph.add_edge("n", END)

    graph.compile().invoke({"already": "here"})
    assert calls == [], "a no-op node should not write a handoff-check receipt at all"
