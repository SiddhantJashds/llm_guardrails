"""Read-only dashboard API: per-agent breakdown for a session, plus the
per-user profile view. The dashboard/ frontend calls these directly.
"""
import sys
from pathlib import Path

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

sys.path.append(str(Path(__file__).resolve().parents[2]))  # allow `import shared`
from shared.db import get_db  # noqa: E402
from shared.models import Receipt, AgentTrustState, UserProfile  # noqa: E402

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/session/{session_id}")
def session_dashboard(session_id: str, db: Session = Depends(get_db)):
    receipts = db.query(Receipt).filter(Receipt.session_id == session_id).order_by(Receipt.timestamp).all()
    agents = db.query(AgentTrustState).filter(AgentTrustState.session_id == session_id).all()

    by_agent: dict = {}
    for agent in agents:
        by_agent[agent.agent_id] = {
            "agent_id": agent.agent_id,
            "current_score": agent.current_score,
            "history": agent.history,
            "violations": [],
            "denied_calls": [],
        }

    for r in receipts:
        bucket = by_agent.setdefault(
            r.agent_id,
            {"agent_id": r.agent_id, "current_score": None, "history": [], "violations": [], "denied_calls": []},
        )
        if r.decision_type == "compliance" and r.verdict != "allow":
            bucket["violations"].append({"reason": r.reason, "timestamp": r.timestamp.isoformat(), "receipt_id": r.receipt_id})
        if r.decision_type == "authority" and r.verdict == "deny":
            bucket["denied_calls"].append({"reason": r.reason, "timestamp": r.timestamp.isoformat(), "receipt_id": r.receipt_id})

    return {"session_id": session_id, "agents": list(by_agent.values())}


@router.get("/user/{user_id}")
def user_dashboard(user_id: str, db: Session = Depends(get_db)):
    # Server-side filter by user_id -- never trust a client-supplied override
    # (docs/HACKATHON_PLAN.md hardening #8).
    profile = db.get(UserProfile, user_id)
    receipts = db.query(Receipt).filter(Receipt.user_id == user_id).order_by(Receipt.timestamp).all()

    return {
        "user_id": user_id,
        "profile": {
            "total_tokens_in": profile.total_tokens_in if profile else 0,
            "total_tokens_out": profile.total_tokens_out if profile else 0,
            "composite_rating": profile.composite_rating if profile else None,
            "effective_use_score": profile.effective_use_score if profile else None,
            "violation_count": profile.violation_count if profile else 0,
        },
        "recent_decisions": [
            {"verdict": r.verdict, "decision_type": r.decision_type, "timestamp": r.timestamp.isoformat(), "reason": r.reason}
            for r in receipts[-50:]
        ],
    }
