"""DPDP pack: street-address / PIN detection, consent_purpose_flag, and the
bare-Indian-mobile recall fix (Data Scientist Day 2 #5). Name/place NER and
shared phone/email patterns are covered by detectors/tests/test_ner.py.
"""
import pytest

from detectors.dpdp.identifiers import find_all as find_dpdp
from detectors.scoring.signals import NO_SIGNAL_IDENTIFIERS, phi_signal


def _spans(hits, identifier):
    return {span for name, span in hits if name == identifier}


# ------------------------------------------------------------------ positives

@pytest.mark.parametrize(
    "text,expected_span",
    [
        ("House No. 23, Indiranagar", "House No. 23, Indiranagar"),
        ("Flat No. 4B, MG Road", "Flat No. 4B, MG Road"),
        ("He lives on MG Road near the signal.", "MG Road"),
        ("Sector 15, Noida", "Sector 15"),
        ("Phase 2, Gurgaon", "Phase 2"),
    ],
)
def test_detects_street_or_locality(text, expected_span):
    assert expected_span in _spans(find_dpdp(text), "residential_address")


@pytest.mark.parametrize("text,pin", [("PIN: 560001", "560001"), ("pincode 110001", "110001")])
def test_detects_pin_code_with_label(text, pin):
    assert _spans(find_dpdp(text), "residential_address") == {pin}


def test_bare_six_digit_number_is_not_a_pin_code_without_a_label():
    assert _spans(find_dpdp("Order 560001 shipped."), "residential_address") == set()


@pytest.mark.parametrize(
    "text",
    [
        "Consent obtained for marketing communications.",
        "Purpose: Analytics and service improvement",
        "Purpose of processing: Billing and dispute resolution",
        "consent: yes",
    ],
)
def test_detects_consent_purpose_flag(text):
    assert any(name == "consent_purpose_flag" for name, _ in find_dpdp(text))


@pytest.mark.parametrize(
    "text",
    ["Call him at 9876543210.", "9876543210", "contact: 8123456789"],
)
def test_bare_indian_mobile_is_caught_unlike_hipaas_generic_bare_digits(text):
    assert "9876543210" in _spans(find_dpdp(text), "phone_number") or "8123456789" in _spans(
        find_dpdp(text), "phone_number"
    )


def test_web_url_and_ip_address_are_reused_from_hipaa_pack():
    """docs/adr/0016 -- these were HIPAA-only even though neither is
    healthcare-specific; now shared via overlap_map.yaml."""
    hits = find_dpdp("Visit https://example.com/profile from 203.0.113.7")
    assert "https://example.com/profile" in _spans(hits, "web_url")
    assert "203.0.113.7" in _spans(hits, "ip_address")


# ------------------------------------------------------- false-positive guards

@pytest.mark.parametrize(
    "text",
    [
        "They closed the road for repairs.",
        "Growth driven by the IT sector.",
        "The purpose of this meeting is clear.",
        "assigned to sector 7 for review",
    ],
)
def test_lowercase_generic_phrases_are_not_an_address_or_consent_flag(text):
    hits = find_dpdp(text)
    assert _spans(hits, "residential_address") == set()
    assert not any(name == "consent_purpose_flag" for name, _ in hits)


@pytest.mark.parametrize("text", ["Order 1234567890 shipped.", "Case 5678901234 filed."])
def test_ten_digit_numbers_not_starting_6_to_9_are_not_a_phone_number(text):
    assert _spans(find_dpdp(text), "phone_number") == set()


# -------------------------------------------------- consent_purpose_flag scoring

def test_consent_purpose_flag_is_a_no_signal_identifier():
    assert NO_SIGNAL_IDENTIFIERS == {"consent_purpose_flag"}


def test_consent_purpose_flag_alone_costs_nothing():
    assert phi_signal(["consent_purpose_flag"]) is None


def test_consent_purpose_flag_alongside_a_real_hit_still_penalizes_for_the_real_hit():
    assert phi_signal(["consent_purpose_flag", "aadhaar_like"]) == "phi_in_output"
    assert phi_signal(["consent_purpose_flag", "full_name"]) == "phi_in_output_low_confidence"
