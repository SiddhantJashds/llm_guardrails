# Architecture Decision Records

Short records of decisions that were non-obvious, contested, or hard to reverse — not a changelog of every choice made. Use [0000-template.md](0000-template.md) for new ones.

An ADR is worth writing when a decision:
- picks between two or more real alternatives (not "the only sane option"),
- would be expensive or awkward to reverse later,
- trades away something explicitly listed as in-scope (see the problem statement's Objectives/Non-Goals), or
- someone on another team will need to know *why*, not just *what*.

If you're not sure whether something rises to that bar, ask — or use the `decision-logger` skill (`.claude/skills/decision-logger/`), which is meant to catch this mid-conversation and ask before it gets lost.

## Index

| # | Title | Status |
|---|---|---|
| [0001](0001-storage-sqlite-default.md) | SQLite as the default datastore, Postgres via `DATABASE_URL` | Accepted |
| [0002](0002-no-post-model-hook-lock-in.md) | Wrap LangGraph nodes directly instead of relying on `post_model_hook` | Accepted |
| [0003](0003-redact-by-default.md) | Redact-by-default, even for higher-authority callers | Accepted |
| [0004](0004-deterministic-compliance-no-self-attestation.md) | Compliance/authority decisions are deterministic, never LLM self-attested | Accepted |
| [0005](0005-user-identity-no-auth.md) | No auth/RBAC/user creation; per-user_id override table instead | Accepted |
| [0006](0006-shared-progress-file.md) | Shared `docs/PROGRESS.md` over per-developer local progress files | Accepted |
| [0007](0007-tests-and-ci-before-handoff.md) | Automated tests + CI as a readiness gate before handoff | Accepted |
| [0008](0008-ner-low-confidence-tier.md) | NER-derived detections are a low-confidence tier (small penalty, never block) | Accepted |
| [0009](0009-no-signal-identifiers-for-metadata-markers.md) | Metadata markers (DPDP's `consent_purpose_flag`) cost the agent nothing | Accepted |
| [0010](0010-wire-injection-detection-into-compliance-routes.md) | Wire prompt-injection detection into the real decision pipeline | Accepted |
| [0011](0011-composite-rating-and-effective-use-formulas.md) | Composite trust rating / effective-use score: real formulas | Accepted |
| [0012](0012-langchain-langgraph-verified-against-installed-apis.md) | LangChain/LangGraph integrations verified against installed APIs | Accepted |
| [0013](0013-session-scoped-trust-state.md) | Trust state keyed per (agent, session), not per agent | Accepted |
| [0014](0014-tool-result-scans-dont-charge-score.md) | Tool-result scans redact but don't charge score | Accepted |
| [0015](0015-governance-console.md) | Governance console: vendored assets, live profiles, redacted conversation capture | Accepted |
| [0016](0016-redaction-redesign.md) | Redaction redesign: stable placeholders, sender restoration, and role-capped views | Accepted |
| [0017](0017-dpdp-coverage-audit-and-web-url-ip-reuse.md) | DPDP coverage audit: reuse `web_url`/`ip_address` from HIPAA, rest stays out of scope | Accepted |
