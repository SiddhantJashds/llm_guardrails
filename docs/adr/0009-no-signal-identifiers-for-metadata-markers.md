# 0009. Metadata markers (DPDP's `consent_purpose_flag`) cost the agent nothing

Status: Accepted
Date: 2026-10-05

## Context

DPDP's pack lists `consent_purpose_flag` as `log_only`: "pass through, just record it" ([docs/HACKATHON_PLAN.md](../HACKATHON_PLAN.md) Data Scientist Day1 #2) — it's a marker that a consent/purpose statement is present in text (e.g. "Consent obtained for marketing communications."), not a PHI/PII leak. Its detector (`detectors/dpdp/identifiers.py::_find_consent_purpose`) is a loose keyword heuristic by design, since a false positive is harmless *as long as nothing downstream treats it as a violation*.

But `governance_api/routes/governance.py`'s compliance-check/handoff-check routes didn't distinguish: `if violations: engine.apply_signal(..., phi_signal(violations))` fired on *any* non-empty violation list, regardless of the identifier's configured action. Shipping the `consent_purpose_flag` detector without fixing this would have docked an agent the full `phi_in_output` penalty (−20, since it isn't in [0008](0008-ner-low-confidence-tier.md)'s `LOW_CONFIDENCE_IDENTIFIERS`) every time it correctly logged a benign consent statement — a self-inflicted authority drain for doing exactly what the pack config asks.

## Decision

**Add `detectors/scoring/signals.py::NO_SIGNAL_IDENTIFIERS` (currently just `consent_purpose_flag`). `phi_signal()` filters these out before deciding a signal; if nothing punishable remains, it returns `None`, and the route skips `apply_signal` entirely rather than calling it with a zero-penalty signal.**

The compliance engine's block-downgrade guard (0008's `block` → `redact` rule) is widened from `LOW_CONFIDENCE_IDENTIFIERS` alone to `LOW_CONFIDENCE_IDENTIFIERS | NO_SIGNAL_IDENTIFIERS` — an admin misconfiguring `consent_purpose_flag` to `block` must not be able to nuke a whole response over a benign sentence, for the same reason a statistical NER hit can't.

This identifier still appears in `violations`/the receipt `reason` — it's genuinely useful to have on record that a consent/purpose statement was present — it just never reaches `AuthorityEngine.apply_signal`.

## Consequences

- A correctly-functioning `consent_purpose_flag` detection is free: no score cost, no block risk, no history-entry noise.
- Any future `log_only`-by-design identifier (not just PHI/PII, more like structured metadata) should be added to `NO_SIGNAL_IDENTIFIERS` rather than assumed safe by its `log_only` config alone — the config's action and the scoring signal are two separate mechanisms that happened to both need fixing here.
- If a *real* PHI/PII identifier is ever misconfigured to `log_only` (e.g. an admin fat-fingers `ssn_like` to `log_only`), it still costs the full `phi_in_output` penalty — only identifiers in this explicit set are exempt, not every `log_only`-configured one. That's deliberate: the exemption is about what the detector *is* (a non-PII marker), not how an admin happens to have it configured today.
