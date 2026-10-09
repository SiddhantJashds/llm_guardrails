# 0015. Governance console: vendored assets, live profiles, redacted conversation capture

Status: Accepted
Date: 2026-10-09

## Context

The dashboard was blank in every browser: it loaded Chart.js 4.4.4 from
cdnjs, which never published that version, so the script was blocked and the
first chart call threw before anything rendered. Behind that: every view
needed a session or user id typed in by hand, timestamps rendered 5h30m off
(naive UTC), per-user tiles read 0 because the profile rollup job never ran,
and there was no way to see what was actually said in a session. The user
asked for one console usable by judges, for debugging and for analysis,
including GuardRailBench runs and a way to exercise every feature. Design and
plan: `docs/superpowers/specs/2026-10-09-dashboard-redesign-design.md`,
`docs/superpowers/plans/2026-10-09-dashboard-redesign.md`.

## Decision

1. **No runtime CDN.** Chart.js 4.5.1, Material Icons, Inter and JetBrains
   Mono are vendored in `dashboard/static/vendor/` with their licenses. The
   console is static ES modules, no build step.
2. **Per-user numbers are computed live** from receipts and token events with
   `user_profile_job.profile_from_rows()` (ADR 0011 formulas), not read from
   the `UserProfile` table, so they're never stale and never disagree with
   the job.
3. **Conversation capture stores redacted text only.** Each compliance
   receipt's `payload` holds the text *after* governance cleaned it — what
   the model actually received — plus direction. Raw input is never stored,
   including under an unredacted override (a separately redacted copy is
   stored instead). `payload` stays outside the hashed decision, so every
   existing chain keeps verifying.
4. **Browser access is allow-listed.** The proxy accepts CORS only from the
   dashboard origins, only `POST`, only the identity/pack headers — never
   `x-request-unredacted`. The bench bridge's live feed is `GET`-only to the
   same origins. The GuardRailBench apps (another repo, no CORS) are reached
   through `governance_api`'s `/playground/bench/*` forwarder.
5. **Data reset** (`POST /admin/reset`, body `{"confirm": "RESET"}`) deletes
   activity data and keeps policy settings.

## Consequences

- The console works offline and looks the same on every machine; vendored
  files (~0.6 MB) must be updated by hand.
- Conversation text is a new store of content: anything the detectors miss is
  kept as forwarded (e.g. the hyphenated MRN gap fixed alongside this). It is
  display data, not covered by the chain's tamper evidence.
- Reset and the playground forwarder inherit `/admin`'s no-auth stance
  (ADR 0005); in a real deployment both sit behind platform auth.
- Bench out-of-scope denials are decided inside the bridge without a receipt,
  so they appear in Live bench but not in the ledger
  (docs/MOCKED_VS_PRODUCTION.md).
