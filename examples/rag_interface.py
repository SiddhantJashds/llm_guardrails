"""Minimal RAG reference agent -- retrieves context, then routes the final
completion through the reverse proxy so retrieved-document PHI/PII is caught
on the way out, same as any other completion.

TODO: replace `fake_retrieve` with a real vector store lookup.
"""

import httpx

from example_config import DEFAULT_USER_ID, MODEL, PROXY_URL


def fake_retrieve(query: str) -> str:
    # TODO (whoever builds this reference use case): wire to a real retriever.
    return "Patient record: John Doe, phone 555-123-4567, last visit 2026-01-10."


def ask(query: str, user_id: str = DEFAULT_USER_ID) -> str:
    context = fake_retrieve(query)
    prompt = f"Context:\n{context}\n\nQuestion: {query}"

    resp = httpx.post(
        PROXY_URL,
        json={
            "model": MODEL,
            "messages": [{"role": "user", "content": prompt}],
        },
        headers={"x-user-id": user_id},
        timeout=30.0,
    )
    data = resp.json()
    if "error" in data:
        return f"[blocked] {data['error']}: {data.get('violations')}"
    return data.get("choices", [{}])[0].get("message", {}).get("content", "")


if __name__ == "__main__":
    print(ask("When was the patient's last visit?"))
