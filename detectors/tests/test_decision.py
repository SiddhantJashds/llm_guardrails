"""Decision-model router tests -- no network (httpx.post monkeypatched)."""
import os

import pytest

from detectors.decision import config, router
from detectors.decision.client import LayaUnavailableError
from detectors.decision import client as laya_client


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for key in ("DECISION_MODE", "LAYA_ENDPOINT", "LAYA_API_KEY", "LAYA_THRESHOLD", "LAYA_FAIL_OPEN"):
        monkeypatch.delenv(key, raising=False)


def _ner(text):
    return [("ssn_like", "123-45-6789")] if "123-45-6789" in text else []


def test_default_mode_is_ner():
    assert config.get_mode() == "ner"


def test_unknown_mode_falls_back_to_ner():
    os.environ["DECISION_MODE"] = "bogus"
    assert config.get_mode() == "ner"


def test_ner_mode_ignores_laya(monkeypatch):
    monkeypatch.setenv("DECISION_MODE", "ner")
    assert router.find_all("SSN 123-45-6789", "hipaa", _ner) == [("ssn_like", "123-45-6789")]


def test_laya_maps_firing_questions_to_full_text_span(monkeypatch):
    monkeypatch.setenv("DECISION_MODE", "laya")
    monkeypatch.setattr(laya_client, "query", lambda text, pack: {"government_id": 0.97, "person_name": 0.11})
    hits = router.find_all("My SSN is 123-45-6789", "hipaa", _ner)
    assert hits == [("laya_government_id", "My SSN is 123-45-6789")]


def test_laya_empty_text_never_emits_empty_span(monkeypatch):
    monkeypatch.setenv("DECISION_MODE", "laya")
    monkeypatch.setattr(laya_client, "query", lambda text, pack: {"government_id": 0.99})
    assert router.find_all("   ", "hipaa", _ner) == []


def test_cascade_unions_laya_first(monkeypatch):
    monkeypatch.setenv("DECISION_MODE", "cascade")
    monkeypatch.setattr(laya_client, "query", lambda text, pack: {"health_info": 0.9})
    hits = router.find_all("patient has diabetes, SSN 123-45-6789", "hipaa", _ner)
    assert hits[0] == ("laya_health_info", "patient has diabetes, SSN 123-45-6789")
    assert ("ssn_like", "123-45-6789") in hits


def test_fail_open_falls_back_to_ner(monkeypatch):
    monkeypatch.setenv("DECISION_MODE", "laya")
    def _boom(text, pack):
        raise LayaUnavailableError("tunnel down")
    monkeypatch.setattr(laya_client, "query", _boom)
    assert router.find_all("SSN 123-45-6789", "hipaa", _ner) == [("ssn_like", "123-45-6789")]


def test_fail_closed_propagates(monkeypatch):
    monkeypatch.setenv("DECISION_MODE", "laya")
    monkeypatch.setenv("LAYA_FAIL_OPEN", "0")
    def _boom(text, pack):
        raise LayaUnavailableError("tunnel down")
    monkeypatch.setattr(laya_client, "query", _boom)
    with pytest.raises(LayaUnavailableError):
        router.find_all("SSN 123-45-6789", "hipaa", _ner)


def test_client_parses_noul_probs(monkeypatch):
    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"answers": {"government_id": {"type": "noul", "noul": 0.97}}}
    import httpx
    monkeypatch.setenv("LAYA_ENDPOINT", "https://x.example")
    monkeypatch.setenv("LAYA_API_KEY", "k")
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _Resp())
    assert laya_client.query("SSN 123-45-6789", "hipaa")["government_id"] == pytest.approx(0.97)
