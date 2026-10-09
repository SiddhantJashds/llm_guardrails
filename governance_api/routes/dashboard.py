"""Read-only dashboard API. The dashboard/ frontend calls these directly.

Detail views (`/session/{id}`, `/user/{id}`) filter by the path id in the
query itself (docs/HACKATHON_PLAN.md hardening #8). List views give the same
admin-level visibility the admin page already has (docs/adr/0005: no auth).
Shaping lives in insights/shaping.py; this module only queries and groups.
"""
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

sys.path.append(str(Path(__file__).resolve().parents[2]))  # allow `import shared` / `import data_pipeline`
from shared.db import get_db  # noqa: E402
from shared.models import AgentTrustState, Receipt, TokenUsageEvent  # noqa: E402
from data_pipeline.aggregation.user_profile_job import profile_from_rows  # noqa: E402
from data_pipeline.ledger.verify_chain import check_chain  # noqa: E402

from insights.bench_reports import bench_reports_dir, list_runs, load_hooks, load_run  # noqa: E402
from insights.shaping import (  # noqa: E402
    OUTCOMES,
    activity_buckets,
    conversation,
    identifier_counts,
    is_flag,
    iso_utc,
    outcome,
    receipt_item,
    trajectory,
)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

_EPOCH = datetime.min


def _outcome_counts(receipts) -> dict:
    counts = {o: 0 for o in OUTCOMES}
    for r in receipts:
        o = outcome(r.decision_type, r.verdict)
        counts[o if o in counts else "allow"] += 1
    return counts


def _span(receipts, tokens):
    times = [r.timestamp for r in receipts if r.timestamp] + [t.timestamp for t in tokens if t.timestamp]
    return (min(times), max(times)) if times else (None, None)


def _session_summary(session_id: str, receipts: list, states: list, tokens: list) -> dict:
    counts = _outcome_counts(receipts)
    user_ids = list(dict.fromkeys([r.user_id for r in receipts] + [t.user_id for t in tokens]))
    agents = list(dict.fromkeys([r.agent_id for r in receipts] + [s.agent_id for s in states] + [t.agent_id for t in tokens]))
    scores = [s.current_score for s in states if s.current_score is not None]
    first, last = _span(receipts, tokens)
    return {
        "session_id": session_id,
        "user_id": user_ids[0] if user_ids else None,
        "user_ids": user_ids,
        "agents": agents,
        "decisions": len(receipts),
        "redactions": counts["redact"],
        "blocks": counts["block"],
        "denials": counts["deny"],
        "flags": counts["redact"] + counts["block"] + counts["deny"],
        "min_score": min(scores) if scores else None,
        "tokens_in": sum(t.tokens_in or 0 for t in tokens),
        "tokens_out": sum(t.tokens_out or 0 for t in tokens),
        "first_seen": iso_utc(first),
        "last_seen": iso_utc(last),
        "_last": last or _EPOCH,
        "chain_ok": check_chain(receipts)["ok"] if receipts else None,
    }


def _public(summary: dict) -> dict:
    return {k: v for k, v in summary.items() if not k.startswith("_")}


def _group_sessions(receipts, states, tokens) -> list:
    """Every session that left any trace (receipt, trust state, or token
    event), newest activity first. Receipts must arrive in timestamp order."""
    by_r, by_s, by_t = defaultdict(list), defaultdict(list), defaultdict(list)
    for r in receipts:
        by_r[r.session_id].append(r)
    for s in states:
        by_s[s.session_id].append(s)
    for t in tokens:
        by_t[t.session_id].append(t)
    ids = set(by_r) | set(by_s) | set(by_t)
    summaries = [_session_summary(sid, by_r[sid], by_s[sid], by_t[sid]) for sid in ids]
    return sorted(summaries, key=lambda s: s["_last"], reverse=True)


def _all(db: Session):
    receipts = db.query(Receipt).order_by(Receipt.timestamp).all()
    states = db.query(AgentTrustState).all()
    tokens = db.query(TokenUsageEvent).order_by(TokenUsageEvent.timestamp).all()
    return receipts, states, tokens


