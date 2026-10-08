"""Minimal chat-interface reference agent -- hits the reverse proxy directly,
the simplest of the four cross-team standardized use cases
(docs/HACKATHON_PLAN.md Integration Contract, option 1).

Run: `python examples/chat_interface.py` (with proxy/main.py running on :8000).
"""
import os

import httpx

PROXY_URL = os.getenv("PROXY_URL", "http://localhost:8000/v1/chat/completions")


def ask(message: str, user_id: str = "demo_user") -> str:
    resp = httpx.post(
        PROXY_URL,
        json={"model": "nvidia/Qwen3.6-35B-A3B-NVFP4", "messages": [{"role": "user", "content": message}]},
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
