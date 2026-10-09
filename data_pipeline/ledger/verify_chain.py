"""Walk the receipt hash chain for a session and confirm it hasn't been
tampered with -- the audit-trail integrity check backing
docs/HACKATHON_PLAN.md hardening #4.

Run: `python data_pipeline/ledger/verify_chain.py <session_id>` from the repo root.
"""
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))  # allow `import shared`

from shared.db import SessionLocal
from shared.models import Receipt

# Re-implemented here (rather than importing governance_api) so this script
# has no dependency on the API service being importable/running.
import hashlib
import hmac
import json
import os

SIGNING_SECRET = os.getenv("RECEIPT_SIGNING_SECRET", "dev-only-change-me")
GENESIS_HASH = "0" * 64


def _compute_hash(prev_hash: str, decision: dict) -> str:
    payload = json.dumps(decision, sort_keys=True).encode()
    return hashlib.sha256(prev_hash.encode() + payload).hexdigest()


def _sign(hash_value: str) -> str:
    return hmac.new(SIGNING_SECRET.encode(), hash_value.encode(), hashlib.sha256).hexdigest()


def check_chain(receipts: list) -> dict:
    """Verify one session's receipts (already in timestamp order). Names the
    first failure: "link" (prev_hash doesn't point at the previous receipt),
    "hash" (a hashed field was edited), or "signature" (HMAC mismatch)."""
    prev_hash = GENESIS_HASH
    for r in receipts:
        decision = {
            "user_id": r.user_id,
            "session_id": r.session_id,
            "agent_id": r.agent_id,
            "parent_agent_id": r.parent_agent_id,
            "decision_type": r.decision_type,
            "verdict": r.verdict,
            "reason": r.reason,
            "ref_id": r.ref_id,
        }
        problem = None
        if r.prev_hash != prev_hash:
            problem = "link"
        elif _compute_hash(prev_hash, decision) != r.hash:
            problem = "hash"
        elif _sign(r.hash) != r.signature:
            problem = "signature"
        if problem:
            return {"ok": False, "checked": len(receipts), "broken_receipt_id": r.receipt_id, "problem": problem}
        prev_hash = r.hash
    return {"ok": True, "checked": len(receipts), "broken_receipt_id": None, "problem": None}


def verify_session_chain(session_id: str) -> bool:
    db = SessionLocal()
    try:
        receipts = (
            db.query(Receipt)
            .filter(Receipt.session_id == session_id)
            .order_by(Receipt.timestamp)
            .all()
        )
        result = check_chain(receipts)
        if result["problem"] == "signature":
            print(f"SIGNATURE MISMATCH at receipt {result['broken_receipt_id']}")
        elif not result["ok"]:
            print(f"TAMPER DETECTED at receipt {result['broken_receipt_id']}")
        else:
            print(f"chain OK: {len(receipts)} receipts verified for session {session_id}")
        return result["ok"]
    finally:
        db.close()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: python verify_chain.py <session_id>")
        sys.exit(1)
    ok = verify_session_chain(sys.argv[1])
    sys.exit(0 if ok else 1)
