"""Hash-chained, HMAC-signed audit receipts.

The signing key lives only here, server-side -- an agent's generated text can
never alter a receipt or the chain (docs/HACKATHON_PLAN.md hardening #4).
Chain is scoped per session_id.
"""
import hashlib
import hmac
import json
import os
from typing import Optional

from sqlalchemy.orm import Session

from shared.models import Receipt

SIGNING_SECRET = os.getenv("RECEIPT_SIGNING_SECRET", "dev-only-change-me")
GENESIS_HASH = "0" * 64


def _compute_hash(prev_hash: str, decision: dict) -> str:
    payload = json.dumps(decision, sort_keys=True).encode()
    return hashlib.sha256(prev_hash.encode() + payload).hexdigest()


def _sign(hash_value: str) -> str:
    return hmac.new(SIGNING_SECRET.encode(), hash_value.encode(), hashlib.sha256).hexdigest()


def write_receipt(
    db: Session,
    *,
    user_id: str,
    session_id: str,
    agent_id: str,
    parent_agent_id: Optional[str],
    decision_type: str,
    verdict: str,
    reason: Optional[str],
    ref_id: Optional[str],
) -> Receipt:
    last = (
        db.query(Receipt)
        .filter(Receipt.session_id == session_id)
        .order_by(Receipt.timestamp.desc())
        .first()
    )
    prev_hash = last.hash if last else GENESIS_HASH

    decision = {
        "user_id": user_id,
        "session_id": session_id,
        "agent_id": agent_id,
        "parent_agent_id": parent_agent_id,
        "decision_type": decision_type,
        "verdict": verdict,
        "reason": reason,
        "ref_id": ref_id,
    }
    new_hash = _compute_hash(prev_hash, decision)
    signature = _sign(new_hash)

    receipt = Receipt(
        prev_hash=prev_hash,
        hash=new_hash,
        signature=signature,
        user_id=user_id,
        session_id=session_id,
        agent_id=agent_id,
        parent_agent_id=parent_agent_id,
        decision_type=decision_type,
        verdict=verdict,
        reason=reason,
        ref_id=ref_id,
    )
    db.add(receipt)
    db.commit()
    db.refresh(receipt)
    return receipt
