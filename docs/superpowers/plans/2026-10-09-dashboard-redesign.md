# Dashboard Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the blank, ID-only dashboard with an auto-loading console that browses every session, user, receipt and bench run, verifies the receipt chain, and embeds a governed chat drawer.

**Architecture:** Read-only aggregation endpoints in `governance_api/routes/dashboard.py`, backed by pure shaping helpers in a new `governance_api/insights/` package and by refactored, shared functions in `data_pipeline` (chain check, per-user profile). The frontend is one static ES-module shell (`dashboard/index.html`) with hash routes, a single poll loop, and Chart.js 4.4.1 vendored locally.

**Tech Stack:** FastAPI + SQLAlchemy (existing), pytest + TestClient (existing), vanilla JS ES modules, Chart.js 4.4.1 (vendored UMD), Node 26 built-ins + Google Chrome for the smoke script.

**Spec:** `docs/superpowers/specs/2026-10-09-dashboard-redesign-design.md`

## Global Constraints

- No build step, no framework, no CDN at runtime: Chart.js served from `dashboard/static/vendor/chart.umd.min.js` (4.4.1).
- Every server-supplied string reaches the DOM via `escapeHtml` or `textContent`. Never raw `innerHTML` interpolation.
- All API timestamps are UTC with an explicit offset: `datetime.isoformat()` on a tz-aware UTC value (`…+00:00`).
- Existing response fields of `/dashboard/session/{id}` and `/dashboard/user/{id}` keep their names and shapes.
- `log_only` is never counted as a violation (ADR 0009/0011).
- Proxy CORS: only dashboard origins (`DASHBOARD_ORIGINS`, default `http://localhost:8080,http://localhost:8081,http://127.0.0.1:8080,http://127.0.0.1:8081`), method `POST`, headers `content-type, x-user-id, x-session-id, x-agent-id, x-compliance-pack`. Never `x-request-unredacted`.
- `PROXY_PUBLIC_URL` default `http://localhost:8000`. `BENCH_REPORTS_DIR` default `<repo>/../GuardRailBench-Sample/reports`. Bench file names must match `^[A-Za-z0-9._-]+\.json$`.
- Poll interval 5 s, current view only, pausable.
- Commit messages carry no Claude co-author or "Generated with" line.
- Run `pytest` from the repo root before each commit that touches `governance_api/`, `shared/`, `proxy/`, `bench_bridge/` or `data_pipeline/` (ADR 0007).

## Review Focus

1. **Fresh clone, empty database.** Every endpoint returns well-formed empty JSON, and every view shows an empty state with zero console errors. → `test_every_list_endpoint_is_well_formed_on_empty_db` (Task 4) and a smoke run against an empty temp API (Task 12).
2. **Hostile identity strings** (`<img src=x onerror=window.__xss=1>` as user/session/agent id). Rendered as text on every view, never executed. → smoke `--seed-hostile` asserts `window.__xss === undefined` on all routes (Task 12).
3. **API unreachable mid-session.** A visible banner, polling keeps going, it recovers on its own, and polls never stack after route changes. → smoke `--expect-api-down` run plus the per-route `activePolls() <= 1` assertion (Task 8/12).
4. **Naive SQLite datetimes.** Serialized with `+00:00`, so the browser shows local time correctly. → `test_timestamps_carry_utc_offset` (Task 3).
5. **IDs with URL-special characters** (`#`, `?`, space, `%`). They round-trip through hash routes and API paths. → `test_user_and_session_ids_with_special_characters_round_trip` (Task 3). A `/` inside an ID is unsupported and documented, because Starlette path params can't carry it.

---

### Task 1: Pure shaping helpers (`governance_api/insights/shaping.py`)

**Files:**
- Create: `governance_api/insights/__init__.py` (empty), `governance_api/insights/shaping.py`
- Test: `governance_api/tests/test_dashboard_shaping.py`

