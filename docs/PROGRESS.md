# Progress

Shared checklist mirroring the step-by-step plan in [HACKATHON_PLAN.md](HACKATHON_PLAN.md). One section per role. Read and updated by the `dev-next-steps` skill (`.claude/skills/dev-next-steps/`) — you can also check boxes by hand.

Legend: `[ ]` not started · `[~]` scaffolded (file/wiring exists, real logic still a placeholder — see [MOCKED_VS_PRODUCTION.md](MOCKED_VS_PRODUCTION.md)) · `[x]` done and verified.

Before marking anything `[x]` that touches `shared/`, `authority/`, `compliance/`, `access_control/`, or a route: run `pytest` from the repo root ([docs/adr/0007](adr/0007-tests-and-ci-before-handoff.md)). It also runs automatically in CI on every push/PR.

Last updated: 2026-10-09 (SWE#1 Day2 #11 done: `examples/demo_scenarios.py` runs the 3 canonical scenarios through the real LangChain and LangGraph paths with dashboard attribution asserted; `pytest` 207 passed + 2 xfailed. SWE#2 Day2 #9 done: per-user token tiles + per-call usage chart read live from TokenUsageEvent. Data Engineer Day2 #5 done: proxy calls ingest_event from upstream response; .env DATABASE_URL fix applied. Bench integration: `bench_bridge/` serves the GuardRailBench hook contract — sample-edition scenarios 1, 4, 13 score 3/3 PASS; trust state re-keyed per (agent, session) [adr/0013]; tool-result scans redact without charging score [adr/0014]; `run.sh` is `.env`-driven via `WITH_BRIDGE`; `examples/chat_memory.py` adds LangGraph-checkpoint memory; `pytest` 176 passed + 1 xfailed.)

## Bench bridge (cross-cutting, 2026-10-09)

- [x] `bench_bridge/main.py` — 5 hook endpoints → `compliance-check`/`tool-check` (+ out-of-scope deny), fail-closed, seed-if-absent bench thresholds (low 50 / medium 60 / high 80); `scripts/check_contract.py` 5/5; full `run_all.py` 3/3 PASS (see [docs/BENCH_BRIDGE.md](BENCH_BRIDGE.md))
- [x] Session-scoped trust — composite PK `(agent_id, session_id)`; same-session parent cap; regression test `test_scores_are_isolated_between_sessions` ([adr/0013](adr/0013-session-scoped-trust-state.md)); requires `governance.db` rebuild
- [x] `apply_score` on `compliance-check` — tool-result scans redact + receipt, no penalty ([adr/0014](adr/0014-tool-result-scans-dont-charge-score.md)); SDK `check_compliance` passes it through
- [x] `run.sh` — one-command startup, `WITH_BRIDGE` read from `.env` (never sourced), ordered boot (api → rest), proxy on `:8002` + dashboard on `:8081` in bench mode
- [x] `examples/chat_memory.py` — LangGraph `InMemorySaver` memory chat through the proxy (verified two-turn recall); `examples/rag_interface.py` model fixed to the served Qwen model; LangGraph demo catches its own `PermissionError` denial instead of tracebacking

## SWE #1 (Sauda) — Gateway & Integration Engineer

**Day 1**
- [x] 1. Scaffold `governance_sdk` package with `GovernanceClient` + `@governed_tool` — now exercised against a real running agent ([docs/adr/0012](adr/0012-langchain-langgraph-verified-against-installed-apis.md); `governance_sdk/tests/`)
- [x] 2. OpenAI-compatible reverse proxy (`proxy/main.py`) — accepts requests, calls governance_api, forwards upstream, and now writes redacted text back into the forwarded request and returned completion (`proxy/tests/test_payload_rewriting.py`, real governance_api in-process + stubbed upstream)
- [x] 3. Identity Envelope Binder wired, never derived from model output
- [x] 4. Receipt writer: hash-chain + HMAC sign, verified against `data_pipeline/ledger/verify_chain.py`
- [x] 5. LangChain callback handler (`GovernanceCallbackHandler`) — exercised against a real (scripted, no API key) `langchain.agents.create_agent` loop; found and fixed a real bug along the way: `raise_error` defaults to `False` on `BaseCallbackHandler`, so a `PermissionError` raised in `on_tool_start` was being silently swallowed and the tool ran anyway (see adr/0012) — now set to `True` and pinned with a regression test
- [x] 6. End-to-end: one real LangChain single-agent flow, one real tool, HIPAA pack, full loop verified (`governance_sdk/tests/test_langchain_integration.py`, `examples/langchain_single_agent.py`) — against the real `governance_api` in-process (no server/API key needed), not mocked

**Day 2**
- [x] 7. LangGraph `@governed_node` wrapping — verified against the installed LangGraph API (adr/0012): `wrap_graph_nodes`'s original attribute assignment was genuinely broken (`.runnable` is a `RunnableCallable`, not directly callable — fixed by mutating `.runnable.func` in place); also found and fixed `governed_node` re-penalizing every downstream node for an upstream node's leak it only carried forward in state, never caused itself (`governance_sdk/tests/test_langgraph_integration.py`, `examples/langgraph_multi_agent.py`)
- [x] 8. Delegation capping — `authority/delegation.py`, enforced in `AuthorityEngine.get_or_create`
- [x] 9. Fail-closed behavior — `GovernanceClient._post`, proxy's `_fail_closed`
- [x] 10. DPDP pack through the proxy path — `proxy/main.py` takes the pack from an `x-compliance-pack` header (`hipaa` default, `dpdp`; unknown value → 400, since the engine would otherwise silently allow it); DPDP PAN hashed / Aadhaar blocked / HIPAA-only SSN left alone, inbound and outbound, against the real governance_api with the shipped pack configs (`proxy/tests/test_pack_selection.py`)
- [x] 11. Demo script's three scenarios wired through both single- and multi-agent paths — `examples/demo_scenarios.py` runs benign / violation / repeated-then-denied through a real `create_agent` loop with `GovernanceCallbackHandler` and a real compiled orchestrator→worker LangGraph (`@governed_node` + `wrap_graph_nodes` + `@governed_tool`), asserting the outcome and the per-`agent_id` dashboard row after each (`python examples/demo_scenarios.py`, or `--live` against a running API so the dashboard shows the sessions; CI: `examples/tests/test_demo_scenarios.py`, scenario 3 is threshold-agnostic). **Found along the way (SWE#2's area, see #10 below):** on the LangGraph path `handoff-check` writes no `compliance` receipt, so a leak shows as a score drop + `history` entry but not in the dashboard's violations table (strict `xfail` pins it); and neither path rewrites the leaked text (only the proxy does)

## SWE #2 (Harsh) — Authority Engine & Dashboard Engineer

**Day 1**
- [x] 1. Authority Engine: per-agent score, `get_or_create`, threshold check
- [x] 2. Monotonic reduction — `apply_signal` only ever subtracts
- [x] 3. Governance REST API (`/governance/tool-check`, `/compliance-check`, `/handoff-check`) — implemented and smoke-tested
- [x] 4. Dashboard backend (`GET /dashboard/session/{id}`) — implemented and smoke-tested
- [x] 5. End-to-end demo: score visibly drops after a real violation, next call denied — verified via `governance_api/tests/test_demo_scenarios.py` (all 8 scenarios pass: detector catches PHI → score drops via `apply_signal` → `tool-check` denies below threshold)

**Day 2**
- [x] 6. Per-tool thresholds admin-editable (not hardcoded) — `ToolThresholdConfig`, `/admin/tool-thresholds`
- [x] 7. Per-agent rollup across a session (block final output if enough agents violate) — `handoff_check` now queries all `AgentTrustState` rows for the session, uses the lowest score vs. `DEFAULT_THRESHOLD` (60) to decide; added tests `test_handoff_check_blocks_when_session_min_score_falls_below_threshold` and `test_handoff_check_allows_when_all_agents_stay_above_threshold`
- [x] 8. Dashboard frontend — session view + per-user view built (`dashboard/index.html`, `user.html`); live polling at 3s interval with green "● Live (3s)" badge, starts on "Load" click, stops on re-load (clears interval); static CSS badge added
- [x] 8b. Admin page (config-only, [docs/adr/0005](adr/0005-user-identity-no-auth.md)) — thresholds, pack actions, per-user_id override, `dashboard/admin.html`
- [x] 9. Per-user token usage display — `/dashboard/user/{id}` sums `TokenUsageEvent` rows live (so tiles don't wait on the manual `user_profile_job.py` run) and returns a per-call `token_usage` series; `user.html` chart is now a line chart of tokens in/out per call. Route-tested (`test_dashboard_user_token_totals_come_from_events_without_the_aggregation_job`, per-user isolation test); not yet eyeballed in a browser with live proxy traffic
- [x] 11. Governance console redesign (2026-10-09): auto-loading dashboard with overview, sessions, users, audit ledger, live bench, evaluations, policy settings + data reset, and a docked test console (proxy chat, GuardRailBench apps, direct checks, 25 sample cases). Backed by new `/dashboard/*`, `/playground/*`, `/admin/reset` endpoints with tests; see README "Governance console" and [adr/0015](adr/0015-governance-console.md)
- [x] 12. Redaction redesign & policy console (2026-10-09, [docs/adr/0016](adr/0016-redaction-redesign.md)): session-stable typed placeholders (`[NAME_1]`), sender value restoration (`x-restore-to-sender`), role-capped visibility matrix (`clinician`, `auditor`), user role assignments, identifier styles (token/partial/masked), test console model vs. display text view with kindLegend, 32 sample cases (7 redaction views).
- [x] 10. Demo script attribution check across both paths (2026-10-09) — `handoff_check` now writes a compliance receipt on violations so LangGraph handoff leaks appear in the dashboard violations table; `test_langgraph_leak_appears_in_the_dashboards_violations_table` passes without xfail.

## Data Engineer (Somu) — Ledger, Pipeline & Storage

**Day 1**
- [x] 1. Audit ledger schema + append (via `write_receipt`) + `verify_chain.py` — implemented and smoke-tested (tamper/signature check included)
- [x] 2. Compliance pack config storage (`CompliancePackConfig`, seeded from YAML) — implemented and smoke-tested
- [x] 3. Storage/query layer for the dashboard backend — implemented and smoke-tested
- [x] 4. End-of-day check: ledger accepts writes, chain-verify runs clean — verified 2026-09-28

**Day 2**
- [x] 5. Token-usage ingestion pipeline — proxy calls `ingest_event` with tokens_in/tokens_out from upstream response; verified with real DB row
- [x] 6. User profile aggregation job — `user_profile_job.py` now uses the Data Scientist's real formulas ([docs/adr/0011](adr/0011-composite-rating-and-effective-use-formulas.md)); unit+integration-tested
- [x] 7. HIPAA↔DPDP overlap mapping (`data_pipeline/config/overlap_map.yaml`)
- [x] 8. Latency/overhead benchmarking — script ran against real upstream LLM, produced before/after timing (0.341s direct vs 0.424s proxied, ~83ms overhead)
- [ ] 9. Cross-team schema compatibility check against the other 3 teams' reference agents — **deferred to end-of-dev** (2026-10-05): blocked on those agents existing, nothing to run this against yet; revisit once they're available rather than waiting on them

## Data Scientist (Siddhant) — Compliance Detection & Scoring Logic

**Day 1**
- [x] 1. HIPAA pack v1 detectors — 16 identifier classes via regex (`detectors/hipaa/identifiers.py`) + `full_name`/`geographic_subdivision` via pinned spaCy NER (`detectors/ner.py`, low-confidence tier, [docs/adr/0008](adr/0008-ner-low-confidence-tier.md)); unit-tested (`detectors/tests/`). `biometric`/`full_face` still need image analysis; known NER gaps in MOCKED_VS_PRODUCTION.md
- [x] 2. Four compliance actions (redact/block/hash/log_only) implemented, including the redact-by-default override logic ([docs/adr/0003](adr/0003-redact-by-default.md))
- [x] 3. Signal→penalty table (`detectors/scoring/signals.py`) handed to the Authority Engine
- [x] 4. **End-of-day-1 blocker: detectors are not called from `governance_api/compliance/engine.py` yet** (`_run_detectors` returns `[]` — see its TODO). Wiring this in is what actually closes the Day-1 MVP loop end to end. A test already exists and is marked `xfail(strict=True)` for exactly this gap: `governance_api/tests/test_api_routes.py::test_compliance_check_actually_catches_phi_once_detectors_are_wired` — once you wire the detectors in, remove that marker; CI will fail (XPASS) if you forget.

**Day 2**
- [x] 5. DPDP pack detectors — phone/email/aadhaar/pan regex + NER `full_name`/place-level `residential_address` (low-confidence tier) + street-address & labelled-PIN regex + bare-Indian-mobile recall fix + `consent_purpose_flag` heuristic (always zero-cost, [docs/adr/0009](adr/0009-no-signal-identifiers-for-metadata-markers.md)); overlap map done; unit-tested (`detectors/tests/test_dpdp.py`)
- [x] 6. Composite trust rating / effective-use score — rate-based `composite_rating` (0-100, violations weighted above denials) + `effective_use_score` (tokens per completed task); implemented in `data_pipeline/aggregation/user_profile_job.py`, unit+integration-tested (`data_pipeline/tests/test_user_profile_job.py`), see [docs/adr/0011](adr/0011-composite-rating-and-effective-use-formulas.md). Also fixed `violation_count` wrongly counting `log_only` verdicts as violations (adr/0009's principle extended here)
- [x] 7. Prompt-injection heuristics (`detectors/injection/heuristics.py`) — instruction-override + forged-identity patterns, Unicode-normalization evasion handling, unit-tested; **and now actually wired into `compliance-check`/`handoff-check`** ([docs/adr/0010](adr/0010-wire-injection-detection-into-compliance-routes.md)) — the detector existed and passed its own tests since Day 2, but nothing in `governance_api` called it until now, so `prompt_injection_detected` never fired through the real API
- [x] 8. Validate against demo script's 3 scenarios + adversarial injection case per pack — `governance_api/tests/test_demo_scenarios.py`, both packs, run against the real API (scope note in the file: this covers the governance_api-level pipeline the Data Scientist owns; wiring it through the actual LangChain/LangGraph paths is SWE#1 Day1 #6 / Day2 #7/#11)
- [ ] 9. Cross-team detector coverage check — **deferred to end-of-dev** (2026-10-05): blocked on those agents existing, nothing to run this against yet; revisit once they're available rather than waiting on them
