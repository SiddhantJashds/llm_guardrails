"""The /governance/* API -- the single decision surface every integration
(reverse proxy, LangChain callback, LangGraph node wrapper) calls into.
"""
import sys
from pathlib import Path

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

sys.path.append(str(Path(__file__).resolve().parents[2]))  # allow `import shared`
from shared.db import get_db  # noqa: E402
from shared.schemas import (  # noqa: E402
    ComplianceCheckRequest,
    ComplianceCheckResponse,
    ToolCheckRequest,
    ToolCheckResponse,
    HandoffCheckRequest,
    HandoffCheckResponse,
)

from detectors.scoring.signals import phi_signal  # noqa: E402
from access_control.overrides import is_unredacted_allowed
from authority.engine import AuthorityEngine
from authority.policy_gates import required_threshold
from compliance import engine as compliance_engine
from receipts.writer import write_receipt

router = APIRouter(prefix="/governance", tags=["governance"])


@router.post("/compliance-check", response_model=ComplianceCheckResponse)
def compliance_check(req: ComplianceCheckRequest, db: Session = Depends(get_db)):
    allow_unredacted = is_unredacted_allowed(db, req.identity.user_id, req.request_unredacted)
    verdict, cleaned_text, violations = compliance_engine.check(db, req.text, req.pack_id, allow_unredacted)

    if violations:
        engine = AuthorityEngine(db)
        engine.get_or_create(req.identity.agent_id, req.identity.session_id, req.identity.parent_agent_id)
        signal = phi_signal(violations)
        if signal:  # None if every matched identifier is a NO_SIGNAL_IDENTIFIERS marker (e.g. consent_purpose_flag)
            engine.apply_signal(req.identity.agent_id, signal)

    reason = ", ".join(violations) if violations else None
    if violations and allow_unredacted:
        reason = f"{reason} [unredacted_override_applied: user_id={req.identity.user_id}]"

    receipt = write_receipt(
        db,
        user_id=req.identity.user_id,
        session_id=req.identity.session_id,
        agent_id=req.identity.agent_id,
        parent_agent_id=req.identity.parent_agent_id,
        decision_type="compliance",
        verdict=verdict,
        reason=reason,
        ref_id=req.pack_id,
    )
    return ComplianceCheckResponse(
        verdict=verdict, cleaned_text=cleaned_text, violations=violations, receipt_id=receipt.receipt_id
    )


@router.post("/tool-check", response_model=ToolCheckResponse)
def tool_check(req: ToolCheckRequest, db: Session = Depends(get_db)):
    engine = AuthorityEngine(db)
    state = engine.get_or_create(req.identity.agent_id, req.identity.session_id, req.identity.parent_agent_id)
    threshold = required_threshold(db, req.tool_id)
    allowed = state.current_score >= threshold
    reason = None if allowed else f"score {state.current_score} below required {threshold} for '{req.tool_id}'"

    receipt = write_receipt(
        db,
        user_id=req.identity.user_id,
        session_id=req.identity.session_id,
        agent_id=req.identity.agent_id,
        parent_agent_id=req.identity.parent_agent_id,
        decision_type="authority",
        verdict="allow" if allowed else "deny",
        reason=reason,
        ref_id=req.tool_id,
    )
    return ToolCheckResponse(
        allowed=allowed,
        current_score=state.current_score,
        required_threshold=threshold,
        reason=reason,
        receipt_id=receipt.receipt_id,
    )


@router.post("/handoff-check", response_model=HandoffCheckResponse)
def handoff_check(req: HandoffCheckRequest, db: Session = Depends(get_db)):
    # Handoffs are agent-to-agent, not a user-facing response -- the
    # allow_unredacted override intentionally does not apply here.
    verdict, _cleaned, violations = compliance_engine.check(db, req.output_text, req.pack_id)
    engine = AuthorityEngine(db)
    engine.get_or_create(req.identity.agent_id, req.identity.session_id, req.identity.parent_agent_id)

    if violations:
        signal = phi_signal(violations)
        if signal:
            engine.apply_signal(req.identity.agent_id, signal)

    # TODO (SWE#2 Day2 #7): roll up multiple agents' scores in a session so
    # the FINAL output can be blocked even if no single agent alone breaches
    # threshold -- currently this only evaluates the one agent_id in `req`.
    allowed = verdict != "block"
    reason = None if allowed else f"output blocked: not {req.pack_id.upper()}-compliant"

    receipt = write_receipt(
        db,
        user_id=req.identity.user_id,
        session_id=req.identity.session_id,
        agent_id=req.identity.agent_id,
        parent_agent_id=req.identity.parent_agent_id,
        decision_type="authority",
        verdict="allow" if allowed else "deny",
        reason=reason,
        ref_id=req.pack_id,
    )
    return HandoffCheckResponse(allowed=allowed, verdict=verdict, reason=reason, receipt_id=receipt.receipt_id)
