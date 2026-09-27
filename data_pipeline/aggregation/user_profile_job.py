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


def _composite_rating(violation_count: int, denied_count: int) -> float:
    """TODO (Data Scientist): replace with the real formula.

    Simple transparent proxy for now: start at 100, lose points per violation
    and per denied call, floor at 0.
    """
    return max(0.0, 100.0 - (violation_count * 5.0) - (denied_count * 3.0))


def _effective_use_score(total_tokens: int, violation_count: int) -> float:
    """TODO (Data Scientist): replace with the real formula.

    Placeholder proxy: tokens spent per violation, inverted so higher = better.
    """
    if violation_count == 0:
        return float(total_tokens)
    return float(total_tokens) / violation_count


def run_aggregation() -> None:
    db = SessionLocal()
    try:
        user_ids = {row[0] for row in db.query(TokenUsageEvent.user_id).distinct()}
        user_ids |= {row[0] for row in db.query(Receipt.user_id).distinct()}

        for user_id in user_ids:
            tokens_in = db.query(func.sum(TokenUsageEvent.tokens_in)).filter(TokenUsageEvent.user_id == user_id).scalar() or 0
            tokens_out = db.query(func.sum(TokenUsageEvent.tokens_out)).filter(TokenUsageEvent.user_id == user_id).scalar() or 0
            violation_count = (
                db.query(Receipt)
                .filter(Receipt.user_id == user_id, Receipt.decision_type == "compliance", Receipt.verdict != "allow")
                .count()
            )
            denied_count = (
                db.query(Receipt)
                .filter(Receipt.user_id == user_id, Receipt.decision_type == "authority", Receipt.verdict == "deny")
                .count()
            )

            profile = db.get(UserProfile, user_id)
            if profile is None:
                profile = UserProfile(user_id=user_id)
                db.add(profile)

            profile.total_tokens_in = tokens_in
            profile.total_tokens_out = tokens_out
            profile.violation_count = violation_count
            profile.composite_rating = _composite_rating(violation_count, denied_count)
            profile.effective_use_score = _effective_use_score(tokens_in + tokens_out, violation_count)

        db.commit()
        print(f"aggregated profiles for {len(user_ids)} user(s)")
    finally:
        db.close()


if __name__ == "__main__":
    run_aggregation()
