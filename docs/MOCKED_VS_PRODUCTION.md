# Mocked / Simplified vs. Production-Grade

Required by the problem statement's deliverable #8 write-up. Read this before demoing or before anyone assumes a piece is further along than it is.

## Mocked or simplified (placeholder as of this scaffold)

| Area | What's mocked | File | Real version would need |
|---|---|---|---|
| PHI/PII detection | Regex only; `full_name` and `geographic_subdivision` have no real detector at all | `detectors/hipaa/identifiers.py`, `detectors/dpdp/identifiers.py` | A NER model (e.g. spaCy, a fine-tuned small model) for name/address extraction; regex alone under-recalls badly on these two |
| Compliance action wiring | `governance_api/compliance/engine.py`'s `_run_detectors` returns `[]` — detectors aren't called from the engine yet | `governance_api/compliance/engine.py` | Import and call `detectors.hipaa/dpdp.identifiers.find_all` for real |
| Composite trust rating / effective-use score | Simple linear formulas (`100 - violations*5 - denials*3`, tokens-per-violation) | `data_pipeline/aggregation/user_profile_job.py` | Whatever weighting the Data Scientist validates against real usage patterns — still meant to stay a transparent proxy, not ML, per the problem statement's non-goals |
| Anomaly/injection detection | A short, hand-written regex list | `detectors/injection/heuristics.py` | Broader adversarial test coverage; still explicitly rule-based per non-goals ("no real anomaly-detection ML") |
| Signing | HMAC-SHA256 with a static secret in an env var | `governance_api/receipts/writer.py` | A real KMS-backed key, rotation, per-environment secrets — explicitly out of scope per non-goals ("cryptographically rigorous signing (hash-chaining only)") |
| Multi-agent score rollup | `/governance/handoff-check` only evaluates the one agent in the request; it does not yet aggregate multiple agents' scores within a session to decide whether the *final* output should be blocked | `governance_api/routes/governance.py` (`handoff_check`, see its TODO) | The rollup logic objective #4/#6 describes: block the final output if enough agents (or one severely) violate policy |
| Token usage capture | `data_pipeline/ingestion/token_usage_pipeline.py`'s `ingest_event` exists but nothing calls it from the proxy yet | `proxy/main.py` | Read `usage.prompt_tokens`/`usage.completion_tokens` off the real upstream response and call `ingest_event` |
| Admin portal | Config-only CRUD (thresholds, pack actions, per-user_id override); no auth on the admin routes themselves | `governance_api/routes/admin.py`, `dashboard/admin.html` | Whatever auth the surrounding platform provides — deliberately out of scope, see [docs/adr/0005](adr/0005-user-identity-no-auth.md) |
| Dashboard "live" updates | Manual "Load" button, one-shot fetch | `dashboard/static/js/session_dashboard.js`, `user_dashboard.js` | Polling or SSE for the "live" score trend the problem statement's objective #11 asks for |
| LangGraph node wrapping | `wrap_graph_nodes` sketches the intent against an assumed `StateGraph` internals shape, unverified against the installed LangGraph version | `governance_sdk/governance_sdk/integrations/langgraph_wrapper.py` | Verification against the actual installed LangGraph API (this was an open action item from the kickoff meeting) |
| Proxy payload rewriting | `_apply_cleaned_text` is a no-op — redacted/hashed text is computed but not actually written back into the request/response payload sent onward | `proxy/main.py` | Write `cleaned_text` into the right message field before forwarding |
| Dashboard JS test coverage | None — no JS test runner set up in this scaffold, so `dashboard/static/js/*.js` is only covered by manual QA | `dashboard/static/js/` | A lightweight JS test setup (e.g. Playwright or Vitest) if the dashboard grows past what manual QA can reliably catch |
| Docker Compose path | Written but not build-tested end-to-end (`docker compose up --build`) — only the direct pip/uvicorn path (README's "Local setup") has actually been run and verified | `docker-compose.yml`, `governance_api/Dockerfile`, `proxy/Dockerfile` | A CI job (or at least one manual run) that actually builds and boots the compose stack before relying on it for a demo |

## Already real / production-shaped (not mocked)

- **Identity envelope discipline** — `user_id`/`session_id`/`agent_id`/`parent_agent_id` are set by trusted code paths only, never parsed from LLM text, everywhere in this codebase (proxy, SDK, API routes).
- **Hash-chain + signature verification** — `governance_api/receipts/writer.py` and `data_pipeline/ledger/verify_chain.py` are the real mechanism (only the *key management* around the signature is a placeholder, not the chaining/verification logic itself).
- **Monotonic reduction** — `governance_api/authority/engine.py` genuinely cannot increase a score except through `get_or_create`'s initial value; there is no code path that raises `current_score` afterward.
- **Delegation capping** — `governance_api/authority/delegation.py`'s `capped_initial_score` is enforced at agent-state creation time, not advisory.
- **Fail-closed behavior** — `GovernanceClient._post` and the proxy's `_fail_closed` genuinely deny on any transport/HTTP error; this isn't simplified, it's the actual intended behavior.
- **DB connection layering** — SQLite-by-default / Postgres-via-env-var (`shared/db.py`) is a real production pattern, not a shortcut that needs replacing later.
- **Dashboard output escaping** — every field rendered into the dashboard (`reason`, `agent_id`, `user_id`, etc.) goes through `escapeHtml()` (`dashboard/static/js/api.js`) before hitting `innerHTML`. This was a real stored-XSS gap until 2026-09-28 (a caller-supplied `user_id` — untrusted by design, see [docs/adr/0005](adr/0005-user-identity-no-auth.md) — could flow into a receipt's `reason` and execute in an admin's browser); it's fixed now, not merely documented as a rule.
- **CORS** — `governance_api` explicitly allows the dashboard's cross-origin fetches (`CORSMiddleware` in `governance_api/main.py`); without it the dashboard silently fails in a real browser despite passing every `curl`/`TestClient`-based check.
