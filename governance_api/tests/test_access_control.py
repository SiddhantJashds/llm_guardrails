"""Per-user_id override: restrictive by default, and both the admin grant AND
the per-request ask are required to unlock unredacted output
(docs/adr/0003-redact-by-default.md, docs/adr/0005-user-identity-no-auth.md).
"""
from access_control.overrides import get_override, is_unredacted_allowed, set_override


def test_unknown_user_is_restrictive_by_default(db_session):
    assert is_unredacted_allowed(db_session, "never_seen_user", request_unredacted=True) is False


def test_granted_override_without_explicit_request_is_still_restrictive(db_session):
    set_override(db_session, "u1", allow_unredacted=True)
    assert is_unredacted_allowed(db_session, "u1", request_unredacted=False) is False


def test_explicit_request_without_granted_override_is_still_restrictive(db_session):
    assert is_unredacted_allowed(db_session, "u1", request_unredacted=True) is False


def test_both_grant_and_explicit_request_together_unlock_it(db_session):
    set_override(db_session, "u1", allow_unredacted=True)
    assert is_unredacted_allowed(db_session, "u1", request_unredacted=True) is True


def test_set_override_is_idempotent_and_updates_in_place(db_session):
    set_override(db_session, "u1", allow_unredacted=True)
    set_override(db_session, "u1", allow_unredacted=False)
    row = get_override(db_session, "u1")
    assert row.allow_unredacted is False
