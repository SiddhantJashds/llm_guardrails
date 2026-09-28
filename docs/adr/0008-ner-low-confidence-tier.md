# 0008. NER-derived detections are a low-confidence tier

Status: Accepted
Date: 2026-09-28

## Context

`full_name` and `geographic_subdivision` (HIPAA) and `residential_address` (DPDP) can't be caught by regex, so they need a statistical NER model. Unlike a pattern for an SSN, an NER hit is frequently wrong: eponymous diseases ("Parkinson's") and place-like words get tagged, and the model also misses names (non-Western names, partial spans like "Kumar Iyer" for "Ramesh Kumar Iyer"). Every compliance violation costs the agent `phi_in_output` (−20) and authority only ever decreases (monotonic reduction, no recovery path) — so a handful of false positives on innocuous text could lock a legitimate agent out of its tools.

Alternatives considered: treat NER hits like any other identifier (simple, but false positives are punished as hard as a leaked SSN); drop NER and ship regex-only (misses names entirely — the identifier a compliance reviewer looks for first); call an LLM to judge (ruled out by [0004](0004-deterministic-compliance-no-self-attestation.md)).

## Decision

**Use a pinned local spaCy model (`en_core_web_sm` 3.8.0) and treat its output as a low-confidence tier.**

- `detectors/scoring/signals.py::LOW_CONFIDENCE_IDENTIFIERS` = `full_name`, `geographic_subdivision`, `residential_address`. If *only* these matched, the signal is `phi_in_output_low_confidence` (−5); if any other identifier matched, it's the full `phi_in_output` (−20). The two penalty tables (`detectors/scoring/signals.py` and `governance_api/authority/engine.py`) must stay equal — a test enforces it.
- The compliance engine downgrades a configured `block` to `redact` for these identifiers, so a statistical false positive can never wipe a whole response.
- Filters cut known false positives: state-level-and-above places are ignored (Safe Harbor only covers units *smaller* than a state); single-word eponymous diseases and "X's disease/syndrome" forms aren't names; a zip code needs context ("NY 10001", "zip code 90210") instead of matching any 5-digit number. The eponym list is deliberately narrow and only applies to a bare single-word entity — a missed name is a PHI leak, a redacted disease name is only a utility hit.
- **Fail-closed:** if the model can't load, `detectors.ner` raises `NERUnavailableError` (the API refuses to start; a request would 5xx and the proxy already fails closed). `GUARDRAILS_NER_DISABLED=1` is the explicit, logged opt-out for a regex-only run.

## Consequences

- Redaction of names/places is now live in both packs, at a cost of ~3–5 ms per check (CPU).
- Legitimate text can still be redacted (e.g. an unusual place-like word), but it costs an agent 5 points, not 20, and never blocks.
- Recall is bounded by a small model. Misses cost nothing in score (no detection) — the more dangerous direction. Known gaps are listed in `docs/MOCKED_VS_PRODUCTION.md`.
- The tier is by identifier name, not by source, so a context-gated zip code is also low-confidence.
- Adds a ~13 MB model download (in `detectors/requirements.txt`; already covered by CI's `pip install -r requirements-dev.txt`).
