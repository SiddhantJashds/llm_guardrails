"""Config-only admin API -- no login, no roles, no user creation (see
docs/adr/0005-user-identity-no-auth.md). Backs the dashboard/admin.html page:
edit per-tool authority thresholds, per-identifier compliance actions, and
grant/revoke the per-user_id unredacted override.

Nothing here authenticates the caller -- in a real deployment this would sit
behind whatever auth the surrounding platform provides. For the hackathon
it's deliberately just CRUD over config tables, matching the "config-only
admin page" scope decision.
"""
import sys
from pathlib import Path
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

sys.path.append(str(Path(__file__).resolve().parents[2]))  # allow `import shared`
from shared.db import get_db  # noqa: E402
from shared.models import AgentTrustState, CompliancePackConfig, RedactionRole, Receipt, TokenUsageEvent, UserProfile, UserRole  # noqa: E402
from access_control import roles as roles_mod  # noqa: E402
from compliance import redaction, vault  # noqa: E402

from access_control.overrides import get_override, list_overrides, set_override
from authority.policy_gates import list_thresholds, set_threshold

router = APIRouter(prefix="/admin", tags=["admin"])


class ThresholdUpdate(BaseModel):
    threshold: float


class PackActionUpdate(BaseModel):
    action: Literal["redact", "block", "hash", "log_only"]


class OverrideUpdate(BaseModel):
    allow_unredacted: bool
    tool_overrides: Optional[dict] = None


@router.get("/tool-thresholds")
def get_tool_thresholds(db: Session = Depends(get_db)):
    return [{"tool_id": t.tool_id, "threshold": t.threshold} for t in list_thresholds(db)]


@router.put("/tool-thresholds/{tool_id}")
def put_tool_threshold(tool_id: str, body: ThresholdUpdate, db: Session = Depends(get_db)):
    row = set_threshold(db, tool_id, body.threshold)
    return {"tool_id": row.tool_id, "threshold": row.threshold}


@router.get("/compliance-pack/{pack_id}")
def get_pack_config(pack_id: str, db: Session = Depends(get_db)):
    rows = db.query(CompliancePackConfig).filter(CompliancePackConfig.pack_id == pack_id).all()
    return [{"identifier": r.identifier, "action": r.action} for r in rows]


@router.put("/compliance-pack/{pack_id}/{identifier}")
def put_pack_action(pack_id: str, identifier: str, body: PackActionUpdate, db: Session = Depends(get_db)):
    row = db.get(CompliancePackConfig, (pack_id, identifier))
    if row is None:
        row = CompliancePackConfig(pack_id=pack_id, identifier=identifier, action=body.action)
        db.add(row)
    else:
        row.action = body.action
    db.commit()
    return {"pack_id": pack_id, "identifier": identifier, "action": body.action}


@router.get("/users")
def get_user_overrides(db: Session = Depends(get_db)):
    return [
        {"user_id": o.user_id, "allow_unredacted": o.allow_unredacted, "tool_overrides": o.tool_overrides}
        for o in list_overrides(db)
    ]


@router.get("/users/{user_id}")
def get_user_override(user_id: str, db: Session = Depends(get_db)):
    override = get_override(db, user_id)
    if override is None:
        return {"user_id": user_id, "allow_unredacted": False, "tool_overrides": None}
    return {"user_id": user_id, "allow_unredacted": override.allow_unredacted, "tool_overrides": override.tool_overrides}


@router.put("/users/{user_id}")
def put_user_override(user_id: str, body: OverrideUpdate, db: Session = Depends(get_db)):
    row = set_override(db, user_id, body.allow_unredacted, body.tool_overrides)
    return {"user_id": row.user_id, "allow_unredacted": row.allow_unredacted, "tool_overrides": row.tool_overrides}


class ResetRequest(BaseModel):
    confirm: str


@router.post("/reset")
def reset_activity(body: ResetRequest, db: Session = Depends(get_db)):
    """Delete all recorded activity (audit records, trust state, token usage,
    user profiles) so a demo can start fresh. Policy settings -- thresholds,
    pack actions, overrides -- are kept. Requires {"confirm": "RESET"} so a
    stray request can't wipe the ledger; like the rest of /admin it has no
    auth (docs/adr/0005)."""
    if body.confirm != "RESET":
        raise HTTPException(status_code=400, detail='Send {"confirm": "RESET"} to delete all activity data.')
    deleted = {}
    for model in (Receipt, AgentTrustState, TokenUsageEvent, UserProfile):
        deleted[model.__tablename__] = db.query(model).delete()
    db.commit()
    vault.clear()  # placeholder mappings belong to the deleted sessions
    return {"deleted": deleted}



