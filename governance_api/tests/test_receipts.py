"""Receipt hash-chain: links correctly, and tampering is detectable.

This is the audit-trail integrity guarantee from docs/HACKATHON_PLAN.md
hardening #4 -- if this silently breaks, "tamper-evident" stops being true
even though receipts keep getting written.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # allow `import data_pipeline`

from receipts.writer import write_receipt, GENESIS_HASH
from data_pipeline.ledger.verify_chain import verify_session_chain


def _write(db_session, session_id="sess1", agent_id="agent1"):
    return write_receipt(
        db_session,
        user_id="u1",
        session_id=session_id,
        agent_id=agent_id,
        parent_agent_id=None,
        decision_type="authority",
        verdict="allow",
        reason=None,
        ref_id="some_tool",
    )


def test_first_receipt_chains_from_genesis(db_session):
    receipt = _write(db_session)
    assert receipt.prev_hash == GENESIS_HASH
    assert receipt.hash != GENESIS_HASH


def test_second_receipt_chains_from_first(db_session):
    first = _write(db_session)
    second = _write(db_session)
    assert second.prev_hash == first.hash


def test_different_sessions_have_independent_chains(db_session):
    a = _write(db_session, session_id="sess_a")
    b = _write(db_session, session_id="sess_b")
    assert a.prev_hash == GENESIS_HASH
    assert b.prev_hash == GENESIS_HASH  # not chained to sess_a just because it was written second


def test_verify_chain_passes_on_untampered_receipts(db_session):
    _write(db_session, session_id="sess1")
    _write(db_session, session_id="sess1")
    assert verify_session_chain("sess1") is True


def test_verify_chain_detects_tampered_reason(db_session):
    from shared.models import Receipt

    _write(db_session, session_id="sess1")
    receipt = db_session.query(Receipt).filter(Receipt.session_id == "sess1").first()
    receipt.reason = "not what was actually decided"  # tamper with a field the hash covers
    db_session.commit()

    assert verify_session_chain("sess1") is False


def test_verify_chain_detects_forged_signature(db_session):
    from shared.models import Receipt

    _write(db_session, session_id="sess1")
    receipt = db_session.query(Receipt).filter(Receipt.session_id == "sess1").first()
    receipt.signature = "0" * 64  # forged -- doesn't match RECEIPT_SIGNING_SECRET
    db_session.commit()

    assert verify_session_chain("sess1") is False
