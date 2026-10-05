# 0011. Composite trust rating / effective-use score: real formulas

Status: Accepted
Date: 2026-10-05

## Context

`data_pipeline/aggregation/user_profile_job.py` shipped with placeholder formulas, explicitly marked `TODO (Data Scientist)`:

```python
composite_rating = max(0, 100 - violation_count * 5 - denied_count * 3)
effective_use_score = total_tokens / violation_count  # (or raw tokens if 0 violations)
```

Both have a real problem, not just a "needs tuning" one. `composite_rating` was a raw count, not a rate: a user with one violation out of two total calls and a user with one violation out of ten thousand calls scored identically. `effective_use_score` inverted its own meaning depending on whether `violation_count` was zero — a clean user's score was just their raw token total (unbounded, and purely a function of how much they'd used the system, not how well), while a user with any violations got a completely different, rate-shaped number. Neither was comparable across users.

`docs/HACKATHON_PLAN.md`'s own wording for this item: "simple weighted combinations of violation frequency, denied-call rate, and token usage per completed task (transparent proxies, explicitly not ML per non-goals)." That's the brief this ADR implements literally.

Alternatives considered: tune the existing placeholders' constants instead of changing their shape (rejected — a raw-count formula can't be fixed by retuning weights; the scale problem is structural); any ML-based scoring (ruled out by the plan's own non-goals).

## Decision

**`composite_rating`** (0–100, trust-facing): `100 * (1 - (0.7 * violation_rate + 0.3 * denial_rate))`, clamped to `[0, 100]`, where both rates are out of the user's `total_checks` (every compliance + authority receipt they have, any verdict). Zero recorded activity returns the neutral default, `100.0`, not a division by zero.

Violations are weighted above denials (0.7 vs 0.3): a violation is an actual PHI/PII hit that needed redacting/blocking — the thing this whole system exists to catch. A denial is an out-of-scope tool call governance *already correctly stopped* — the system working as intended, still worth tracking, but a lighter signal than a leak attempt.

**`effective_use_score`** (an efficiency/volume proxy, not a 0–100 "goodness" score): `total_tokens / completed_tasks`, where `completed_tasks` = the user's receipts that were neither a violation nor a denial. Zero completed tasks returns `0.0`, not the raw token count — a user whose only recorded activity was violations/denials shouldn't show a misleadingly large "effective" number just because tokens were spent getting there.

**Correctness fix bundled in:** `violation_count`'s query previously counted any `Receipt.verdict != "allow"`, which included `log_only` verdicts. A `log_only`-by-design hit (e.g. DPDP's `consent_purpose_flag`, [0009](0009-no-signal-identifiers-for-metadata-markers.md)) already costs the agent's authority score nothing — it shouldn't cost the user's `composite_rating` anything either, for the same reason. The query now excludes `log_only` from the violation count, and `log_only` receipts count toward `completed_tasks` instead.

**Testing note:** adding `data_pipeline/tests/` (new) to `pytest.ini`'s `testpaths` surfaced that `shared.db`'s module-level engine is a process-global singleton bound at first import — two conftests setting `DATABASE_URL` in the same combined `pytest` run only matters for *which* throwaway file wins, not correctness, since every test resets its own schema (`reset_db` autouse fixture, same pattern both directories now share). Both conftests now use `os.environ.setdefault(...)` instead of a plain assignment, so neither can clobber whichever one happens to import first.

## Consequences

- Both scores are now genuinely comparable across users with different activity volumes — the problem the placeholders had.
- `effective_use_score` isn't a "the user is good" signal despite living next to `composite_rating` on the same row — it's a usage/efficiency number. The dashboard (SWE#2 Day2 #9) should present it as such, not alongside `composite_rating` as if they're the same kind of thing.
- `data_pipeline/tests/` is new — it wasn't covered by `pytest` from the repo root before this (confirmed: `pytest.ini`'s `testpaths` didn't include it). Any future `data_pipeline/` logic should be tested there, now that CI actually runs it.
