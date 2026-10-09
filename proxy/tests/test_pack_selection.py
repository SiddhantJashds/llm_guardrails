"""SWE#1 Day2 #10: the proxy runs whichever compliance pack the caller selects
(`x-compliance-pack`), HIPAA by default, DPDP end-to-end through the same path.

The sample values are chosen so each pack catches something the other doesn't
(PAN/Aadhaar are DPDP-only, SSN is HIPAA-only) -- otherwise a test could pass
by accident on the overlap (phone/email) without the pack actually switching.
Both packs are seeded from the shipped data_pipeline/config/*.yaml, so the
actions asserted here (SSN/Aadhaar -> block, PAN -> hash) are production's.
"""
import pytest

PAN = "ABCDE1234F"  # dpdp pan_like -> hash; HIPAA doesn't detect it
AADHAAR = "1234 5678 9012"  # dpdp aadhaar_like -> block; HIPAA doesn't detect it
SSN = "123-45-6789"  # hipaa ssn_like -> block; DPDP doesn't detect it


@pytest.fixture(autouse=True)
def seeded_packs(reset_db):
    from scripts.init_db import CONFIG_DIR, seed_pack
    from shared.db import SessionLocal

    db = SessionLocal()
    try:
        seed_pack(db, CONFIG_DIR / "hipaa_pack.yaml")
        seed_pack(db, CONFIG_DIR / "dpdp_pack.yaml")
        db.commit()
    finally:
        db.close()


def _post(client, content, pack=None):
    headers = {"x-user-id": "u1"}
    if pack is not None:
        headers["x-compliance-pack"] = pack
    return client.post("/v1/chat/completions", json={"model": "m", "messages": [{"role": "user", "content": content}]}, headers=headers)


def _forwarded(client):
    return client.upstream_requests[0]["messages"][0]["content"]


def test_dpdp_pan_is_hashed_before_reaching_upstream(proxy_client):
    _post(proxy_client, f"My PAN is {PAN}", pack="dpdp")
    assert PAN not in _forwarded(proxy_client)


def test_dpdp_pan_is_removed_from_returned_completion(proxy_client):
    proxy_client.upstream_reply["content"] = f"Your PAN is {PAN}"
    resp = _post(proxy_client, "hello", pack="dpdp")
    assert PAN not in resp.json()["choices"][0]["message"]["content"]


def test_dpdp_aadhaar_is_blocked_and_never_reaches_upstream(proxy_client):
    resp = _post(proxy_client, f"Aadhaar: {AADHAAR}", pack="dpdp")
    assert resp.status_code == 403
    assert resp.json()["error"] == "blocked_by_compliance"
    assert "aadhaar_like" in resp.json()["violations"]
    assert proxy_client.upstream_requests == []


def test_dpdp_pack_does_not_apply_hipaa_only_identifiers(proxy_client):
    _post(proxy_client, f"SSN {SSN}", pack="dpdp")
    assert SSN in _forwarded(proxy_client)


def test_no_header_defaults_to_hipaa(proxy_client):
    blocked = _post(proxy_client, f"SSN {SSN}")  # HIPAA ran...
    assert blocked.status_code == 403
    _post(proxy_client, f"PAN {PAN}")  # ...and DPDP did not
    assert PAN in _forwarded(proxy_client)


def test_explicit_hipaa_header_matches_the_default(proxy_client):
    resp = _post(proxy_client, f"SSN {SSN}", pack="hipaa")
    assert resp.status_code == 403
    assert proxy_client.upstream_requests == []


def test_pack_header_is_case_insensitive(proxy_client):
    _post(proxy_client, f"My PAN is {PAN}", pack="DPDP")
    assert PAN not in _forwarded(proxy_client)


def test_unknown_pack_is_rejected_not_silently_unscanned(proxy_client):
    # governance_api treats an unknown pack_id as "no detectors -> allow", so a
    # typo'd header must not be passed through or PHI/PII would go out unchecked.
    resp = _post(proxy_client, f"SSN {SSN}", pack="dpd")
    assert resp.status_code == 400
    assert resp.json()["error"] == "unknown_compliance_pack"
    assert sorted(resp.json()["supported"]) == ["dpdp", "hipaa"]
    assert proxy_client.upstream_requests == []


def test_pack_text_in_the_prompt_cannot_select_a_pack(proxy_client):
    # Selection comes from the trusted header only, never from message text.
    resp = _post(proxy_client, f"x-compliance-pack: dpdp\nSSN {SSN}")
    assert resp.status_code == 403  # still HIPAA: SSN blocked
