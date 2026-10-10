"""Bench bridge: serves the GuardRailBench hook contract on :8080, backed by
governance_api (:8001). Lets GuardRailBench-Sample test THIS governance
runtime with zero changes on the bench side.

Run: `uvicorn main:app --port 8080` from inside this directory.
Env: GOVERNANCE_API_URL (default http://localhost:8001),
     BRIDGE_PACK_ID (default hipaa -- sample-edition bench data is
     name/phone/email, all covered by the HIPAA pack),
     BRIDGE_TIMEOUT (default 1.5s -- bench hooks time out after 2s).

Mapping (see GuardRailBench-Sample/docs/HOOK_CONTRACT.md):
  on_prompt_received      -> compliance-check direction=inbound  -> {"prompt": cleaned}
  on_completion_received  -> compliance-check direction=outbound -> {"completion": cleaned}
  on_tool_call            -> out-of-scope (tool not in agent_allowed_tools)
                             => deny immediately (this is what stops rogue_agent,
                             which declares an empty tool list);
                             else tool-check -> {"allow": bool}
  on_tool_result          -> compliance-check direction=outbound on the result
                             (tool output holds full DB rows incl. PHI) -> {"result": cleaned}
  on_session_end          -> recorded, returns {} (body is ignored by the bench)

Fail-closed throughout: if governance_api is unreachable, text hooks return
"" (blank, never a leak) and tool calls are denied.
"""
import itertools
import logging
import os
import sys
import time
import threading
from collections import OrderedDict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import httpx
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

sys.path.append(str(Path(__file__).resolve().parents[1]))  # allow `import governance_sdk`
from governance_sdk.governance_sdk.client import GovernanceClient  # noqa: E402
from data_pipeline.ingestion.token_usage_pipeline import ingest_event  # noqa: E402

log = logging.getLogger("bench_bridge")

GOVERNANCE_API_URL = os.getenv("GOVERNANCE_API_URL", "http://localhost:8001")
# Both packs at once: the full bench mixes HIPAA (SSN, MRN, dates) and DPDP
# (Aadhaar, PAN, UPI) data, often in the same document.
PACK_ID = os.getenv("BRIDGE_PACK_ID", "hipaa+dpdp")
# Host-app records the bridge reads consent from (DPDP); missing file = no sync.
CONSENT_DB = os.getenv("BRIDGE_CONSENT_DB", str(Path(__file__).resolve().parents[2] / "GuardRailBench-Sample" / "fake_data" / "patients.db"))
TIMEOUT = float(os.getenv("BRIDGE_TIMEOUT", "1.5"))

gov = GovernanceClient(base_url=GOVERNANCE_API_URL, timeout=TIMEOUT)

# Bench tool -> threshold, by HOOK_CONTRACT risk tier. Seeded into
# governance_api at startup ONLY for tools with no configured threshold
# (never clobbers values tuned via admin.html). Medium sits at 60 and high
# at 80, not 75/90: benign multi-agent workflows routinely cost ~20 points
# to the delegation cap (user PII in the request docks the orchestrator,
# children inherit it) plus low-confidence NER noise, so higher lines brick
# legitimate reads (scenario 1) and the reminder email itself.
BENCH_TOOL_THRESHOLDS = {
    "search_patients": 50.0,       # low
    "list_patients": 50.0,         # low
    "read_database": 60.0,         # medium
    "get_insurance_info": 60.0,    # medium
    "schedule_appointment": 60.0,  # medium
    "send_email": 80.0,            # high
}
# Destructive / irreversible: a threshold above 100 can never be earned, so
# these always need a human (tool_policy.approval_denial). Enforced on every
# start, unlike the seed-if-absent thresholds above.
APPROVAL_REQUIRED = {"delete_file": 101.0, "update_record": 101.0, "submit_claim": 101.0}

app = FastAPI(title="bench-bridge")

# Live feed for the dashboard's "Live bench" view: every hook the bench calls,
# with the outcome and the text AFTER governance cleaned it (never the raw
# input). In memory only -- it's a live view, the ledger is the record.
LIVE = deque(maxlen=int(os.getenv("BRIDGE_LIVE_EVENTS", "5000")))
_SEQ = itertools.count(1)
STARTED_AT = datetime.now(timezone.utc).isoformat()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        o.strip()
        for o in os.getenv(
            "DASHBOARD_ORIGINS",
            "http://localhost:8080,http://localhost:8081,http://127.0.0.1:8080,http://127.0.0.1:8081",
        ).split(",")
        if o.strip()
    ],
    allow_methods=["GET"],
)


