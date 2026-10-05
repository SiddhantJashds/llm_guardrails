"""Deterministic compliance checking.

Never delegates the "is this compliant" judgment to an LLM -- decisions come
from rule-based detectors reading raw text (docs/HACKATHON_PLAN.md hardening
#1: No self-attestation). Detector implementations live in the top-level
`detectors/` package, owned by the Data Scientist.

`allow_unredacted` is computed by the caller (routes/governance.py) from the
admin-granted UserAccessOverride AND the request's explicit ask -- this
function never looks that up itself, so it stays a pure function of its
inputs and is trivial to unit test.
"""
import sys
from pathlib import Path
from typing import List, Tuple

sys.path.append(str(Path(__file__).resolve().parents[2]))  # allow `import detectors`

from sqlalchemy.orm import Session

from shared.models import CompliancePackConfig
from detectors.scoring.signals import LOW_CONFIDENCE_IDENTIFIERS, NO_SIGNAL_IDENTIFIERS

# Identifiers that must never be configurable to `block`: statistical/NER hits
# (LOW_CONFIDENCE_IDENTIFIERS) and metadata markers that aren't PII at all
# (NO_SIGNAL_IDENTIFIERS, e.g. DPDP's consent_purpose_flag) -- either one, a
# false positive must not be able to nuke the whole response (docs/adr/0008).
_NEVER_BLOCK = LOW_CONFIDENCE_IDENTIFIERS | NO_SIGNAL_IDENTIFIERS

from . import actions

Verdict = str  # "allow" | "redact" | "block" | "hash" | "log_only"


_HIPAA_DETECTOR = None
_DPDP_DETECTOR = None


def _get_detector(pack_id: str):
    """Lazy-import the correct detector for the requested pack."""
    global _HIPAA_DETECTOR, _DPDP_DETECTOR
    if _HIPAA_DETECTOR is None:
        from detectors.hipaa.identifiers import find_all as _hipaa_find_all
        _HIPAA_DETECTOR = _hipaa_find_all
    if _DPDP_DETECTOR is None:
        from detectors.dpdp.identifiers import find_all as _dpdp_find_all
        _DPDP_DETECTOR = _dpdp_find_all
    return {"hipaa": _HIPAA_DETECTOR, "dpdp": _DPDP_DETECTOR}.get(pack_id)


def _run_detectors(text: str, pack_id: str) -> List[Tuple[str, str]]:
    """Return [(identifier_name, matched_span), ...] found in `text`."""
    detector = _get_detector(pack_id)
    if detector is None:
        return []
    return detector(text)


def _action_for(db: Session, pack_id: str, identifier: str) -> str:
    row = db.get(CompliancePackConfig, (pack_id, identifier))
    return row.action if row is not None else "redact"  # fail toward the safer action


def check(db: Session, text: str, pack_id: str, allow_unredacted: bool = False) -> Tuple[Verdict, str, List[str]]:
    violations = _run_detectors(text, pack_id)
    if not violations:
        return "allow", text, []

    cleaned = text
    verdict: Verdict = "log_only"
    for identifier, span in violations:
        action = _action_for(db, pack_id, identifier)
        if action == "block" and identifier in _NEVER_BLOCK:
            # A statistical hit must never kill the whole response (nor, via an
            # admin misconfig, turn a false positive into a hard denial).
            action = "redact"

        if action == "block":
            # block is never overridable by allow_unredacted.
            return "block", "", [name for name, _ in violations]
        elif action == "redact":
            if allow_unredacted:
                # Admin grant + explicit ask, both satisfied: leave this span
                # visible. Still surfaced in the receipt reason by the caller.
                verdict = "log_only" if verdict == "log_only" else verdict
                continue
            cleaned = actions.redact(cleaned, span)
            verdict = "redact"
        elif action == "hash":
            # hash is never overridable -- it's the deterministic-anonymize path.
            cleaned = actions.hash_value(cleaned, span)
            verdict = "hash" if verdict != "redact" else verdict
        # "log_only" leaves cleaned/verdict untouched for this span

    violation_names = [name for name, _ in violations]
    return verdict, cleaned, violation_names
