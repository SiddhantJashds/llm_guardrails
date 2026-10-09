# Dashboard redesign: auto-loading, full-history governance console

Date: 2026-10-09 · Status: approved in conversation, pending spec review

## Why

The dashboard was blank in every browser: `Chart.js/4.4.4` doesn't exist on
cdnjs, the 404 HTML page is blocked as a script, `new Chart()` throws, and
`refreshData()` swallows the error *before* the tables render (fixed on
2026-10-09 by pinning 4.4.1; this redesign vendors the library). Behind
that sat a usability gap: every view needs a `session_id` / `user_id` typed
in by hand, and nothing lists them. Bench sessions are random UUIDs.

Findings this design also fixes:

- Timestamps are stored as UTC but SQLite drops the tzinfo, so the API
  emits naive ISO strings and the browser renders them 5h30m off (IST).
- The trust trend chart replays deltas from 100, but delegation capping
  sets a child's starting score without a history entry. `data_agent` was
  drawn at 95 while its real score was 75 (started at 80, capped by
  `orchestrator`).
- `user_profiles` is empty because nothing schedules
  `data_pipeline/aggregation/user_profile_job.py`, so every per-user tile
  reads 0.
- The bench bridge receives `prompt_tokens`/`completion_tokens` on
  `on_completion_received` and drops them. Bench users never get token
  usage.
- No endpoint verifies the receipt hash chain, though tamper evidence is
  a judging criterion.

## Who it's for

Everyone: judges on Day 2 (projector, no ID hunting, story at a glance),
the team (debugging), and analysis (history, bench runs). One console, no
mode switch.

## Success criteria

1. Opening `http://localhost:<dash>/` shows live data immediately. No input
   needed.
2. Every session and user that ever existed is browsable, searchable, and
   one click from its detail view (chat and bench alike).
3. Session detail shows agents (with delegation tree), correct trust
   trajectories, every decision in order, what was redacted/denied and why,
   tokens, and whether the receipt chain verifies.
4. Each GuardRailBench run is viewable with its scenarios, checks, and links
   to the sessions it produced.
5. A chat drawer (memory or brief mode) lets you talk to the governed model
   from the dashboard and watch its decisions appear.
6. Works offline (no CDN), light and dark, down to phone width; errors are
   visible, never silent.

## Approach

Plain static HTML/CSS/JS (ES modules, no build step, no framework), Chart.js
4.4.1 vendored at `dashboard/static/vendor/`. Served exactly as today
(`python -m http.server` from `run.sh`). A single shell page with hash
routes (`#/overview`, `#/sessions`, `#/session/<id>`, `#/users`,
`#/user/<id>`, `#/ledger`, `#/bench`, `#/bench/<run>`, `#/admin`), so views
deep-link and survive refresh. All aggregation happens server-side in
read-only `governance_api` endpoints. Rejected: hand-drawn SVG charts (more
code, same result) and React/Vite (adds a build toolchain on Day 2).

## Pages

Global shell: top bar (title, nav, live badge with pause/resume, theme
toggle), error banner when the API is unreachable, polling every 5 s for the
current view only. All server text goes through `escapeHtml` (stored-XSS
rule, `docs/HACKATHON_PLAN.md` hardening #3).

- **Overview** (default): KPI tiles (decisions, redactions, blocks,
  denials, sessions, users, tokens in/out, chain status); activity over
  time stacked by outcome; top detected identifier types; live decision
  feed; recent sessions. Everything clicks through.
- **Sessions:** table of all sessions with search (id/user/agent) and
  filters (has violations, has denials, user). Columns: session, user,
  agents, decisions, redactions, denials, lowest trust score, tokens, last
  activity, chain status.
- **Session detail:** header (user, time span, chain verified ✓/✗ with first
  broken receipt); agent cards in delegation-tree order (score, starting
  score, signals, tokens); trust trajectory chart; full decision timeline
  with verdict chips and identifier chips deduplicated as `full_name ×17`;
  denied tool calls.
- **Users:** table of all users (sessions, decisions, redactions, denials,
  tokens, composite rating, last seen), searchable.
- **User detail:** live profile tiles (tokens, composite rating, effective
  use score, violations, denials); token usage over time; outcome mix; their
  sessions; decision history with a "hide allows" toggle.
- **Ledger:** the raw audit log as a clean paged table: every receipt with
  filters (type, verdict, user, session, agent, text) and the hash/prev-hash
  shown short, so nobody needs to read the database.
- **Bench runs:** list of GuardRailBench reports (time, edition, PASS/FAIL/SKIP
  totals). Run detail: scenarios with status, reason, checks, request/response
  text, per-user summary, and links to each scenario's session.
- **Admin:** today's admin features (tool thresholds, pack actions, per-user
  overrides) restyled inside the shell. `user.html`/`admin.html` become
  redirect stubs so old links keep working.
- **Chat drawer** (small "Chat" button, bottom corner, on every page):
  user_id field, mode toggle **Memory** (sends full history, like
  `examples/chat_memory.py`) / **Brief** (sends only the latest message, like
  `examples/chat_interface.py`), compliance pack (hipaa/dpdp), "new
  conversation". Each conversation gets one `session_id`
  (`sess_dash_<hex>`) and a stable `x-agent-id: dashboard_chat`, plus a
  link to its session view. Blocked replies show the violation list inline.

## Backend: `governance_api/routes/dashboard.py` (read-only)

All timestamps are serialized as UTC with an explicit offset
(`2026-10-09T10:34:10.018417+00:00`). Existing response fields of
`/dashboard/session/{id}` and `/dashboard/user/{id}` stay intact; new fields
are added alongside them.