@router.get("/config")
def config():
    d = bench_reports_dir()
    return {
        "proxy_url": os.getenv("PROXY_PUBLIC_URL", "http://localhost:8000"),
        "chat_model": os.getenv("CHAT_MODEL", "nvidia/Qwen3.6-35B-A3B-NVFP4"),
        "bridge_url": os.getenv("BRIDGE_PUBLIC_URL", "http://localhost:8080"),
        "bench_available": d.is_dir(),
        "bench_dir": str(d),
    }


@router.get("/overview")
def overview(db: Session = Depends(get_db)):
    receipts, states, tokens = _all(db)
    counts = _outcome_counts(receipts)
    sessions = _group_sessions(receipts, states, tokens)

    by_session = defaultdict(list)
    for r in receipts:
        by_session[r.session_id].append(r)
    broken = []
    for sid, rows in by_session.items():
        result = check_chain(rows)
        if not result["ok"]:
            broken.append({"session_id": sid, "receipt_id": result["broken_receipt_id"], "problem": result["problem"]})

    users = {r.user_id for r in receipts} | {t.user_id for t in tokens}
    agents = {(r.session_id, r.agent_id) for r in receipts} | {(s.session_id, s.agent_id) for s in states}
    return {
        "generated_at": iso_utc(datetime.now(timezone.utc)),
        "totals": {
            "decisions": len(receipts),
            "allows": counts["allow"],
            "redactions": counts["redact"],
            "blocks": counts["block"],
            "denials": counts["deny"],
            "log_only": counts["log_only"],
            "sessions": len(sessions),
            "users": len(users),
            "agents": len(agents),
            "tokens_in": sum(t.tokens_in or 0 for t in tokens),
            "tokens_out": sum(t.tokens_out or 0 for t in tokens),
        },
        "identifiers": identifier_counts(r.reason for r in receipts if r.decision_type == "compliance")[:12],
        "activity": activity_buckets([(r.timestamp, outcome(r.decision_type, r.verdict)) for r in receipts]),
        "chain": {"sessions_checked": len(by_session), "sessions_ok": len(by_session) - len(broken), "broken": broken},
        "recent_sessions": [_public(s) for s in sessions[:8]],
    }


@router.get("/feed")
def feed(limit: int = Query(50, ge=1, le=200), db: Session = Depends(get_db)):
    rows = db.query(Receipt).order_by(Receipt.timestamp.desc()).limit(limit).all()
    return {"items": [receipt_item(r) for r in rows]}


