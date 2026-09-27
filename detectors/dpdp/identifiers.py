"""DPDP (India) pack detectors -- general-PII identifiers, distinct from
HIPAA's healthcare focus (docs/HACKATHON_PLAN.md, Data Scientist Day2 #5).
Shares `phone_number`/`email_address` with the HIPAA pack -- see
data_pipeline/config/overlap_map.yaml -- reuse detectors/hipaa/identifiers.py
for those instead of re-implementing them here.
"""
import re
from typing import List, Tuple

from detectors.hipaa.identifiers import PATTERNS as HIPAA_PATTERNS

PATTERNS = {
    "phone_number": HIPAA_PATTERNS["phone_number"],
    "email_address": HIPAA_PATTERNS["email_address"],
    "aadhaar_like": re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b"),
    "pan_like": re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b"),
    # TODO: `residential_address` needs NER, same as HIPAA's geographic_subdivision.
}


def find_all(text: str) -> List[Tuple[str, str]]:
    violations: List[Tuple[str, str]] = []
    for name, pattern in PATTERNS.items():
        for match in pattern.finditer(text):
            violations.append((name, match.group(0)))
    return violations
