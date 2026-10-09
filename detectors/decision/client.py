"""Thin `systemOne` client. One POST per text, all pack questions at once.

Fail-open policy lives with the caller (router.py): this module raises
`LayaUnavailableError` on any transport/non-200/parse problem, and the router
decides fallback vs propagate from `LAYA_FAIL_OPEN`.
"""
import logging
from typing import Dict, List, Tuple

import httpx

from . import config
from .questions import questions_for

log = logging.getLogger(__name__)


class LayaUnavailableError(RuntimeError):
    pass


def query(text: str, pack_id: str) -> Dict[str, float]:
    """Return {question_key: P(yes)} for the pack's question set."""
    endpoint = config.laya_endpoint()
    api_key = config.laya_api_key()
    if not endpoint or not api_key:
        raise LayaUnavailableError("LAYA_ENDPOINT / LAYA_API_KEY not configured")
    questions = questions_for(pack_id)
    try:
        resp = httpx.post(
            f"{endpoint}/v1/systemone",
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
            json={"state": text, "model": config.laya_model(), "questions": questions},
            timeout=config.laya_timeout_s(),
        )
        resp.raise_for_status()
        answers = resp.json().get("answers", {})
    except Exception as exc:
        raise LayaUnavailableError(f"laya request failed: {exc}") from exc
    probs: Dict[str, float] = {}
    for qid in questions:
        try:
            probs[qid] = float(answers.get(qid, {}).get("noul", 0.0))
        except (TypeError, ValueError):
            probs[qid] = 0.0
    return probs


def find_all(text: str, pack_id: str) -> List[Tuple[str, str]]:
    """Map firing questions to [(laya_<qid>, <full text>), ...].

    Full-text span is deliberate (see package docstring): the engine's
    `redact(cleaned, span)` then coarse-redacts the segment instead of
    missing. Empty/blank text short-circuits to [] so span is never "".
    """
    if not text or not text.strip():
        return []
    threshold = config.laya_threshold()
    probs = query(text, pack_id)
    hits = [(f"laya_{qid}", text) for qid, p in probs.items() if p >= threshold]
    if hits:
        log.info(
            "laya %s: %d/%d questions fired (threshold %.2f)",
            pack_id, len(hits), len(probs), threshold,
        )
    return hits
