"""Redaction policy layer (docs/adr/0016): turns detections into two texts.

- model_text: what is forwarded to the model. Identifiers become typed,
  numbered placeholders ("[NAME_1]"), a partial mask ("(•••) •••-7788") or a
  typed mask ("[REDACTED_PHONE]") per identifier; never raw values.
- display_text: what the requesting person sees. Placeholders for values the
  same user typed themselves (opted in) are restored; with an explicit
  unredacted ask, the user's role may reveal more (full or partial). Block and
  hash are never relaxed.

Detection and the action per identifier come from compliance/engine.py
(deterministic, ADR 0004); this module only decides how a value is shown.
"""
from dataclasses import dataclass
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from shared.models import CompliancePackConfig
from . import actions, engine, vault

STYLES = ("token", "partial", "masked")
DIRECTIONS = ("both", "inbound", "outbound")
LEVELS = ("hidden", "partial", "full")


@dataclass
class Policy:
    style: str = "token"
    keep_last: int = 4
    restore_to_sender: bool = True
    applies_to: str = "both"


def policy_for(db: Session, pack_id: str, identifier: str) -> Policy:
    row = db.get(CompliancePackConfig, (pack_id, identifier))
    cfg = (row.config or {}) if row is not None else {}
    p = Policy()
    if cfg.get("style") in STYLES:
        p.style = cfg["style"]
    if isinstance(cfg.get("keep_last"), int) and 0 <= cfg["keep_last"] <= 12:
        p.keep_last = cfg["keep_last"]
    if isinstance(cfg.get("restore_to_sender"), bool):
        p.restore_to_sender = cfg["restore_to_sender"]
    if cfg.get("applies_to") in DIRECTIONS:
        p.applies_to = cfg["applies_to"]
    return p


def partial(identifier: str, value: str, keep_last: int) -> str:
    """Mask every letter/digit except the last `keep_last` (emails keep the
    first character of the local part and the domain)."""
    if identifier == "email_address" and "@" in value:
        local, domain = value.split("@", 1)
        return (local[:1] + "•" * max(1, len(local) - 1)) + "@" + domain
    keep = sum(1 for ch in value if ch.isalnum())
    remaining = keep - keep_last
    out = []
    for ch in value:
        if ch.isalnum():
            out.append("•" if remaining > 0 else ch)
            remaining -= 1
        else:
            out.append(ch)
    return "".join(out)


def masked(identifier: str) -> str:
    return f"[REDACTED_{vault.label_for(identifier)}]"


@dataclass
class Result:
    verdict: str
    model_text: str
    display_text: str
    violations: List[str]
    entities: List[dict]
    role_view_applied: bool = False


def process(
    db: Session,
    text: str,
    pack_id: str,
    *,
    session_id: str,
    user_id: str,
    direction: str,
    scored: bool = True,
    restore_to_sender: bool = False,
    visibility: Optional[Dict[str, str]] = None,
) -> Result:
    hits = engine.planned_actions(db, text, pack_id)
    violations = [name for name, _, _ in hits]
    if not hits:
        # Nothing new detected -- but an outbound reply may still carry
        # placeholders ("Hello, [NAME_1]!") that must be restored for display.
        display, role_applied, _ = _display(db, text, pack_id, session_id, user_id, direction, restore_to_sender, visibility)
        return Result("allow", text, display, [], [], role_applied)
    if any(action == "block" for _, _, action in hits):
        return Result("block", "", "", violations, [{"type": n, "action": "block"} for n, _, a in hits if a == "block"])

    if direction == "inbound":
        origin = "sender" if restore_to_sender else "context"
    else:
        origin = "model" if scored else "tool"

    model_text = text
    verdict = "log_only"
    entities: List[dict] = []
    # Longest spans first so a value contained in another is not split.
    for identifier, span, action in sorted(hits, key=lambda h: -len(h[1])):
        policy = policy_for(db, pack_id, identifier)
        if policy.applies_to not in ("both", direction):
            action = "log_only"
        if action == "log_only" or span not in model_text:
            entities.append({"type": identifier, "action": "log_only"})
            continue
        if action == "hash":
            model_text = actions.hash_value(model_text, span)
            verdict = "hash" if verdict != "redact" else verdict
            entities.append({"type": identifier, "action": "hash"})
            continue
        # redact
        if policy.style == "partial":
            replacement = partial(identifier, span, policy.keep_last)
        elif policy.style == "masked":
            replacement = masked(identifier)
        else:
            replacement = vault.token_for(session_id, identifier, span, origin, user_id)
        model_text = model_text.replace(span, replacement)
        verdict = "redact"
        entities.append({"type": identifier, "action": "redact", "style": policy.style, "shown_to_model": replacement})

    display_text, role_applied, restored = _display(db, model_text, pack_id, session_id, user_id, direction, restore_to_sender, visibility)
    for e in entities:
        token = e.get("shown_to_model")
        if token in restored:
            e["restored"] = restored[token]
    return Result(verdict, model_text, display_text, violations, entities, role_applied)


def _display(db, model_text, pack_id, session_id, user_id, direction, restore_to_sender, visibility):
    """Replace placeholders in what the person will see. Only outbound text
    (a reply, a tool result shown onward) is restored; inbound text goes to
    the model and keeps its placeholders."""
    restored: Dict[str, str] = {}
    role_applied = False
    if direction != "outbound":
        return model_text, role_applied, restored

    def swap(m):
        nonlocal role_applied
        token = m.group(0)
        entry = vault.lookup(session_id, token)
        if entry is None:
            return token
        policy = policy_for(db, pack_id, entry.identifier)
        if restore_to_sender and entry.origin == "sender" and entry.user_id == user_id and policy.restore_to_sender:
            restored[token] = "sender"
            return entry.value
        level = (visibility or {}).get(entry.identifier)
        if level == "full":
            role_applied = True
            restored[token] = "role_full"
            return entry.value
        if level == "partial":
            role_applied = True
            restored[token] = "role_partial"
            return partial(entry.identifier, entry.value, policy.keep_last)
        return token

    return vault.TOKEN_RE.sub(swap, model_text), role_applied, restored