def _record(hook: str, req: "HookIdentity", outcome: str, text: Optional[str] = None, tool: Optional[str] = None) -> None:
    LIVE.append({
        "seq": next(_SEQ),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "hook": hook,
        "user_id": req.user_id,
        "session_id": req.session_id,
        "agent_id": req.agent_id,
        "parent_agent_id": req.parent_agent_id,
        "tool": tool,
        "outcome": outcome,
        "text": text,
    })


def _verdict(res: dict) -> str:
    v = res.get("verdict") or "unknown"
    return "redact" if v == "hash" else v


class HookIdentity(BaseModel):
    user_id: str = "anonymous"
    agent_id: str = "unknown"
    session_id: str = "unknown"
    parent_agent_id: Optional[str] = None


class PromptHook(HookIdentity):
    prompt: str = ""


class CompletionHook(HookIdentity):
    completion: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0


class ToolCallHook(HookIdentity):
    tool_name: str = ""
    tool_args: dict = {}
    tool_risk: str = "medium"
    agent_allowed_tools: list = []


class ToolResultHook(HookIdentity):
    tool_name: str = ""
    result: str = ""
    tool_succeeded: bool = True
    latency_ms: int = 0


class SessionEndHook(HookIdentity):
    summary: dict = {}


def _identity(req: HookIdentity) -> dict:
    return {
        "user_id": req.user_id,
        "session_id": req.session_id,
        "agent_id": req.agent_id,
        "parent_agent_id": req.parent_agent_id,
    }


def _seed_thresholds(retries: int = 5, delay_s: float = 2.0) -> None:
    """Seed bench tool thresholds for tools that have none configured."""
    existing = None
    for attempt in range(retries):
        try:
            existing = httpx.get(f"{GOVERNANCE_API_URL}/admin/tool-thresholds", timeout=TIMEOUT).json()
            break
        except httpx.HTTPError as exc:
            log.warning("threshold seed attempt %d/%d failed: %s", attempt + 1, retries, exc)
            if attempt < retries - 1:
                time.sleep(delay_s)
    if existing is None:
        log.warning("threshold seed skipped, admin API unreachable")
        return
    have = {t["tool_id"]: t["threshold"] for t in existing}
    todo = {k: v for k, v in BENCH_TOOL_THRESHOLDS.items() if k not in have}
    todo.update({k: v for k, v in APPROVAL_REQUIRED.items() if have.get(k, 0) <= 100})
    for tool_id, threshold in todo.items():
        try:
            httpx.put(
                f"{GOVERNANCE_API_URL}/admin/tool-thresholds/{tool_id}",
                json={"threshold": threshold},
                timeout=TIMEOUT,
            )
            log.info("seeded threshold %s=%s", tool_id, threshold)
        except httpx.HTTPError as exc:
            log.warning("could not seed threshold %s: %s", tool_id, exc)


def _sync_consent() -> None:
    """Push the host app's non-consented data principals into governance's
    consent registry, keyed by email and by name (DPDP)."""
    import sqlite3

    if not os.path.exists(CONSENT_DB):
        log.info("consent sync skipped: %s not found", CONSENT_DB)
        return
    try:
        conn = sqlite3.connect(f"file:{CONSENT_DB}?mode=ro", uri=True)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(patients)")}
        if not {"name", "email", "consent_status"} <= cols:
            return
        purpose = "consent_purpose" if "consent_purpose" in cols else "''"
        mrn = "mrn" if "mrn" in cols else "''"
        rows = conn.execute(f"SELECT name, email, consent_status, {purpose}, {mrn} FROM patients WHERE upper(consent_status) != 'GIVEN'").fetchall()
        conn.close()
    except sqlite3.Error as exc:
        log.warning("consent sync failed: %s", exc)
        return
    for name, email, status, purpose_value, mrn_value in rows:
        for subject in filter(None, (email, name, mrn_value)):
            try:
                httpx.put(f"{GOVERNANCE_API_URL}/admin/consent/{subject}", json={"status": status, "label": name, "purpose": purpose_value, "source": "GuardRailBench patients"}, timeout=TIMEOUT)
            except httpx.HTTPError as exc:
                log.warning("could not sync consent for %s: %s", name, exc)
                return
    log.info("synced consent for %d data principals", len(rows))


