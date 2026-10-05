"""Data Scientist Day 2 #6: real composite_rating / effective_use_score
formulas (docs/adr/0011), replacing user_profile_job.py's placeholder ones.
"""
import pytest

from shared.models import Receipt, TokenUsageEvent, UserProfile
from user_profile_job import _composite_rating, _effective_use_score, run_aggregation


# ------------------------------------------------------------- pure formulas

def test_composite_rating_is_100_for_a_user_with_no_recorded_activity():
    assert _composite_rating(violation_count=0, denied_count=0, total_checks=0) == 100.0


def test_composite_rating_is_rate_based_not_a_raw_count():
    # One violation out of 2 checks hurts far more than one violation out of 100.
    heavy_penalty = _composite_rating(violation_count=1, denied_count=0, total_checks=2)
    light_penalty = _composite_rating(violation_count=1, denied_count=0, total_checks=100)
    assert heavy_penalty < light_penalty
    assert light_penalty > 99.0


def test_composite_rating_weighs_violations_above_denials():
    # Same rate (1/10), but a violation is a real PHI/PII hit; a denial is
    # governance already correctly stopping an out-of-scope attempt.
    all_violations = _composite_rating(violation_count=1, denied_count=0, total_checks=10)
    all_denials = _composite_rating(violation_count=0, denied_count=1, total_checks=10)
    assert all_violations < all_denials


def test_composite_rating_never_leaves_the_0_100_range():
    assert _composite_rating(violation_count=50, denied_count=50, total_checks=10) == 0.0
    assert 0.0 <= _composite_rating(violation_count=3, denied_count=2, total_checks=7) <= 100.0


def test_effective_use_score_is_zero_with_no_completed_tasks():
    # A user whose only recorded activity was violations/denials shouldn't
    # show a large "effective" number just because tokens were spent.
    assert _effective_use_score(total_tokens=5000, completed_tasks=0) == 0.0


def test_effective_use_score_is_tokens_per_completed_task():
    assert _effective_use_score(total_tokens=1000, completed_tasks=4) == 250.0


# --------------------------------------------------------- run_aggregation()

def _seed_receipt(db_session, user_id, decision_type, verdict):
    db_session.add(
        Receipt(
            prev_hash="0" * 64,
            hash=f"h-{decision_type}-{verdict}-{id(object())}",
            signature="sig",
            user_id=user_id,
            session_id="s1",
            agent_id="a1",
            decision_type=decision_type,
            verdict=verdict,
        )
    )


def test_run_aggregation_excludes_log_only_from_violation_count(db_session):
    # consent_purpose_flag-style hits are log_only and cost the agent's
    # authority score nothing (docs/adr/0009) -- they must not count against
    # the user's composite_rating either.
    _seed_receipt(db_session, "u1", "compliance", "log_only")
    db_session.add(TokenUsageEvent(user_id="u1", session_id="s1", agent_id="a1", tokens_in=100, tokens_out=50))
    db_session.commit()

    run_aggregation()

    profile = db_session.get(UserProfile, "u1")
    assert profile.violation_count == 0
    assert profile.composite_rating == 100.0


def test_run_aggregation_computes_both_scores_from_seeded_receipts(db_session):
    # 1 real violation (redact), 1 denial, 2 clean/completed receipts, out of 4 total.
    _seed_receipt(db_session, "u2", "compliance", "redact")
    _seed_receipt(db_session, "u2", "authority", "deny")
    _seed_receipt(db_session, "u2", "compliance", "allow")
    _seed_receipt(db_session, "u2", "authority", "allow")
    db_session.add(TokenUsageEvent(user_id="u2", session_id="s1", agent_id="a1", tokens_in=300, tokens_out=100))
    db_session.commit()

    run_aggregation()

    profile = db_session.get(UserProfile, "u2")
    assert profile.violation_count == 1
    assert profile.total_tokens_in == 300
    assert profile.total_tokens_out == 100
    assert profile.composite_rating == pytest.approx(100.0 * (1.0 - (0.7 * 0.25 + 0.3 * 0.25)))
    assert profile.effective_use_score == 200.0  # 400 tokens / 2 completed tasks


def test_run_aggregation_is_idempotent_on_an_existing_profile(db_session):
    _seed_receipt(db_session, "u3", "compliance", "allow")
    db_session.add(TokenUsageEvent(user_id="u3", session_id="s1", agent_id="a1", tokens_in=10, tokens_out=10))
    db_session.commit()

    run_aggregation()
    run_aggregation()  # re-running must update in place, not duplicate the row

    assert db_session.query(UserProfile).filter_by(user_id="u3").count() == 1
