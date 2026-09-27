"""OpenAI-compatible reverse proxy.

This is the single-LLM-call integration point (docs/HACKATHON_PLAN.md,
Integration Contract option 1): point an existing OpenAI-compatible client's
`base_url` at this service and every prompt/completion is checked before it
reaches, or after it leaves, the real upstream LLM.

Run: `uvicorn main:app --port 8000` from inside this directory.
"""
import os
import sys
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

sys.path.append(str(Path(__file__).resolve().parents[1]))  # allow `import shared`
from shared.identity import new_session_id, new_agent_id  # noqa: E402

UPSTREAM_LLM_BASE_URL = os.getenv("UPSTREAM_LLM_BASE_URL", "https://api.openai.com/v1")
UPSTREAM_LLM_API_KEY = os.getenv("UPSTREAM_LLM_API_KEY", "")
GOVERNANCE_API_URL = os.getenv("GOVERNANCE_API_URL", "http://localhost:8001")

app = FastAPI(title="governance-proxy")


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    body = await request.json()

    # Identity is set here, by trusted proxy code -- never parsed from the
    # request body's message content (see docs/HACKATHON_PLAN.md hardening #2).
    user_id = request.headers.get("x-user-id", "anonymous")  # caller-supplied; no auth per non-goals
    session_id = request.headers.get("x-session-id") or new_session_id()
    agent_id = request.headers.get("x-agent-id") or new_agent_id()
    identity = {"user_id": user_id, "session_id": session_id, "agent_id": agent_id, "parent_agent_id": None}

    # Trusted request context, set here from a header -- NEVER parsed from the
    # prompt/completion text itself (that would let injected text grant its
    # own unredaction; see docs/adr/0005 and docs/HACKATHON_PLAN.md hardening #2).
    request_unredacted = request.headers.get("x-request-unredacted", "false").lower() == "true"

    prompt_text = _extract_prompt_text(body)

    async with httpx.AsyncClient(timeout=10.0) as client:
        # 1. Inbound compliance check
        compliance = _fail_closed(
            await client.post(
                f"{GOVERNANCE_API_URL}/governance/compliance-check",
                json={
                    "identity": identity,
                    "text": prompt_text,
                    "direction": "inbound",
                    "pack_id": "hipaa",
                    "request_unredacted": request_unredacted,
                },
            )
        )
        if compliance["verdict"] == "block":
            return JSONResponse(status_code=403, content={"error": "blocked_by_compliance", "violations": compliance.get("violations")})
        body = _apply_cleaned_text(body, compliance.get("cleaned_text", prompt_text))

        # 2. Forward to the real upstream LLM
        upstream_resp = await client.post(
            f"{UPSTREAM_LLM_BASE_URL}/chat/completions",
            json=body,
            headers={"Authorization": f"Bearer {UPSTREAM_LLM_API_KEY}"},
        )
        completion = upstream_resp.json()
        completion_text = _extract_completion_text(completion)

        # 3. Outbound compliance check
        outbound = _fail_closed(
            await client.post(
                f"{GOVERNANCE_API_URL}/governance/compliance-check",
                json={
                    "identity": identity,
                    "text": completion_text,
                    "direction": "outbound",
                    "pack_id": "hipaa",
                    "request_unredacted": request_unredacted,
                },
            )
        )
        if outbound["verdict"] == "block":
            return JSONResponse(status_code=403, content={"error": "blocked_by_compliance", "violations": outbound.get("violations")})
        completion = _apply_cleaned_text(completion, outbound.get("cleaned_text", completion_text))

    return completion


def _fail_closed(resp: httpx.Response) -> dict:
    """Any governance_api error is a block, never a silent allow."""
    if resp.status_code >= 400:
        return {"verdict": "block", "violations": ["governance_api_error"]}
    return resp.json()


def _extract_prompt_text(body: dict) -> str:
    # TODO: handle multi-message / multi-modal / tool-call payloads properly
    messages = body.get("messages", [])
    return " ".join(m.get("content", "") for m in messages if isinstance(m.get("content"), str))


def _extract_completion_text(completion: dict) -> str:
    choices = completion.get("choices", [])
    if not choices:
        return ""
    return choices[0].get("message", {}).get("content", "")


def _apply_cleaned_text(payload: dict, cleaned_text: str) -> dict:
    # TODO: write `cleaned_text` back into the right field of `payload`
    # (last user message on the way in, message content on the way out).
    return payload


@app.get("/healthz")
def healthz():
    return {"status": "ok"}
