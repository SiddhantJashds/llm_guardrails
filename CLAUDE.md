# llm_guardrails

Compliance + Earned-Authority Governance Runtime for a 2-day hackathon (Oct 9–10). If this is your first time in this repo, read [docs/DEVELOPER_GUIDE.md](docs/DEVELOPER_GUIDE.md) before doing anything else — it's the single "what do I do" document. `docs/HACKATHON_PLAN.md` and `README.md` are reference material you'll come back to, not a starting sequence.

If a developer opens a session here without saying what they're working on, point them at `docs/DEVELOPER_GUIDE.md` first. If they already know their role (SWE #1, SWE #2, Data Engineer, Data Scientist — see `docs/HACKATHON_PLAN.md`), use the `dev-next-steps` skill to hand them their next task from `docs/PROGRESS.md` directly.

Two project skills exist for this repo and should be used proactively, not just when invoked by name:
- **`dev-next-steps`** — hands a developer their next task from `docs/PROGRESS.md`, one at a time.
- **`decision-logger`** — fires whenever a design/architecture/scope decision is being made in conversation, to ask whether it should be captured as an ADR (`docs/adr/`) or elsewhere before it's lost.

Run `pytest` from the repo root before treating any change to `shared/`, `authority/`, `compliance/`, `access_control/`, or a route as done — see `docs/adr/0007-tests-and-ci-before-handoff.md` for why. It also runs in CI on every push/PR.
