# 0016. Redaction redesign: stable placeholders, sender restoration, and role-capped views

Status: Accepted (supersedes ADR 0015 point 4 on x-request-unredacted; tightens ADR 0003)
Date: 2026-10-09

## Context

Under the original redaction design (ADR 0003, ADR 0015), values were replaced with generic `[REDACTED]` markers or hashes. This created three problems:
1. **Model incoherence**: the model lost the ability to distinguish different people or correlate recurring entities across conversation turns (e.g., patient vs. physician).
2. **Loss of sender context**: a user providing their own name received `Hello [REDACTED]!` in model replies, degrading user experience unnecessarily.
3. **All-or-nothing visibility**: unredacted access was an all-or-nothing per-user override that exposed everything or nothing, with no middle ground for clinical staff who need names but only partial phone numbers.

## Decision

1. **Typed, numbered placeholders for the model**:
   Entities are replaced with stable tokens per session: `[NAME_1]`, `[PHONE_1]`, `[EMAIL_1]`. These placeholders are mapped in an in-memory session vault (`governance_api/compliance/vault.py`) with a configurable TTL (default 7200s). The model never sees raw values, even under an unredacted override or role view.

2. **Restore sender's own values in replies (opt-in only)**:
   Placeholders for values typed by the end-user can be restored in outbound replies (`Hello, Alex`), but **only when the caller explicitly opts in**:
   - Proxy: clients send `x-restore-to-sender: true`. The proxy applies this only to `user`-role messages.
   - Bench bridge and SDK: **never** opt in. RAG context and database records must never be restored, preserving GuardRailBench scenario 4 compliance.

3. **Roles as a cap (tightens ADR 0003)**:
   Redaction roles (`RedactionRole`) define granular visibility per identifier: `hidden` (placeholder), `partial` (masked with unmasked suffix), or `full`.
   - Roles act as a **cap**, applying **only** when the caller explicitly requests it (`request_unredacted: true` / header `x-request-unredacted: true`). Without the ask, all callers receive placeholders.
   - Block and hash actions are **never** relaxed by any role.
   - The legacy `allow_unredacted` override is retained and behaves as an all-`full` role.
   - Default roles provided: `clinician` (full names, dates, locations; partial contact info) and `auditor` (everything hidden).
   - This supersedes ADR 0015's CORS restriction against `x-request-unredacted`; the header is now allowed and evaluated server-side.

4. **Per-identifier policy options**:
   Configured in `CompliancePackConfig.config` JSON:
   - `action`: `redact`, `block`, `hash`, `log_only`
   - `style`: `token` (numbered placeholder), `partial` (with `keep_last`), `masked` (`[REDACTED_PHONE]`)
   - `restore_to_sender`: boolean
   - `applies_to`: `both`, `inbound`, `outbound`

5. **Visual distinction in UI**:
   Categorical entity palette by kind:
   - NAME: series-1 (blue)
   - PHONE: series-2 (orange)
   - EMAIL: series-3 (green)
   - LOCATION: series-4 (red)
   - DATE: series-5 (purple)
   - DEVICE: series-6 (teal)
   - ID numbers: series-7 (amber)
   - Other / unknown: neutral grey

## Consequences

- The LLM receives structured, consistent placeholder tokens, improving multi-turn reasoning without exposing raw PII.
- Stored ledger records (`Receipt.payload`) record only the model-side text (placeholders and masks), never raw values or restored display text.
- The vault is in-memory and per-process; in multi-node deployments, session affinity or a distributed cache (e.g. Redis) is required.
