"""DPDP (India) pack detectors -- general-PII identifiers, distinct from
HIPAA's healthcare focus (docs/HACKATHON_PLAN.md, Data Scientist Day2 #5).
Shares `phone_number`/`email_address` with the HIPAA pack -- see
data_pipeline/config/overlap_map.yaml -- reuse detectors/hipaa/identifiers.py
for those instead of re-implementing them here.
"""
import re
from typing import List, Tuple

from detectors import ner
from detectors.hipaa.identifiers import PATTERNS as HIPAA_PATTERNS

PATTERNS = {
    "phone_number": HIPAA_PATTERNS["phone_number"],
    "email_address": HIPAA_PATTERNS["email_address"],
    "aadhaar_like": re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b"),
    "pan_like": re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b"),
}


def find_all(text: str) -> List[Tuple[str, str]]:
    violations: List[Tuple[str, str]] = []
    for name, pattern in PATTERNS.items():
        for match in pattern.finditer(text):
            violations.append((name, match.group(0)))
    # NER-derived, low-confidence (detectors/scoring/signals.py). Places only
    # approximate `residential_address` -- a street address regex is still TODO.
    violations.extend(ner.find_names(text))
    violations.extend(ner.find_locations(text, identifier="residential_address"))
    return violations
