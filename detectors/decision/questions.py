"""Per-pack Noul question sets, one `systemOne` call per text.

Kept small (5-6 questions) for demo latency. Question keys are caller-chosen;
identifiers emitted as `laya_<key>`. Shaped after the jev-pii-checker gate
(person/email/address/gov-id/financial/health) trimmed to what maps cleanly
onto the HIPAA and DPDP packs.
"""
from typing import Dict

_QUESTION = {"type": "noul"}  # type key kept for readability; transport sends instructions+criteria


def _noul(instructions: str, true: str, false: str) -> Dict:
    return {
        "type": "noul",
        "instructions": instructions,
        "criteria": {"true": true, "false": false},
    }


HIPAA_QUESTIONS: Dict[str, Dict] = {
    "person_name": _noul(
        "Does the text contain the name of a specific individual?",
        "Contains a real person's name",
        "No person name present",
    ),
    "email_or_phone": _noul(
        "Does the text contain a personal email address or phone number?",
        "Contains a personal email or phone number",
        "No personal email or phone",
    ),
    "government_id": _noul(
        "Does the text contain a government-issued ID (SSN, passport, driver's licence, MRN)?",
        "Contains a government-issued ID number",
        "No government ID",
    ),
    "health_info": _noul(
        "Does the text reveal health, medical, or biometric information about a person?",
        "Contains health/medical/biometric information",
        "No health information",
    ),
    "financial_account": _noul(
        "Does the text contain a financial account, card, or claim number?",
        "Contains a financial/claim identifier",
        "No financial identifier",
    ),
    "postal_address": _noul(
        "Does the text contain a postal/street address smaller than a state?",
        "Contains a street/city/zip-level address",
        "No sub-state address",
    ),
}

DPDP_QUESTIONS: Dict[str, Dict] = {
    "person_name": _noul(
        "Does the text contain the name of a specific individual?",
        "Contains a real person's name",
        "No person name present",
    ),
    "email_or_phone": _noul(
        "Does the text contain a personal email address or phone number?",
        "Contains a personal email or phone number",
        "No personal email or phone",
    ),
    "government_id": _noul(
        "Does the text contain an Aadhaar, PAN, passport, or voter ID number?",
        "Contains an Indian government-issued ID number",
        "No government ID",
    ),
    "residential_address": _noul(
        "Does the text contain a residential or street-level address?",
        "Contains a residential/street address",
        "No residential address",
    ),
    "financial_account": _noul(
        "Does the text contain a bank account, card, or financial identifier?",
        "Contains a financial identifier",
        "No financial identifier",
    ),
}

PACK_QUESTIONS: Dict[str, Dict[str, Dict]] = {
    "hipaa": HIPAA_QUESTIONS,
    "dpdp": DPDP_QUESTIONS,
}


def questions_for(pack_id: str) -> Dict[str, Dict]:
    return PACK_QUESTIONS.get(pack_id, HIPAA_QUESTIONS)
