"""HIPAA Safe Harbor detector pack -- all 18 identifier classes from 45 CFR
164.514(b)(2). Deterministic regex for what regex can catch; a pinned local NER model
(detectors/ner.py) for names and places; biometrics/face images that need
image analysis remain undetected.

Every detector is a pure function: (text) -> list of matched spans. No LLM
call, no self-attestation -- compliance decisions must be reproducible and
tamper-proof (docs/HACKATHON_PLAN.md hardening #1).
"""
import re
from typing import Any, List, Tuple

import regex

from detectors import ner

PATTERNS: dict[str, Any] = {  # compiled `re` (or `regex`) patterns, all exposing .finditer/.search
    # ------------------------------------------------------------------ Dates
    # Elements of dates directly related to an individual, except the year.
    # Month/day/year in common formats; also "Month DD, YYYY" and "DD Month YYYY".
    "date_except_year": re.compile(
        r"\b"
        r"(?:"
        r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}"               # MM/DD/YYYY or MM-DD-YYYY
        r"|"
        r"(?:"
            r"(?:January|February|March|April|May|June|"
               r"July|August|September|October|November|December)"
            r"|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
            r"\s+\d{1,2},?\s+\d{4}"                      # January 1, 2020
        r")"
        r"\b",
        re.IGNORECASE,
    ),

    # ---------------------------------------------------------------- Phone / Fax
    # A bare 10-digit run is only a phone number with a "phone/mobile/..." label
    # before it (span = digits only); otherwise it needs formatting (separators,
    # parentheses, +91/+1). Uses `regex` for the variable-length lookbehind.
    # Trade-off: an unlabelled, unformatted 10-digit number (e.g. Indian "9876543210"
    # on its own) is NOT caught -- see docs/MOCKED_VS_PRODUCTION.md.
    "phone_number": regex.compile(
        r"(?:"
        r"\(\d{3}\)\s?\d{3}[-.\s]?\d{4}"                                 # (555) 123-4567
        r"|\+91[\s.-]?\d{5}[\s.-]?\d{5}"                                 # +91 98765 43210
        r"|\+1[\s.-]?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}"                # +1 555 123 4567
        r"|\b\d{3}[-.\s]\d{3}[-.\s]?\d{4}\b"                             # 555-123-4567, 555-1234567
        r"|\b\d{3}[-.\s]?\d{3}[-.\s]\d{4}\b"                             # 555123-4567
        r"|\b[6-9]\d{4}[\s-]\d{5}\b"                                     # 98765 43210
        r"|(?<=\b(?:phone|tel|telephone|mobile|mob|cell|call|whatsapp|contact)"
        r"(?:\s*(?:number|no\.?|#))?\s*[:\-]?\s*)\d{10}\b"               # phone: 5551234567
        r")",
        regex.IGNORECASE,
    ),
    "fax_number": re.compile(r"\bfax[:\s]+\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b", re.IGNORECASE),

    # ----------------------------------------------------------- Email & Web / IP
    "email_address": re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"),
    "web_url": re.compile(
        r"\b(?:https?://|www\.)"
        r"[A-Za-z0-9][-A-Za-z0-9]*\.[A-Za-z]{2,}"
        r"(?:/[^ \)\]\"'<>]*)?",
    ),
    "ip_address": re.compile(
        r"\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}"
        r"(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b"
    ),

    # ------------------------------------------------------- SSN / Health Plan / MRN
    "ssn_like": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    # Keyword + an ID value that contains a digit. The bare word "beneficiary"
    # (or "beneficiary informed") is ordinary prose, not an identifier.
    "health_plan_beneficiary_number": re.compile(
        r"\b(?:HP[._\s]?[BN]|beneficiary(?:[\s_]+(?:id|number|no\.?|#))?|plan[._\s]?number)"
        r"[.:#]?\s+(?=[A-Z0-9-]*\d)[A-Z0-9][A-Z0-9-]{3,15}\b",
        re.IGNORECASE,
    ),
    "medical_record_number": re.compile(
        r"\bMRN[:\s#]*\d{5,10}\b", re.IGNORECASE
    ),

    # ------------------------------------------------ Account / Certificate / Vehicle / Device
    "account_number": re.compile(
        r"\b(?:(?:account|claim|patient|bill)[_.\s]?(?:number|#|no\.?)?)[:\s]+"
        r"(?=[A-Za-z0-9]*\d)[A-Za-z0-9]{4,20}\b",  # value must contain a digit ("bill Smith" isn't an account)
        re.IGNORECASE,
    ),
    "certificate_license_number": re.compile(
        r"(?:(?:driver['\s]s?\s?license|passport|state[-\s]id|"
        r"medical[-\s]license|npi|license)[_.\s]?(?:number|#|no\.?)?)[:\s]+"
        r"(?=[A-Z0-9]*\d)[A-Z0-9]{4,20}",
        re.IGNORECASE,
    ),
    "vehicle_identifier": re.compile(
        r"(?:vehicle|car|license[_.\s]plate|vin)[_.\s]?(?:number|#|no\.?)?[:\s]+"
        r"(?=[A-Z0-9\-]*\d)[A-Z0-9][A-Z0-9\-]{2,20}",
        re.IGNORECASE,
    ),
    "device_identifier": re.compile(
        r"\b(?:(?:serial[_.\s]?number|sn|s/n|device[_.\s]?id)[\s:]+)"
        r"(?=[A-Za-z0-9\-]*\d)[A-Za-z0-9\-]{4,20}\b",
        re.IGNORECASE,
    ),

    # --------------------------------------------------------------- Biometrics / Unique
    # Basic pattern: "biometric|fingerprint|voiceprint: <value>" — captures
    # encoded or transcribed biometric data. Actual face-prints need ML.
    "biometric_identifier": re.compile(
        r"\b(?:biometric|fingerprint|voiceprint|retina|iris)[\s:]+[^\n]{4,}",
        re.IGNORECASE,
    ),
    "unique_identifying_code": re.compile(
        r"\b(?:(?:unique|patient|case|research)[_.\s]?(?:id|number|#|"
        r"identifier|code))[\s:]+(?=[A-Z0-9]*\d)[A-Z0-9]{6,}\b",
        re.IGNORECASE,
    ),

    # --- NOT reliably regex-detectable (see NER TODOs below) ---
    # "full_name"     -> see NER placeholder below
    # "geographic_subdivision" -> see NER placeholder below
}


