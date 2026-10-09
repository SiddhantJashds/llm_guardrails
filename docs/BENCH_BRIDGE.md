# Bench bridge: GuardRailBench-Sample ↔ this runtime

`bench_bridge/main.py` serves the GuardRailBench hook contract
(`GuardRailBench-Sample/docs/HOOK_CONTRACT.md`: 5× `POST /api/v1/*` on
`:8080`) backed by `governance_api` (`:8001`), so the bench tests this
runtime with zero changes on the bench side. Result against the sample
edition (scenarios 1, 4, 13): **3/3 PASS**
(`GuardRailBench-Sample/reports/bridge-run3.json`).

## Mapping

| Bench hook | Backing call | Bridge response |
|---|---|---|
| `on_prompt_received` | `compliance-check`, `direction=inbound`, pack `BRIDGE_PACK_ID` (default `hipaa`) | `{"prompt": cleaned}` (`""` on block) |
| `on_completion_received` | `compliance-check`, `direction=outbound` | `{"completion": cleaned}` |
| `on_tool_call` | out-of-scope (`tool_name` not in `agent_allowed_tools`) → deny immediately; else `tool-check` | `{"allow": bool}` |
| `on_tool_result` | `compliance-check`, `direction=outbound`, `apply_score=False` ([adr/0014](adr/0014-tool-result-scans-dont-charge-score.md)) | `{"result": cleaned}` |
| `on_session_end` | logged only (bench ignores the body) | `{}` |

Fail-closed throughout: governance unreachable → blank text + denied tools.
`BRIDGE_TIMEOUT` (default `1.5s`) stays inside the bench hooks' 2s budget.

## Threshold seeding

At startup the bridge seeds thresholds for the 9 bench tool names — but only
for tools with none configured (never clobbers values tuned via `admin.html`):

| Tier | Value | Tools |
|---|---|---|
| low | 50 | `search_patients`, `list_patients` |
| medium | 60 | `read_database`, `update_record`, `get_insurance_info`, `schedule_appointment` |
| high | 80 | `delete_file`, `send_email`, `submit_claim` |

Medium/high sit below the runtime's own 75/90 defaults deliberately: benign
multi-agent flows cost ~20 points to the delegation cap (user PII in the
request docks the orchestrator; children inherit it) plus low-confidence NER
noise, so higher lines brick legitimate reads and the reminder email itself
(observed: `send_email` denied at 90 for a clean sub-agent capped at 80).

## Running it

`WITH_BRIDGE=1` in `.env`, then `./run.sh` from the repo root: bridge on
`:8080`, proxy moves to `:8002` (the bench server needs `:8000`; bench apps call
the LLM directly), dashboard moves to `:8081`. The examples pick up `:8002`
automatically (`examples/example_config.py` reads `WITH_BRIDGE`); set `PROXY_URL`
to override. Flip back to `0` afterwards.

```bash
# llm_guardrails/
WITH_BRIDGE=1 ./run.sh   # via .env, no CLI flags needed
# GuardRailBench-Sample/ (.env: LLM_BASE_URL, EMBED_BASE_URL, model names)
uv run python run_all.py --report reports/bridge-run3.json
```

`run_all.py` reuses whatever is already on `:8080` (the bridge), builds
`chroma_db/` if missing, starts the bench on `:8000` (or reuses the one
`run.sh` already started there), runs `scripts/check_contract.py` (5/5 shape
checks), then the suite.

## In the dashboard

- **Live bench** (`#/live`): the bridge keeps every hook call in an in-memory
  feed (`GET /live/events?after=<seq>`, outcome plus the cleaned text only,
  never raw input; CORS allows the dashboard origins, read-only). The view
  polls it every 1.5s while `run_all.py` runs, groups events into runs by the
  per-run user suffix (`alice-ce70` -> run `ce70`), and links the report once
  it's written.
- **Evaluations** (`#/bench`): every report in `GuardRailBench-Sample/reports`
  (override with `BENCH_REPORTS_DIR` for `governance_api`), a scenario-by-run
  matrix, checks, and each scenario's full hook log on demand.
- **Token usage**: `on_completion_received` records the bench's
  `prompt_tokens`/`completion_tokens` per user/session/agent, so bench users
  have real token numbers.
- **Test console**: in bench mode `run.sh` also starts the GuardRailBench
  sample apps on `:8000` (when `../GuardRailBench-Sample` with its `.venv`
  exists), so the console can run the multi-agent, single-agent and RAG apps
  through `governance_api`'s `/playground/bench/*` forwarder.

## Startup-ordering gotcha (fixed)

The bridge seeds thresholds from the admin API at startup, but
`governance_api` loads the spaCy model first and isn't listening yet when
both boot together — the seed failed with connection-refused and never
retried. Fixed on both sides: `run.sh` waits for `:8001/healthz` before
starting anything else, and the bridge retries the seed (5×2s).
