"""Rule-based prompt-injection detection signals (docs/HACKATHON_PLAN.md,
Data Scientist Day2 #7). These feed the Authority Engine's monotonic
reduction as an additional evidence signal -- they never gate a decision by
themselves, and they never ask an LLM to judge the text (hardening #1).
"""
import re
import unicodedata
from typing import List

# TODO: expand this list from real adversarial test cases; keep it a flat,
# auditable list rather than a black-box classifier.
INSTRUCTION_OVERRIDE_PATTERNS = [
    re.compile(r"ignore (all )?(previous|prior|above) instructions", re.IGNORECASE),
    re.compile(r"disregard (the )?(system|previous) prompt", re.IGNORECASE),
    re.compile(r"you are now (in )?(developer|admin|unrestricted) mode", re.IGNORECASE),
]

ROLE_CLAIM_PATTERNS = [
    re.compile(r"as (the |a )?(supervisor|admin|manager),?\s+(un)?redact", re.IGNORECASE),
    re.compile(r"trust_score\s*[:=]\s*\d+", re.IGNORECASE),
    re.compile(r"agent_id\s*[:=]", re.IGNORECASE),
]


def normalize(text: str) -> str:
    """Strip zero-width/homoglyph evasion before matching (hardening #7)."""
    normalized = unicodedata.normalize("NFKC", text)
    return "".join(ch for ch in normalized if unicodedata.category(ch) != "Cf")


def detect(text: str) -> List[str]:
    """Return a list of matched heuristic names, e.g. ['instruction_override']."""
    clean = normalize(text)
    hits: List[str] = []
    if any(p.search(clean) for p in INSTRUCTION_OVERRIDE_PATTERNS):
        hits.append("instruction_override")
    if any(p.search(clean) for p in ROLE_CLAIM_PATTERNS):
        hits.append("forged_identity_or_role_claim")
    return hits
