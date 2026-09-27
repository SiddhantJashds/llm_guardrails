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

from . import actions

Verdict = str  # "allow" | "redact" | "block" | "hash" | "log_only"


def _run_detectors(text: str, pack_id: str) -> List[Tuple[str, str]]:
    """Return [(identifier_name, matched_span), ...] found in `text`.

    TODO (Data Scientist): wire in the real detectors, e.g.:
        from detectors.hipaa.identifiers import find_all as find_hipaa
        from detectors.dpdp.identifiers import find_all as find_dpdp
    """
    return []


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