| Endpoint | Returns |
|---|---|
| `GET /dashboard/config` | `proxy_url` (from `PROXY_PUBLIC_URL`, default `http://localhost:8000`), whether the bench reports dir exists |
| `GET /dashboard/overview` | totals, outcome counts per decision type, identifier type counts, activity buckets (≤60 buckets sized to the data span), chain summary (sessions checked/ok, broken list) |
| `GET /dashboard/feed?limit=` | newest receipts first (default 50, max 200) |
| `GET /dashboard/sessions?q=&user_id=&limit=` | session summaries (fields as the Sessions table) |
| `GET /dashboard/session/{id}` | existing fields + per agent `parent_agent_id`, `initial_score`, `trajectory`, tokens, counts; session `user_ids`, `first_seen`, `last_seen`, `timeline`, `tokens`, `chain` |
| `GET /dashboard/users?q=&limit=` | user summaries |
| `GET /dashboard/user/{id}` | existing fields with `profile` computed live + `sessions`, `token_series`, `outcomes` |
| `GET /dashboard/ledger?...&limit=&offset=` | filtered receipts + `total` |
| `GET /dashboard/bench/runs` | report summaries from `BENCH_REPORTS_DIR` (default `<repo>/../GuardRailBench-Sample/reports`) |
| `GET /dashboard/bench/runs/{name}` | one report (scenarios, checks, requests, per-user summary; hook-log entries counted, not inlined) |

Rules:

- **Outcome classes:** `allow`; interventions are `redact`, `hash`,
  `block` (compliance/handoff) and `deny` (authority). `log_only` counts as
  allowed-with-note, not a violation (ADR 0009/0011).
- **Identifier types** are parsed from compliance `reason` strings
  (`"phone_number, full_name"`), only for non-allow compliance receipts.
- **Trust trajectory:** `initial_score = min(100, current_score - Σdeltas)`,
  then one point per history entry. Exact unless the score hit the 0 floor,
  which is flagged as approximate. No schema change.
- **Live profile:** the composite rating, effective-use score, and counts
  come from the same functions `user_profile_job.py` uses (refactored into a
  per-user `compute_profile` that `run_aggregation` also calls), so the
  dashboard and the job can't disagree. The job and `user_profiles` table
  stay as they are.
- **Chain verification:** per session, walk receipts in timestamp order;
  check `prev_hash` linkage from genesis, recompute the hash from the stored
  decision fields, check the HMAC. Report the first failure and its kind
  (`link`, `hash`, `signature`). Uses `governance_api/receipts/writer.py`'s
  own helpers. A secret mismatch (API restarted with a different
  `RECEIPT_SIGNING_SECRET`) shows up as signature failures, which is correct.
- **Bench files:** only names matching `^[A-Za-z0-9._-]+\.json$` that
  resolve inside the directory; anything else is 404. Missing directory →
  empty list with `available: false`.
- **Per-user isolation:** `/dashboard/user/{id}` keeps filtering by
  `user_id` in the query (hardening #8). The cross-user list views are the
  same admin-level visibility the admin page already has (ADR 0005: no auth).

## Other changes

- **Bench bridge** (`bench_bridge/main.py`): on `on_completion_received`,
  record a token-usage event via `ingest_event`. Wrapped so a DB failure is
  logged and never changes the hook response (fail-closed behavior is about
  verdicts, not accounting).
- **Proxy** (`proxy/main.py`): `CORSMiddleware` allowing only the dashboard
  origins (`localhost`/`127.0.0.1` on `:8080` and `:8081`, overridable via
  `DASHBOARD_ORIGINS`), methods `POST`, headers `content-type`,
  `x-user-id`, `x-session-id`, `x-agent-id`, `x-compliance-pack`.
  `x-request-unredacted` is deliberately not allowed from the browser.
- **`run.sh`**: start `governance_api` with
  `PROXY_PUBLIC_URL=http://localhost:$PROXY_PORT` so the chat drawer finds
  the proxy in both modes.

## Testing

- `governance_api/tests/test_dashboard_*.py`: every endpoint; UTC offset on
  timestamps; trajectory start for a capped child; identifier parsing and
  dedup; chain verification ok / tampered hash / broken link / bad
  signature; ledger filters and paging; bench listing, detail, path
  traversal and bad-name rejection, missing dir; live profile matches
  `run_aggregation`'s numbers; existing fields still present.
- `bench_bridge/tests`: token event recorded on completion; ingestion
  failure doesn't change the response.
- `proxy/tests`: CORS preflight allowed for a dashboard origin, refused for
  another origin, and `x-request-unredacted` not in allowed headers.
- `data_pipeline/tests`: existing job tests still pass after the refactor.
- Frontend: `scripts/dashboard_smoke.mjs` (headless Chrome over CDP, no
  installs) loads every route against live data, fails on console errors or
  failed requests, and saves screenshots. Run manually (CI has no Chrome);
  checked in light, dark and 390px width before handoff.

## Out of scope

SSE/websockets (polling is enough), auth (ADR 0005), editing data from the
dashboard (admin page aside), adding timestamps to trust history (schema
change), cross-session reputation (ADR 0013).

## Docs to update

README dashboard section, `DEVELOPER_GUIDE.md` (blank-dashboard
troubleshooting row, where dashboard pieces live), `MOCKED_VS_PRODUCTION.md`
(live profile, smoke script, proxy CORS), `PROGRESS.md` (SWE #2 item 9),
`BENCH_BRIDGE.md` (token recording, Bench runs view).

## Ownership

`dashboard/` and `routes/dashboard.py` are SWE #2's (Harsh) area per
`docs/HACKATHON_PLAN.md`; give him a heads-up before this lands on `main`.
