# 0015: Decision-model detector behind `DECISION_MODE` (`ner` | `laya` | `cascade`)

Status: Accepted (feature branch `feature_dc_model`)

## Context

The classic path (regex + spaCy NER) misses paraphrased or context-dependent
PII ("my social, you know, the nine-digit one") that a decision model
(Laya / Typesafe `systemOne`, Noul P(yes) per question) catches semantically --
and the decision model over-fires borderline categories (SSN text scored
`financial_account: 0.50`, `health_info` intermittently) that regex pins
precisely. Either backend alone has a recall/precision hole the other covers.
The Laya endpoint is also an ephemeral tunnel (trycloudflare): it WILL die
mid-demo, so any integration must survive its absence.

## Decision

New self-contained package `detectors/decision/` (config, per-pack Noul
question sets, `systemOne` client, mode router) selected by `DECISION_MODE`:

- `ner` (default, unset/unknown): classic path, byte-for-byte old behavior.
- `laya`: decision model only; firing questions emit `(laya_<qid>, full text)`
  -- full-text span is deliberate, so the unchanged engine coarse-redacts the
  segment instead of `str.replace("", ...)` poisoning it. Ordered first.
- `cascade`: union of both, Laya hits first; worst verdict wins (= max-score
  rule); one check still costs one penalty via the existing `phi_signal`.

Merge-safety: zero edits to `detectors/hipaa|dpdp|ner.py`; the single hook in
`compliance/engine.py::_run_detectors` delegates to the router and passes the
pack detector in, so upstream pack edits are picked up with no duplication.
`laya_*` identifiers are namespaced (high-confidence tier, default `redact`,
block-configurable) and can never collide with future regex names.
`LAYA_FAIL_OPEN=1` (default): Laya error -> warn + fall back to `ner`, so a
dead tunnel degrades to classic behavior instead of breaking the demo;
`0` propagates `LayaUnavailableError` for fail-closed CI.

## Consequences

- Demo-safe: tunnel death is a warning + ner fallback (verified live: a
  timed-out clean-text check still returned `allow` via fallback).
- Calibration knob `LAYA_THRESHOLD` (default 0.5, recall-leaning); borderline
  over-fire only ever redacts more, never lets PII through.
- Cost: one `systemOne` POST per check in `laya`/`cascade` (5-6 questions
  batched); `LAYA_TIMEOUT_S` bounds it.
- No DB migration: unknown `laya_*` identifiers default to `redact`.
