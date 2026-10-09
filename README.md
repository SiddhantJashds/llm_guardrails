# Compliance + Earned-Authority Governance Runtime

Scaffold for the hackathon project described in [docs/HACKATHON_PLAN.md](docs/HACKATHON_PLAN.md) — read that first for the architecture, team-role split, and the prompt-injection hardening rules every piece of this code must follow.

## New to this repo?

Read [docs/DEVELOPER_GUIDE.md](docs/DEVELOPER_GUIDE.md) first — it's the single "what do I do" document (setup, the daily loop, conventions, git etiquette for 4 people with nobody centrally reviewing, and a troubleshooting table). Everything below this point is reference material you'll come back to, not a sequence to follow top to bottom.

## Running tests

```bash
pip install -r requirements-dev.txt
pytest              # runs governance_api/tests/ + detectors/tests/
```

Runs automatically on every push/PR via `.github/workflows/tests.yml`. One test is deliberately marked `xfail(strict=True)` — [docs/adr/0007](docs/adr/0007-tests-and-ci-before-handoff.md) explains why; don't "fix" it by loosening the assertion, fix it by wiring the real detectors in.

## Docs

| Doc | What's in it |
|---|---|
| [docs/DEVELOPER_GUIDE.md](docs/DEVELOPER_GUIDE.md) | **Start here.** Setup, the daily workflow, conventions, git etiquette, troubleshooting |
| [docs/HACKATHON_PLAN.md](docs/HACKATHON_PLAN.md) | Architecture, team/role split, day-by-day build plan, prompt-injection hardening rules |
| [docs/adr/](docs/adr/README.md) | Architecture Decision Records — why the non-obvious choices were made |
| [docs/INTEGRATION_CONTRACT.md](docs/INTEGRATION_CONTRACT.md) | The handoff doc for the other 3 hackathon teams: exactly how to attach a LangChain/LangGraph/chat/RAG agent to this runtime |
| [docs/MOCKED_VS_PRODUCTION.md](docs/MOCKED_VS_PRODUCTION.md) | What's a real implementation vs. a placeholder, and what production-grade would need |
| [docs/PROGRESS.md](docs/PROGRESS.md) | Live per-role checklist against the plan's build steps |
| [docs/BENCH_BRIDGE.md](docs/BENCH_BRIDGE.md) | Running GuardRailBench-Sample against this runtime via `bench_bridge/` (mapping, thresholds, 3/3 result) |

## Layout

