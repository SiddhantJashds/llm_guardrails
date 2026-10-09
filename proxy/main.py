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

# ── auto-load .env from repo root so env vars are always available ──
# We always run uvicorn from inside proxy/, so the repo root is one level up.
# Use cwd (guaranteed to be proxy/) → parent = repo root, not __file__ which
# may resolve differently depending on how uvicorn imports the module.
_REPO_ROOT = str(Path.cwd().parent)
_ENV_PATH = os.path.join(_REPO_ROOT, ".env")
if os.path.isfile(_ENV_PATH):
    with open(_ENV_PATH) as _f:
        for line in _f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip()
                os.environ[key] = value

import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

sys.path.append(str(Path(__file__).resolve().parents[1]))  # allow `import shared`
from shared.identity import new_session_id, new_agent_id  # noqa: E402

sys.path.append(str(Path(__file__).resolve().parents[2]))  # allow `import data_pipeline`
from data_pipeline.ingestion.token_usage_pipeline import ingest_event  # noqa: E402

UPSTREAM_LLM_BASE_URL = os.getenv("UPSTREAM_LLM_BASE_URL", "https://api.openai.com/v1")
UPSTREAM_LLM_API_KEY = os.getenv("UPSTREAM_LLM_API_KEY", "")
GOVERNANCE_API_URL = os.getenv("GOVERNANCE_API_URL", "http://localhost:8001")

app = FastAPI(title="governance-proxy")


@app.middleware("http")
async def debug_request(request: Request, call_next):
    if request.url.path == "/v1/chat/completions":
        print(f"[DEBUG] {request.method} {request.url.path} cl={request.headers.get('content-length')} ct={request.headers.get('content-type')}")
    try:
        return await call_next(request)
    except Exception as exc:
        import traceback
        print(f"[DEBUG EXC] {request.url.path}: {exc}")
        traceback.print_exc()
        return JSONResponse(status_code=500, content={"error": str(exc)})


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    try:
        body = await request.json()
    except Exception as exc:
        print(f"[DEBUG JSON ERROR] {exc}")
        return JSONResponse(status_code=400, content={"error": f"invalid_json: {exc}"})

    print(f"[DEBUG] body model={body.get('model')} messages={len(body.get('messages',[]))}")

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

    async with httpx.AsyncClient(timeout=10.0) as client:
        async def check(text: str, direction: str) -> dict:
            print(f"[DEBUG] compliance-check dir={direction} text_len={len(text)}")
            return _fail_closed(
                await client.post(
                    f"{GOVERNANCE_API_URL}/governance/compliance-check",
                    json={
                        "identity": identity,
                        "text": text,
                        "direction": direction,
                        "pack_id": "hipaa",
                        "request_unredacted": request_unredacted,
                    },
                )
            )

        # 1. Inbound compliance check
        segments = _prompt_segments(body)
        print(f"[DEBUG] step1: inbound check, segments={len(segments)}")
        cleaned_parts = []
        for _, (_kind, _idx, text) in segments:
            result = await check(text, "inbound")
            print(f"[DEBUG] compliance verdict={result['verdict']}")
            if result["verdict"] == "block":
                return _blocked(result)
            cleaned_parts.append(result.get("cleaned_text", text))
        try:
            body = _apply_cleaned_prompt(body, segments, cleaned_parts)
        except ValueError:
            print(f"[DEBUG] step1: apply_cleaned_prompt FAILED")
            return _cannot_apply_cleaned_text()
        print(f"[DEBUG] step1 done")

        # 2. Forward to the real upstream LLM
        print(f"[DEBUG] step2: forward to upstream {UPSTREAM_LLM_BASE_URL}")
        upstream_resp = await client.post(
            f"{UPSTREAM_LLM_BASE_URL}/chat/completions",
            json=body,
            headers={"Authorization": f"Bearer {UPSTREAM_LLM_API_KEY}"},
        )
        print(f"[DEBUG] upstream status={upstream_resp.status_code}")
        try:
            completion = upstream_resp.json()
        except ValueError:
            return JSONResponse(status_code=502, content={"error": "upstream_invalid_response"})
        if upstream_resp.status_code >= 400:
            print(f"[DEBUG] upstream error body={upstream_resp.text[:200]}")
            return JSONResponse(status_code=upstream_resp.status_code, content=completion)

        # Ingest token usage for per-user tracking
        usage = completion.get("usage", {})
        ingest_event(identity["user_id"], identity["session_id"], identity["agent_id"],
                     tokens_in=usage.get("prompt_tokens", 0) or 0,
                     tokens_out=usage.get("completion_tokens", 0) or 0)

        # 3. Outbound compliance check
        segments = _completion_segments(completion)
        print(f"[DEBUG] step3: outbound check, segments={len(segments)}")
        cleaned_parts = []
        for _, (_kind, _idx, text) in segments:
            result = await check(text, "outbound")
            print(f"[DEBUG] outbound verdict={result['verdict']}")
            if result["verdict"] == "block":
                return _blocked(result)
            cleaned_parts.append(result.get("cleaned_text", text))
        try:
            completion = _apply_cleaned_completion(completion, segments, cleaned_parts)
        except ValueError:
            print(f"[DEBUG] step3: apply_cleaned_completion FAILED")
            return _cannot_apply_cleaned_text()
        print(f"[DEBUG] step3 done — returning response")

    return completion


