"""Pure helpers that turn ledger rows into dashboard-shaped JSON.

No DB access here -- routes/dashboard.py queries, these shape. Kept pure so
the tricky bits (UTC serialization, reason parsing, trust trajectories,
activity buckets) are unit-tested without a database.
"""
import math
from datetime import datetime, timezone
from typing import Iterable, Optional

OUTCOMES = ("allow", "redact", "block", "deny", "log_only")
_FLAGS = {"redact", "block", "deny"}
_BUCKET_SIZES = (60, 300, 900, 1800, 3600, 10800, 21600, 43200, 86400)
_INJECTION_PREFIX = "injection_detected:"


def _as_utc(dt: datetime) -> datetime:
    # SQLite drops tzinfo on the way back out, but every timestamp the models
    # write is UTC (shared/models.py `_now`), so naive means UTC here.
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def iso_utc(dt: Optional[datetime]) -> Optional[str]:
    return None if dt is None else _as_utc(dt).isoformat()


def parse_identifiers(reason: Optional[str]) -> list:
    """Identifier types from a compliance reason, e.g.
    "phone_number, full_name [unredacted_override_applied: user_id=x]; injection_detected: role_claim"
    -> ["phone_number", "full_name", "injection:role_claim"]."""
    if not reason:
        return []
    found = []
    for part in reason.split(";"):
        part = part.strip()
        if part.startswith(_INJECTION_PREFIX):
            found += [f"injection:{h.strip()}" for h in part[len(_INJECTION_PREFIX):].split(",") if h.strip()]
        else:
            found += [p.strip() for p in part.split(" [", 1)[0].split(",") if p.strip()]
    return found


def identifier_counts(reasons: Iterable[Optional[str]]) -> list:
    counts: dict = {}
    for reason in reasons:
        for kind in parse_identifiers(reason):
            counts[kind] = counts.get(kind, 0) + 1
    return [{"type": k, "count": n} for k, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]


def outcome(decision_type: str, verdict: str) -> str:
    if verdict == "hash":
        return "redact"
    if decision_type == "authority":
        return "deny" if verdict == "deny" else "allow"
    return verdict


def is_flag(o: str) -> bool:
    return o in _FLAGS


def trajectory(current_score: Optional[float], history: Optional[list]) -> dict:
    """Replay an agent's score from its real starting point.

    Delegation capping sets a child's starting score without a history
    entry, so replaying deltas from 100 is wrong; back-computing the start
    from the current score is exact -- unless the 0 floor clipped a delta,
    which is flagged as approximate.
    """
    if current_score is None:
        return {"initial_score": None, "points": [], "approximate": False}
    history = history or []
    deltas = [float(h.get("delta") or 0.0) for h in history]
    initial = min(100.0, current_score - sum(deltas))
    points = [{"score": initial, "signal": "start", "delta": 0.0}]
    score = initial
    for h, d in zip(history, deltas):
        score = max(0.0, score + d)
        points.append({"score": score, "signal": h.get("signal"), "delta": d})
    return {"initial_score": initial, "points": points, "approximate": current_score == 0.0 and bool(history)}


def activity_buckets(rows: list, max_buckets: int = 60) -> dict:
    """(timestamp, outcome) rows -> at most `max_buckets` time buckets, each
    counting every outcome. Bucket size is the smallest "nice" size that fits."""
    if not rows:
        return {"bucket_seconds": 60, "buckets": []}
    times = [_as_utc(t).timestamp() for t, _ in rows]
    first, last = min(times), max(times)
    span = max(60.0, last - first)
    size = next((s for s in _BUCKET_SIZES if math.ceil(span / s) + 1 <= max_buckets), None)
    if size is None:
        size = math.ceil(span / (max_buckets - 1))
    start0 = math.floor(first / size) * size
    count = int((last - start0) // size) + 1
    buckets = [
        {"start": iso_utc(datetime.fromtimestamp(start0 + i * size, tz=timezone.utc)), **{o: 0 for o in OUTCOMES}}
        for i in range(count)
    ]
    for ts, (_, o) in zip(times, rows):
        buckets[int((ts - start0) // size)][o if o in OUTCOMES else "allow"] += 1
    return {"bucket_seconds": size, "buckets": buckets}


def receipt_item(r) -> dict:
    o = outcome(r.decision_type, r.verdict)
    return {
        "receipt_id": r.receipt_id,
        "timestamp": iso_utc(r.timestamp),
        "user_id": r.user_id,
        "session_id": r.session_id,
        "agent_id": r.agent_id,
        "parent_agent_id": r.parent_agent_id,
        "decision_type": r.decision_type,
        "verdict": r.verdict,
        "outcome": o,
        "reason": r.reason,
        "identifiers": identifier_counts([r.reason]) if r.decision_type == "compliance" else [],
        "ref_id": r.ref_id,
        "hash": r.hash,
        "prev_hash": r.prev_hash,
        **message_fields(r),
    }


def message_fields(r) -> dict:
    """direction / kind / redacted text from a compliance receipt's payload.
    kind: "input" (inbound prompt, incl. RAG context), "output" (model or
    agent answer), "tool_result" (outbound scan that isn't charged to the
    agent), or None for receipts without stored text."""
    p = r.payload if isinstance(r.payload, dict) else {}
    direction = p.get("direction")
    kind = None
    if direction == "inbound":
        kind = "input"
    elif direction == "outbound":
        kind = "output" if p.get("scored", True) else "tool_result"
    return {"direction": direction, "kind": kind, "text": p.get("text"), "blocked": r.verdict == "block"}


def conversation(receipts: list) -> list:
    """Compliance receipts with stored text, in order, as conversation turns.
    Memory-mode clients resend the whole history every turn, so a text
    already shown for the same agent is skipped instead of repeated."""
    turns, seen = [], set()
    for r in receipts:
        if r.decision_type != "compliance":
            continue
        m = message_fields(r)
        if m["kind"] is None or (m["text"] is None and not m["blocked"]):
            continue
        key = (r.agent_id, m["text"])
        if m["text"] is not None and key in seen:
            continue
        seen.add(key)
        turns.append({
            "receipt_id": r.receipt_id,
            "timestamp": iso_utc(r.timestamp),
            "agent_id": r.agent_id,
            "parent_agent_id": r.parent_agent_id,
            "user_id": r.user_id,
            "outcome": outcome(r.decision_type, r.verdict),
            "identifiers": identifier_counts([r.reason]),
            **m,
        })
    return turns