# ---------------------------------------------------------------------------
# Redaction options and roles (docs/adr/0016)
# ---------------------------------------------------------------------------

class IdentifierPolicyUpdate(BaseModel):
    action: Optional[Literal["redact", "block", "hash", "log_only"]] = None
    style: Optional[Literal["token", "partial", "masked"]] = None
    keep_last: Optional[int] = None
    restore_to_sender: Optional[bool] = None
    applies_to: Optional[Literal["both", "inbound", "outbound"]] = None


@router.get("/identifier-policy/{pack_id}")
def get_identifier_policy(pack_id: str, db: Session = Depends(get_db)):
    rows = db.query(CompliancePackConfig).filter(CompliancePackConfig.pack_id == pack_id).all()
    out = []
    for r in sorted(rows, key=lambda r: r.identifier):
        p = redaction.policy_for(db, pack_id, r.identifier)
        out.append({
            "identifier": r.identifier,
            "action": r.action,
            "style": p.style,
            "keep_last": p.keep_last,
            "restore_to_sender": p.restore_to_sender,
            "applies_to": p.applies_to,
            "placeholder": f"[{vault.label_for(r.identifier)}_1]",
        })
    return out


@router.put("/identifier-policy/{pack_id}/{identifier}")
def put_identifier_policy(pack_id: str, identifier: str, body: IdentifierPolicyUpdate, db: Session = Depends(get_db)):
    if body.keep_last is not None and not 0 <= body.keep_last <= 12:
        raise HTTPException(status_code=400, detail="keep_last must be between 0 and 12.")
    row = db.get(CompliancePackConfig, (pack_id, identifier))
    if row is None:
        row = CompliancePackConfig(pack_id=pack_id, identifier=identifier, action=body.action or "redact")
        db.add(row)
    if body.action is not None:
        row.action = body.action
    cfg = dict(row.config or {})
    for key in ("style", "keep_last", "restore_to_sender", "applies_to"):
        value = getattr(body, key)
        if value is not None:
            cfg[key] = value
    row.config = cfg
    db.commit()
    return get_identifier_policy(pack_id, db)


class RoleUpdate(BaseModel):
    label: str
    description: Optional[str] = None
    default_level: Literal["hidden", "partial", "full"] = "hidden"
    visibility: dict = {}


@router.get("/roles")
def list_roles(db: Session = Depends(get_db)):
    roles_mod.ensure_defaults(db)
    return [roles_mod.as_dict(r) for r in db.query(RedactionRole).order_by(RedactionRole.role_id).all()]


@router.put("/roles/{role_id}")
def put_role(role_id: str, body: RoleUpdate, db: Session = Depends(get_db)):
    bad = {k: v for k, v in body.visibility.items() if v not in roles_mod.LEVELS}
    if bad:
        raise HTTPException(status_code=400, detail=f"Visibility levels must be one of {', '.join(roles_mod.LEVELS)}.")
    roles_mod.ensure_defaults(db)
    row = db.get(RedactionRole, role_id)
    if row is None:
        row = RedactionRole(role_id=role_id, label=body.label)
        db.add(row)
    row.label, row.description, row.default_level, row.visibility = body.label, body.description, body.default_level, body.visibility
    db.commit()
    return roles_mod.as_dict(row)


@router.delete("/roles/{role_id}")
def delete_role(role_id: str, db: Session = Depends(get_db)):
    row = db.get(RedactionRole, role_id)
    if row is None:
        raise HTTPException(status_code=404, detail="No such role.")
    unassigned = db.query(UserRole).filter(UserRole.role_id == role_id).delete()
    db.delete(row)
    db.commit()
    return {"deleted": role_id, "users_unassigned": unassigned}


class UserRoleUpdate(BaseModel):
    role_id: Optional[str] = None


@router.get("/user-roles")
def list_user_roles(db: Session = Depends(get_db)):
    return [{"user_id": r.user_id, "role_id": r.role_id} for r in db.query(UserRole).order_by(UserRole.user_id).all()]


@router.put("/user-roles/{user_id}")
def put_user_role(user_id: str, body: UserRoleUpdate, db: Session = Depends(get_db)):
    roles_mod.ensure_defaults(db)
    row = db.get(UserRole, user_id)
    if body.role_id is None:
        if row is not None:
            db.delete(row)
            db.commit()
        return {"user_id": user_id, "role_id": None}
    if db.get(RedactionRole, body.role_id) is None:
        raise HTTPException(status_code=404, detail=f"No role '{body.role_id}'.")
    if row is None:
        row = UserRole(user_id=user_id, role_id=body.role_id)
        db.add(row)
    row.role_id = body.role_id
    db.commit()
    return {"user_id": user_id, "role_id": row.role_id}