**Interfaces:**
- Produces:
  - `iso_utc(dt: datetime | None) -> str | None`: naive is treated as UTC. Returns `dt.replace(tzinfo=timezone.utc).isoformat()`, or `dt.astimezone(timezone.utc).isoformat()` if already aware.
  - `parse_identifiers(reason: str | None) -> list[str]`: split on `,`, strip, drop empties. Order kept, duplicates kept.
  - `identifier_counts(reasons: Iterable[str | None]) -> list[dict]`: `[{"type": str, "count": int}]`, count descending, then type ascending.
  - `OUTCOMES = ("allow", "redact", "block", "deny", "log_only")`
  - `outcome(decision_type: str, verdict: str) -> str`: `hash` → `"redact"`. Compliance `allow`/`redact`/`block`/`log_only` pass through. Authority `deny` → `"deny"`. Anything else → `"allow"` if verdict is `allow`, otherwise the verdict.
  - `is_flag(o: str) -> bool`: True for `redact`, `block`, `deny`.
  - `trajectory(current_score: float | None, history: list[dict] | None) -> dict`: returns `{"initial_score", "points": [{"score", "signal", "delta"}], "approximate": bool}`.
  - `activity_buckets(rows: list[tuple[datetime, str]], max_buckets: int = 60) -> dict`: rows are `(timestamp, outcome)`. Returns `{"bucket_seconds": int, "buckets": [{"start": iso_utc, **{o: n for o in OUTCOMES}}]}`.
  - `receipt_item(r: Receipt) -> dict`: keys `receipt_id, timestamp, user_id, session_id, agent_id, parent_agent_id, decision_type, verdict, outcome, reason, identifiers, ref_id, hash, prev_hash`. `identifiers` is `identifier_counts([reason])` for compliance receipts and `[]` otherwise.

- [ ] **Step 1: Write failing tests**

```python
def test_iso_utc_marks_naive_datetimes_as_utc():
    assert iso_utc(datetime(2026, 10, 9, 10, 34, 10)) == "2026-10-09T10:34:10+00:00"
    assert iso_utc(None) is None

def test_identifier_counts_dedupes_and_sorts():
    assert identifier_counts(["full_name, full_name, phone_number", None, "phone_number, full_name"]) == [
        {"type": "full_name", "count": 3}, {"type": "phone_number", "count": 2}]

def test_outcome_maps_hash_to_redact_and_keeps_log_only():
    assert outcome("compliance", "hash") == "redact"
    assert outcome("compliance", "log_only") == "log_only"
    assert outcome("authority", "deny") == "deny"
    assert not is_flag("log_only") and is_flag("block")

def test_trajectory_recovers_capped_start():
    t = trajectory(75.0, [{"signal": "phi_in_output_low_confidence", "delta": -5.0}])
    assert t["initial_score"] == 80.0
    assert [p["score"] for p in t["points"]] == [80.0, 75.0]
    assert t["approximate"] is False

def test_trajectory_flags_zero_floor_as_approximate():
    t = trajectory(0.0, [{"signal": "x", "delta": -60.0}, {"signal": "x", "delta": -60.0}])
    assert t["initial_score"] == 100.0 and t["approximate"] is True

def test_activity_buckets_cap_count_and_sum_rows():
    base = datetime(2026, 10, 9, 10, 0, 0)
    rows = [(base + timedelta(minutes=m), "allow") for m in range(0, 180)] + [(base, "redact")]
    out = activity_buckets(rows, max_buckets=60)
    assert len(out["buckets"]) <= 60
    assert sum(b["allow"] for b in out["buckets"]) == 180
    assert sum(b["redact"] for b in out["buckets"]) == 1

def test_activity_buckets_empty():
    assert activity_buckets([]) == {"bucket_seconds": 60, "buckets": []}
```

