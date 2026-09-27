# 0001. SQLite as the default datastore, Postgres via `DATABASE_URL`

Status: Accepted
Date: 2026-09-27

## Context

The runtime needs a datastore for receipts, agent trust state, user profiles, token usage, and compliance pack config from day one of the hackathon. Standing up Postgres (or any external DB) before anyone can write a line of business logic costs setup time neither team member wants to spend on day 1, per the "start MVP first" guidance from the kickoff meeting.

## Decision

`shared/db.py` defaults to a local SQLite file (anchored to the repo root, not the process's cwd — see the bug this caused and fixed on 2026-09-28), via a single SQLAlchemy engine used identically by both `proxy/` and `governance_api/`. `DATABASE_URL` swaps to Postgres with no code change; `docker-compose.yml` wires a Postgres service and Dockerfiles for exactly that.

## Consequences

Zero external setup to start coding — clone, `pip install`, `python scripts/init_db.py`, go. SQLite serializes writes (one writer at a time), which is a real limit under concurrent multi-agent load but not a hackathon-day problem. SQLite is file-based: if the demo ever runs proxy/governance_api on different machines without a shared filesystem, they must point `DATABASE_URL` at a real Postgres instance instead, or they'll silently operate on different databases (this is exactly what the cwd-relative-path bug did on 2026-09-28, before the path was anchored to the repo root).
