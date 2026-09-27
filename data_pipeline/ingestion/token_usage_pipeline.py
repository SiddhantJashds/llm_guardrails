"""Ingests per-request token usage events emitted by the proxy.

TODO (Data Engineer): call `ingest_event` from the proxy after each upstream
LLM response (the completion payload's `usage.prompt_tokens` /
`usage.completion_tokens`), either inline or via a small queue if request
volume grows past what a direct DB write can handle during the demo.
"""
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))  # allow `import shared`

from shared.db import SessionLocal
from shared.models import TokenUsageEvent


def ingest_event(user_id: str, session_id: str, agent_id: str, tokens_in: int, tokens_out: int) -> None:
    db = SessionLocal()
    try:
        db.add(
            TokenUsageEvent(
                user_id=user_id,
                session_id=session_id,
                agent_id=agent_id,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
            )
        )
        db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    # Smoke test / example usage.
    ingest_event("demo_user", "sess_demo", "agent_demo", tokens_in=120, tokens_out=340)
    print("ingested one demo token usage event")
