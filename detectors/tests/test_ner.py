"""NER-backed name/place detection + its false-positive guards (docs/adr/0008).

The corpus below is small and hand-written -- it pins known behavior of the
pinned model (en_core_web_sm 3.8.0) and catches regressions; it is NOT a
validation of real-world recall. Data Scientist Day 2 #8 still needs a real
labelled set.
"""
import pytest

from detectors import ner
from detectors.hipaa.identifiers import PATTERNS, find_all as find_hipaa
from detectors.dpdp.identifiers import find_all as find_dpdp
from detectors.scoring.signals import LOW_CONFIDENCE_IDENTIFIERS, compute_signals, phi_signal


def _spans(hits, identifier):
    return {span for name, span in hits if name == identifier}


# ------------------------------------------------------------------ positives

def test_detects_person_and_city():
    hits = find_hipaa("Patient John Smith was seen in Boston last week.")
    assert "John Smith" in _spans(hits, "full_name")
    assert "Boston" in _spans(hits, "geographic_subdivision")


def test_detects_all_caps_text():
    hits = find_hipaa("PATIENT: MARY JOHNSON LIVES IN SPRINGFIELD")
    assert "MARY JOHNSON" in _spans(hits, "full_name")


def test_dpdp_maps_places_to_residential_address():
    hits = find_dpdp("Priya Sharma lives in Pune.")
    assert "Priya Sharma" in _spans(hits, "full_name")
    assert "Pune" in _spans(hits, "residential_address")
    assert not _spans(hits, "geographic_subdivision")


# ------------------------------------------------------- false-positive guards

@pytest.mark.parametrize(
    "text",
    [
        "He was diagnosed with Parkinson's disease.",
        "History of Crohn's disease and Down syndrome.",
        "Presents with Bell's palsy.",
        "Alzheimer's screening is scheduled.",
        "Tylenol 500 mg twice daily.",
    ],
)
def test_clinical_eponyms_and_drug_names_are_not_names(text):
    assert _spans(find_hipaa(text), "full_name") == set()


@pytest.mark.parametrize(
    "text",
    [
        "Cases rose in California and Texas.",
        "She travelled from India to Turkey.",
        "Data from the United States and Maharashtra.",
    ],
)
def test_state_level_and_above_is_not_a_safe_harbor_identifier(text):
    assert find_hipaa(text) == []


def test_eponym_filter_only_applies_to_a_bare_single_word_entity():
    from spacy.tokens import Span

    nlp = ner.load_model()

    def person_ent(text, start, end):
        doc = nlp.make_doc(text)
        return Span(doc, start, end, label="PERSON"), text

    assert ner._is_person(*person_ent("Parkinson", 0, 1)) is False
    # A patient actually named Parkinson/Addison must not be dropped.
    assert ner._is_person(*person_ent("Sarah Parkinson", 0, 2)) is True
    assert ner._is_person(*person_ent("Addison Clark", 0, 2)) is True


@pytest.mark.parametrize("text", ["Order 12345 shipped.", "Give 10000 units.", "Ref 90210 filed."])
def test_bare_five_digit_numbers_are_not_zip_codes(text):
    assert _spans(find_hipaa(text), "geographic_subdivision") == set()


@pytest.mark.parametrize(
    "text,zip_",
    [("Lives at NY 10001", "10001"), ("zip code: 90210", "90210"), ("ZIP 60601-1234", "60601-1234")],
)
def test_zip_with_context_is_flagged_digits_only(text, zip_):
    assert zip_ in _spans(find_hipaa(text), "geographic_subdivision")


@pytest.mark.parametrize(
    "name,text",
    [
        ("account_number", "Please bill Smith; patient Johnson attended."),
        ("certificate_license_number", "The license agreement was signed."),
        ("vehicle_identifier", "A car insurance quote."),
        ("device_identifier", "sn: hello-world"),
        ("unique_identifying_code", "case number: fictional"),
        ("health_plan_beneficiary_number", "The beneficiary was informed."),
        ("health_plan_beneficiary_number", "beneficiary informed"),
        ("phone_number", "Total 1234567890 units shipped."),
        ("phone_number", "Order id 9876543210."),
    ],
)
def test_keyword_patterns_need_a_digit_in_the_value(name, text):
    assert not PATTERNS[name].search(text)


