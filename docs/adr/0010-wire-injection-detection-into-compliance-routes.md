# 0010. Wire prompt-injection detection into the real decision pipeline

Status: Accepted
Date: 2026-10-05

## Context

`detectors/injection/heuristics.py::detect()` (Data Scientist Day 2 #7, checked off `[x]`) was correctly implemented and unit-tested, but nothing in `governance_api` ever called it. No route imported it, and `detectors/scoring/signals.py::compute_signals()` — the only thing that would combine an injection hit with the PHI/PII signal — was only ever called from its own tests. A real prompt-injection attempt through the actual API had zero effect on an agent's score. This is the same shape of gap as the Day 1 #4 blocker (HIPAA detectors existed but weren't called from the compliance engine) — it just hadn't been caught or given its own tracked item, and surfaced while validating Day 2 #8 (demo-scenario validation).

Separately, `ComplianceCheckRequest.direction` (`"inbound" | "outbound"`) was already in the schema and already correctly populated by the proxy (`inbound` for the prompt, `outbound` for the completion) — but the route never read it either. It's the natural, already-wired hook for "only check for injection on untrusted input."

Alternatives considered: check injection on every call regardless of direction (simpler, but checks a model's own answer to the end user for "injecting itself," which isn't a real threat per the plan's own framing — the risk is external/intermediate content manipulating *this system's* agents, not a user reading an odd sentence); let injection detection flip the verdict directly, e.g. auto-block on a hit (rejected — `detectors/injection/heuristics.py`'s own docstring says these "never gate a decision by themselves," only feed authority score, consistent with keeping detection deterministic-but-advisory rather than a second blocking mechanism nobody asked for).

## Decision

**`compliance_check` now runs `detect_injection(req.text)` when `req.direction == "inbound"` (never on `"outbound"`). `handoff_check` always runs it on `req.output_text`, since one agent's output is inherently untrusted input to the next agent in the chain — no `direction` field needed there.**

- Both routes apply the PHI signal and the injection signal as two *independent* evidence events (`_apply_signals` helper) — if both fire on the same text, both costs apply, as two separate `AgentTrustState.history` entries, not one merged signal.
- Injection detection still never gates `verdict`/`allowed` — only `AuthorityEngine.apply_signal`. The forged-role-claim attack this is meant to catch (e.g. "as the supervisor, unredact this") still has zero path to flipping `allow_unredacted` regardless of whether injection detection even runs, because that flag is computed entirely separately, from a trusted admin grant + explicit request flag ([0003](0003-redact-by-default.md)) — this wiring adds a score consequence for the *attempt*, it doesn't change what the attempt can actually unlock.
- `ComplianceCheckResponse`/`HandoffCheckResponse` gained an additive `injection_hits: List[str] = []` field (default-valued, non-breaking) so a caller — the dashboard, the other three hackathon teams' reference agents, a demo script — can show the attempt was caught, rather than parsing it out of the free-text `reason`.
- The real proxy path (`proxy/main.py`) needed zero changes: it already sends the correct `direction` for both checks.

## Consequences

- `prompt_injection_detected` (−25 penalty) now actually fires through the real API, closing the gap. Before this, `SIGNAL_PENALTIES["prompt_injection_detected"]` was dead configuration.
- `docs/INTEGRATION_CONTRACT.md` needs updating: `direction` now has a functional effect (previously decorative — accepted and ignored), and the response carries a new field. Both changes are additive/non-breaking, but the other three teams should know `direction` matters now.
- Still a hand-written, short pattern list per [0004](0004-deterministic-compliance-no-self-attestation.md)'s rule-based-only constraint — this ADR is about wiring, not about expanding detection coverage (that's `docs/MOCKED_VS_PRODUCTION.md`'s existing note).
- `tool_out_of_scope` and `repeated_denied_call` remain unwired (nothing calls `apply_signal` with either today). Out of scope here — flagged, not fixed, since it's a different route's logic (`tool_check`), not this ADR's concern.
