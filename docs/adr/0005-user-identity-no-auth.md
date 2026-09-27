# 0005. No auth/RBAC/user creation; per-user_id override table instead

Status: Accepted
Date: 2026-09-28

## Context

The problem statement lists "User authentication/identity management — user_id passed in with each request" as an explicit non-goal. Separately, there was a request to add an admin portal that could "define access for a particular role and create user profiles" — full RBAC and user management, which would directly contradict that non-goal and add meaningful scope to a 2-day build.

## Decision

No login, no roles, no user creation. `user_id` remains exactly what the non-goal describes: a caller-supplied string, trusted the same way `shared/identity.py`'s `IdentityEnvelope` already trusts it. The only new surface is `shared/models.py`'s `UserAccessOverride` — a single per-`user_id` row (`allow_unredacted: bool`, optional `tool_overrides`) that an admin can set via `governance_api/routes/admin.py` / `dashboard/admin.html`. Default (no row) is fully restrictive. This is data an admin annotates against an identifier the caller already provides, not an identity or permission system — see [0003](0003-redact-by-default.md) for how the flag actually gets used.

## Consequences

The "admin portal" ask is satisfied for the one thing that was concretely needed (letting an admin loosen redaction for a specific user_id) without building login, sessions, or a user table with real identity semantics. If a future requirement needs actual role-based tool-call authority (not just a redaction override), that's new scope requiring its own ADR — this decision does not extend to it.
