# 0013. Trust state is keyed per (agent, session), not per agent

Status: Accepted
Date: 2026-10-09

## Context

`AgentTrustState`'s own docstring said "for one agent within one session",
but its primary key was `agent_id` alone. So `AuthorityEngine.get_or_create`
returned the same row for an agent name in every session — and every user.
Consequences, all observed live (not hypothetical):

1. GuardRailBench scenario 1 drained `data_agent`'s score; scenario 13, in a
   fresh session, inherited that same row and denied a benign
   `search_patients` call (`score 40.0 below required 50.0`). Bench scenarios
   poisoned each other; likewise any two users sharing agent names would have
   shared (and mutually drained) scores.
2. The per-session dashboard view (`GET /dashboard/session/{id}`) could never
   find the state rows: they carried the `session_id` of whichever session
   created them first, so the session filter missed and every agent rendered
   with `current_score: null, history: []`.
3. The same-session delegation cap (`capped_initial_score`) read the parent's
   score from whatever session touched the parent name last — cross-session
   contamination in both directions.

## Decision

Composite primary key `(agent_id, session_id)` on `agent_trust_state`
(`shared/models.py`). `get_or_create` / `apply_signal` / `check_threshold`
all take `session_id` and address the row by the full key; the delegation cap
reads the parent's row in the *same* session. The handoff-check session
rollup already filtered by `session_id` and is unchanged. Schema change, so
an existing `governance.db` must be rebuilt (`rm governance.db &&
python scripts/init_db.py`, per the standing rule in
`docs/DEVELOPER_GUIDE.md`). Pinned with
`test_scores_are_isolated_between_sessions` in
`governance_api/tests/test_authority_engine.py`.

## Consequences

- Scores are now genuinely per-conversation: a degraded agent in one session
  cannot deny tools in another, and per-user isolation falls out for free
  (different users get different sessions).
- The session dashboard shows real scores/history again.
- Anything that cached an `agent_id`-only assumption (tests calling
  `apply_signal`/`check_threshold` positionally) had to gain the session
  argument — mechanical, but a reminder that the engine's method signatures
  are a shared contract across roles (see [0007](0007-tests-and-ci-before-handoff.md)).
