"""Redaction roles: what a person may see when they explicitly ask for an
unredacted view (docs/adr/0016). Config only -- no login (docs/adr/0005).

A role is a CAP, not a default: without request_unredacted, everyone gets
placeholders (plus their own values restored, when the caller opts in). With
the ask, each identifier is shown per the user's role: "hidden" (placeholder),
"partial" (masked except the last characters) or "full". Block and hash
actions are never relaxed by any role. The older per-user override
(allow_unredacted) still works and behaves like an all-"full" role.
"""
from typing import Dict, Optional

from sqlalchemy.orm import Session

from shared.models import RedactionRole, UserAccessOverride, UserRole

LEVELS = ("hidden", "partial", "full")

DEFAULT_ROLES = [
    {
        "role_id": "clinician",
        "label": "Clinician",
        "description": "Treating staff: sees names, locations and dates; contact details partially.",
        "default_level": "hidden",
        "visibility": {
            "full_name": "full",
            "geographic_subdivision": "full",
            "residential_address": "partial",
            "date_except_year": "full",
            "phone_number": "partial",
            "fax_number": "partial",
            "email_address": "partial",
        },
    },
    {
        "role_id": "auditor",
        "label": "Auditor",
        "description": "Reviews activity: identifiers stay as placeholders, nothing is revealed.",
        "default_level": "hidden",
        "visibility": {},
    },
]


def ensure_defaults(db: Session) -> None:
    if db.query(RedactionRole).count():
        return
    for r in DEFAULT_ROLES:
        db.add(RedactionRole(**r))
    db.commit()


def as_dict(role: RedactionRole) -> dict:
    return {
        "role_id": role.role_id,
        "label": role.label,
        "description": role.description,
        "default_level": role.default_level,
        "visibility": role.visibility or {},
    }


def role_for_user(db: Session, user_id: str) -> Optional[RedactionRole]:
    link = db.get(UserRole, user_id)
    return db.get(RedactionRole, link.role_id) if link else None


def visibility_for(db: Session, user_id: str, request_unredacted: bool, identifiers) -> Optional[Dict[str, str]]:
    """identifier -> level for this request, or None when nothing extra may be
    shown. Requires the explicit ask (ADR 0003); the role, if any, caps it;
    the legacy override means "full" for everything."""
    if not request_unredacted:
        return None
    role = role_for_user(db, user_id)
    if role is not None:
        levels = role.visibility or {}
        return {i: levels.get(i, role.default_level) for i in identifiers}
    override = db.get(UserAccessOverride, user_id)
    if override and override.allow_unredacted:
        return {i: "full" for i in identifiers}
    return None


def describe(db: Session, user_id: str) -> str:
    role = role_for_user(db, user_id)
    return f"role={role.role_id}" if role else "override"
