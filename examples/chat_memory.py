"""Memory-enabled chat reference agent -- same proxy path as chat_interface.py,
plus conversation memory via LangGraph's built-in checkpointer
(`InMemorySaver`), so nothing is implemented from scratch.

Memory model: one LangGraph thread per conversation. `MessagesState`'s
`add_messages` reducer appends each turn to the checkpoint; every turn the
node sends the FULL history to the proxy, so governance still scans
everything and the upstream model sees prior turns.

Run: `uv run examples/chat_memory.py` (with proxy on :8000).
Caveat: `InMemorySaver` is process-local -- restart the script and the
history is gone. Production would swap in a Postgres/Redis checkpointer;
the node and REPL stay the same.
"""
import os
import uuid

import httpx
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, MessagesState, StateGraph

PROXY_URL = os.getenv("PROXY_URL", "http://localhost:8000/v1/chat/completions")
MODEL = os.getenv("CHAT_MODEL", "nvidia/Qwen3.6-35B-A3B-NVFP4")

_ROLE_MAP = {"human": "user", "ai": "assistant", "system": "system"}


def _to_openai(messages: list[BaseMessage]) -> list[dict]:
    return [
        {"role": _ROLE_MAP.get(m.type, "user"), "content": m.content}
        for m in messages
    ]


def build_chat_graph(user_id: str, session_id: str):
    """Single-node graph: chat node -> END, compiled with a checkpointer."""

    def chat_node(state: MessagesState) -> dict:
        resp = httpx.post(
            PROXY_URL,
            json={"model": MODEL, "messages": _to_openai(state["messages"])},
            headers={"x-user-id": user_id, "x-session-id": session_id},
            timeout=60.0,
        )
        data = resp.json()
        if "error" in data:  # governance block from the proxy
            return {"messages": [AIMessage(content=f"[blocked] {data['error']}: {data.get('violations')}")]}
        if "choices" not in data:  # upstream error, e.g. {"detail": ...}
            return {"messages": [AIMessage(content=f"[error] {data}")]}
        content = data["choices"][0].get("message", {}).get("content", "") or "[empty reply]"
        return {"messages": [AIMessage(content=content)]}

    graph = StateGraph(MessagesState)
    graph.add_node("chat", chat_node)
    graph.add_edge(START, "chat")
    graph.add_edge("chat", END)
    return graph.compile(checkpointer=InMemorySaver())


def main() -> None:
    user_id = input("user_id [demo_user]: ").strip() or "demo_user"
    session_id = f"sess_{uuid.uuid4().hex[:8]}"
    chat = build_chat_graph(user_id, session_id)
    config = {"configurable": {"thread_id": session_id}}
    print(f"Chat with memory (session {session_id}, type 'quit' or 'exit' to stop)\n")
    while True:
        user_input = input("> ")
        if user_input.lower() in ("quit", "exit"):
            break
        result = chat.invoke({"messages": [HumanMessage(content=user_input)]}, config)
        print(f"{result['messages'][-1].content}\n")


if __name__ == "__main__":
    main()