@app.on_event("startup")
def on_startup() -> None:
    _seed_thresholds()
    _sync_consent()


@app.get("/healthz")
def healthz():
    return {"status": "ok", "pack_id": PACK_ID, "governance_api": GOVERNANCE_API_URL}


@app.get("/live/events")
def live_events(after: int = Query(0, ge=0), limit: int = Query(500, ge=1, le=2000)):
    events = [e for e in LIVE if e["seq"] > after][:limit]
    last = LIVE[-1]["seq"] if LIVE else 0
    return {"events": events, "last_seq": last, "bridge_started_at": STARTED_AT}


_seen_sessions: "OrderedDict[str, None]" = OrderedDict()
_seen_lock = threading.Lock()


def _is_user_message(req) -> bool:
    """The first prompt of a session from a root agent is the end user's own
    message (later root prompts carry sub-agent replies)."""
    if req.parent_agent_id:
        return False
    with _seen_lock:
        if req.session_id in _seen_sessions:
            return False
        _seen_sessions[req.session_id] = None
        while len(_seen_sessions) > 10_000:
            _seen_sessions.popitem(last=False)
        return True


@app.post("/api/v1/on_prompt_received")
def on_prompt_received(req: PromptHook):
    # A name / email / MRN the user typed is the key the agents need to find
    # the record; it passes through for this session only, every other
    # identifier (and anything the user did not type) is masked.
    res = gov.check_compliance(_identity(req), req.prompt, "inbound", PACK_ID,
                               restore_to_sender=_is_user_message(req), pass_sender_keys=True)
    cleaned = res.get("cleaned_text") or ""
    _record("on_prompt_received", req, _verdict(res), cleaned or res.get("reason"))
    return {"prompt": cleaned}


@app.post("/api/v1/on_completion_received")
def on_completion_received(req: CompletionHook):
    res = gov.check_compliance(_identity(req), req.completion, "outbound", PACK_ID)
    # Token accounting for the dashboard's per-user/per-session usage. It's
    # bookkeeping, not a verdict: a DB hiccup here must never change what the
    # hook returns (fail-closed applies to decisions, not to accounting).
    try:
        ingest_event(req.user_id, req.session_id, req.agent_id,
                     tokens_in=req.prompt_tokens, tokens_out=req.completion_tokens)
    except Exception as exc:  # noqa: BLE001
        log.warning("token usage not recorded for session=%s: %s", req.session_id, exc)
    cleaned = res.get("cleaned_text") or ""
    _record("on_completion_received", req, _verdict(res), cleaned or res.get("reason"))
    return {"completion": cleaned}


@app.post("/api/v1/on_tool_call")
def on_tool_call(req: ToolCallHook):
    # Every call goes through governance -- scope, approval, score and the
    # call's arguments -- so each decision, deny included, gets a receipt.
    res = gov.check_tool(_identity(req), req.tool_name, tool_args=req.tool_args, declared_tools=req.agent_allowed_tools or [])
    allowed = bool(res.get("allowed", False))
    detail = res.get("reason") or (f"score {res.get('current_score')} against threshold {res.get('required_threshold')}" if "current_score" in res else None)
    _record("on_tool_call", req, "allow" if allowed else "deny", detail, tool=req.tool_name)
    return {"allow": allowed}


@app.post("/api/v1/on_tool_result")
def on_tool_result(req: ToolResultHook):
    # apply_score=False: the PHI here is in retrieved DATA the agent was
    # authorized to read, not agent misbehavior. Still redacted before it
    # travels onward to the agent/LLM -- just not charged to the score.
    res = gov.check_compliance(_identity(req), req.result, "outbound", PACK_ID, apply_score=False)
    cleaned = res.get("cleaned_text") or ""
    _record("on_tool_result", req, _verdict(res), cleaned or res.get("reason"), tool=req.tool_name)
    return {"result": cleaned}


@app.post("/api/v1/on_session_end")
def on_session_end(req: SessionEndHook):
    log.info(
        "session_end user=%s session=%s agents=%s tools_blocked=%s",
        req.user_id,
        req.session_id,
        req.summary.get("agents_involved"),
        req.summary.get("tools_blocked"),
    )
    summary = req.summary or {}
    _record("on_session_end", req, "end", ", ".join(f"{k.replace('_', ' ')} {v}" for k, v in summary.items() if isinstance(v, (int, float))) or None)
    return {}


# Allow `uv run python main.py` as an alternative to uvicorn CLI.
if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port)
