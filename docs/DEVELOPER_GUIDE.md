# Developer Guide

This is the one document meant to answer "what do I do" without asking the team lead. If you're new to this repo, read this top to bottom once — everything else (`README.md`, `docs/HACKATHON_PLAN.md`, the ADRs) is reference material you'll come back to, not a sequence to follow.

## 1. First 15 minutes

1. Clone the repo.
2. Get `UPSTREAM_LLM_API_KEY` (and anything else `.env.example` lists) from your team lead, out-of-band (Slack/1Password/whatever they use) — nothing in this repo can hand you that.
3. Set up your environment:
   ```bash
   python -m venv .venv && source .venv/bin/activate
   pip install -r requirements-dev.txt
   cp .env.example .env   # then fill in the values from step 2
   python scripts/init_db.py
   ```
4. Confirm the baseline is green **before** writing any code:
   ```bash
   pytest
   ```
   If this isn't green on a fresh clone, stop and fix your environment (see [Troubleshooting](#troubleshooting)) rather than building on top of a broken baseline — you won't be able to tell your changes apart from a pre-existing problem later.
5. Open Claude Code in this repo and say what your role is (SWE #1, SWE #2, Data Engineer, or Data Scientist) or just run `/dev-next-steps`. It reads `docs/PROGRESS.md` and hands you your first task with the context to start — you shouldn't need to read the entire `docs/HACKATHON_PLAN.md` cover-to-cover before writing your first line of code, just the section it points you to.

## 2. The loop you'll repeat all day

1. Ask `/dev-next-steps` (or just say "what's next") for your next task. It gives you exactly one task, not your whole remaining list on purpose — see [docs/adr/0006](adr/0006-shared-progress-file.md) if you're curious why.
2. Build it.
3. Run `pytest` from the repo root. If your task touched `shared/`, `authority/`, `compliance/`, `access_control/`, or a route, this is not optional — those are the files every other role's code also imports, and a silent break there is the exact "hiccup" this whole setup exists to prevent (see [docs/adr/0007](adr/0007-tests-and-ci-before-handoff.md)). Add a test alongside new logic if there isn't one already covering it — look at `governance_api/tests/` for the style (terse, one behavior per test, named for what it checks).
4. Commit and push in a small chunk (see [Git workflow](#4-git-workflow-for-4-people-with-nobody-centrally-reviewing) below) — don't sit on a big local diff all day.
5. Go back to `/dev-next-steps` and tell it the task's done. If you can say how you verified it (ran it, saw the expected output, tests pass), it'll check the item off in `docs/PROGRESS.md` and hand you the next one. If a task you finished closes a gap listed in `docs/MOCKED_VS_PRODUCTION.md` as mocked/placeholder, that file should get updated too — the skill will prompt for this, but flag it yourself if it doesn't.
6. If you notice yourself making a real decision along the way (picked one approach over another, cut scope, changed something hard to reverse) — the `decision-logger` skill should catch this and ask where to record it. If it doesn't fire and you think it should have, just say "log this as a decision" and it'll walk through the same flow.

## 3. Conventions worth knowing before you fight them

- **`sys.path.append(...)` at the top of most files under `governance_api/` and `proxy/`.** This looks unusual but is intentional: each service is meant to be run from inside its own directory (`cd governance_api && uvicorn main:app`), and these lines make `shared/` and sibling packages (`authority/`, `compliance/`, etc.) importable from that working directory without installing anything. Don't "clean this up" by removing them — it'll break the exact run commands this repo documents everywhere.
- **Identity fields never come from generated text.** `user_id`/`session_id`/`agent_id`/`parent_agent_id` are always set by trusted wrapper/proxy code, never parsed out of a prompt, completion, or tool argument. If you're adding a new place these fields get read, this rule still applies — see `docs/HACKATHON_PLAN.md`'s hardening section for why.
- **Fail-closed, always.** Any new integration point that talks to `governance_api` should treat an error/timeout as a deny, never a silent allow. Look at `GovernanceClient._post` or the proxy's `_fail_closed` for the pattern.
- **Compliance/authority decisions are deterministic code, never an LLM call.** See [docs/adr/0004](adr/0004-deterministic-compliance-no-self-attestation.md). If you're tempted to "just ask the model whether this is compliant" to save time on a detector, don't — that's the exact trust gap this whole project exists to close.
- **Example constants live in `examples/example_config.py`.** The proxy URL, model, and default user are defined once there (process env > repo `.env` > default, with the proxy port following `WITH_BRIDGE` like `run.sh`). A new example should import from it rather than hardcoding `localhost:8000`. It has tests in `examples/tests/`.
- **Don't set a relative `DATABASE_URL` in `.env`.** Leave it unset so every service shares the repo-root `governance.db`; `proxy/` and `governance_api/` run from their own directories, so a `./`-relative path gives each one a different file (see Troubleshooting).
- **Schema changes require a fresh DB, not a migration.** There's no Alembic here (deliberately, for hackathon scope). `Base.metadata.create_all()` (used everywhere) only creates tables that don't exist yet — it will **not** add a new column to an existing table or alter one. If you change anything in `shared/models.py`, say so when you push (a one-line note in your commit message is enough), and anyone who pulls it needs to delete their local `governance.db` and rerun `python scripts/init_db.py`. This is the single most likely "why is my API throwing a weird SQL error" moment — see Troubleshooting below.

## 4. Git workflow for 4 people with nobody centrally reviewing

There's no dedicated reviewer watching this repo during the build, so a few small habits do the job a reviewer normally would:

- Commit and push small, working chunks often, rather than one large diff at the end of the day. A broken half-finished commit is fine as long as `main` at HEAD passes `pytest` (CI will tell you if it doesn't).
- `git pull` before you start a session and before you push — four people on `main` means you will occasionally land behind someone else's push.
- If you're about to change something another role's code already calls (a function signature in `shared/`, `authority/policy_gates.py`'s `required_threshold`, etc.), grep for its call sites first (`grep -rn "required_threshold("`) so you know who else you're affecting, and consider a quick heads-up message rather than finding out from a broken CI run later.
- If CI goes red on `main`, that's the top-priority thing to fix — don't build on top of a known-broken baseline waiting for someone else to notice.

## 5. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `sqlite3.OperationalError: no such column` / table mismatch after pulling | Someone changed `shared/models.py`; your local `governance.db` predates it (see [Conventions](#3-conventions-worth-knowing-before-you-fight-them) above) | `rm governance.db && python scripts/init_db.py` |
| `ModuleNotFoundError: No module named 'shared'` (or `authority`, `compliance`, ...) | You ran `uvicorn` or a script from the wrong directory | `governance_api/` and `proxy/` are meant to be run with `cd <that dir> && uvicorn main:app --port ...` — see README's "Local setup" |
| Dashboard page loads but tables never populate, browser console shows a CORS error | You're on a version before `governance_api/main.py`'s `CORSMiddleware` was added, or `GOVERNANCE_API_BASE_URL` in `dashboard/static/js/api.js` points somewhere the browser can't reach | Pull latest; check the URL matches where `governance_api` is actually running |
| `pytest` fails immediately on collection with an import error | Usually a stale `.venv` missing a new dependency | `pip install -r requirements-dev.txt` again |
| Two services both seem to "work" alone but data from one doesn't show up in the other's dashboard | Each is pointed at a different SQLite file (this exact bug happened once already — see [docs/adr/0001](adr/0001-storage-sqlite-default.md)) | Confirm both have the same `DATABASE_URL` (or both are relying on the same repo-root-anchored default — don't override it per-service without a reason) |
| `NERUnavailableError` at `governance_api` startup, or `detectors/tests/test_ner.py` errors | The spaCy model `en_core_web_sm` isn't installed in your venv (it's a direct-URL requirement, easy to miss) | `pip install -r requirements-dev.txt` again (needs network for the ~13 MB model). To run regex-only in a pinch: `GUARDRAILS_NER_DISABLED=1` — NER tests will then fail, and names/places won't be detected |
| A test you didn't touch starts failing after you pull | Someone else's change broke something (that's what CI is for) — or, if it's `test_compliance_check_actually_catches_phi_once_detectors_are_wired`, that one is *supposed* to flip once detectors are wired in (see [docs/adr/0007](adr/0007-tests-and-ci-before-handoff.md)) | Check `git log` / recent commits on the affected file before assuming it's your fault |
| The proxy returns 500 with `no such table: token_usage_events` (or another table), and an empty `proxy/governance.db` appears | `DATABASE_URL` in `.env` is a relative SQLite path (`sqlite:///./governance.db`). The proxy loads `.env` itself and runs from `proxy/`, so it opens its own empty database; `governance_api` doesn't load `.env`, so it keeps using the root `governance.db`. Same class of bug as [docs/adr/0001](adr/0001-storage-sqlite-default.md) | Comment out `DATABASE_URL` in `.env` (unset = the shared repo-root default), delete the stray `proxy/governance.db`, restart `./run.sh`. Use an absolute path or Postgres if you really need to override it |
| An `examples/*.py` script dies with `httpx.ConnectError: [Errno 111] Connection refused` | Nothing is listening where the example looks. In bench mode (`WITH_BRIDGE=1`) the proxy is on `:8002`, not `:8000`; the examples follow `WITH_BRIDGE` via `examples/example_config.py`, but only if `.env` matches how `run.sh` was started | Make `WITH_BRIDGE` in `.env` match the running `./run.sh` (restart it after changing the flag), or set `PROXY_URL` in your shell or `.env` |

## 6. Where things live (quick reference)

For the full picture see the README's "Docs" table and "Layout" section — this is just the fast lookup:

- Your task list: `docs/PROGRESS.md` (read via `/dev-next-steps`, not by hand)
- Architecture + role split: `docs/HACKATHON_PLAN.md`
- Why a non-obvious decision was made: `docs/adr/`
- What's real vs. still a placeholder: `docs/MOCKED_VS_PRODUCTION.md`
- How another team's agent attaches to this runtime: `docs/INTEGRATION_CONTRACT.md`