def _fail_closed(resp: httpx.Response) -> dict:
    """Any governance_api error is a block, never a silent allow."""
    if resp.status_code >= 400:
        return {"verdict": "block", "violations": ["governance_api_error"]}
    return resp.json()


def _blocked(result: dict) -> JSONResponse:
    return JSONResponse(status_code=403, content={"error": "blocked_by_compliance", "violations": result.get("violations")})


# Every piece of text (each string message, each text part of a list-style
# message, each tool-call's arguments string, each completion choice) gets its
# OWN compliance check, so a detector can never match across two pieces (the
# NER model happily joins "John" / "Smith" across any separator) and a
# caller's text can't collide with any delimiter. Checks run sequentially so
# receipts append to the hash chain in order. Cost: one governance call per
# piece -- see docs/MOCKED_VS_PRODUCTION.md.
# Non-text parts (images/audio) are not inspected -- out of scope per the
# problem statement's non-goals (text identifiers only).


def _message_segments(message: dict) -> list:
    """(kind, index, text) for each checked piece of one message; kind is
    "content" (index None), "part" (content-list index) or "tool" (tool_calls index)."""
    segments = []
    content = message.get("content")
    if isinstance(content, str):
        segments.append(("content", None, content))
    elif isinstance(content, list):
        for j, part in enumerate(content):
            if isinstance(part, dict) and part.get("type") == "text" and isinstance(part.get("text"), str):
                segments.append(("part", j, part["text"]))
    tool_calls = message.get("tool_calls")
    if isinstance(tool_calls, list):
        for k, call in enumerate(tool_calls):
            args = call.get("function", {}).get("arguments") if isinstance(call, dict) else None
            if isinstance(args, str):
                segments.append(("tool", k, args))
    return [seg for seg in segments if seg[2].strip()]  # nothing to check in blank text


def _apply_to_message(message: dict, segments: list, parts: list) -> dict:
    message = dict(message)
    for (kind, idx, original), part in zip(segments, parts):
        if kind == "content":
            message["content"] = part
        elif kind == "part":
            content = list(message["content"])
            content[idx] = {**content[idx], "text": part}
            message["content"] = content
        else:
            if part != original:
                try:
                    json.loads(part)
                except ValueError:  # redaction broke the arguments JSON -> don't forward it
                    raise ValueError("cleaned tool-call arguments are no longer valid JSON")
            calls = list(message["tool_calls"])
            calls[idx] = {**calls[idx], "function": {**calls[idx]["function"], "arguments": part}}
            message["tool_calls"] = calls
    return message


def _segments(container: dict, key: str, unwrap) -> list:
    """(item_index, segment) pairs over container[key] items (messages or choices)."""
    out = []
    for i, item in enumerate(container.get(key, [])):
        msg = unwrap(item)
        if isinstance(msg, dict):
            out.extend((i, seg) for seg in _message_segments(msg))
    return out


def _prompt_segments(body: dict) -> list:
    return _segments(body, "messages", lambda m: m)


def _completion_segments(completion: dict) -> list:
    return _segments(completion, "choices", lambda c: c.get("message") if isinstance(c, dict) else None)


def _rewrite(container: dict, key: str, unwrap, wrap, segments: list, parts: list) -> dict:
    """Write `parts` (one cleaned string per segment) back. Raises ValueError if
    a cleaned piece can't be applied."""
    if len(parts) != len(segments):
        raise ValueError("cleaned text does not match original segment count")
    items = [dict(x) if isinstance(x, dict) else x for x in container.get(key, [])]
    by_item = {}
    for (i, seg), part in zip(segments, parts):
        by_item.setdefault(i, ([], []))
        by_item[i][0].append(seg)
        by_item[i][1].append(part)
    for i, (segs, prts) in by_item.items():
        items[i] = wrap(items[i], _apply_to_message(unwrap(items[i]), segs, prts))
    return {**container, key: items}


def _apply_cleaned_prompt(body: dict, segments: list, parts: list) -> dict:
    return _rewrite(body, "messages", lambda m: m, lambda _old, new: new, segments, parts)


def _apply_cleaned_completion(completion: dict, segments: list, parts: list) -> dict:
    return _rewrite(
        completion, "choices", lambda c: c["message"], lambda old, new: {**old, "message": new}, segments, parts,
    )


def _cannot_apply_cleaned_text() -> JSONResponse:
    return JSONResponse(status_code=403, content={"error": "blocked_by_compliance", "violations": ["cleaned_text_unapplicable"]})


@app.get("/healthz")
def healthz():
    return {"status": "ok"}
