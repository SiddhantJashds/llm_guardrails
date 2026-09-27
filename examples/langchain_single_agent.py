"""LangChain single-agent reference flow, governed via callback handler
(docs/HACKATHON_PLAN.md Integration Contract, option 2).

Requires `langchain` + `langchain-openai` installed separately -- this file
is a template showing the wiring, not a ready-to-run script until those are
added to a requirements file for this example.
"""
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from shared.identity import new_session_id, new_agent_id
from governance_sdk.governance_sdk.integrations.langchain_callback import GovernanceCallbackHandler

# TODO: from langchain.agents import AgentExecutor, create_tool_calling_agent
# TODO: from langchain_openai import ChatOpenAI


def build_governed_agent(user_id: str = "demo_user"):
    identity = {
        "user_id": user_id,
        "session_id": new_session_id(),
        "agent_id": new_agent_id("sql_agent"),
        "parent_agent_id": None,
    }
    callback = GovernanceCallbackHandler(identity=identity)

    # TODO: wire `callback` into the real AgentExecutor, e.g.:
    #   llm = ChatOpenAI(model="gpt-4o-mini")
    #   agent = create_tool_calling_agent(llm, tools=[...], prompt=...)
    #   return AgentExecutor(agent=agent, tools=[...], callbacks=[callback])
    return callback


if __name__ == "__main__":
    build_governed_agent()
    print("template only -- fill in the TODOs with the real LangChain agent")
