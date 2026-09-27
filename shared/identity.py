"""The identity envelope: user_id -> session_id -> agent_id -> parent_agent_id.

Set ONLY by trusted wrapper/proxy code, never parsed out of prompt or
completion text. This is what stops an agent from spoofing its own identity
or authority via prompt injection (see docs/HACKATHON_PLAN.md, hardening #2).
"""
import uuid
from dataclasses import dataclass, asdict
from typing import Optional


@dataclass(frozen=True)
class IdentityEnvelope:
    user_id: str
    session_id: str
    agent_id: str
    parent_agent_id: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


def new_session_id() -> str:
    return f"sess_{uuid.uuid4().hex[:12]}"


def new_agent_id(prefix: str = "agent") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"
