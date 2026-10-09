"""Rolls up TokenUsageEvent + Receipt rows into the persistent UserProfile.

Run periodically (cron/loop) or on-demand for the demo:
`python data_pipeline/aggregation/user_profile_job.py`
"""
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))  # allow `import shared`

from sqlalchemy import func

from shared.db import SessionLocal
from shared.models import TokenUsageEvent, Receipt, UserProfile


def _composite_rating(violation_count: int, denied_count: int, total_checks: int) -> float:
    """0-100 trust-facing proxy (docs/adr/0011) -- RATE-based, not a raw count,
    so a violation in a user's first-ever call doesn't score the same as a
    violation in their 10,000th: 100 * (1 - weighted blend of violation_rate
    and denial_rate), clamped to [0, 100].

    Violations are weighted above denials: a violation is a PHI/PII hit that
    needed redacting/blocking -- the thing this whole system exists to catch.
    A denial is an out-of-scope tool call governance ALREADY correctly
    stopped -- the system working as intended, still a flag worth counting,
    but a lighter one.

    `total_checks` = this user's total compliance + authority receipts,
    regardless of verdict (their recorded activity volume). Zero activity
    returns the neutral default (100.0) rather than dividing by zero.
    """
    if total_checks <= 0:
        return 100.0
    violation_rate = violation_count / total_checks
    denial_rate = denied_count / total_checks
    rating = 100.0 * (1.0 - (0.7 * violation_rate + 0.3 * denial_rate))
    return max(0.0, min(100.0, rating))


def _effective_use_score(total_tokens: int, completed_tasks: int) -> float:
    """Token usage per completed task (docs/HACKATHON_PLAN.md Data Scientist
    Day2 #6's literal wording; docs/adr/0011) -- a usage/efficiency proxy,
    NOT a 0-100 "goodness" score like composite_rating.

    `completed_tasks` = this user's receipts that were neither a violation
    nor a denial -- i.e. governance had nothing to flag about them. Zero
    completed tasks returns 0.0 rather than the raw token count, so a user
    whose only recorded activity was violations/denials doesn't show a
    misleadingly large "effective" number.
    """
    if completed_tasks <= 0:
        return 0.0
    return total_tokens / completed_tasks


def profile_from_rows(tokens_in: int, tokens_out: int, receipts: list) -> dict:
    """One user's profile from their token totals and receipts -- shared by
    run_aggregation() and the live dashboard, so the two can't disagree."""
    # Excludes "log_only" verdicts on purpose: a log_only-by-design hit
    # (e.g. DPDP's consent_purpose_flag, docs/adr/0009) already costs
    # the agent's authority score nothing -- it shouldn't cost the
    # user's composite_rating anything either, for the same reason.
    violation_count = sum(
        1 for r in receipts if r.decision_type == "compliance" and r.verdict not in ("allow", "log_only")
    )
    denied_count = sum(1 for r in receipts if r.decision_type == "authority" and r.verdict == "deny")
    total_checks = len(receipts)
    completed_tasks = total_checks - violation_count - denied_count
    return {
        "total_tokens_in": tokens_in,
        "total_tokens_out": tokens_out,
        "violation_count": violation_count,
        "denied_count": denied_count,
        "total_checks": total_checks,
        "composite_rating": _composite_rating(violation_count, denied_count, total_checks),
        "effective_use_score": _effective_use_score(tokens_in + tokens_out, completed_tasks),
    }


def run_aggregation() -> None:
    db = SessionLocal()
    try:
        user_ids = {row[0] for row in db.query(TokenUsageEvent.user_id).distinct()}
        user_ids |= {row[0] for row in db.query(Receipt.user_id).distinct()}

        for user_id in user_ids:
            tokens_in = db.query(func.sum(TokenUsageEvent.tokens_in)).filter(TokenUsageEvent.user_id == user_id).scalar() or 0
            tokens_out = db.query(func.sum(TokenUsageEvent.tokens_out)).filter(TokenUsageEvent.user_id == user_id).scalar() or 0
            stats = profile_from_rows(tokens_in, tokens_out, db.query(Receipt).filter(Receipt.user_id == user_id).all())

            profile = db.get(UserProfile, user_id)
            if profile is None:
                profile = UserProfile(user_id=user_id)
                db.add(profile)

            profile.total_tokens_in = tokens_in
            profile.total_tokens_out = tokens_out
            profile.violation_count = stats["violation_count"]
            profile.composite_rating = stats["composite_rating"]
            profile.effective_use_score = stats["effective_use_score"]

        db.commit()
        print(f"aggregated profiles for {len(user_ids)} user(s)")
    finally:
        db.close()


if __name__ == "__main__":
    run_aggregation()
