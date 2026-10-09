"""NER vs Laya backend comparison -- would laya-only mode hold up?

Runs the same corpus through the real regex+spaCy HIPAA detector and through
the decision router in `laya` mode (Laya stubbed with canned P(yes) values
captured from live tunnel runs -- noted per case, so this stays deterministic
with no network). Each side is reduced to violations + authority penalty via
the real `phi_signal`, i.e. exactly what the score would cost in production.

For a LIVE comparison against your tunnel (nondeterministic, not CI):
  LAYA_ENDPOINT=... LAYA_API_KEY=... uv run python detectors/decision/eval_compare.py
"""
import pytest

from detectors.hipaa.identifiers import find_all as ner_find_all
from detectors.scoring.signals import SIGNAL_PENALTIES, phi_signal
from detectors.decision import client as laya_client
from detectors.decision import router


def _penalty(violations):
    signal = phi_signal([name for name, _ in violations])
    return SIGNAL_PENALTIES[signal] if signal else 0.0


# text -> canned {question: P(yes)} -- real tunnel observations, Oct 2026.
# Laya is nondeterministic run-to-run; these pin one observed run so CI is
# stable. Notable in this run: names MISSED (person_name 0.25), phone text
# over-fired 4 categories, paraphrase flagged via the WRONG category
# (email_or_phone, not government_id). The eval script re-measures live.
CANNED = {
    "My SSN is 123-45-6789": {
        "person_name": 0.131, "email_or_phone": 0.540, "government_id": 0.961,
        "health_info": 0.573, "financial_account": 0.801, "postal_address": 0.260,
    },
    "Please call 555-123-4567 to confirm.": {
        "person_name": 0.583, "email_or_phone": 0.939, "government_id": 0.762,
        "health_info": 0.263, "financial_account": 0.774, "postal_address": 0.098,
    },
    "John Smith lives in Austin.": {
        "person_name": 0.249, "email_or_phone": 0.179, "government_id": 0.196,
        "health_info": 0.015, "financial_account": 0.265, "postal_address": 0.314,
    },
    "The weather is nice today.": {
        "person_name": 0.010, "email_or_phone": 0.069, "government_id": 0.145,
        "health_info": 0.035, "financial_account": 0.094, "postal_address": 0.034,
    },
    "My nine-digit social ends in 6789, don't share it.": {
        "person_name": 0.148, "email_or_phone": 0.760, "government_id": 0.061,
        "health_info": 0.002, "financial_account": 0.295, "postal_address": 0.220,
    },
}


@pytest.fixture(autouse=True)
def laya_mode(monkeypatch):
    monkeypatch.setenv("DECISION_MODE", "laya")
    monkeypatch.setenv("LAYA_THRESHOLD", "0.5")
    monkeypatch.setattr(laya_client, "query", lambda text, pack: CANNED[text])


def _laya(text):
    return router.find_all(text, "hipaa", ner_find_all)


def test_exact_pii_parity_ssn():
    # Both flag; both high-confidence (-20). Laya-only holds here.
    ner, laya = ner_find_all("My SSN is 123-45-6789"), _laya("My SSN is 123-45-6789")
    assert any(n == "ssn_like" for n, _ in ner)
    assert any(n == "laya_government_id" for n, _ in laya)
    assert _penalty(ner) == _penalty(laya) == 20.0


def test_exact_pii_parity_phone():
    ner = ner_find_all("Please call 555-123-4567 to confirm.")
    laya = _laya("Please call 555-123-4567 to confirm.")
    assert any(n == "phone_number" for n, _ in ner)
    assert any(n == "laya_email_or_phone" for n, _ in laya)
    assert _penalty(ner) == _penalty(laya) == 20.0


def test_names_ner_catches_what_laya_misses():
    # The reverse gap, and the reason laya-only mode is NOT safe alone:
    # NER sees "John Smith" + "Austin" (low-conf, -5); Laya scored
    # person_name 0.25 and flagged nothing. Each backend has a blind spot
    # the other covers -- the empirical case for cascade.
    ner = ner_find_all("John Smith lives in Austin.")
    laya = _laya("John Smith lives in Austin.")
    assert ner and _penalty(ner) == 5.0
    assert laya == [] and _penalty(laya) == 0.0


def test_clean_stays_clean_both():
    assert ner_find_all("The weather is nice today.") == []
    assert _laya("The weather is nice today.") == []


def test_laya_only_recall_win_on_paraphrase():
    # No digits formatted for regex, no names/places for NER -- classic path
    # is blind; the decision model still flags it (via email_or_phone, not
    # government_id -- right verdict, wrong category, a categorization caveat
    # for anyone reading laya_* names as ground truth). This is the case
    # laya-only mode buys you.
    assert ner_find_all("My nine-digit social ends in 6789, don't share it.") == []
    laya = _laya("My nine-digit social ends in 6789, don't share it.")
    assert laya and _penalty(laya) == 20.0


def test_scoreboard_agreement_summary():
    # Whole-corpus view: detection agreement (flag/no-flag), not penalty.
    # SSN/phone/clean agree; names (laya miss) and paraphrase (ner miss)
    # differ -- 3/5, i.e. neither backend subsumes the other.
    agree = sum(
        bool(ner_find_all(t)) == bool(router.find_all(t, "hipaa", ner_find_all))
        for t in CANNED
    )
    assert agree == 3
