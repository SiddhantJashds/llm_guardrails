# Progress

Shared checklist mirroring the step-by-step plan in [HACKATHON_PLAN.md](HACKATHON_PLAN.md). One section per role. Read and updated by the `dev-next-steps` skill (`.claude/skills/dev-next-steps/`) — you can also check boxes by hand.

Legend: `[ ]` not started · `[~]` scaffolded (file/wiring exists, real logic still a placeholder — see [MOCKED_VS_PRODUCTION.md](MOCKED_VS_PRODUCTION.md)) · `[x]` done and verified.

Before marking anything `[x]` that touches `shared/`, `authority/`, `compliance/`, `access_control/`, or a route: run `pytest` from the repo root ([docs/adr/0007](adr/0007-tests-and-ci-before-handoff.md)). It also runs automatically in CI on every push/PR.

Last updated: 2026-10-08 (Data Engineer Day2 #8 done: latency benchmarking script ran against real upstream LLM, ~83ms overhead; benchmark_latency.py syntax fix applied.)

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
- [~] 10. DPDP pack through the proxy path — pack config seeded; detectors ARE now wired into the engine (this note was stale — see Data Scientist Day1 #4/Day2 #5), so the only remaining blocker is `proxy/main.py` hardcoding `"pack_id": "hipaa"` on both compliance-check calls instead of making it selectable
- [~] 11. Demo script's three scenarios wired through both single- and multi-agent paths — the MECHANISM is now proven working through both paths (#6/#7 above: tool allow/deny, PHI redaction+scoring, multi-agent handoff all verified for real), but the actual 3 canonical demo-script scenarios (same ones in `governance_api/tests/test_demo_scenarios.py`) haven't been composed into one script run through each path yet

## SWE #2 (Harsh) — Authority Engine & Dashboard Engineer

**Day 1**
- [x] 1. Authority Engine: per-agent score, `get_or_create`, threshold check
- [x] 2. Monotonic reduction — `apply_signal` only ever subtracts
- [x] 3. Governance REST API (`/governance/tool-check`, `/compliance-check`, `/handoff-check`) — implemented and smoke-tested
- [x] 4. Dashboard backend (`GET /dashboard/session/{id}`) — implemented and smoke-tested
- [ ] 5. End-to-end demo: score visibly drops after a real violation, next call denied (blocked on detectors being wired in — see SWE#1 Day1 #10 / Data Scientist Day1 #4)

**Day 2**
- [x] 6. Per-tool thresholds admin-editable (not hardcoded) — `ToolThresholdConfig`, `/admin/tool-thresholds`
- [x] 7. Per-agent rollup across a session (block final output if enough agents violate) — `handoff_check` now queries all `AgentTrustState` rows for the session, uses the lowest score vs. `DEFAULT_THRESHOLD` (60) to decide; added tests `test_handoff_check_blocks_when_session_min_score_falls_below_threshold` and `test_handoff_check_allows_when_all_agents_stay_above_threshold`
- [x] 8. Dashboard frontend — session view + per-user view built (`dashboard/index.html`, `user.html`); live polling at 3s interval with green "● Live (3s)" badge, starts on "Load" click, stops on re-load (clears interval); static CSS badge added
- [x] 8b. Admin page (config-only, [docs/adr/0005](adr/0005-user-identity-no-auth.md)) — thresholds, pack actions, per-user_id override, `dashboard/admin.html`
- [~] 9. Per-user token usage display — dashboard reads `UserProfile`; nothing populates it yet (see Data Engineer Day2 #5)
- [ ] 10. Demo script attribution check across both paths

## Data Engineer (Somu) — Ledger, Pipeline & Storage

**Day 1**
- [x] 1. Audit ledger schema + append (via `write_receipt`) + `verify_chain.py` — implemented and smoke-tested (tamper/signature check included)
- [x] 2. Compliance pack config storage (`CompliancePackConfig`, seeded from YAML) — implemented and smoke-tested
- [x] 3. Storage/query layer for the dashboard backend — implemented and smoke-tested
- [x] 4. End-of-day check: ledger accepts writes, chain-verify runs clean — verified 2026-09-28

**Day 2**
- [~] 5. Token-usage ingestion pipeline — `ingest_event` exists; proxy doesn't call it yet (see MOCKED_VS_PRODUCTION.md)
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
