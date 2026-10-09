"""Read-only dashboard API: per-agent breakdown for a session, plus the
per-user profile view. The dashboard/ frontend calls these directly.
"""
import sys
from pathlib import Path

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

sys.path.append(str(Path(__file__).resolve().parents[2]))  # allow `import shared`
from shared.db import get_db  # noqa: E402
from shared.models import Receipt, AgentTrustState, UserProfile, TokenUsageEvent  # noqa: E402

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
    usage_events = (
        db.query(TokenUsageEvent).filter(TokenUsageEvent.user_id == user_id).order_by(TokenUsageEvent.timestamp).all()
    )

    return {
        "user_id": user_id,
        "profile": {
            # Token totals come straight from the raw events, not UserProfile:
            # that table is only refreshed when user_profile_job.py runs, which
            # is manual, so the live-polling dashboard would sit at 0 until then.
            "total_tokens_in": sum(e.tokens_in or 0 for e in usage_events),
            "total_tokens_out": sum(e.tokens_out or 0 for e in usage_events),
            "composite_rating": profile.composite_rating if profile else None,
            "effective_use_score": profile.effective_use_score if profile else None,
            "violation_count": profile.violation_count if profile else 0,
        },
        "token_usage": [
            {"timestamp": e.timestamp.isoformat(), "tokens_in": e.tokens_in or 0, "tokens_out": e.tokens_out or 0}
            for e in usage_events[-50:]
        ],
        "recent_decisions": [
            {"verdict": r.verdict, "decision_type": r.decision_type, "timestamp": r.timestamp.isoformat(), "reason": r.reason}
            for r in receipts[-50:]
        ],
    }