- [ ] **Step 2: Run** `pytest governance_api/tests/test_dashboard_shaping.py -q`. Expected: ImportError (module missing).
- [ ] **Step 3: Implement `shaping.py`.** Trajectory algorithm: `total = sum(h["delta"] for h in history)`, `raw_start = current - total`, `initial = min(100.0, raw_start)`, `approximate = current_score == 0.0 and bool(history)` (once the 0 floor is hit, recorded deltas can overshoot). Points start at `{"score": initial, "signal": "start", "delta": 0}`, then a running sum per entry clamped at 0. `current_score is None` gives `{"initial_score": None, "points": [], "approximate": False}`. Buckets: span = last − first (min 60 s). `bucket_seconds` = smallest of `[60, 300, 900, 1800, 3600, 10800, 21600, 43200, 86400]` with `ceil(span/size)+1 <= max_buckets`, otherwise `ceil(span/max_buckets)`. Bucket starts align to `first` floored to `bucket_seconds`.
- [ ] **Step 4: Run** the same command. Expected: 7 passed.
- [ ] **Step 5: Commit** `feat(dashboard): pure shaping helpers for dashboard endpoints`.

### Task 2: Shared chain check and per-user profile (`data_pipeline`)

**Files:**
- Modify: `data_pipeline/ledger/verify_chain.py`, `data_pipeline/aggregation/user_profile_job.py`
- Test: `governance_api/tests/test_receipts.py` (append), `data_pipeline/tests/test_user_profile_job.py` (append)

**Interfaces:**
- Produces:
  - `check_chain(receipts: list[Receipt]) -> dict` in `verify_chain.py` (receipts already in timestamp order). Returns `{"ok": bool, "checked": int, "broken_receipt_id": str | None, "problem": None | "link" | "hash" | "signature"}`. Checks in that order per receipt: `prev_hash` linkage, then recomputed hash, then HMAC. `verify_session_chain(session_id) -> bool` becomes a wrapper (same prints, same return).
  - `profile_from_rows(tokens_in: int, tokens_out: int, receipts: list[Receipt]) -> dict` in `user_profile_job.py`. Returns `{"total_tokens_in", "total_tokens_out", "violation_count", "denied_count", "total_checks", "composite_rating", "effective_use_score"}` using the existing `_composite_rating` / `_effective_use_score` and the existing counting rules. `run_aggregation()` uses it, with behavior unchanged.

- [ ] **Step 1: Write failing tests**

```python
# test_receipts.py
def test_check_chain_names_the_failure_kind(db_session):
    from shared.models import Receipt
    from data_pipeline.ledger.verify_chain import check_chain
    _write(db_session); _write(db_session)
    rows = db_session.query(Receipt).order_by(Receipt.timestamp).all()
    assert check_chain(rows) == {"ok": True, "checked": 2, "broken_receipt_id": None, "problem": None}
    rows[1].prev_hash = "f" * 64
    assert check_chain(rows)["problem"] == "link"
    rows[1].prev_hash = rows[0].hash; rows[1].reason = "edited"
    assert check_chain(rows)["problem"] == "hash"
    rows[1].reason = None; rows[1].signature = "0" * 64
    out = check_chain(rows)
    assert out["problem"] == "signature" and out["broken_receipt_id"] == rows[1].receipt_id

# test_user_profile_job.py
def test_profile_from_rows_matches_run_aggregation(db_session):  # seed: 2 allow, 1 redact, 1 log_only, 1 authority deny, tokens 100/40
    ...  # assert profile_from_rows(...) equals the UserProfile row run_aggregation() writes, field for field, plus denied_count == 1, total_checks == 5
```

- [ ] **Step 2: Run** `pytest governance_api/tests/test_receipts.py data_pipeline/tests -q`. Expected: the new tests fail with ImportError.
- [ ] **Step 3: Implement** both functions and rewire `verify_session_chain` / `run_aggregation` onto them.
- [ ] **Step 4: Run** `pytest -q`. Expected: everything passes, including the existing receipt and job tests.
- [ ] **Step 5: Commit** `refactor: expose check_chain and profile_from_rows for the dashboard`.

### Task 3: Extended session and user detail endpoints

**Files:**
- Modify: `governance_api/routes/dashboard.py`
- Test: `governance_api/tests/test_dashboard_api.py` (new)

