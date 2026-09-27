# 0004. Compliance/authority decisions are deterministic, never LLM self-attested

Status: Accepted
Date: 2026-09-27

## Context

This runtime exists specifically because agent self-reporting isn't trustworthy: the problem statement's "Evidence-Based Boundaries" core concept states authority must be based on "verified proof of prior correct behavior, not just the LLM's self-reported claim that a step succeeded." Because the runtime is itself a target for prompt injection (a security system whose own decision logic can be attacked is worse than no system), it can't reintroduce that same trust gap by asking an LLM "was this compliant?" as part of its own decision path.

## Decision

`governance_api/compliance/engine.py` and `detectors/*/identifiers.py` are pure, deterministic functions — regex/NER pattern matching against raw text, table lookups against `CompliancePackConfig` — with no LLM call anywhere in the decision path. `governance_api/authority/engine.py`'s trust score only ever changes via `SIGNAL_PENALTIES`, a fixed table (`detectors/scoring/signals.py`), never via a model's judgment call. `detectors/injection/heuristics.py` follows the same rule for injection detection itself: regex heuristics, not an LLM judge.

## Consequences

Every decision is reproducible and auditable from the receipt alone (no model non-determinism to explain away in a demo). The tradeoff: regex/NER detectors have real recall limits — `detectors/hipaa/identifiers.py` flags `full_name` and `geographic_subdivision` as needing a proper NER model rather than regex, which is still a TODO. This is an explicit, accepted gap for the hackathon scope (non-goal: "Real anomaly-detection ML — rule-based evidence signals only"), not an oversight.
