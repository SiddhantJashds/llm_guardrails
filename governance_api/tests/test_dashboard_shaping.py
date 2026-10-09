from datetime import datetime, timedelta

from insights.shaping import (
    activity_buckets,
    identifier_counts,
    is_flag,
    iso_utc,
    outcome,
    parse_identifiers,
    trajectory,
)


def test_iso_utc_marks_naive_datetimes_as_utc():
    assert iso_utc(datetime(2026, 10, 9, 10, 34, 10)) == "2026-10-09T10:34:10+00:00"
    assert iso_utc(None) is None


def test_identifier_counts_dedupes_and_sorts():
    assert identifier_counts(["full_name, full_name, phone_number", None, "phone_number, full_name"]) == [
        {"type": "full_name", "count": 3},
        {"type": "phone_number", "count": 2},
    ]


def test_parse_identifiers_handles_override_suffix_and_injection_note():
    reason = "phone_number, full_name [unredacted_override_applied: user_id=x]; injection_detected: role_claim, ignore_previous"
    assert parse_identifiers(reason) == ["phone_number", "full_name", "injection:role_claim", "injection:ignore_previous"]
    assert parse_identifiers("injection_detected: role_claim") == ["injection:role_claim"]


def test_outcome_maps_hash_to_redact_and_keeps_log_only():
    assert outcome("compliance", "hash") == "redact"
    assert outcome("compliance", "log_only") == "log_only"
    assert outcome("authority", "deny") == "deny"
    assert outcome("authority", "allow") == "allow"
    assert not is_flag("log_only") and is_flag("block")


def test_trajectory_recovers_capped_start():
    t = trajectory(75.0, [{"signal": "phi_in_output_low_confidence", "delta": -5.0}])
    assert t["initial_score"] == 80.0
    assert [p["score"] for p in t["points"]] == [80.0, 75.0]
    assert t["approximate"] is False


def test_trajectory_flags_zero_floor_as_approximate():
    t = trajectory(0.0, [{"signal": "x", "delta": -60.0}, {"signal": "x", "delta": -60.0}])
    assert t["initial_score"] == 100.0 and t["approximate"] is True
    assert t["points"][-1]["score"] == 0.0


def test_activity_buckets_cap_count_and_sum_rows():
    base = datetime(2026, 10, 9, 10, 0, 0)
    rows = [(base + timedelta(minutes=m), "allow") for m in range(0, 180)] + [(base, "redact")]
    out = activity_buckets(rows, max_buckets=60)
    assert len(out["buckets"]) <= 60
    assert sum(b["allow"] for b in out["buckets"]) == 180
    assert sum(b["redact"] for b in out["buckets"]) == 1


def test_activity_buckets_empty():
    assert activity_buckets([]) == {"bucket_seconds": 60, "buckets": []}