**Interfaces:**
- Consumes: Task 1 helpers, Task 2 `check_chain`, `profile_from_rows`.
- Produces (JSON contracts the frontend uses):
  - `GET /dashboard/session/{id}` returns `session_id, user_ids, first_seen, last_seen, decisions, redactions, blocks, denials, tokens_in, tokens_out, identifiers, chain, timeline: [receipt_item], agents`. Each agent has `agent_id, parent_agent_id, current_score, initial_score, trajectory, approximate, history, violations, denied_calls, decisions, tokens_in, tokens_out`. Agents come in delegation-tree DFS order: roots by first activity, children by first activity. `violations`/`denied_calls` keep their old item shape with `timestamp` now via `iso_utc`. `violations` now contains only compliance receipts whose `outcome` is a flag, so `log_only` drops out (it was counted before, contradicting ADR 0011). Add `test_log_only_is_not_listed_as_a_violation`.
  - `GET /dashboard/user/{id}` returns `user_id, profile` (the old 5 keys plus `denied_count`, `total_checks`, now from `profile_from_rows` instead of `UserProfile`), `recent_decisions` (old keys plus `outcome, session_id, agent_id, identifiers`), `sessions: [session_summary]`, `token_series: [{timestamp, tokens_in, tokens_out, session_id, agent_id}]`, `outcomes: {o: n for o in OUTCOMES}`.
  - Module-internal `session_summary(session_id, receipts, states, token_rows) -> dict`, also used by Task 4. Keys: `session_id, user_id, user_ids, agents, decisions, redactions, blocks, denials, flags, min_score, tokens_in, tokens_out, first_seen, last_seen, chain_ok`.

- [ ] **Step 1: Write failing tests** (seed through `/governance/*` and `AuthorityEngine` like `test_api_routes.py`):
  - `test_timestamps_carry_utc_offset`: every `timeline[].timestamp` and `first_seen` ends with `+00:00`.
  - `test_session_detail_orders_agents_by_delegation_and_recovers_capped_start`: parent gets one `phi_in_output` (100→80), the child is created with `parent_agent_id`, then gets one low-confidence signal. Assert the agent order is `[parent, child]` and the child has `initial_score == 80.0` and `trajectory[-1]["score"] == current_score`.
  - `test_session_detail_reports_chain_ok_then_tampered`: `chain["ok"] is True`. After editing one receipt's `reason` in the DB, `chain == {"ok": False, ..., "problem": "hash"}`.
  - `test_session_detail_counts_tokens_per_agent`: two `ingest_event` rows give per-agent and session `tokens_in/out` sums.
  - `test_user_profile_is_live_without_rollup`: with no `UserProfile` row, `profile["total_tokens_in"]` equals the ingested sum and `composite_rating` is a float.
  - `test_existing_session_and_user_fields_still_present`: the old keys exist with the old types.
  - `test_user_and_session_ids_with_special_characters_round_trip`: for `"a b#c?d%e"`, `client.get("/dashboard/user/" + quote(x, safe=""))` returns `user_id == x`, and the same holds for a session.
