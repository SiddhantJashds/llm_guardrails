"""ORM models shared by proxy + governance_api.

Table-per-concept, matching docs/HACKATHON_PLAN.md's data layer:
Receipt (audit ledger), AgentTrustState (authority engine), UserProfile +
TokenUsageEvent (per-user accountability), CompliancePackConfig (HIPAA/DPDP config).
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, String, Integer, Float, Boolean, DateTime, JSON

from .db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Receipt(Base):
    """Hash-chained, signed audit record for one compliance or authority decision.

    Chain is scoped per session_id: each new receipt's prev_hash points at the
    last receipt written for that session (see receipts/writer.py).
    """

    __tablename__ = "receipts"

    receipt_id = Column(String, primary_key=True, default=_uuid)
    prev_hash = Column(String, nullable=False)
    hash = Column(String, nullable=False, unique=True)
    signature = Column(String, nullable=False)
    timestamp = Column(DateTime, default=_now, nullable=False)

    user_id = Column(String, nullable=False, index=True)
    session_id = Column(String, nullable=False, index=True)
    agent_id = Column(String, nullable=False, index=True)
    parent_agent_id = Column(String, nullable=True)

    decision_type = Column(String, nullable=False)  # "compliance" | "authority"
    verdict = Column(String, nullable=False)  # "allow" | "deny" | "redact" | "block" | "hash" | "log_only"
    reason = Column(String, nullable=True)
    ref_id = Column(String, nullable=True)  # pack_id or tool_id

    payload = Column(JSON, nullable=True)  # TODO: keep small; never store raw PHI/PII here


class AgentTrustState(Base):
    """Live, monotonically-decreasing trust score for one agent within one session."""

    __tablename__ = "agent_trust_state"

    # Composite PK: trust is per (agent, session). A global agent_id PK leaked
    # scores across sessions AND users (bench scenarios poisoned each other,
    # and the per-session dashboard view could never find the state rows).
    agent_id = Column(String, primary_key=True)
    session_id = Column(String, primary_key=True, index=True)
    parent_agent_id = Column(String, nullable=True)
    current_score = Column(Float, default=100.0, nullable=False)
    last_updated = Column(DateTime, default=_now, onupdate=_now)
    history = Column(JSON, default=list)  # list of {"signal": str, "delta": float, "timestamp": str}


class UserProfile(Base):
    """Persistent per-user rollup: token usage, composite rating, effective-use score."""

    __tablename__ = "user_profiles"

    user_id = Column(String, primary_key=True)
    total_tokens_in = Column(Integer, default=0)
    total_tokens_out = Column(Integer, default=0)
    violation_count = Column(Integer, default=0)
    composite_rating = Column(Float, default=100.0)  # TODO: Data Scientist formula
    effective_use_score = Column(Float, default=0.0)  # TODO: Data Scientist formula
    last_updated = Column(DateTime, default=_now, onupdate=_now)


class TokenUsageEvent(Base):
    """Raw per-request token usage event; aggregated into UserProfile by data_pipeline."""

    __tablename__ = "token_usage_events"

    event_id = Column(String, primary_key=True, default=_uuid)
    user_id = Column(String, nullable=False, index=True)
    session_id = Column(String, nullable=False, index=True)
    agent_id = Column(String, nullable=False, index=True)
    tokens_in = Column(Integer, default=0)
    tokens_out = Column(Integer, default=0)
    timestamp = Column(DateTime, default=_now)


class CompliancePackConfig(Base):
    """Structured identifier + action config for a compliance pack (HIPAA/DPDP).

    Composite key (pack_id, identifier) -- e.g. ("hipaa", "phone_number") -> "redact".
    """

    __tablename__ = "compliance_pack_config"

    pack_id = Column(String, primary_key=True)
    identifier = Column(String, primary_key=True)
    action = Column(String, nullable=False)  # "redact" | "block" | "hash" | "log_only"
    config = Column(JSON, nullable=True)


class ToolThresholdConfig(Base):
    """Admin-editable per-tool authority threshold (replaces the hardcoded
    dict that used to live in authority/policy_gates.py, seeded from
    data_pipeline/config/tool_thresholds.yaml)."""

    __tablename__ = "tool_threshold_config"

    tool_id = Column(String, primary_key=True)
    threshold = Column(Float, nullable=False)


class UserAccessOverride(Base):
    """Per-user_id access override -- NOT a role or login (see docs/adr/0005).

    Default (no row, or allow_unredacted=False) is fully restrictive: redact
    actions always mask, no exceptions. An admin can grant allow_unredacted
    for a specific user_id, but the compliance engine only actually skips
    masking when the CALLER ALSO explicitly requests unredacted output on
    that request (ComplianceCheckRequest.request_unredacted) -- admin grant
    AND explicit ask, both required. This never affects block/hash actions.
    """

    __tablename__ = "user_access_overrides"

    user_id = Column(String, primary_key=True)
    allow_unredacted = Column(Boolean, default=False, nullable=False)
    tool_overrides = Column(JSON, nullable=True)  # optional {"tool_id": threshold_override}
    updated_at = Column(DateTime, default=_now, onupdate=_now)


class RedactionRole(Base):
    """A named view policy for people who may see more than placeholders
    (docs/adr/0016). `visibility` maps identifier -> "hidden" | "partial" |
    "full"; identifiers not listed fall back to `default_level`. A role is a
    CAP: it only takes effect when the request also explicitly asks for an
    unredacted view (ADR 0003), and it never relaxes block or hash actions."""

    __tablename__ = "redaction_roles"

    role_id = Column(String, primary_key=True)
    label = Column(String, nullable=False)
    description = Column(String, nullable=True)
    default_level = Column(String, nullable=False, default="hidden")
    visibility = Column(JSON, nullable=True)
    updated_at = Column(DateTime, default=_now, onupdate=_now)


class UserRole(Base):
    """Admin-assigned role per user_id. Config only, no login (docs/adr/0005)."""

    __tablename__ = "user_roles"

    user_id = Column(String, primary_key=True)
    role_id = Column(String, nullable=False)
    updated_at = Column(DateTime, default=_now, onupdate=_now)
