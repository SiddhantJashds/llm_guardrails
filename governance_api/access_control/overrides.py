"""Per-user_id access overrides -- not RBAC, not login (docs/adr/0005).

Default is fully restrictive: no row (or allow_unredacted=False) means every
"redact" action always masks, no exceptions. This module only reads/writes
that one override bit (plus optional per-tool threshold overrides); it never
introduces authentication.
"""
from typing import Optional

from sqlalchemy.orm import Session

from shared.models import UserAccessOverride


def get_override(db: Session, user_id: str) -> Optional[UserAccessOverride]:
    return db.get(UserAccessOverride, user_id)


def is_unredacted_allowed(db: Session, user_id: str, request_unredacted: bool) -> bool:
    """True only if the admin granted this user_id the override AND the
    caller explicitly asked for unredacted output on this specific request."""
    if not request_unredacted:
        return False
    override = get_override(db, user_id)
    return bool(override and override.allow_unredacted)


def set_override(
    db: Session, user_id: str, allow_unredacted: bool, tool_overrides: Optional[dict] = None
) -> UserAccessOverride:
    row = get_override(db, user_id)
    if row is None:
        row = UserAccessOverride(user_id=user_id)
        db.add(row)
    row.allow_unredacted = allow_unredacted
    if tool_overrides is not None:
        row.tool_overrides = tool_overrides
    db.commit()
    db.refresh(row)
    return row


def list_overrides(db: Session) -> list:
    return db.query(UserAccessOverride).all()