```
shared/            DB connection, ORM models, identity envelope, API schemas -- used by both services
governance_sdk/    pip-installable client: GovernanceClient, @governed_tool, @governed_node, LangChain/LangGraph integrations   [SWE #1 -- Sauda]
proxy/             OpenAI-compatible reverse proxy (single-LLM-call integration point)                                          [SWE #1 -- Sauda]
governance_api/    Authority engine, compliance engine, receipt writer, /governance/* and /dashboard/* REST API                 [SWE #2 -- Harsh]
dashboard/         Governance console: static ES-module SPA, vendored Chart.js/icons/fonts, no build step                      [SWE #2 -- Harsh]
data_pipeline/     Ledger chain verification, token-usage ingestion, user-profile aggregation, compliance pack config, benchmarking [Data Engineer -- Somu]
detectors/         HIPAA/DPDP identifier detectors, prompt-injection heuristics, trust-score signal table                        [Data Scientist -- Siddhant]
examples/          Reference agents: stateless chat, memory chat (LangGraph checkpointer), RAG, LangChain single-agent, LangGraph multi-agent
bench_bridge/      GuardRailBench hook-contract adapter (`/api/v1/*` on :8080 → governance_api) -- see docs/BENCH_BRIDGE.md
scripts/           init_db.py -- creates tables + seeds compliance pack config from data_pipeline/config/*.yaml
run.sh             One-command startup (uv): reads WITH_BRIDGE from .env, starts api/proxy/dashboard (+bridge and GuardRailBench apps in bench mode)
```

Every file with a `TODO` is a placeholder — the shapes, wiring, and interfaces are real; the detection/scoring logic inside them is not.

## Local setup (no Docker)

```bash
uv venv && uv pip install -r requirements-dev.txt
uv pip install -r governance_api/requirements.txt -r proxy/requirements.txt -r data_pipeline/requirements.txt -r detectors/requirements.txt
uv pip install -e governance_sdk/

cp .env.example .env   # then edit UPSTREAM_LLM_API_KEY etc.
uv run scripts/init_db.py

./run.sh   # starts api :8001, proxy :8000, dashboard :8080 (all via `uv run`)
```

`run.sh` reads `WITH_BRIDGE` from `.env`: `0` is normal dev (above);
`1` is bench mode — bridge on `:8080`, proxy moves to `:8002` (the bench server
needs `:8000`; `examples/` follow `WITH_BRIDGE` via `examples/example_config.py`,
or set `PROXY_URL` to override), dashboard moves to `:8081`. See [docs/BENCH_BRIDGE.md](docs/BENCH_BRIDGE.md).

Then try a reference agent end-to-end:

```bash
uv run examples/chat_interface.py   # stateless REPL
uv run examples/chat_memory.py      # same path + LangGraph-checkpoint memory
```

## Docker Compose (Postgres instead of SQLite)

```bash
docker compose up --build
```

## Governance console (dashboard)

`./run.sh` serves it on `:8080` (`:8081` in bench mode). Open `http://localhost:8080/` — everything
loads by itself, no ids to type. It's static HTML/CSS/ES modules with no build step and no CDN:
Chart.js 4.5.1, Material Icons, Inter and JetBrains Mono live in `dashboard/static/vendor/` (licenses
beside them), so it works offline. It reads `governance_api` on `:8001`; point it elsewhere with
`?api=http://host:port` in the URL.

| Page | What it shows |
|---|---|
| **Overview** | Decisions, sessions, users, redactions, blocks, denials, tokens; audit-integrity status (every session's receipt chain re-hashed and signature-checked); the most recent audit records; decision volume over time; detected identifier types; recent sessions and decisions |
| **Sessions** / **Session** | Every session ever recorded, searchable and sortable. A session shows its agents as a delegation tree with real trust trajectories (including the delegation-cap starting score), the conversation as forwarded after redaction, detected identifiers, denied tool calls, and every decision with its record hash. Select an agent to filter to it |
| **Users** / **User** | Every user with a live composite rating (same formulas as `user_profile_job.py`), token usage over time, outcome mix, their sessions and decision history |
| **Audit ledger** | Every signed, hash-chained receipt, filterable and paged |
| **Live bench** | A GuardRailBench run as it happens (`python run_all.py`): runs grouped by the bench's per-run user suffix, live counts, every hook event with its cleaned text; links the run's report once written |
| **Evaluations** | Every GuardRailBench report: scenario pass/fail matrix across runs, checks, request/response text, per-hook input/output logs, links to the sessions each scenario produced |
| **Policy settings** | Tool thresholds, HIPAA/DPDP identifier actions, unredacted overrides (see [Admin portal](#admin-portal)), and **Reset activity data** |

**Test console** (sidebar): a docked, resizable panel. The mode dropdown covers chat through the
proxy (with memory or single turn), the GuardRailBench sample apps (multi-agent workflow, single
agent with tools, RAG chatbot — bench mode only), and direct governance checks with no model
(compliance check, tool permission, handoff). Replies render Markdown safely (escaped first). Start a
new session, a new conversation in the same session, or load any existing session and continue it.
The **Sample cases** tab runs 25 one-click cases — allowed, redacted (including hash), blocked,
denied, and edge cases such as zero-width-character injection, forged role claims, an unknown pack,
the unredacted override and chain integrity — each in a fresh session that you can open and inspect.
"Run all checks" runs the 22 that need no model.

Sessions only show conversation text for checks made after message capture was added; the text is
always the redacted version the model received, never the raw input
([docs/adr/0015](docs/adr/0015-governance-console.md)). The old `user.html`/`admin.html` links
redirect into the console.

## Integrating a RAG application

The proxy doesn't care whether your prompt came from a user typing or from a retriever — treat retrieved document text as just more input and route the whole thing through `/v1/chat/completions` like any other completion call:

```python
import httpx

def ask(query: str, user_id: str) -> str:
    context = my_vector_store.retrieve(query)  # your existing retriever, unchanged
    prompt = f"Context:\n{context}\n\nQuestion: {query}"

    resp = httpx.post(
        "http://localhost:8000/v1/chat/completions",
        json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": prompt}]},
        headers={"x-user-id": user_id},
    )
    data = resp.json()
    if "error" in data:
        return f"[blocked] {data['error']}: {data.get('violations')}"
    return data["choices"][0]["message"]["content"]
```

That's the entire integration. Both the retrieved context and the model's answer pass through the same inbound/outbound HIPAA/DPDP checks as a plain chat message — if a retrieved patient record contains a phone number, it gets redacted from the outbound completion the same way a directly-typed one would. See `examples/rag_interface.py` for a runnable version, and [docs/INTEGRATION_CONTRACT.md](docs/INTEGRATION_CONTRACT.md) for the full attachment-point reference (chat/RAG, LangChain, LangGraph).

## Admin portal

There's no login and no role/permission system — see [docs/adr/0005](docs/adr/0005-user-identity-no-auth.md) for why, given the problem statement's explicit non-goal on auth/identity management. What exists instead is a **config-only** **Policy settings** page in the console (`index.html#/admin`; the old `dashboard/admin.html` redirects there):

- **Per-tool authority thresholds** — edit the score a tool requires (e.g. `sql_query_tool: 75`) and save; takes effect on the next `/governance/tool-check` immediately, no restart needed.
- **HIPAA / DPDP pack actions** — change what happens when an identifier is found (`redact` / `block` / `hash` / `log_only`) per identifier, per pack.
- **Per-`user_id` unredacted override** — every user is fully restrictive by default (redact always wins). Enter a `user_id`, check "allow unredacted", save. This alone does **not** unmask anything — the caller must *also* send `x-request-unredacted: true` on that specific request (see `proxy/main.py`). Both are required, matching the "redact by default, explicit ask to see it" rule from the kickoff meeting ([docs/adr/0003](docs/adr/0003-redact-by-default.md)). `block`/`hash` identifiers (SSN, Aadhaar, etc.) are never affected by this override.

- **Reset activity data** — deletes all audit records, trust state, token usage and user profiles for a fresh demo (type `RESET` to confirm); policy settings are kept. `POST /admin/reset` with `{"confirm": "RESET"}`.

All of this is backed by `governance_api/routes/admin.py` if you'd rather script changes than click through the page — e.g. `curl -X PUT localhost:8001/admin/users/demo_user -d '{"allow_unredacted": true}'`.

## Working on this repo

Two Claude Code skills live in `.claude/skills/` for this project:

- **`decision-logger`** — during any conversation about this codebase, if a design/architecture/scope decision is being made (a choice between alternatives, a scope cut, something hard to reverse), it asks whether that decision should be captured as an ADR (or elsewhere) before it's lost. The ADRs in `docs/adr/` came out of exactly this kind of moment.
- **`dev-next-steps`** — tell it your role (SWE / Data Engineer / Data Scientist) and it reads [docs/PROGRESS.md](docs/PROGRESS.md), hands you your current task with the context you need to start, and — once you confirm it's done and working — checks it off and hands you the next one, keeping `PROGRESS.md` (and this README, when something structural changes) up to date as you go.

## Where each objective in the plan lands

| Plan deliverable | Code |
|---|---|
| Reverse proxy, inbound/outbound compliance check | `proxy/main.py` |
| `@governed_tool` / `@governed_node` decorators | `governance_sdk/governance_sdk/decorators.py` |
| LangChain callback / LangGraph node wrapping | `governance_sdk/governance_sdk/integrations/` |
| Trust score, monotonic reduction, delegation capping | `governance_api/authority/` (session-scoped per [adr/0013](docs/adr/0013-session-scoped-trust-state.md)) |
| Redact / block / hash / log-only actions | `governance_api/compliance/actions.py` (tool-result scans redact without charging score, [adr/0014](docs/adr/0014-tool-result-scans-dont-charge-score.md)) |
| Hash-chained signed receipts | `governance_api/receipts/writer.py`, verified by `data_pipeline/ledger/verify_chain.py` |
| HIPAA / DPDP identifier detectors + overlap map | `detectors/hipaa/`, `detectors/dpdp/`, `data_pipeline/config/overlap_map.yaml` |
| Prompt-injection heuristics | `detectors/injection/heuristics.py` |
| Per-user token usage + composite rating | `data_pipeline/ingestion/`, `data_pipeline/aggregation/user_profile_job.py` |
| Dashboard (governance console: overview, sessions, users, ledger, live bench, evaluations, test console) | `dashboard/`, `governance_api/routes/dashboard.py`, `governance_api/insights/` |
| Admin config (thresholds, pack actions, per-user_id override, data reset) | `governance_api/routes/admin.py`, `governance_api/access_control/`, `dashboard/static/js/views/admin.js` |
| Latency benchmarking | `data_pipeline/benchmark/benchmark_latency.py` |
| Automated tests + CI | `governance_api/tests/`, `detectors/tests/`, `.github/workflows/tests.yml` |
| Memory chat (LangGraph checkpointer, still via proxy) | `examples/chat_memory.py` |
| GuardRailBench hook-contract bridge | `bench_bridge/main.py`, [docs/BENCH_BRIDGE.md](docs/BENCH_BRIDGE.md) |
