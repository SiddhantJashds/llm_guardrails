"""Compliance engine action branching + the redact-by-default override rule
(docs/adr/0003-redact-by-default.md).

`_run_detectors` is monkeypatched here so these tests verify the engine's OWN
logic (action lookup, override gating, the low-confidence block downgrade)
independent of what any detector returns -- end-to-end detector coverage
lives in detectors/tests/ and test_api_routes.py.
"""
import compliance.engine as compliance_engine
from shared.models import CompliancePackConfig


def _seed_action(db_session, pack_id, identifier, action):
    db_session.add(CompliancePackConfig(pack_id=pack_id, identifier=identifier, action=action))
    db_session.commit()


def test_redact_action_masks_the_matched_span(db_session, monkeypatch):
    _seed_action(db_session, "hipaa", "phone_number", "redact")
    monkeypatch.setattr(compliance_engine, "_run_detectors", lambda text, pack_id: [("phone_number", "555-123-4567")])

    verdict, cleaned, violations = compliance_engine.check(db_session, "call 555-123-4567 now", "hipaa")
    assert verdict == "redact"
    assert "555-123-4567" not in cleaned
    assert violations == ["phone_number"]


def test_block_action_returns_empty_text_and_is_never_overridable(db_session, monkeypatch):
    _seed_action(db_session, "hipaa", "ssn_like", "block")
    monkeypatch.setattr(compliance_engine, "_run_detectors", lambda text, pack_id: [("ssn_like", "123-45-6789")])

    verdict, cleaned, _ = compliance_engine.check(db_session, "ssn 123-45-6789", "hipaa", allow_unredacted=True)
    assert verdict == "block"
    assert cleaned == ""


def test_hash_action_replaces_span_and_is_never_overridable(db_session, monkeypatch):
    _seed_action(db_session, "hipaa", "medical_record_number", "hash")
    monkeypatch.setattr(compliance_engine, "_run_detectors", lambda text, pack_id: [("medical_record_number", "MRN12345")])

    verdict, cleaned, _ = compliance_engine.check(db_session, "MRN12345 on file", "hipaa", allow_unredacted=True)
    assert verdict == "hash"
    assert "MRN12345" not in cleaned
    assert "[HASH:" in cleaned


def test_allow_unredacted_skips_masking_only_for_redact_action(db_session, monkeypatch):
    _seed_action(db_session, "hipaa", "phone_number", "redact")
    monkeypatch.setattr(compliance_engine, "_run_detectors", lambda text, pack_id: [("phone_number", "555-123-4567")])

    verdict, cleaned, violations = compliance_engine.check(db_session, "call 555-123-4567 now", "hipaa", allow_unredacted=True)
    assert "555-123-4567" in cleaned  # left visible
    assert violations == ["phone_number"]  # still surfaced -- override doesn't hide that it happened


def test_missing_pack_config_defaults_to_the_safer_redact_action(db_session, monkeypatch):
    # No CompliancePackConfig row seeded at all for this identifier.
    monkeypatch.setattr(compliance_engine, "_run_detectors", lambda text, pack_id: [("unknown_identifier", "some-span")])

    verdict, cleaned, _ = compliance_engine.check(db_session, "some-span here", "hipaa")
    assert verdict == "redact"
    assert "some-span" not in cleaned


def test_no_violations_is_a_clean_allow(db_session, monkeypatch):
    monkeypatch.setattr(compliance_engine, "_run_detectors", lambda text, pack_id: [])

    verdict, cleaned, violations = compliance_engine.check(db_session, "nothing sensitive here", "hipaa")
    assert verdict == "allow"
    assert cleaned == "nothing sensitive here"
    assert violations == []


def test_block_is_downgraded_to_redact_for_low_confidence_identifiers(db_session, monkeypatch):
    # An admin (mis)configuring NER-derived `full_name` to "block" must not let
    # a statistical false positive wipe the whole response (docs/adr/0008).
    _seed_action(db_session, "hipaa", "full_name", "block")
    monkeypatch.setattr(compliance_engine, "_run_detectors", lambda text, pack_id: [("full_name", "Jane Roe")])

    verdict, cleaned, violations = compliance_engine.check(db_session, "Seen by Jane Roe today", "hipaa")
    assert verdict == "redact"
    assert cleaned == "Seen by [REDACTED] today"
    assert violations == ["full_name"]
