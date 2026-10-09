"""Live per-agent trust score with monotonic reduction.

Score can only decrease from a violation/anomaly signal -- never silently
reset upward without a fresh evidence trail (docs/HACKATHON_PLAN.md, core
concept: Monotonic Reduction).
"""
from typing import Optional

from sqlalchemy.orm import Session

from shared.models import AgentTrustState

from .delegation import capped_initial_score

DEFAULT_SCORE = 100.0

# TODO (Data Scientist hands this table over, see detectors/scoring/signals.py):
# signal name -> score penalty.
SIGNAL_PENALTIES = {
    "phi_in_output": 20.0,
    "phi_in_output_low_confidence": 5.0,
    "tool_out_of_scope": 15.0,
    "repeated_denied_call": 10.0,
    "prompt_injection_detected": 25.0,
}


class AuthorityEngine:
    def __init__(self, db: Session):
        self.db = db

    def get_or_create(self, agent_id: str, session_id: str, parent_agent_id: Optional[str]) -> AgentTrustState:
        state = self.db.get(AgentTrustState, (agent_id, session_id))
        if state is not None:
            return state

        initial_score = DEFAULT_SCORE
        if parent_agent_id:
            # Same-session parent only: another session's (or user's) score
            # must never cap this agent.
            parent = self.db.get(AgentTrustState, (parent_agent_id, session_id))
            if parent is not None:
                initial_score = capped_initial_score(DEFAULT_SCORE, parent.current_score)

        state = AgentTrustState(
            agent_id=agent_id,
            session_id=session_id,
            parent_agent_id=parent_agent_id,
            current_score=initial_score,
            history=[],
        )
        self.db.add(state)
        self.db.commit()
        self.db.refresh(state)
        return state

    def apply_signal(self, agent_id: str, session_id: str, signal: str) -> AgentTrustState:
        state = self.db.get(AgentTrustState, (agent_id, session_id))
        if state is None:
            raise ValueError(f"unknown agent_id: {agent_id}")
        penalty = SIGNAL_PENALTIES.get(signal, 0.0)
        state.current_score = max(0.0, state.current_score - penalty)  # monotonic: never increases here
        state.history = [*(state.history or []), {"signal": signal, "delta": -penalty}]
        self.db.commit()
        self.db.refresh(state)
        return state

    def check_threshold(self, agent_id: str, session_id: str, required_threshold: float) -> bool:
        state = self.db.get(AgentTrustState, (agent_id, session_id))
        current = state.current_score if state else DEFAULT_SCORE
        return current >= required_threshold
