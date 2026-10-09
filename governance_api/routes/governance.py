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

from detectors.injection.heuristics import detect as detect_injection  # noqa: E402
from detectors.scoring.signals import phi_signal  # noqa: E402
from access_control.overrides import is_unredacted_allowed
from authority.engine import AuthorityEngine, DEFAULT_SCORE
from shared.models import AgentTrustState
from authority.policy_gates import required_threshold, DEFAULT_THRESHOLD
from compliance import engine as compliance_engine
from receipts.writer import write_receipt

router = APIRouter(prefix="/governance", tags=["governance"])


def _apply_signals(
    engine: AuthorityEngine, agent_id: str, session_id: str, violations: list, injection_hits: list
) -> None:
    """Apply the PHI/PII signal and the injection signal independently -- each
    is its own evidence event (and its own authority-history entry), not a
    single merged one, so monotonic reduction stacks them correctly if both
    fire on the same text."""
    phi = phi_signal(violations)
    if phi:  # None if clean, or if every match is a NO_SIGNAL_IDENTIFIERS marker (e.g. consent_purpose_flag)
        engine.apply_signal(agent_id, session_id, phi)
    if injection_hits:
        engine.apply_signal(agent_id, session_id, "prompt_injection_detected")


@router.post("/compliance-check", response_model=ComplianceCheckResponse)
def compliance_check(req: ComplianceCheckRequest, db: Session = Depends(get_db)):
    allow_unredacted = is_unredacted_allowed(db, req.identity.user_id, req.request_unredacted)
    verdict, cleaned_text, violations = compliance_engine.check(db, req.text, req.pack_id, allow_unredacted)

    # Prompt-injection phrasing ("ignore previous instructions", a forged
    # "as the supervisor" role claim, ...) is a risk on untrusted INPUT --
    # inbound: the user's prompt, or RAG-retrieved text concatenated into it
    # (docs/INTEGRATION_CONTRACT.md). Not checked on outbound (the model's
    # own answer to the end user isn't "injecting" anything into this system).
    # This never gates the verdict itself (detectors/injection/heuristics.py:
    # a rule-based signal, not a decision) -- it only costs authority score.
    injection_hits = detect_injection(req.text) if req.direction == "inbound" else []

    # apply_score=False (e.g. tool-result scans): redact + receipt, but leave
    # the score alone -- and don't even create trust state for it.
    if (violations or injection_hits) and req.apply_score:
        engine = AuthorityEngine(db)
        engine.get_or_create(req.identity.agent_id, req.identity.session_id, req.identity.parent_agent_id)
        _apply_signals(engine, req.identity.agent_id, req.identity.session_id, violations, injection_hits)

    reason = ", ".join(violations) if violations else None
    if violations and allow_unredacted:
        reason = f"{reason} [unredacted_override_applied: user_id={req.identity.user_id}]"
    if injection_hits:
        injection_note = f"injection_detected: {', '.join(injection_hits)}"
        reason = f"{reason}; {injection_note}" if reason else injection_note

    # What the dashboard's conversation view shows: the text AFTER governance
    # cleaned it -- i.e. exactly what travelled onward. Never the raw input:
    # with an unredacted override the caller gets raw text back, so store a
    # separately redacted copy instead (receipts must never hold raw PHI/PII).
    stored_text = cleaned_text if verdict != "block" else None
    if violations and allow_unredacted and verdict != "block":
        stored_text = compliance_engine.check(db, req.text, req.pack_id, False)[1]

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
        payload={"direction": req.direction, "text": stored_text, "scored": req.apply_score},
    )
    return ComplianceCheckResponse(
        verdict=verdict,
        cleaned_text=cleaned_text,
        violations=violations,
        injection_hits=injection_hits,
        receipt_id=receipt.receipt_id,
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
    # One agent's output becomes the NEXT agent's input -- an injected
    # instruction/role-claim here is exactly as much a risk as in a user
    # prompt, so always checked (no `direction` field needed: a handoff is
    # inherently "inbound" from the receiving agent's point of view).
    injection_hits = detect_injection(req.output_text)

    engine = AuthorityEngine(db)
    engine.get_or_create(req.identity.agent_id, req.identity.session_id, req.identity.parent_agent_id)

    if violations or injection_hits:
        _apply_signals(engine, req.identity.agent_id, req.identity.session_id, violations, injection_hits)

    # Roll up all agents' scores in this session so the FINAL output can be
    # blocked even if no single agent alone breaches threshold -- if the
    # lowest score across all agents in the session is below the default
    # authority threshold, block with an explicit per-agent reason.
    all_states = (
        db.query(AgentTrustState)
        .filter(AgentTrustState.session_id == req.identity.session_id)
        .all()
    )
    session_min_score = min((s.current_score for s in all_states), default=DEFAULT_SCORE)

    allowed = verdict != "block" and session_min_score >= DEFAULT_THRESHOLD
    reason = None
    if not allowed:
        if verdict == "block":
            reason = f"output blocked: not {req.pack_id.upper()}-compliant"
        else:
            worst = min(all_states, key=lambda s: s.current_score)
            reason = (
                f"session-level block: lowest score {worst.current_score:.1f} "
                f"(agent_id={worst.agent_id}) below threshold"
            )

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
    return HandoffCheckResponse(
        allowed=allowed, verdict=verdict, reason=reason, injection_hits=injection_hits, receipt_id=receipt.receipt_id
    )
