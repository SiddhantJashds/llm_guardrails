"""LangGraph multi-agent reference flow: an orchestrator delegating to 2
sub-agents, each wrapped at the node boundary (docs/HACKATHON_PLAN.md
Integration Contract, option 3 -- not relying on `post_model_hook` alone;
SWE#1 Day2 #7).

A REAL, runnable graph -- no LLM, no API key needed. Nodes here are plain
deterministic Python (a text-to-SQL agent and a drive-search agent would
normally call a real LLM/tool internally; that's orthogonal to what this
file verifies, which is the governance wrapping at the node boundary).

Verified against langgraph==1.2.12 (docs/adr/0012). Two wrapping styles are
both exercised below, since both are real usage patterns:
  1. `@governed_node` applied directly at node-definition time (the pattern
     already used here) -- the straightforward case, works with zero
     langgraph-internals knowledge needed.
  2. `wrap_graph_nodes` retrofitting an UNDECORATED node after the graph is
     already built (e.g. a graph handed to you by another team you don't
     want to -- or can't -- edit the source of) -- this is the path that
     had the actual bug: `graph.nodes[name].runnable` is a `RunnableCallable`
     wrapping the real function at `.runnable.func`, not directly callable
     itself. See governance_sdk/governance_sdk/integrations/langgraph_wrapper.py.

Run: `python examples/langgraph_multi_agent.py` from the repo root, with
`governance_api` running on :8001 -- or see
`governance_sdk/tests/test_langgraph_integration.py` for a version that runs
the real governance_api in-process, no server needed.
"""
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from shared.identity import new_session_id, new_agent_id  # noqa: E402
from governance_sdk.governance_sdk.decorators import governed_node  # noqa: E402
from governance_sdk.governance_sdk.integrations.langgraph_wrapper import wrap_graph_nodes  # noqa: E402

from langgraph.graph import StateGraph, START, END

SESSION_ID = new_session_id()
ORCHESTRATOR_ID = new_agent_id("orchestrator")
SQL_AGENT_ID = new_agent_id("sql_agent")
DRIVE_AGENT_ID = new_agent_id("drive_agent")


def _identity_for(agent_id: str, parent_agent_id: str = None, user_id: str = "demo_user") -> dict:
    return {"user_id": user_id, "session_id": SESSION_ID, "agent_id": agent_id, "parent_agent_id": parent_agent_id}


@governed_node(identity_fn=lambda state: _identity_for(ORCHESTRATOR_ID))
def orchestrator_node(state: dict) -> dict:
    return {**state, "route": "sql_agent"}


@governed_node(identity_fn=lambda state: _identity_for(SQL_AGENT_ID, ORCHESTRATOR_ID))
def sql_agent_node(state: dict) -> dict:
    # Deliberately "leaks" PHI in its result, to exercise the handoff check
    # below -- the next node (drive_agent) receives this agent's OUTPUT as
    # its input, same as a real multi-agent pipeline.
    return {**state, "sql_result": "Patient SSN on file: 123-45-6789"}


def drive_agent_node_undecorated(state: dict) -> dict:
    """Deliberately left undecorated here, to demonstrate the RETROFIT path
    (`wrap_graph_nodes`) below instead of `@governed_node` at definition
    time -- as if this node came from code you don't control."""
    return {**state, "drive_result": "found 3 matching documents"}


def build_graph():
    graph = StateGraph(dict)
    graph.add_node("orchestrator", orchestrator_node)
    graph.add_node("sql_agent", sql_agent_node)
    graph.add_node("drive_agent", drive_agent_node_undecorated)
    graph.add_edge(START, "orchestrator")
    graph.add_edge("orchestrator", "sql_agent")
    graph.add_edge("sql_agent", "drive_agent")
    graph.add_edge("drive_agent", END)

    # Retrofit governance onto the one node that wasn't decorated at
    # definition time -- this is the path that needed the .runnable.func fix.
    wrap_graph_nodes(graph, ["drive_agent"], lambda state: _identity_for(DRIVE_AGENT_ID, SQL_AGENT_ID))

    return graph.compile()


def run_demo() -> None:
    compiled = build_graph()
    print(f"session_id: {SESSION_ID}")
    try:
        result = compiled.invoke({"user_id": "demo_user"})
    except PermissionError as e:
        print(f"[denied] {e}")
        print(
            "note: sql_agent's PHI leak above was caught by its handoff-check "
            "(costing its authority score) -- check governance_api's "
            "/dashboard/session/{session_id} for the per-agent breakdown."
        )
        return
    print(f"final state: {result}")
    print(
        "note: sql_agent's PHI leak above was caught by its handoff-check "
        "(costing its authority score) -- check governance_api's "
        "/dashboard/session/{session_id} for the per-agent breakdown."
    )


if __name__ == "__main__":
    run_demo()
