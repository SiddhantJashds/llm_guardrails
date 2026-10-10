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
    # Let names/emails/MRNs the user typed in this session through to the
    # model (compliance/redaction.py SENDER_KEYS). Trusted callers only.
    pass_sender_keys: bool = False
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
    # Trusted-caller opt-in (docs/adr/0016): this inbound text was typed by the
    # end user themselves, so identifiers in it may be restored when the reply
    # comes back to that same user. Never set it for text that includes
    # retrieved/third-party data (RAG context, tool output) -- the proxy only
    # sets it for user-role messages when the client sends x-restore-to-sender.
    restore_to_sender: bool = False


class ComplianceCheckResponse(BaseModel):
    verdict: Literal["allow", "redact", "block", "hash", "log_only"]
    cleaned_text: str
    violations: List[str] = []
    # Prompt-injection heuristic names matched (detectors/injection/heuristics.py),
    # only checked on direction="inbound" (see governance_api/routes/governance.py).
    # Additive field, default [] -- existing callers unaffected.
    injection_hits: List[str] = []
    receipt_id: str
    # docs/adr/0016. model_text: what goes to the model (placeholders, never
    # raw values). display_text: what the requesting person sees (own values
    # restored, role view applied). cleaned_text keeps its old meaning: the
    # model_text for inbound checks, the display_text for outbound checks.
    model_text: Optional[str] = None
    display_text: Optional[str] = None
    entities: List[dict] = []


class ToolCheckRequest(BaseModel):
    identity: IdentityEnvelopeSchema
    tool_id: str
    # Optional, additive (governance_api/authority/tool_policy.py): the call's
    # arguments (recipient domain, consent and identifier checks) and the
    # tools the agent declared it may use (out-of-scope calls are denied).
    tool_args: Optional[dict] = None
    declared_tools: Optional[List[str]] = None
    pack_id: str = "hipaa+dpdp"


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