@router.get("/sessions")
def sessions(
    q: Optional[str] = None,
    user_id: Optional[str] = None,
    flagged: bool = False,
    limit: int = Query(200, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    items = _group_sessions(*_all(db))
    if user_id:
        items = [s for s in items if user_id in s["user_ids"]]
    if flagged:
        items = [s for s in items if s["flags"]]
    if q:
        needle = q.lower()
        items = [
            s for s in items
            if needle in s["session_id"].lower() or any(needle in (x or "").lower() for x in s["user_ids"] + s["agents"])
        ]
    return {"items": [_public(s) for s in items[:limit]], "total": len(items)}


@router.get("/users")
def users(q: Optional[str] = None, limit: int = Query(200, ge=1, le=1000), db: Session = Depends(get_db)):
    receipts, _, tokens = _all(db)
    by_r, by_t = defaultdict(list), defaultdict(list)
    for r in receipts:
        by_r[r.user_id].append(r)
    for t in tokens:
        by_t[t.user_id].append(t)
    items = []
    for uid in set(by_r) | set(by_t):
        rows, toks = by_r[uid], by_t[uid]
        counts = _outcome_counts(rows)
        tin, tout = sum(t.tokens_in or 0 for t in toks), sum(t.tokens_out or 0 for t in toks)
        _, last = _span(rows, toks)
        items.append({
            "user_id": uid,
            "sessions": len({r.session_id for r in rows} | {t.session_id for t in toks}),
            "decisions": len(rows),
            "redactions": counts["redact"],
            "blocks": counts["block"],
            "denials": counts["deny"],
            "tokens_in": tin,
            "tokens_out": tout,
            "composite_rating": profile_from_rows(tin, tout, rows)["composite_rating"],
            "last_seen": iso_utc(last),
            "_last": last or _EPOCH,
        })
    if q:
        items = [u for u in items if q.lower() in (u["user_id"] or "").lower()]
    items.sort(key=lambda u: u["_last"], reverse=True)
    return {"items": [_public(u) for u in items[:limit]], "total": len(items)}


@router.get("/ledger")
def ledger(
    decision_type: Optional[str] = None,
    verdict: Optional[str] = None,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    query = db.query(Receipt)
    for column, value in (
        (Receipt.decision_type, decision_type),
        (Receipt.verdict, verdict),
        (Receipt.user_id, user_id),
        (Receipt.session_id, session_id),
        (Receipt.agent_id, agent_id),
    ):
        if value:
            query = query.filter(column == value)
    if q:
        query = query.filter(or_(Receipt.reason.contains(q), Receipt.ref_id.contains(q)))
    total = query.count()
    rows = query.order_by(Receipt.timestamp.desc()).offset(offset).limit(limit).all()
    return {"items": [receipt_item(r) for r in rows], "total": total, "limit": limit, "offset": offset}


def _agent_order(agents: dict) -> list:
    """Delegation-tree DFS: roots first, children under their parent, each
    level by first activity."""
    children = defaultdict(list)
    roots = []
    for a in agents.values():
        parent = a["parent_agent_id"]
        (children[parent] if parent in agents and parent != a["agent_id"] else roots).append(a)
    ordered = []

    def visit(node, depth):
        node["depth"] = depth
        ordered.append(node)
        for child in sorted(children[node["agent_id"]], key=lambda c: c["_first"]):
            visit(child, depth + 1)

    for root in sorted(roots, key=lambda a: a["_first"]):
        visit(root, 0)
    return ordered


@router.get("/session/{session_id}")
def session_dashboard(session_id: str, db: Session = Depends(get_db)):
    receipts = db.query(Receipt).filter(Receipt.session_id == session_id).order_by(Receipt.timestamp).all()
    states = db.query(AgentTrustState).filter(AgentTrustState.session_id == session_id).all()
    tokens = db.query(TokenUsageEvent).filter(TokenUsageEvent.session_id == session_id).all()

    agents: dict = {}

    def bucket(agent_id: str, parent: Optional[str], first) -> dict:
        if agent_id not in agents:
            agents[agent_id] = {
                "agent_id": agent_id,
                "parent_agent_id": parent,
                "current_score": None,
                "initial_score": None,
                "trajectory": [],
                "approximate": False,
                "history": [],
                "violations": [],
                "denied_calls": [],
                "decisions": 0,
                "flags": 0,
                "tokens_in": 0,
                "tokens_out": 0,
                "_first": first or _EPOCH,
            }
        a = agents[agent_id]
        if a["parent_agent_id"] is None and parent:
            a["parent_agent_id"] = parent
        return a

    for s in states:
        a = bucket(s.agent_id, s.parent_agent_id, s.last_updated)
        t = trajectory(s.current_score, s.history)
        a.update(current_score=s.current_score, history=s.history or [], initial_score=t["initial_score"],
                 trajectory=t["points"], approximate=t["approximate"])
    for r in receipts:
        a = bucket(r.agent_id, r.parent_agent_id, r.timestamp)
        a["_first"] = min(a["_first"], r.timestamp) if a["_first"] is not _EPOCH else r.timestamp
        a["decisions"] += 1
        o = outcome(r.decision_type, r.verdict)
        if is_flag(o):
            a["flags"] += 1
        entry = {"reason": r.reason, "timestamp": iso_utc(r.timestamp), "receipt_id": r.receipt_id}
        if r.decision_type == "compliance" and is_flag(o):
            a["violations"].append({**entry, "identifiers": identifier_counts([r.reason])})
        if r.decision_type == "authority" and r.verdict == "deny":
            a["denied_calls"].append({**entry, "tool": r.ref_id})
    for t in tokens:
        a = bucket(t.agent_id, None, t.timestamp)
        a["tokens_in"] += t.tokens_in or 0
        a["tokens_out"] += t.tokens_out or 0

    counts = _outcome_counts(receipts)
    first, last = _span(receipts, tokens)
    return {
        "session_id": session_id,
        "user_ids": list(dict.fromkeys([r.user_id for r in receipts] + [t.user_id for t in tokens])),
        "first_seen": iso_utc(first),
        "last_seen": iso_utc(last),
        "decisions": len(receipts),
        "redactions": counts["redact"],
        "blocks": counts["block"],
        "denials": counts["deny"],
        "tokens_in": sum(t.tokens_in or 0 for t in tokens),
        "tokens_out": sum(t.tokens_out or 0 for t in tokens),
        "identifiers": identifier_counts(r.reason for r in receipts if r.decision_type == "compliance"),
        "chain": check_chain(receipts),
        "timeline": [receipt_item(r) for r in receipts],
        "conversation": conversation(receipts),
        "agents": [_public(a) for a in _agent_order(agents)],
    }


@router.get("/user/{user_id}")
def user_dashboard(user_id: str, db: Session = Depends(get_db)):
    # Server-side filter by user_id -- never trust a client-supplied override
    # (docs/HACKATHON_PLAN.md hardening #8).
    receipts = db.query(Receipt).filter(Receipt.user_id == user_id).order_by(Receipt.timestamp).all()
    tokens = db.query(TokenUsageEvent).filter(TokenUsageEvent.user_id == user_id).order_by(TokenUsageEvent.timestamp).all()
    session_ids = {r.session_id for r in receipts} | {t.session_id for t in tokens}
    states = db.query(AgentTrustState).filter(AgentTrustState.session_id.in_(session_ids)).all() if session_ids else []

    tin, tout = sum(t.tokens_in or 0 for t in tokens), sum(t.tokens_out or 0 for t in tokens)
    return {
        "user_id": user_id,
        "profile": profile_from_rows(tin, tout, receipts),
        "recent_decisions": [
            {
                "verdict": r.verdict,
                "decision_type": r.decision_type,
                "timestamp": iso_utc(r.timestamp),
                "reason": r.reason,
                "outcome": outcome(r.decision_type, r.verdict),
                "session_id": r.session_id,
                "agent_id": r.agent_id,
                "identifiers": identifier_counts([r.reason]) if r.decision_type == "compliance" else [],
            }
            for r in receipts[-50:]
        ],
        "sessions": [_public(s) for s in _group_sessions(receipts, states, tokens)],
        "token_series": [
            {"timestamp": iso_utc(t.timestamp), "tokens_in": t.tokens_in or 0, "tokens_out": t.tokens_out or 0,
             "session_id": t.session_id, "agent_id": t.agent_id}
            for t in tokens
        ],
        # Kept for the per-user token chart contract (last 50 upstream calls).
        "token_usage": [
            {"timestamp": iso_utc(t.timestamp), "tokens_in": t.tokens_in or 0, "tokens_out": t.tokens_out or 0}
            for t in tokens[-50:]
        ],
        "outcomes": _outcome_counts(receipts),
    }


@router.get("/bench/runs")
def bench_runs():
    d = bench_reports_dir()
    return {"available": d.is_dir(), "dir": str(d), "items": list_runs(d)}


@router.get("/bench/runs/{name}")
def bench_run(name: str):
    run = load_run(bench_reports_dir(), name)
    if run is None:
        raise HTTPException(status_code=404, detail="no such bench report")
    return run


@router.get("/bench/runs/{name}/scenarios/{index}/hooks")
def bench_run_hooks(name: str, index: int):
    hooks = load_hooks(bench_reports_dir(), name, index)
    if hooks is None:
        raise HTTPException(status_code=404, detail="no such bench scenario")
    return {"items": hooks}
