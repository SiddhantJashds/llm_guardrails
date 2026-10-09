"""Minimal chat-interface reference agent -- hits the reverse proxy directly,
the simplest of the four cross-team standardized use cases
(docs/HACKATHON_PLAN.md Integration Contract, option 1).

Run: `python examples/chat_interface.py` (with the proxy running -- the URL
comes from example_config.py, which follows WITH_BRIDGE in .env).
"""
import httpx

from example_config import DEFAULT_USER_ID, MODEL, PROXY_URL


def ask(message: str, user_id: str = DEFAULT_USER_ID) -> str:
    resp = httpx.post(
        PROXY_URL,
        json={"model": MODEL, "messages": [{"role": "user", "content": message}]},
        headers={"x-user-id": user_id},
        timeout=30.0,
    )
    data = resp.json()
    if "error" in data:
        return f"[blocked] {data['error']}: {data.get('violations')}"
    return data.get("choices", [{}])[0].get("message", {}).get("content", "")


if __name__ == "__main__":
    print("Chat (type 'quit' or 'exit' to stop)\n")
    while True:
        user_input = input("> ")
        if user_input.lower() in ("quit", "exit"):
            break
        response = ask(user_input)
        print(f"{response}\n")
