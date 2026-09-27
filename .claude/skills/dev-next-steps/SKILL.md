---
name: dev-next-steps
description: Invoke this when a developer wants to know what to work on next in this repo (llm_guardrails) -- e.g. "/dev-next-steps", "what should I work on", "what's next for me", "I finished that, what now", or when they identify themselves as one of the hackathon team's four roles (SWE #1, SWE #2, Data Engineer, Data Scientist) and ask for direction. Reads and updates docs/PROGRESS.md to hand out exactly one task at a time, in order, and only advances to the next task once the developer confirms the current one is done and verified.
---

# Developer Next Steps

Four people are building this in two days from `docs/HACKATHON_PLAN.md`. The failure mode this skill guards against isn't "nobody knows the plan" -- the plan is written down -- it's "someone opens a 40-item plan, isn't sure where they left off, and either redoes something or skips a load-bearing step." This skill's job is to always know exactly one true "next thing" per person and hand out only that.

## Flow

### 1. Get oriented: which role

If the developer's role isn't already obvious from the conversation, ask via AskUserQuestion, offering exactly the four roles from `docs/HACKATHON_PLAN.md`:
- SWE #1 -- Gateway & Integration Engineer
- SWE #2 -- Authority Engine & Dashboard Engineer
- Data Engineer -- Ledger, Pipeline & Storage
- Data Scientist -- Compliance Detection & Scoring Logic

### 2. Find where they are

Read `docs/PROGRESS.md` and find that role's section. Items are marked:
- `[ ]` not started
- `[~]` scaffolded (a placeholder exists, but the real logic isn't done -- see `docs/MOCKED_VS_PRODUCTION.md` for what "real" means for that item)
- `[x]` done and verified

The first item that isn't `[x]` is the current task -- including a `[~]` item, since scaffolded-but-not-real still means real work is left. Day 1 items come before Day 2 items for that role; don't skip ahead even if a later item looks more interesting.

### 3. Hand out exactly that one task

Give them enough to start, not the whole remaining list:
- What the task is, in their role's terms -- pull this from `docs/PROGRESS.md`'s item text and the matching step in `docs/HACKATHON_PLAN.md`'s per-role section (the plan doc has more build context than the checklist line does).
- Which file(s) it lives in (`docs/PROGRESS.md`'s items already name these).
- Anything it depends on that isn't done yet -- e.g. if their task needs another role's still-unchecked item, say so plainly rather than letting them discover it mid-work.

Then stop and let them go work. Don't preview the next two or three tasks after this one -- that's what makes this "one small chunk at a time" instead of "here's your whole sprint printed out."

### 4. When they come back saying it's done

Before checking anything off, get a sense of whether it's actually verified, not just written. If they don't volunteer this, ask briefly how they checked it -- ran it, tested it, saw the expected output -- since the difference between "I wrote the code" and "I ran it and it does the thing" is exactly the `[~]` vs `[x]` distinction this file exists to track. Don't be heavy-handed about it; a quick "did you get a chance to run it?" is enough, and take their word for it once they answer.

`governance_api/tests/` (see [docs/adr/0007](../../docs/adr/0007-tests-and-ci-before-handoff.md)) already covers the core engine/receipt/access-control logic and runs in CI on every push -- have them run `pytest` from the repo root before marking anything `[x]` that touches `shared/`, `authority/`, `compliance/`, `access_control/`, or a route, since that's exactly the surface a silent cross-role break shows up on. If their task closes a gap that has a matching `xfail(strict=True)` test (e.g. wiring `detectors/hipaa/identifiers.py` into `compliance/engine.py`'s `_run_detectors` closes `test_compliance_check_actually_catches_phi_once_detectors_are_wired`), have them remove that test's `xfail` marker as part of the same change -- CI will fail loudly (XPASS) if they forget, which is the point. If their task adds new logic with no existing test, encourage (don't insist) adding one alongside it, in the style of the existing `governance_api/tests/` files -- terse, one behavior per test, named for what it verifies.

Then:
1. Check that item `[x]` in `docs/PROGRESS.md`.
2. Update the "Last updated" line at the top of `docs/PROGRESS.md`.
3. If this task closed a gap that `docs/MOCKED_VS_PRODUCTION.md` or the README's "Where each objective in the plan lands" table describes as mocked/placeholder, update that too -- a stale "this is still a placeholder" note is worse than no note, since it actively misleads the next person who reads it.
4. Go back to step 2 and hand out the next task.

### 5. Finishing a day

If every item in their role's "Day 1" section is `[x]`, say so explicitly and point them at "Day 2" rather than silently continuing -- finishing Day 1 is a real milestone worth naming, per the plan's own "MVP first" philosophy.

## Why one-at-a-time, not the full list

Handing someone their whole remaining checklist reads as thorough but actually just moves the "where am I really" problem back onto them. Tracking this in one shared file rather than everyone's own head or a private note (see `docs/adr/0006-shared-progress-file.md` for why that was a deliberate choice) means anyone -- including a future invocation of this skill, for the same person or someone else covering for them -- can answer "what's next for X" without re-deriving it from scratch.