@pytest.mark.parametrize(
    "name,text",
    [
        ("account_number", "Account number: A12345"),
        ("certificate_license_number", "Driver's license: D1234567"),
        ("vehicle_identifier", "VIN: 1HGCM82633A004352"),
        ("device_identifier", "serial number: SN-9981"),
        ("unique_identifying_code", "patient id: P0012345"),
        ("health_plan_beneficiary_number", "Beneficiary ID: 1EG4-TE5-MK73"),
        ("health_plan_beneficiary_number", "plan number 12345678"),
    ],
)
def test_keyword_patterns_still_catch_real_identifiers(name, text):
    assert PATTERNS[name].search(text)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("call 555-123-4567 now", "555-123-4567"),
        ("call 555.123.4567", "555.123.4567"),
        ("(555) 123-4567", "(555) 123-4567"),
        ("+1 555 123 4567", "+1 555 123 4567"),
        ("+91 98765 43210", "+91 98765 43210"),
        ("98765 43210", "98765 43210"),
        ("Phone: 5551234567", "5551234567"),  # bare digits + label -> digits only
        ("mobile number - 9876543210", "9876543210"),
    ],
)
def test_phone_numbers_are_still_caught_when_formatted_or_labelled(text, expected):
    assert _spans(find_hipaa(text), "phone_number") == {expected}
    assert _spans(find_dpdp(text), "phone_number") == {expected}  # DPDP shares the pattern


def test_known_limit_unlabelled_unformatted_ten_digits_is_not_a_phone_number():
    # Deliberate recall trade-off (docs/MOCKED_VS_PRODUCTION.md): indistinguishable from any ID/count.
    assert _spans(find_hipaa("9876543210"), "phone_number") == set()


# --------------------------------------------------- known limits (documented)

@pytest.mark.xfail(
    strict=True,
    reason="en_core_web_sm returns 'Kumar Iyer' for 'Ramesh Kumar Iyer', leaving the given name unredacted "
    "(docs/MOCKED_VS_PRODUCTION.md). XPASSing means the model/filters improved -- remove this marker.",
)
def test_known_limit_partial_multiword_name():
    assert "Ramesh Kumar Iyer" in _spans(find_dpdp("Ramesh Kumar Iyer, Bengaluru"), "full_name")


# ------------------------------------------------------ hand-labelled corpus

# (text, names that must be found, names that must NOT be found)
_CORPUS = [
    ("Patient John Smith was seen on the ward.", {"John Smith"}, set()),
    ("Please contact Maria Garcia about the referral.", {"Maria Garcia"}, set()),
    ("Priya Sharma called the clinic.", {"Priya Sharma"}, set()),
    ("Ask Robert Johnson for the chart.", {"Robert Johnson"}, set()),
    ("The note was signed by Emily Chen.", {"Emily Chen"}, set()),
    ("Parkinson's disease progressed slowly.", set(), {"Parkinson"}),
    ("Crohn's disease flare reported.", set(), {"Crohn"}),
    ("Patient has Down syndrome.", set(), {"Down"}),
    ("Prescribed Tylenol and metformin.", set(), {"Tylenol", "metformin"}),
    ("Blood pressure 120/80, pulse 72.", set(), set()),
    ("The quarterly report is attached.", set(), set()),
]


def test_corpus_precision_and_recall_floor():
    tp = fp = fn = 0
    for text, want, forbid in _CORPUS:
        got = _spans(find_hipaa(text), "full_name")
        tp += len(want & got)
        fn += len(want - got)
        fp += len(got - want)
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    assert precision >= 0.9, f"precision={precision:.2f} tp={tp} fp={fp} fn={fn}"
    assert recall >= 0.8, f"recall={recall:.2f} tp={tp} fp={fp} fn={fn}"


# ------------------------------------------------------------- fail-closed

def test_missing_model_fails_closed(monkeypatch):
    monkeypatch.setattr(ner, "_NLP", None)
    monkeypatch.setattr(ner, "MODEL_NAME", "definitely_not_an_installed_model")
    monkeypatch.delenv("GUARDRAILS_NER_DISABLED", raising=False)
    with pytest.raises(ner.NERUnavailableError):
        find_hipaa("Patient John Smith")


def test_explicit_opt_out_runs_regex_only(monkeypatch):
    monkeypatch.setenv("GUARDRAILS_NER_DISABLED", "1")
    hits = find_hipaa("Patient John Smith, phone 555-123-4567")
    assert _spans(hits, "full_name") == set()
    assert _spans(hits, "phone_number") == {"555-123-4567"}


# ---------------------------------------------------------- tiered signals

def test_low_confidence_identifiers_are_exactly_the_ner_derived_ones():
    assert LOW_CONFIDENCE_IDENTIFIERS == {"full_name", "geographic_subdivision", "residential_address"}


def test_phi_signal_tiers():
    assert phi_signal([]) is None
    assert phi_signal(["full_name"]) == "phi_in_output_low_confidence"
    assert phi_signal(["full_name", "geographic_subdivision"]) == "phi_in_output_low_confidence"
    assert phi_signal(["full_name", "ssn_like"]) == "phi_in_output"
    assert phi_signal(["phone_number"]) == "phi_in_output"


def test_compute_signals_uses_the_tiers():
    assert compute_signals(["full_name"], [], False) == ["phi_in_output_low_confidence"]
    assert compute_signals(["ssn_like"], [], False) == ["phi_in_output"]
