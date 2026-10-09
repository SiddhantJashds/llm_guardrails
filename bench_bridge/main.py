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
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Optional

import httpx
from fastapi import FastAPI
from pydantic import BaseModel

sys.path.append(str(Path(__file__).resolve().parents[1]))  # allow `import governance_sdk`
from governance_sdk.governance_sdk.client import GovernanceClient  # noqa: E402

log = logging.getLogger("bench_bridge")

GOVERNANCE_API_URL = os.getenv("GOVERNANCE_API_URL", "http://localhost:8001")
PACK_ID = os.getenv("BRIDGE_PACK_ID", "hipaa")
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
    "update_record": 60.0,         # medium
    "get_insurance_info": 60.0,    # medium
    "schedule_appointment": 60.0,  # medium
    "delete_file": 80.0,           # high
    "send_email": 80.0,            # high
    "submit_claim": 80.0,          # high
}

app = FastAPI(title="bench-bridge")


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
    have = {t["tool_id"] for t in existing}
    for tool_id, threshold in BENCH_TOOL_THRESHOLDS.items():
        if tool_id in have:
            continue
        try:
            httpx.put(
                f"{GOVERNANCE_API_URL}/admin/tool-thresholds/{tool_id}",
                json={"threshold": threshold},
                timeout=TIMEOUT,
            )
            log.info("seeded threshold %s=%s", tool_id, threshold)
        except httpx.HTTPError as exc:
            log.warning("could not seed threshold %s: %s", tool_id, exc)


@app.on_event("startup")
def on_startup() -> None:
    _seed_thresholds()


@app.get("/healthz")
def healthz():
    return {"status": "ok", "pack_id": PACK_ID, "governance_api": GOVERNANCE_API_URL}


@app.post("/api/v1/on_prompt_received")
def on_prompt_received(req: PromptHook):
    res = gov.check_compliance(_identity(req), req.prompt, "inbound", PACK_ID)
    return {"prompt": res.get("cleaned_text") or ""}


@app.post("/api/v1/on_completion_received")
def on_completion_received(req: CompletionHook):
    res = gov.check_compliance(_identity(req), req.completion, "outbound", PACK_ID)
    return {"completion": res.get("cleaned_text") or ""}


@app.post("/api/v1/on_tool_call")
def on_tool_call(req: ToolCallHook):
    if req.tool_name not in (req.agent_allowed_tools or []):
        log.info("out-of-scope deny: agent=%s tool=%s", req.agent_id, req.tool_name)
        return {"allow": False}
    res = gov.check_tool(_identity(req), req.tool_name)
    return {"allow": bool(res.get("allowed", False))}


@app.post("/api/v1/on_tool_result")
def on_tool_result(req: ToolResultHook):
    # apply_score=False: the PHI here is in retrieved DATA the agent was
    # authorized to read, not agent misbehavior. Still redacted before it
    # travels onward to the agent/LLM -- just not charged to the score.
    res = gov.check_compliance(_identity(req), req.result, "outbound", PACK_ID, apply_score=False)
    return {"result": res.get("cleaned_text") or ""}


@app.post("/api/v1/on_session_end")
def on_session_end(req: SessionEndHook):
    log.info(
        "session_end user=%s session=%s agents=%s tools_blocked=%s",
        req.user_id,
        req.session_id,
        req.summary.get("agents_involved"),
        req.summary.get("tools_blocked"),
    )
    return {}


# Allow `uv run python main.py` as an alternative to uvicorn CLI.
if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port)
