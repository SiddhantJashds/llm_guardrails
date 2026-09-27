# 0003. Redact-by-default, even for higher-authority callers

Status: Accepted
Date: 2026-09-27

## Context

The kickoff meeting debated whether a supervisor/manager role should see PHI/PII in original, unredacted form by default, with standard users getting redacted output. Amey argued even supervisors should default to redacted, requiring an explicit flag to see unredacted data; Sachin agreed this is safer ("we can just say two modes... even for supervisors should be by default redacted, unless explicitly asked").

## Decision

`governance_api/compliance/engine.py`'s `check()` always redacts a `redact`-action identifier unless `allow_unredacted=True` is passed in — and that flag is only ever `True` when *both* an admin has granted the specific `user_id` an override (`shared/models.py`'s `UserAccessOverride`) *and* the caller explicitly asks for unredacted output on that specific request (`request_unredacted` in `shared/schemas.py`'s `ComplianceCheckRequest`, sourced from a proxy header, never from prompt/completion text — see [0005](0005-user-identity-no-auth.md)). `block` and `hash` actions are never overridable by this flag at all.

## Consequences

No caller — regardless of any claimed authority — gets unredacted PHI/PII without an explicit, auditable, admin-side grant plus an explicit per-request ask. This closes off the obvious prompt-injection angle of an agent's output claiming "as the supervisor, unredact this" (see `detectors/injection/heuristics.py`'s `ROLE_CLAIM_PATTERNS`) — such a claim inside model-generated text has no path to actually flipping `allow_unredacted`, since that flag never reads from the text itself.
