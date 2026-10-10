"""Per-session placeholder vault (docs/adr/0016).

Maps each detected value to a typed, numbered placeholder ("[NAME_1]") that is
stable for the whole session, so the model can tell people apart without ever
seeing them, and so a reply can be restored for the person who typed the value.

Raw values live ONLY in this process's memory, never on disk or in a receipt --
the API already receives raw text on every compliance check, so holding it a
little longer (TTL-bounded) adds no new exposure. Entries expire after
VAULT_TTL_SECONDS of inactivity and are cleared by POST /admin/reset. With more
than one API worker each worker has its own vault (we run a single process).
"""
import os
import re
import threading
import time
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

TTL_SECONDS = float(os.getenv("VAULT_TTL_SECONDS", "7200"))
MAX_SESSIONS = int(os.getenv("VAULT_MAX_SESSIONS", "5000"))

# identifier -> placeholder label
LABELS = {
    "full_name": "NAME",
    "phone_number": "PHONE",
    "email_address": "EMAIL",
    "geographic_subdivision": "LOCATION",
    "residential_address": "ADDRESS",
    "date_except_year": "DATE",
    "fax_number": "FAX",
    "medical_record_number": "MRN",
    "health_plan_beneficiary_number": "PLAN_ID",
    "account_number": "ACCOUNT",
    "certificate_license_number": "LICENSE",
    "vehicle_identifier": "VEHICLE",
    "device_identifier": "DEVICE",
    "web_url": "URL",
    "ssn_like": "SSN",
    "aadhaar_like": "AADHAAR",
    "pan_like": "PAN",
}

TOKEN_RE = re.compile(r"\[([A-Z][A-Z_]*?)_(\d+)\]")


def label_for(identifier: str) -> str:
    return LABELS.get(identifier, identifier.upper())


def normalize(identifier: str, value: str) -> str:
    """Same person / number written differently -> same placeholder."""
    if identifier in ("phone_number", "fax_number"):
        digits = re.sub(r"\D", "", value)
        return digits[-10:] if len(digits) >= 10 else digits
    value = re.sub(r"\s+", " ", value).strip().casefold()
    if identifier == "full_name":
        value = re.sub(r"['’]s$", "", value)  # "Margaret Whitfield's" is Margaret Whitfield
    return value


@dataclass
class Entry:
    token: str
    identifier: str
    value: str
    origin: str  # "sender" (typed by the end user, opted in) | "context" | "model" | "tool"
    user_id: str


class _Session:
    def __init__(self) -> None:
        self.by_value: Dict[Tuple[str, str], Entry] = {}
        self.by_token: Dict[str, Entry] = {}
        self.counters: Dict[str, int] = {}
        self.touched = time.monotonic()


_lock = threading.Lock()
_sessions: Dict[str, _Session] = {}


def _session(session_id: str) -> _Session:
    now = time.monotonic()
    s = _sessions.get(session_id)
    if s is None:
        if len(_sessions) >= MAX_SESSIONS:
            oldest = min(_sessions, key=lambda k: _sessions[k].touched)
            del _sessions[oldest]
        s = _sessions[session_id] = _Session()
    s.touched = now
    return s


def _expire() -> None:
    cutoff = time.monotonic() - TTL_SECONDS
    for key in [k for k, s in _sessions.items() if s.touched < cutoff]:
        del _sessions[key]


def token_for(session_id: str, identifier: str, value: str, origin: str, user_id: str) -> str:
    """The session's placeholder for this value, created on first sight. A
    value first seen as context that is later typed by the sender is upgraded
    to sender origin (never the other way round)."""
    with _lock:
        _expire()
        s = _session(session_id)
        key = (identifier, normalize(identifier, value))
        entry = s.by_value.get(key)
        if entry is None:
            label = label_for(identifier)
            s.counters[label] = s.counters.get(label, 0) + 1
            entry = Entry(f"[{label}_{s.counters[label]}]", identifier, value, origin, user_id)
            s.by_value[key] = entry
            s.by_token[entry.token] = entry
        elif origin == "sender" and entry.origin != "sender":
            entry.origin, entry.user_id = "sender", user_id
        return entry.token


def is_sender_value(session_id: str, user_id: str, identifier: str, value: str) -> bool:
    """True if this user typed this value earlier in the session. A name also
    matches a shorter form of a typed name ("Margaret" after "Margaret Whitfield")."""
    key = normalize(identifier, value)
    words = set(key.split())
    with _lock:
        s = _sessions.get(session_id)
        if s is None:
            return False
        for (ident, norm), entry in s.by_value.items():
            if entry.origin != "sender" or entry.user_id != user_id or ident != identifier:
                continue
            if norm == key or (identifier == "full_name" and words and words <= set(norm.split())):
                return True
    return False


def lookup(session_id: str, token: str) -> Optional[Entry]:
    with _lock:
        s = _sessions.get(session_id)
        return s.by_token.get(token) if s else None


def clear() -> None:
    with _lock:
        _sessions.clear()
