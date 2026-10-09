"""Pydantic request/response contracts for the /governance/* API.

Kept here (not inside governance_api) so governance_sdk's client can import
the same shapes without depending on the whole service.
"""
from typing import List, Optional, Literal

from pydantic import BaseModel


class IdentityEnvelopeSchema(BaseModel):
    user_id: str
    session_id: str
    agent_id: str
    parent_agent_id: Optional[str] = None


class ComplianceCheckRequest(BaseModel):
    identity: IdentityEnvelopeSchema
    direction: Literal["inbound", "outbound"]
    text: str
    pack_id: str = "hipaa"
    # Set ONLY from trusted request context (e.g. a header the proxy reads),
    # never parsed from prompt/completion text -- same rule as the identity
    # envelope. Redaction is skipped only if this AND the user's stored
    # UserAccessOverride.allow_unredacted are both true (see docs/adr/0005).
    request_unredacted: bool = False
    # False = redact + write the receipt, but don't touch the authority score.
    # For tool-result scans: the PHI is in retrieved DATA the agent was
    # authorized to see, not agent misbehavior -- penalizing it bricks
    # legitimate read-then-use workflows (bench scenario 1 proved this).
    apply_score: bool = True


class ComplianceCheckResponse(BaseModel):
    verdict: Literal["allow", "redact", "block", "hash", "log_only"]
    cleaned_text: str
    violations: List[str] = []
    # Prompt-injection heuristic names matched (detectors/injection/heuristics.py),
    # only checked on direction="inbound" (see governance_api/routes/governance.py).
    # Additive field, default [] -- existing callers unaffected.
    injection_hits: List[str] = []
    receipt_id: str


class ToolCheckRequest(BaseModel):
    identity: IdentityEnvelopeSchema
    tool_id: str


class ToolCheckResponse(BaseModel):
    allowed: bool
    current_score: float
    required_threshold: float
    reason: Optional[str] = None
    receipt_id: str


class HandoffCheckRequest(BaseModel):
    identity: IdentityEnvelopeSchema
    output_text: str
    pack_id: str = "hipaa"


class HandoffCheckResponse(BaseModel):
    allowed: bool
    verdict: str
    reason: Optional[str] = None
    injection_hits: List[str] = []
    receipt_id: str
