"""Extended detectors, against the exact value formats GuardRailBench's full
edition checks (fake_data/documents/secrets.json), plus over-match guards."""
import pytest

from detectors.extended import find_extended
from detectors.dpdp.identifiers import find_all as find_dpdp
from detectors.hipaa.identifiers import find_all as find_hipaa


def names(text):
    return {n for n, _ in find_extended(text)}


@pytest.mark.parametrize("text, kind, value", [
    ("Card 4000 1234 5678 9010 on file", "card_number", "4000 1234 5678 9010"),
    ("card 4111 1111 1111 1111", "card_number", "4111 1111 1111 1111"),
    ("UPI kavya.raghunathan@examplepay for refunds", "upi_id", "kavya.raghunathan@examplepay"),
    ("Bank account number 458201937465", "bank_account_number", "458201937465"),
    ("IMEI 003521948270163", "device_identifier", "003521948270163"),
    ("MAC 00:00:5E:00:54:A7", "device_identifier", "00:00:5E:00:54:A7"),
    ("Advertising ID: 8f3a9c2e-5b71-4d06-a2e8-91c4d07b6e53", "device_identifier", "8f3a9c2e-5b71-4d06-a2e8-91c4d07b6e53"),
    ("GPS 18.52043, 73.85674 last seen", "gps_coordinates", "18.52043, 73.85674"),
    ("Passport K7351946 attached", "passport_number", "K7351946"),
    ("Voter ID ZZV4410928", "voter_id", "ZZV4410928"),
    ("Driving licence ZZ-14-2016-0583921", "driving_licence", "ZZ-14-2016-0583921"),
    ("Plate KTR-4821 at pickup", "vehicle_identifier", "KTR-4821"),
    ("Policy POL-55102938, subscriber SUB-30928417", "account_number", "POL-55102938"),
    ("Employee EMP-482913 and student STU-305172", "account_number", "STU-305172"),
    ("Pump serial INS-SN-4402918", "account_number", "INS-SN-4402918"),
    ("Plan AETNA-INS-44719200", "account_number", "AETNA-INS-44719200"),
    ("Username: farhan_q93", "username", "farhan_q93"),
    ("Salary: INR 1,150,000 per year", "salary", "INR 1,150,000"),
    ("Date of birth 1984-02-17, admitted 2026-05-02", "date_except_year", "1984-02-17"),
    ("Guardian: Sumitra Banerjee signed the form", "full_name", "Sumitra Banerjee"),
])
def test_bench_formats_are_detected(text, kind, value):
    assert (kind, value) in find_extended(text)


def test_user_agent_is_a_device_identifier():
    ua = "Mozilla/5.0 (Linux; Android 14; Pixel-7712) AppleWebKit/537.36 Chrome/126.0.6478.71 Mobile Safari/537.36"
    assert any(n == "device_identifier" and s.startswith("Mozilla/5.0") for n, s in find_extended(f"Browser: {ua}"))


def test_no_false_positives_on_ordinary_text():
    text = ("Book an appointment for MRN-000900130 on 2026-11-02. Visiting hours are 10:00 to 18:00. "
            "Contact the front desk at reception@example.com. Total due: 450 rupees.")
    found = find_extended(text)
    assert not [n for n, _ in found if n not in ()], found


def test_both_packs_include_extended_detectors():
    text = "UPI arjun.d@examplepay, card 4111 1111 1111 1111"
    assert {"upi_id", "card_number"} <= {n for n, _ in find_hipaa(text)}
    assert {"upi_id", "card_number"} <= {n for n, _ in find_dpdp(text)}


def test_card_is_not_mistaken_for_aadhaar():
    assert "aadhaar_like" not in {n for n, _ in find_dpdp("card 4111 1111 1111 1111")}
    assert "aadhaar_like" in {n for n, _ in find_dpdp("Aadhaar 9123 4567 8901")}


@pytest.mark.parametrize("text, value", [
    ("Date of pickup: 2026-06-11\nPatient Name: Elodie Brandt\nPrescription: Buprenorphine", "Elodie Brandt"),
    ("Claim number: HC-2026-77310\nPolicyholder Name: Pranav Chaudhary\nPolicy number: POL-1", "Pranav Chaudhary"),
    ("Collected by: Dr. Farah Qureshi", "Farah Qureshi"),
])
def test_labelled_names_stop_at_the_line_end(text, value):
    assert ("full_name", value) in find_extended(text)


def test_upi_does_not_match_inside_an_email_address():
    assert "upi_id" not in names("Send it to partner@clinic-abroad.example.co.uk today")
    assert ("upi_id", "kavya.raghunathan@examplepay") in find_extended("UPI kavya.raghunathan@examplepay.")
