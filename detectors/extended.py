"""Extended identifier detectors shared by the HIPAA and DPDP packs.

Covers identifier classes the full GuardRailBench edition exercises that the
original packs had no detector for: payment (card, UPI, bank account),
device/online (IMEI, MAC, advertising ID, browser fingerprint, GPS),
government documents (passport, voter ID, driving licence), vehicle plates,
prefixed record identifiers (ACCT-, POL-, SUB-, EMP-, STU-, INS-SN-, TXN-...),
keyword-anchored usernames, salaries and dates of birth/admission/discharge,
and names introduced by a role keyword ("Guardian: Sumitra Banerjee").

Deterministic regex + checksum rules only (ADR 0004). Keyword-anchored rules
return just the value, so the keyword itself stays readable.
"""
import re
from typing import List, Tuple


def _luhn_ok(digits: str) -> bool:
    total, parity = 0, len(digits) % 2
    for i, ch in enumerate(digits):
        d = int(ch)
        if i % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


_CARD = re.compile(r"(?<![\d-])(?:\d{4}[ -]){3}\d{4}(?![\d-])|(?<![\d-])\d{13,19}(?![\d-])")
_UPI = re.compile(r"\b[A-Za-z0-9][\w.\-]{1,}@[A-Za-z][A-Za-z0-9]{1,}\b(?![\w-])(?!\.\w)")  # not the start of an email domain
_BANK = re.compile(r"(?i)\b(?:bank\s+)?(?:account|a/c|acct)\s*(?:no\.?|number|#)?\s*[:\-]?\s*(\d{9,18})\b")
_IFSC = re.compile(r"\b[A-Z]{4}0[A-Z0-9]{6}\b")
_IMEI = re.compile(r"(?<!\d)\d{15}(?!\d)")
_MAC = re.compile(r"\b(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b")
_GPS = re.compile(r"(?<![\d.])-?\d{1,2}\.\d{3,}\s*,\s*-?\d{1,3}\.\d{3,}(?![\d.])")
_ADVERTISING = re.compile(
    r"(?i)(?:advertising|ad|idfa|gaid|aaid|device)\s*id\s*[:\-]?\s*"
    r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"
)
_USER_AGENT = re.compile(r"Mozilla/\d\.\d \([^)\n]{3,}\)[^\n]{0,200}")
_PASSPORT = re.compile(r"\b[A-Z][0-9]{7}\b")
_VOTER = re.compile(r"\b[A-Z]{3}[0-9]{7}\b")
_DRIVING = re.compile(r"\b[A-Z]{2}-\d{2}-\d{4}-\d{7}\b|\b[A-Z]{2}\d{2}[ -]?\d{11}\b")
_PLATE = re.compile(r"\b[A-Z]{3}-\d{4}\b|\b[A-Z]{2}[ -]?\d{1,2}[ -]?[A-Z]{1,3}[ -]?\d{4}\b")
# Prefixed record identifiers: ACCT-60417733, POL-55102938, SUB-30928417,
# EMP-482913, STU-305172, INS-SN-4402918, ME-DL-30571928, TXN-90412287,
# AETNA-INS-44719200. MRN-... stays with the medical_record_number detector.
_PREFIXED_ID = re.compile(r"\b(?!MRN-)[A-Z]{2,6}(?:-[A-Z]{2,4})?-\d{5,10}\b")
_USERNAME = re.compile(r"(?i)\b(?:username|user\s*name|login\s*id|handle)\s*[:\-]?\s*([A-Za-z0-9_.]{3,32})\b")
_SALARY = re.compile(r"(?i)\b(?:salary|ctc|compensation|annual\s+pay)\b[^\n]{0,25}?((?:INR|Rs\.?|USD|\$|₹)\s?[\d,]{3,}(?:\.\d+)?)")
_KEYED_DATE = re.compile(
    r"(?i)\b(?:date\s+of\s+birth|dob|born(?:\s+on)?|birth\s*date|admitted(?:\s+on)?|admission(?:\s+date)?|"
    r"discharged(?:\s+on)?|discharge(?:\s+date)?)\b\s*[:\-]?\s*(\d{4}-\d{2}-\d{2}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4})"
)
# "Patient Name: Elodie Brandt", "Policyholder Name: ...", "Guardian: ...",
# "Collected by: ..." -- a labelled person on one line (NER misses these when
# it tags the label itself as the name).
_ROLE_NAME = re.compile(
    r"\b(?:(?:Guardian|Policyholder|Policy holder|Employee|Patient|Spouse|Nominee|Account holder|Parent|Father|Mother|"
    r"Emergency contact|Next of kin|Contact person|Referred by|Prescribed by|Collected by|Picked up by|Requested by|"
    r"Submitted by|Signed by|Data principal|Applicant|Claimant|Insured|Beneficiary|Student|Candidate)"
    r"(?:['’]s)?(?:[ \t]+[Nn]ame)?|[A-Z][a-z]+[ \t]+[Nn]ame|Name)[ \t]*[:\-][ \t]*"
    r"(?:(?:Dr|Mr|Mrs|Ms|Shri|Smt)\.?[ \t]+)?([A-Z][a-z]+(?:[ \t]+[A-Z][a-z.'’-]+){1,2})"
)


def find_extended(text: str) -> List[Tuple[str, str]]:
    hits: List[Tuple[str, str]] = []
    card_spans = set()
    for m in _CARD.finditer(text):
        digits = re.sub(r"\D", "", m.group(0))
        grouped = not m.group(0).isdigit()
        if (grouped and len(digits) == 16) or (13 <= len(digits) <= 19 and _luhn_ok(digits) and len(digits) != 15):
            hits.append(("card_number", m.group(0)))
            card_spans.add(m.group(0))
    for m in _IMEI.finditer(text):
        if m.group(0) not in card_spans and (_luhn_ok(m.group(0)) or re.search(r"(?i)imei", text[max(0, m.start() - 20):m.start()])):
            hits.append(("device_identifier", m.group(0)))
    hits += [("upi_id", m.group(0)) for m in _UPI.finditer(text)]
    hits += [("bank_account_number", m.group(1)) for m in _BANK.finditer(text)]
    hits += [("bank_account_number", m.group(0)) for m in _IFSC.finditer(text)]
    hits += [("device_identifier", m.group(0)) for m in _MAC.finditer(text)]
    hits += [("gps_coordinates", m.group(0)) for m in _GPS.finditer(text)]
    hits += [("device_identifier", m.group(1)) for m in _ADVERTISING.finditer(text)]
    hits += [("device_identifier", m.group(0)) for m in _USER_AGENT.finditer(text)]
    hits += [("passport_number", m.group(0)) for m in _PASSPORT.finditer(text)]
    hits += [("voter_id", m.group(0)) for m in _VOTER.finditer(text)]
    hits += [("driving_licence", m.group(0)) for m in _DRIVING.finditer(text)]
    hits += [("vehicle_identifier", m.group(0)) for m in _PLATE.finditer(text)]
    hits += [("account_number", m.group(0)) for m in _PREFIXED_ID.finditer(text)]
    hits += [("username", m.group(1)) for m in _USERNAME.finditer(text)]
    hits += [("salary", m.group(1)) for m in _SALARY.finditer(text)]
    hits += [("date_except_year", m.group(1)) for m in _KEYED_DATE.finditer(text)]
    hits += [("full_name", m.group(1)) for m in _ROLE_NAME.finditer(text)]
    return hits
