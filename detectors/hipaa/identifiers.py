"""HIPAA pack v1 detectors -- ~8-10 high-signal identifiers (docs/HACKATHON_PLAN.md,
Data Scientist Day1 #1). Deterministic regex only for this placeholder;
swap/extend with a lightweight NER model for `full_name` if regex recall is
too low against real text.

Every detector is a pure function: (text) -> list of matched spans. No LLM
call, no self-attestation -- compliance decisions must be reproducible and
tamper-proof (docs/HACKATHON_PLAN.md hardening #1).
"""
import re
from typing import List, Tuple

# TODO: tune these patterns against real sample data; they are intentionally
# permissive placeholders, not production-grade.
PATTERNS = {
    "phone_number": re.compile(r"\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b"),
    "fax_number": re.compile(r"\bfax[:\s]+\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b", re.IGNORECASE),
    "email_address": re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"),
    "ssn_like": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "medical_record_number": re.compile(r"\bMRN[:\s#]*\d{5,10}\b", re.IGNORECASE),
    "date_except_year": re.compile(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b"),
    "zip_code": re.compile(r"\b\d{5}(-\d{4})?\b"),
    # `full_name` and `geographic_subdivision` are NOT reliably regex-detectable.
    # TODO: plug in a lightweight NER model (e.g. spaCy `en_core_web_sm`) here.
}


def find_all(text: str) -> List[Tuple[str, str]]:
    """Return [(identifier_name, matched_span), ...]."""
    violations: List[Tuple[str, str]] = []
    for name, pattern in PATTERNS.items():
        for match in pattern.finditer(text):
            violations.append((name, match.group(0)))
    return violations
