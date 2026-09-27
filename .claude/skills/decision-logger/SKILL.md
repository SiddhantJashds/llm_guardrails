---
name: decision-logger
description: Use this whenever a design, architecture, scope, or process decision is being made or implied while working in this repo (llm_guardrails) -- not just when explicitly asked to log something. Trigger on phrasing like "should we use X or Y", "let's go with...", "let's skip Z for now", "we decided to...", "I like your recommendation", picking one option among several presented, cutting or expanding scope relative to docs/HACKATHON_PLAN.md or the problem statement's Non-Goals, or any choice that would be awkward to reverse later. Also trigger retroactively if you notice partway through a task that a decision was made a few messages back and never captured. When triggered, ask the user (via AskUserQuestion) whether and where to record it -- a new ADR in docs/adr/, an update to docs/HACKATHON_PLAN.md, a docs/PROGRESS.md status change, or skip -- then write it in the matching format.
---

# Decision Logger

Decisions made in conversation and never written down are the ones a team re-litigates a week later, or the ones a teammate contradicts by accident because they never saw them happen. This skill exists to catch that moment while it's still cheap to write down, not after the fact.

## When to fire

Don't wait for someone to say "let's write this down." Fire the moment you notice any of these happening in the conversation, whether the user is mid-sentence about something else or has just finished a tangent:

- A choice between two or more real alternatives gets made ("SQLite or Postgres?" -> "SQLite for now").
- Scope gets cut or expanded relative to what `docs/HACKATHON_PLAN.md` or the problem statement says ("let's skip full RBAC", "let's also add an admin page").
- A policy gets picked where more than one reasonable policy existed (redact-by-default vs. role-based visibility).
- Something hard to reverse gets committed to (a schema shape, a signing scheme, an integration mechanism).
- The user says "I like your recommendation" or otherwise accepts a proposal you made -- that's still a decision, even though you were the one who framed it.

Skip it for small, non-contentious choices (a variable name, which port a dev server runs on) -- this is for things a teammate would want the *why* behind, not every choice made all day.

## What to do when it fires

1. Name the decision back in one sentence, so the user can correct you if you've misread what was actually decided.
2. Ask (via AskUserQuestion) where it belongs:
   - **New ADR** (`docs/adr/`) -- architectural, non-obvious, or hard to reverse; see `docs/adr/README.md`'s "when is this worth an ADR" list.
   - **Update `docs/HACKATHON_PLAN.md`** -- it changes the build plan itself (a role's responsibilities, the architecture, the day-by-day steps).
   - **Update `docs/PROGRESS.md`** -- it only changes a checklist item's status or scope, not the plan's substance.
   - **Skip** -- always offer this option, so the question doesn't feel like manufactured overhead.
3. If it's a new ADR: read `docs/adr/README.md`'s index for the next number, copy the structure from `docs/adr/0000-template.md`, and write Status/Date/Context/Decision/Consequences in the terse style of the existing ADRs -- look at `docs/adr/0003-redact-by-default.md` for tone: it names who said what and when it's worth it, and links related ADRs with `[NNNN](NNNN-title.md)` instead of repeating their content. Add a row to the index table in `docs/adr/README.md`.
4. If it's the plan or progress doc: make the smallest edit that captures the decision accurately, in that file's existing style -- don't restructure the whole doc for one decision.
5. Tell the user what you wrote and where, in one or two sentences -- don't paste the whole file back into the conversation.

## Why this matters here specifically

This repo's own `docs/adr/` was seeded by exactly this pattern more than once: a clarifying question got asked, an option got proposed, the user said "I like your recommendation," and that exchange became an ADR (see `0005-user-identity-no-auth.md` and `0006-shared-progress-file.md`). That's the shape to watch for -- it's rarely someone announcing "I am now making an architectural decision." It's usually a small "yeah, let's do that" in the middle of something else.
