"""The signal -> penalty table handed to SWE#2's AuthorityEngine
(governance_api/authority/engine.py: SIGNAL_PENALTIES) -- kept here as the
single source of truth the Data Scientist owns and edits.
"""

SIGNAL_PENALTIES = {
    "phi_in_output": 20.0,
    # Only NER-/heuristic-derived identifiers matched (see LOW_CONFIDENCE_IDENTIFIERS).
    "phi_in_output_low_confidence": 5.0,
    "tool_out_of_scope": 15.0,
    "repeated_denied_call": 10.0,
    "prompt_injection_detected": 25.0,
}

# Identifiers whose detection is statistical (NER model or context heuristic)
# rather than a precise pattern. A hit here still gets redacted, but is far
# more likely to be a false positive, so it (a) costs a fraction of the
# authority penalty and (b) can never be configured to `block`
# (governance_api/compliance/engine.py). See docs/adr/0008.
LOW_CONFIDENCE_IDENTIFIERS = frozenset({"full_name", "geographic_subdivision", "residential_address"})

# Identifiers that are metadata markers, not a PHI/PII leak -- their action is
# always `log_only` ("pass through, just record it", per docs/HACKATHON_PLAN.md
# Data Scientist Day1 #2), so a hit must not cost the agent anything. Without
# this, DPDP's `consent_purpose_flag` (a benign "consent obtained for ..."
# statement) would dock the same -20 as a real leak every time it appeared.
NO_SIGNAL_IDENTIFIERS = frozenset({"consent_purpose_flag"})


def phi_signal(violations: list):
    """Authority signal for a compliance-check's violation names, or None if clean
    (or if everything that matched is a NO_SIGNAL_IDENTIFIERS marker).

    Full `phi_in_output` if ANY high-confidence identifier matched; the small
    `phi_in_output_low_confidence` if only low-confidence ones did.
    """
    punishable = [v for v in violations if v not in NO_SIGNAL_IDENTIFIERS]
    if not punishable:
        return None
    if any(v not in LOW_CONFIDENCE_IDENTIFIERS for v in punishable):
        return "phi_in_output"
    return "phi_in_output_low_confidence"


def compute_signals(violations: list, injection_hits: list, tool_out_of_scope: bool) -> list:
    """Combine detector outputs into a flat signal list for the authority engine.

    TODO: tune penalty weights against the demo script's adversarial test
    cases once real detector output is available.
    """
    signals = []
    phi = phi_signal(violations)
    if phi:
        signals.append(phi)
    if injection_hits:
        signals.append("prompt_injection_detected")
    if tool_out_of_scope:
        signals.append("tool_out_of_scope")
    return signals