# ---- Extras that supplement the NER-dependent groups ----
# A bare \d{5} matches order numbers, dosages, counts... so a zip only counts
# with context: a US state abbreviation right before it ("NY 10001") or a
# "zip"/"zip code" label. The span returned is just the digits.
_US_STATE_ABBR = (
    "AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|MT|NE|NV|NH|NJ|NM|NY|"
    "NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY|DC|PR"
)
_ZIP_WITH_CONTEXT = re.compile(
    rf"(?:\b(?:{_US_STATE_ABBR})[ ,]+|(?i:\bzip(?:[ -]?code)?)\s*[:#]?\s*)(\d{{5}}(?:-\d{{4}})?)\b"
)


def _find_zip_code(text: str) -> List[Tuple[str, str]]:
    """Zip codes (with context) as a proxy for geographic_subdivision."""
    return [("geographic_subdivision", m.group(1)) for m in _ZIP_WITH_CONTEXT.finditer(text)]


def find_all(text: str) -> List[Tuple[str, str]]:
    """Return [(identifier_name, matched_span), ...].

    Regex patterns + context-gated zip + NER (names, places). The NER-derived
    identifiers are low-confidence -- see detectors/scoring/signals.py.
    Raises detectors.ner.NERUnavailableError if the model is required but
    missing (fail-closed).
    """
    violations: List[Tuple[str, str]] = []
    for name, pattern in PATTERNS.items():
        for match in pattern.finditer(text):
            violations.append((name, match.group(0)))
    violations.extend(_find_zip_code(text))
    violations.extend(ner.find_names(text))
    violations.extend(ner.find_locations(text))
    return violations
