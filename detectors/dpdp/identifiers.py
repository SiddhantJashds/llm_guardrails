"""DPDP (India) pack detectors -- general-PII identifiers, distinct from
HIPAA's healthcare focus (docs/HACKATHON_PLAN.md, Data Scientist Day2 #5).
Shares `phone_number`/`email_address`/`web_url`/`ip_address` with the HIPAA
pack -- see data_pipeline/config/overlap_map.yaml -- reuse
detectors/hipaa/identifiers.py for those instead of re-implementing them here.
Other HIPAA-pack identifiers (medical_record_number, account_number,
certificate_license_number, device_identifier, health_plan_beneficiary_number,
date_except_year, ...) are deliberately NOT reused here -- DPDP has no
healthcare-record framing and the generic "government ID / bank / payment /
employment / education / financial" categories in India's DPDP personal-data
definition don't match those detectors' keyword assumptions; see docs/adr/0017.

`full_name` / `residential_address` are NER-derived and a low-confidence tier,
same as HIPAA's `full_name` / `geographic_subdivision` (docs/adr/0008).
`consent_purpose_flag` is DPDP-specific: a textual marker that a consent or
purpose-limitation statement is present, not PII itself -- its action is
always `log_only` and it costs the agent nothing (see
detectors/scoring/signals.py's NO_SIGNAL_IDENTIFIERS).
"""
from detectors.extended import find_extended
import re
from typing import List, Tuple

from detectors import ner
from detectors.hipaa.identifiers import PATTERNS as HIPAA_PATTERNS

PATTERNS = {
    "phone_number": HIPAA_PATTERNS["phone_number"],
    "email_address": HIPAA_PATTERNS["email_address"],
    "web_url": HIPAA_PATTERNS["web_url"],
    "ip_address": HIPAA_PATTERNS["ip_address"],
    "aadhaar_like": re.compile(r"(?<![\d-])(?<!\d )\d{4}\s?\d{4}\s?\d{4}(?![ -]?\d)"),  # not inside a 16-digit card
    "pan_like": re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b"),
}

# A bare, unlabelled, unformatted 10-digit run is NOT treated as a phone
# number in the shared HIPAA pattern (too many false positives in a US/generic
# context -- see docs/MOCKED_VS_PRODUCTION.md). Indian mobile numbers are an
# exception worth the trade-off: every Indian mobile number starts with 6-9,
# which a generic 10-digit ID/order-number/count only coincidentally does, so
# this recovers real recall for DPDP specifically rather than HIPAA generally.
# Still a heuristic, still can false-positive on some other 10-digit code
# starting 6-9 -- documented, not eliminated.
_BARE_INDIAN_MOBILE = re.compile(r"(?<!\d)[6-9]\d{9}(?!\d)")

# Street-level address, which `ner.find_locations` (city/county) doesn't catch.
# Two independent shapes, combined under `residential_address`:
#   1. "House/Flat/Plot/Door No. <value>, <Street words>" -- a labelled unit
#      number is the strongest, lowest-noise signal of a real address line.
#   2. "<Capitalized word(s)> <Road/Street/Nagar/Colony/...>" -- a named street
#      or locality. Case-sensitive (no IGNORECASE) and requires a capitalized
#      lead-in specifically to avoid generic lowercase phrases like "closed the
#      road" or "due to colonial history" -- a real address is written as a
#      proper noun.
_HOUSE_UNIT = re.compile(
    r"\b(?:house|flat|plot|door|shop)\s*(?:no\.?|#)?\s*[:.\-]?\s*\d+[A-Za-z]?"
    r"(?:\s*,\s*[A-Za-z][\w\s]{2,40})?",
    re.IGNORECASE,
)
_NAMED_STREET_OR_LOCALITY = re.compile(
    r"\b(?:[A-Z][\w'.]*\s+){1,3}(?:Road|Street|Marg|Nagar|Colony|Society|Chowk|Gali|Lane|Avenue|Layout|Extension)\b"
    r"|\b(?:Sector|Phase|Block|Plot)\s*(?:No\.?)?\s*[0-9A-Z]+\b"
)
# 6-digit Indian PIN code, gated on an explicit label (same reasoning as
# HIPAA's zip: a bare 6-digit run is indistinguishable from any other code).
_PIN_CODE = re.compile(r"\bpin(?:code|\s*code)?\s*[:#]?\s*(\d{6})\b", re.IGNORECASE)

# "Consent obtained/given for ..." / "Purpose: ..." / "Purpose of processing: ..."
# A loose heuristic by design (action is log_only, so a false positive just
# gets recorded, never redacted/blocked) -- but still gated on an explicit
# keyword + separator so it doesn't fire on ordinary sentences that happen to
# contain the word "purpose" (e.g. "the purpose of this meeting").
_CONSENT_PURPOSE = re.compile(
    r"\b(?:consent\s+(?:obtained|given)\s+for|purpose\s+of\s+processing\s*:|purpose\s*:|consent\s*:)"
    r"\s*[A-Za-z][\w\s,./-]{2,60}",
    re.IGNORECASE,
)


def _find_street_address(text: str) -> List[Tuple[str, str]]:
    hits = [("residential_address", m.group(0)) for m in _HOUSE_UNIT.finditer(text)]
    hits += [("residential_address", m.group(0)) for m in _NAMED_STREET_OR_LOCALITY.finditer(text)]
    hits += [("residential_address", m.group(1)) for m in _PIN_CODE.finditer(text)]
    return hits


def _find_consent_purpose(text: str) -> List[Tuple[str, str]]:
    return [("consent_purpose_flag", m.group(0).strip()) for m in _CONSENT_PURPOSE.finditer(text)]


def find_all(text: str) -> List[Tuple[str, str]]:
    violations: List[Tuple[str, str]] = []
    for name, pattern in PATTERNS.items():
        for match in pattern.finditer(text):
            violations.append((name, match.group(0)))
    violations += [("phone_number", m.group(0)) for m in _BARE_INDIAN_MOBILE.finditer(text)]
    violations += _find_street_address(text)
    violations += _find_consent_purpose(text)
    # NER-derived, low-confidence (detectors/scoring/signals.py). Places only
    # approximate `residential_address` at city/county level; see
    # _find_street_address above for the house-number/street-name layer.
    # Payment, device, document and record IDs shared by both packs (detectors/extended.py).
    violations.extend(find_extended(text))
    violations.extend(ner.find_names(text))
    violations.extend(ner.find_locations(text, identifier="residential_address"))
    return violations
