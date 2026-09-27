"""LangGraph multi-agent reference flow: an orchestrator delegating to >=2
sub-agents, each wrapped at the node boundary (docs/HACKATHON_PLAN.md
Integration Contract, option 3 -- not relying on `post_model_hook` alone).

Requires `langgraph` installed separately -- this file is a template showing
the wiring, not a ready-to-run script until that's added.
"""
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from shared.identity import new_session_id, new_agent_id
from governance_sdk.governance_sdk.decorators import governed_node

# TODO: from langgraph.graph import StateGraph

SESSION_ID = new_session_id()
ORCHESTRATOR_ID = new_agent_id("orchestrator")


def _identity_for(state, agent_id: str, parent_agent_id: str = None) -> dict:
    return {
        "user_id": state.get("user_id", "demo_user"),
        "session_id": SESSION_ID,
        "agent_id": agent_id,
        "parent_agent_id": parent_agent_id,
    }


@governed_node(identity_fn=lambda state: _identity_for(state, ORCHESTRATOR_ID))
def orchestrator_node(state: dict) -> dict:
    # TODO: real orchestration logic (route to sql_agent / drive_agent, etc.)
    return {**state, "route": "sql_agent"}


@governed_node(identity_fn=lambda state: _identity_for(state, "sql_agent", ORCHESTRATOR_ID))
def sql_agent_node(state: dict) -> dict:
    # TODO: real text-to-SQL agent logic
    return {**state, "sql_result": "SELECT user_id FROM users WHERE ..."}


@governed_node(identity_fn=lambda state: _identity_for(state, "drive_agent", ORCHESTRATOR_ID))
def drive_agent_node(state: dict) -> dict:
    # TODO: real drive-search agent logic
    return {**state, "drive_result": "found 3 matching documents"}


def build_graph():
    # TODO: wire these nodes into a real langgraph.graph.StateGraph, e.g.:
    #   graph = StateGraph(dict)
    #   graph.add_node("orchestrator", orchestrator_node)
    #   graph.add_node("sql_agent", sql_agent_node)
    #   graph.add_node("drive_agent", drive_agent_node)
    #   graph.set_entry_point("orchestrator")
    #   return graph.compile()
    pass


if __name__ == "__main__":
    build_graph()
    print("template only -- fill in the TODOs with the real LangGraph StateGraph")