- [ ] **Step 2: Run** `pytest governance_api/tests/test_dashboard_api.py -q`. Expected: failures on the new keys.
- [ ] **Step 3: Implement.** Query `Receipt` (ordered by timestamp), `AgentTrustState` and `TokenUsageEvent` filtered server-side by the path ID (hardening #8). Shape them with the Task 1 helpers.
- [ ] **Step 4: Run** `pytest -q`. Expected: all pass, including the old `test_api_routes.py` dashboard tests.
- [ ] **Step 5: Commit** `feat(dashboard): session and user detail with trajectories, chain, tokens, UTC times`.

### Task 4: List endpoints (overview, feed, sessions, users, ledger)

**Files:**
- Modify: `governance_api/routes/dashboard.py`
- Test: `governance_api/tests/test_dashboard_api.py`

**Interfaces:**
- Produces:
  - `GET /dashboard/overview` returns `{generated_at, totals: {decisions, allows, redactions, blocks, denials, log_only, sessions, users, agents, tokens_in, tokens_out}, identifiers (top 12), activity (Task 1 shape), chain: {sessions_checked, sessions_ok, broken: [{session_id, receipt_id, problem}]}, recent_sessions (8 session_summary, newest last_seen first)}`.
  - `GET /dashboard/feed?limit=50` (max 200) returns `{items: [receipt_item]}`, newest first.
  - `GET /dashboard/sessions?q=&user_id=&flagged=false&limit=200` (max 1000) returns `{items: [session_summary], total}`, newest `last_seen` first. `q` is a case-insensitive substring match on session_id, any user_id, or any agent_id.
  - `GET /dashboard/users?q=&limit=200` returns `{items: [{user_id, sessions, decisions, redactions, blocks, denials, tokens_in, tokens_out, composite_rating, last_seen}], total}`, newest `last_seen` first.
  - `GET /dashboard/ledger?decision_type=&verdict=&user_id=&session_id=&agent_id=&q=&limit=100&offset=0` (limit max 500) returns `{items: [receipt_item], total, limit, offset}`, newest first. Filters are exact, except `q` is a substring match on `reason`. Done in SQL.
- [ ] **Step 1: Write failing tests**: `test_every_list_endpoint_is_well_formed_on_empty_db` (all five endpoints return 200 with zero totals and empty lists, and overview `chain.sessions_checked == 0`), `test_overview_totals_and_identifiers`, `test_feed_is_newest_first_and_capped`, `test_sessions_filters_by_q_user_and_flagged`, `test_users_list_has_live_rating`, `test_ledger_filters_and_paginates` (`total` stays the same across pages, pages don't overlap).
- [ ] **Step 2: Run.** Expected: 404 on the new routes.
- [ ] **Step 3: Implement.** Overview, sessions and users load all receipts, states and token rows once per request, then group in Python.
- [ ] **Step 4: Run** `pytest -q`. Expected: all pass.
- [ ] **Step 5: Commit** `feat(dashboard): overview, feed, sessions, users and ledger endpoints`.

### Task 5: Bench reports and config endpoints

**Files:**
- Create: `governance_api/insights/bench_reports.py`
- Modify: `governance_api/routes/dashboard.py`
- Test: `governance_api/tests/test_dashboard_api.py`

**Interfaces:**
- Produces:
  - `bench_reports_dir() -> Path`: reads `BENCH_REPORTS_DIR` at call time. Default `Path(__file__).resolve().parents[2].parent / "GuardRailBench-Sample" / "reports"`.
  - `list_runs(d: Path) -> list[dict]`: `{name, started_at, duration_s, edition, totals, scenarios_run, users, governance_url}`, newest `started_at` first. Unreadable or non-JSON files are skipped.
  - `load_run(d: Path, name: str) -> dict | None`: `None` for a bad name, a path outside `d`, or a missing file. Scenarios keep `number, name, user, role, status, reason, duration_s, session_ids, checks, requests` plus `hook_events = len(hook_log)`.
  - `GET /dashboard/bench/runs` returns `{available, dir, items}`. `GET /dashboard/bench/runs/{name}` returns 200 or 404. `GET /dashboard/config` returns `{proxy_url, bench_available, bench_dir}`.
- [ ] **Step 1: Write failing tests** (with `monkeypatch.setenv("BENCH_REPORTS_DIR", str(tmp_path))` and two report files built from the real report's key set): `test_bench_runs_lists_newest_first`, `test_bench_run_detail_counts_hook_events_instead_of_inlining`, `test_bench_run_rejects_traversal_and_bad_names` (`..%2Fsecret.json`, `x.txt`, `a b.json` all return 404), `test_bench_missing_dir_is_unavailable_not_error`, `test_config_reports_proxy_url_from_env`.
- [ ] **Step 2: Run.** Expected: failures.
- [ ] **Step 3: Implement.** Validate with `re.fullmatch(r"[A-Za-z0-9._-]+\.json", name)`, then check `(d / name).resolve().parent == d.resolve()`.
- [ ] **Step 4: Run** `pytest -q`. Expected: all pass.
- [ ] **Step 5: Commit** `feat(dashboard): bench report and config endpoints`.

### Task 6: Bench bridge records token usage

**Files:**
- Modify: `bench_bridge/main.py`, `bench_bridge/tests/conftest.py` (expose the module as `bridge_client.module`)
- Test: `bench_bridge/tests/test_bridge.py`

**Interfaces:**
- Consumes: `ingest_event(user_id, session_id, agent_id, tokens_in, tokens_out)` from `data_pipeline.ingestion.token_usage_pipeline`, imported at module level as `ingest_event`.
- [ ] **Step 1: Write failing tests**: `test_completion_hook_records_token_usage` (post with `prompt_tokens=12, completion_tokens=34` and get exactly one `TokenUsageEvent` with that identity and those counts), and `test_token_ingest_failure_never_changes_hook_response` (monkeypatch `bridge_client.module.ingest_event` to raise, and the response is still 200 with a `completion` key).
- [ ] **Step 2: Run** `pytest bench_bridge/tests -q`. Expected: the first test fails (0 rows).
- [ ] **Step 3: Implement.** In `on_completion_received`, after the compliance check, call `ingest_event` in `try/except Exception: log.warning(...)`.
- [ ] **Step 4: Run** `pytest -q`. Expected: all pass.
- [ ] **Step 5: Commit** `feat(bench_bridge): record bench token usage for the dashboard`.

### Task 7: Proxy CORS for the chat drawer, and `run.sh` proxy URL

**Files:**
- Modify: `proxy/main.py`, `run.sh`
- Test: `proxy/tests/test_cors.py` (new)

- [ ] **Step 1: Write failing tests**, all as preflights `OPTIONS /v1/chat/completions` with `Access-Control-Request-Method: POST`:
  - `test_dashboard_origin_preflight_allowed`: origin `http://localhost:8081` with headers `content-type,x-user-id,x-session-id,x-agent-id,x-compliance-pack` returns 200, and `access-control-allow-origin` echoes the origin.
  - `test_foreign_origin_preflight_refused`: origin `http://evil.test` gets no `access-control-allow-origin`.
  - `test_unredacted_header_not_allowed_from_browser`: dashboard origin with `x-request-unredacted` returns 400.
- [ ] **Step 2: Run** `pytest proxy/tests/test_cors.py -q`. Expected: failures.
- [ ] **Step 3: Implement.** `app.add_middleware(CORSMiddleware, allow_origins=<DASHBOARD_ORIGINS split on ",">, allow_methods=["POST"], allow_headers=[the five above])`, added after the debug middleware so CORS is outermost. In `run.sh`, start governance_api with `PROXY_PUBLIC_URL="http://localhost:$PROXY_PORT"`.
- [ ] **Step 4: Run** `pytest -q` and `sh -n run.sh`. Expected: all pass, and the syntax check is OK.
- [ ] **Step 5: Commit** `feat(proxy): allow dashboard-origin CORS for the chat drawer`.

### Task 8: Frontend shell, design system, Overview, smoke script

Load the `frontend-design` and `dataviz` skills before writing any of this.

**Files:**
- Create: `dashboard/static/vendor/chart.umd.min.js` (4.4.1, downloaded once and committed), `dashboard/static/js/{app,api,ui,charts}.js`, `dashboard/static/js/views/overview.js`, `scripts/dashboard_smoke.mjs`
- Modify: `dashboard/index.html` (shell), `dashboard/static/css/style.css` (rewrite; keep the token-on-`:root` plus dark-mode pattern)
- Modify: `dashboard/user.html`, `dashboard/admin.html` → redirect stubs to `index.html#/users` and `index.html#/admin`. Delete `static/js/session_dashboard.js` and `user_dashboard.js` once the matching views exist (Task 9/10). Keep `admin.js` until Task 11.

**Interfaces:**
- `api.js`: `apiBase` comes from the `?api=` query, else `window.GOVERNANCE_API_BASE_URL`, else `http://localhost:8001`. Exports `getJSON(path, params?) -> Promise<any>` (throws `ApiError{status, message}`), `putJSON(path, body)`, and `escapeHtml(v)`.
- View module contract (every `views/*.js`): `export async function mount(el, params, ctx) -> { refresh(): Promise<void>, destroy(): void }`. `ctx = { navigate(hash), getJSON, putJSON, charts, ui }`.
- `app.js`: route table `#/overview` (default), `#/sessions`, `#/session/:id`, `#/users`, `#/user/:id`, `#/ledger`, `#/bench`, `#/bench/:name`, `#/admin`. IDs are `decodeURIComponent`'d. It runs one `setTimeout` poll loop (5 s) that calls only the current view's `refresh`, has a pause/resume toggle, persists the theme toggle in `localStorage` (try/catch), and shows an error banner on `ApiError` that clears on the next success. It exposes `window.__dash = { activePolls() }` for the smoke script.
- `charts.js`: `lineChart(canvas, cfg)`, `stackedBarChart(canvas, cfg)`, `barChart(canvas, cfg)`. Each returns `{update(cfg)}` that mutates data in place (no destroy per poll) and reads colours from CSS tokens, re-reading them on theme change.
- `scripts/dashboard_smoke.mjs --dash URL [--api URL] [--routes a,b] [--out DIR] [--width N] [--dark] [--seed-hostile] [--expect-api-down]`. `--expect-api-down` inverts the API check: the run passes only if the error banner is visible and there are no uncaught exceptions, and failed requests to the API are expected. launches Chrome headless with a temp profile and the cache disabled. For each route it collects console errors, exceptions and failed requests, checks `window.__xss === undefined` and `__dash.activePolls() <= 1`, and saves a PNG. It exits 1 if anything fails. `--seed-hostile` first POSTs `/governance/compliance-check` with hostile `user_id`/`session_id`/`agent_id`.
- [ ] **Step 1:** Download the vendor file and check its content-type and that it defines `Chart`.
- [ ] **Step 2:** Build the shell, styles, `api/ui/charts/app.js` and the Overview view (KPI tiles, activity stacked bars, identifier bars, live feed, recent sessions, chain badge).
- [ ] **Step 3: Verify.** Run `node scripts/dashboard_smoke.mjs --dash http://localhost:8081 --routes overview` against the live stack, light and dark, then at `--width 390`. Expected: exit 0. Look at the screenshots.
- [ ] **Step 4: Commit** `feat(dashboard): new shell, design system, vendored Chart.js, overview`.

### Task 9: Sessions list and Session detail views

**Files:** Create `dashboard/static/js/views/{sessions,session}.js`. Delete `static/js/session_dashboard.js`.
- Sessions: search box (debounced 250 ms, `q`), user filter, "flagged only" toggle, table columns per spec, row click → `#/session/<id>`.
- Session detail: header (user links, time span, chain badge with problem kind, KPI row); agent cards in API order, indented by depth (score, start→current, signals, tokens); trust trajectory line chart (one series per agent, x = step index, y 0–100, threshold reference line at 60); timeline table (time, agent, type, outcome chip, identifier chips `type ×n`, ref_id); denied calls list.
- [ ] **Verify:** smoke `--routes sessions,session/dd5428b5-7c82-4370-91b4-6b86da0fabc6,session/sess_6acbbb5c` exits 0. In the screenshots, the `data_agent` trajectory starts at 80.
- [ ] **Commit** `feat(dashboard): sessions list and session detail`.

### Task 10: Users list and User detail views

**Files:** Create `dashboard/static/js/views/{users,user}.js`. Delete `static/js/user_dashboard.js`.
- Users: searchable table per spec, row → `#/user/<id>`.
- User detail: profile tiles (tokens in/out, composite rating, effective use, violations, denials), cumulative token line from `token_series`, outcome mix bars, sessions table, decision history with a "hide allows" toggle (on by default).
- [ ] **Verify:** smoke `--routes users,user/alice-72e0,user/demo_user` exits 0, and the tiles are non-zero for `demo_user`.
- [ ] **Commit** `feat(dashboard): users list and user detail`.

### Task 11: Ledger, Bench runs, Admin views

**Files:** Create `dashboard/static/js/views/{ledger,bench,admin}.js`. Delete `static/js/admin.js` (logic moves into `views/admin.js`, unchanged behavior and endpoints).
- Ledger: filter bar (type, verdict, user, session, agent, reason text), paged table (100/page, prev/next, total), short hashes with full value in `title`.
- Bench: runs list (time, edition, PASS/FAIL/SKIP chips, duration) → run detail (scenario cards: status, reason, checks, request/response text in collapsible blocks, session links → `#/session/<id>`, per-user summary). Shows a "reports folder not found: <dir>" state when `available` is false.
- Admin: thresholds, both packs, overrides. Same PUTs as today.
- [ ] **Verify:** smoke `--routes ledger,bench,admin` plus one `bench/<newest>` route exits 0.
- [ ] **Commit** `feat(dashboard): ledger, bench runs and admin views`.

### Task 12: Chat drawer, docs, ADR, end-to-end verification

**Files:** Create `dashboard/static/js/chat.js`, `docs/adr/0015-dashboard-console-choices.md`. Modify `docs/adr/README.md` (index row), `README.md` (dashboard section), `docs/DEVELOPER_GUIDE.md` (blank-dashboard troubleshooting row, where the dashboard lives), `docs/MOCKED_VS_PRODUCTION.md` (live profile, smoke script, proxy CORS, bridge's local out-of-scope denies write no receipt), `docs/PROGRESS.md` (SWE #2 item 9 → done), `docs/BENCH_BRIDGE.md` (token recording, Bench view).

**Interfaces:**
- `chat.js` exports `initChat(ctx)`. It adds the corner button and drawer. On first open it fetches `proxy_url` via `GET /dashboard/config`. State: `{userId (default "dashboard_user"), mode: "memory" | "brief", pack: "hipaa" | "dpdp", sessionId: "sess_dash_" + 12 hex, messages[]}`. Each send POSTs `{model: "nvidia/Qwen3.6-35B-A3B-NVFP4", messages}` (full history in memory mode, last user message only in brief mode) with headers `x-user-id`, `x-session-id`, `x-agent-id: dashboard_chat`, `x-compliance-pack`. A 403 `blocked_by_compliance` renders the violations inline. A network error renders "proxy unreachable at <url>". There's a "New conversation" button and an "Open session" link → `#/session/<sessionId>`.
- ADR 0015 records: vendored chart library, live per-user profile computation, and the proxy CORS allowlist for the drawer (Context / Decision / Consequences, terse, like 0013/0014).
- [ ] **Step 1:** Build the chat drawer. Verify on the live stack by sending one memory-mode and one brief-mode message through headless Chrome: replies render, and the session view lists the `dashboard_chat` agent.
- [ ] **Step 2: Review Focus runs.**
  - Temp API: `cd governance_api && DATABASE_URL=sqlite:///<scratch>/smoke.db GUARDRAILS_NER_DISABLED=1 uvicorn main:app --port 8011`.
  - Run smoke `--api http://localhost:8011` on all routes while the database is still empty. Expected: exit 0 and empty states in the screenshots.
  - Run smoke `--api http://localhost:8011 --seed-hostile` on all routes. Expected: exit 0, no `__xss`.
  - Run smoke `--api http://127.0.0.1:9 --expect-api-down --routes overview,sessions`. Expected: exit 0, meaning the banner is shown and nothing throws.
- [ ] **Step 3: End to end.**
  - Run GuardRailBench `run_all.py` against the live bridge. Expected: 3/3 PASS.
  - Then smoke the newest `bench/<run>` and its session links. Expected: bench users show non-zero tokens.
- [ ] **Step 4:** Write the docs and the ADR. Run `pytest -q` and expect everything to pass.
- [ ] **Step 5: Commit** `feat(dashboard): chat drawer` and `docs: dashboard console ADR 0015 and docs`.
