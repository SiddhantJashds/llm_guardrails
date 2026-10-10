"""Policy gates beyond the trust score, applied at the execution boundary
before a tool runs (problem statement: "every tool call is checked
immediately before it's allowed to proceed").

1. Declared scope: a tool the agent did not declare is denied.
2. Human approval: a tool whose threshold is above 100 can never be earned
   by score alone -- destructive or irreversible actions (delete, change a
   record, submit a claim) need a person (DPDP erasure, HIPAA integrity).
3. Arguments:
   - recipients outside the allowed email domains are denied (external or
     cross-border transfer);
   - recipients/subjects whose consent is not GIVEN are denied (DPDP);
   - arguments carrying identifiers whose pack action is `block` are denied.
All deterministic (ADR 0004); every outcome is receipted by the caller.
"""
import json
import os
import re
from typing import Iterable, List, Optional

from sqlalchemy.orm import Session

from shared.models import ConsentRecord

APPROVAL_THRESHOLD = 100.0
# Tools that act on a data principal (contact them, book, bill, change). Reads
# stay allowed so staff can still look up and process e.g. an erasure request.
CONSENT_GATED_TOOLS = frozenset(
    t.strip() for t in os.getenv("CONSENT_GATED_TOOLS", "send_email,schedule_appointment,submit_claim,update_record,delete_file").split(",") if t.strip()
)
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})")
RECIPIENT_KEYS = {"to", "cc", "bcc", "recipient", "recipients", "email", "address", "send_to"}


def allowed_email_domains() -> List[str]:
    raw = os.getenv("ALLOWED_EMAIL_DOMAINS", "example.com")
    return [d.strip().lower() for d in raw.split(",") if d.strip()]


def _strings(value) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _strings(v)
    elif isinstance(value, (list, tuple)):
        for v in value:
            yield from _strings(v)
    elif value is not None:
        yield str(value)


def _recipients(args: dict) -> List[str]:
    found = []
    for key, value in (args or {}).items():
        if key.lower() in RECIPIENT_KEYS:
            for text in _strings(value):
                found += [m.group(0).lower() for m in EMAIL.finditer(text)]
    return found


def scope_denial(tool_id: str, declared_tools: Optional[List[str]]) -> Optional[str]:
    if declared_tools is not None and tool_id not in declared_tools:
        return f"'{tool_id}' is outside this agent's declared tools"
    return None


def approval_denial(tool_id: str, threshold: float) -> Optional[str]:
    if threshold > APPROVAL_THRESHOLD:
        return f"'{tool_id}' requires human approval (destructive or irreversible action)"
    return None


def _resolve_placeholders(args: dict, session_id: Optional[str]) -> dict:
    """An agent may pass "[EMAIL_1]" as a recipient: check the real value."""
    if not session_id:
        return args
    from compliance import vault  # local import: avoid a cycle at module load

    def swap(m):
        entry = vault.lookup(session_id, m.group(0))
        return entry.value if entry is not None else m.group(0)

    return json.loads(vault.TOKEN_RE.sub(lambda m: json.dumps(swap(m))[1:-1], json.dumps(args, ensure_ascii=False)))


def argument_denial(db: Session, tool_id: str, args: Optional[dict], pack_id: str, session_id: Optional[str] = None) -> Optional[str]:
    if not args:
        return None
    args = _resolve_placeholders(args, session_id)
    allowed = allowed_email_domains()
    for email in _recipients(args):
        domain = email.split("@", 1)[1]
        if domain not in allowed:
            return f"recipient domain '{domain}' is outside the allowed domains ({', '.join(allowed)}): external transfer denied"
    if tool_id in CONSENT_GATED_TOOLS:
        # Any non-consented data principal named anywhere in the call: as the
        # recipient, in the body, or by name / MRN.
        text = " ".join(_strings(args)).lower()
        for record in db.query(ConsentRecord).all():
            if record.status.upper() == "GIVEN":
                continue
            if re.search(r"(?<![\w.@-])" + re.escape(record.subject) + r"(?![\w@-])", text):
                who = record.label or record.subject
                return f"consent {record.status.lower()} for {who}: data principal has not consented to '{tool_id}'"
    # Identifiers whose configured action is `block` may not travel in a tool call
    from compliance import engine  # local import: avoid a cycle at module load

    blob = json.dumps(args, ensure_ascii=False)
    blocked = sorted({name for name, _, action in engine.planned_actions(db, blob, pack_id) if action == "block"})
    if blocked:
        return f"tool arguments contain {', '.join(blocked)}, which policy blocks from leaving the system"
    return None
