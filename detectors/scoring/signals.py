"""The signal -> penalty table handed to SWE#2's AuthorityEngine
(governance_api/authority/engine.py: SIGNAL_PENALTIES) -- kept here as the
single source of truth the Data Scientist owns and edits.
"""

SIGNAL_PENALTIES = {
    "phi_in_output": 20.0,
    "tool_out_of_scope": 15.0,
    "repeated_denied_call": 10.0,
    "prompt_injection_detected": 25.0,
}


def compute_signals(violations: list, injection_hits: list, tool_out_of_scope: bool) -> list:
    """Combine detector outputs into a flat signal list for the authority engine.

    TODO: tune penalty weights against the demo script's adversarial test
    cases once real detector output is available.
    """
    signals = []
    if violations:
        signals.append("phi_in_output")
    if injection_hits:
        signals.append("prompt_injection_detected")
    if tool_out_of_scope:
        signals.append("tool_out_of_scope")
    return signals
