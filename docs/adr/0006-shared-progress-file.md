# 0006. Shared `docs/PROGRESS.md` over per-developer local progress files

Status: Accepted
Date: 2026-09-28

## Context

The `dev-next-steps` skill (`.claude/skills/dev-next-steps/`) needs somewhere to persist each developer's position through the plan's step-by-step checklist, across conversations and across whoever's asking. Two real options: one shared, git-committed checklist visible to the whole team, or four separate untracked local files (no merge conflicts between commits, but no shared visibility).

## Decision

One shared, git-committed `docs/PROGRESS.md`, one section per role, mirroring `docs/HACKATHON_PLAN.md`'s per-role Day 1/Day 2 steps.

## Consequences

Anyone — including a future invocation of `dev-next-steps` answering for a different person, or a teammate just checking status — can see where the whole team stands without asking around, and that state travels with the repo the same way code does. The tradeoff: four people occasionally editing different sections of the same file can produce a merge conflict. This is expected to be cheap to resolve, since each role owns a disjoint section of the file.
