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
