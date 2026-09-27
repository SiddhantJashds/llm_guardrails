# Progress

Shared checklist mirroring the step-by-step plan in [HACKATHON_PLAN.md](HACKATHON_PLAN.md). One section per role. Read and updated by the `dev-next-steps` skill (`.claude/skills/dev-next-steps/`) — you can also check boxes by hand.

Legend: `[ ]` not started · `[~]` scaffolded (file/wiring exists, real logic still a placeholder — see [MOCKED_VS_PRODUCTION.md](MOCKED_VS_PRODUCTION.md)) · `[x]` done and verified.

Before marking anything `[x]` that touches `shared/`, `authority/`, `compliance/`, `access_control/`, or a route: run `pytest` from the repo root ([docs/adr/0007](adr/0007-tests-and-ci-before-handoff.md)). It also runs automatically in CI on every push/PR.

Last updated: 2026-09-28 (initial scaffold pass + test suite/CI added — see git history / ADRs for what changed since).

## SWE #1 — Gateway & Integration Engineer

**Day 1**
- [~] 1. Scaffold `governance_sdk` package with `GovernanceClient` + `@governed_tool` — client and decorator exist, not yet used against a real running agent
- [~] 2. OpenAI-compatible reverse proxy (`proxy/main.py`) — accepts requests, calls governance_api, forwards upstream; `_apply_cleaned_text` is a no-op (see MOCKED_VS_PRODUCTION.md)
- [x] 3. Identity Envelope Binder wired, never derived from model output
- [x] 4. Receipt writer: hash-chain + HMAC sign, verified against `data_pipeline/ledger/verify_chain.py`
- [~] 5. LangChain callback handler (`GovernanceCallbackHandler`) — written, not exercised against a real LangChain agent yet
- [ ] 6. End-to-end: one real LangChain single-agent flow, one real tool, HIPAA pack, full loop verified

**Day 2**
- [~] 7. LangGraph `@governed_node` wrapping — decorator + helper exist; `wrap_graph_nodes` unverified against installed LangGraph API (see [docs/adr/0002](adr/0002-no-post-model-hook-lock-in.md))
- [x] 8. Delegation capping — `authority/delegation.py`, enforced in `AuthorityEngine.get_or_create`
- [x] 9. Fail-closed behavior — `GovernanceClient._post`, proxy's `_fail_closed`
- [~] 10. DPDP pack through the proxy path — pack config seeded, detectors not yet wired into the engine
- [ ] 11. Demo script's three scenarios wired through both single- and multi-agent paths

## SWE #2 — Authority Engine & Dashboard Engineer

**Day 1**
- [x] 1. Authority Engine: per-agent score, `get_or_create`, threshold check
- [x] 2. Monotonic reduction — `apply_signal` only ever subtracts
- [x] 3. Governance REST API (`/governance/tool-check`, `/compliance-check`, `/handoff-check`) — implemented and smoke-tested
- [x] 4. Dashboard backend (`GET /dashboard/session/{id}`) — implemented and smoke-tested
- [ ] 5. End-to-end demo: score visibly drops after a real violation, next call denied (blocked on detectors being wired in — see SWE#1 Day1 #10 / Data Scientist Day1 #4)

**Day 2**
- [x] 6. Per-tool thresholds admin-editable (not hardcoded) — `ToolThresholdConfig`, `/admin/tool-thresholds`
- [ ] 7. Per-agent rollup across a session (block final output if enough agents violate) — `handoff_check` currently only evaluates one agent, see TODO in `governance_api/routes/governance.py`
- [~] 8. Dashboard frontend — session view + per-user view built (`dashboard/index.html`, `user.html`); no live polling yet, manual "Load" button
- [x] 8b. Admin page (config-only, [docs/adr/0005](adr/0005-user-identity-no-auth.md)) — thresholds, pack actions, per-user_id override, `dashboard/admin.html`
- [~] 9. Per-user token usage display — dashboard reads `UserProfile`; nothing populates it yet (see Data Engineer Day2 #5)
- [ ] 10. Demo script attribution check across both paths

## Data Engineer — Ledger, Pipeline & Storage

**Day 1**
- [x] 1. Audit ledger schema + append (via `write_receipt`) + `verify_chain.py` — implemented and smoke-tested (tamper/signature check included)
- [x] 2. Compliance pack config storage (`CompliancePackConfig`, seeded from YAML) — implemented and smoke-tested
- [x] 3. Storage/query layer for the dashboard backend — implemented and smoke-tested
- [x] 4. End-of-day check: ledger accepts writes, chain-verify runs clean — verified 2026-09-28

**Day 2**
- [~] 5. Token-usage ingestion pipeline — `ingest_event` exists; proxy doesn't call it yet (see MOCKED_VS_PRODUCTION.md)
- [~] 6. User profile aggregation job — `user_profile_job.py` implemented with placeholder formulas; needs Data Scientist's real formulas
- [x] 7. HIPAA↔DPDP overlap mapping (`data_pipeline/config/overlap_map.yaml`)
- [ ] 8. Latency/overhead benchmarking — script exists (`benchmark_latency.py`), not yet run against a real upstream LLM
- [ ] 9. Cross-team schema compatibility check against the other 3 teams' reference agents

## Data Scientist — Compliance Detection & Scoring Logic

**Day 1**
- [~] 1. HIPAA pack v1 detectors — regex identifiers implemented + unit-tested (`detectors/tests/test_detectors.py`, 6/6 passing); `full_name`/`geographic_subdivision` have no detector at all yet (need NER)
- [x] 2. Four compliance actions (redact/block/hash/log_only) implemented, including the redact-by-default override logic ([docs/adr/0003](adr/0003-redact-by-default.md))
- [x] 3. Signal→penalty table (`detectors/scoring/signals.py`) handed to the Authority Engine
- [ ] 4. **End-of-day-1 blocker: detectors are not called from `governance_api/compliance/engine.py` yet** (`_run_detectors` returns `[]` — see its TODO). Wiring this in is what actually closes the Day-1 MVP loop end to end. A test already exists and is marked `xfail(strict=True)` for exactly this gap: `governance_api/tests/test_api_routes.py::test_compliance_check_actually_catches_phi_once_detectors_are_wired` — once you wire the detectors in, remove that marker; CI will fail (XPASS) if you forget.

**Day 2**
- [~] 5. DPDP pack detectors — phone/email/aadhaar/pan regex implemented + unit-tested; overlap map done; `residential_address` needs NER same as HIPAA's name/address gap
- [~] 6. Composite trust rating / effective-use score — placeholder linear formulas in `user_profile_job.py`, need real formulas from you
- [x] 7. Prompt-injection heuristics (`detectors/injection/heuristics.py`) — instruction-override + forged-identity patterns, Unicode-normalization evasion handling, unit-tested
- [ ] 8. Validate against demo script's 3 scenarios + adversarial injection case per pack
- [ ] 9. Cross-team detector coverage check
