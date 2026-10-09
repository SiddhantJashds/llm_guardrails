"""Typed placeholders, restore-to-sender, display styles, direction scope and
roles (docs/adr/0016) -- end to end through /governance/compliance-check."""
import pytest

from compliance import redaction, vault


@pytest.fixture(autouse=True)
def fresh_vault():
    vault.clear()
    yield
    vault.clear()


def _check(client, text, *, direction="inbound", user="alex", session="sess_r", restore=False, ask=False, scored=True, pack="hipaa"):
    return client.post("/governance/compliance-check", json={
        "identity": {"user_id": user, "session_id": session, "agent_id": "a1", "parent_agent_id": None},
        "text": text, "direction": direction, "pack_id": pack,
        "restore_to_sender": restore, "request_unredacted": ask, "apply_score": scored,
    }).json()


def test_model_gets_typed_numbered_placeholders_stable_per_session(client):
    a = _check(client, "Hello, my name is Alex Morgan and my phone is (555) 201-7788.")
    assert a["cleaned_text"] == "Hello, my name is [NAME_1] and my phone is [PHONE_1]."
    b = _check(client, "Call 555-201-7788 and tell Alex Morgan that Priya Raman called.")
    assert b["cleaned_text"] == "Call [PHONE_1] and tell [NAME_1] that [NAME_2] called."


def test_reply_restores_the_senders_own_values_only_when_opted_in(client, db_session):
    _check(client, "Hello, my name is Alex Morgan.", restore=True)
    reply = _check(client, "Hello, [NAME_1]! How can I help?", direction="outbound", restore=True)
    assert reply["cleaned_text"] == "Hello, Alex Morgan! How can I help?"
    assert reply["model_text"] == "Hello, [NAME_1]! How can I help?"
    from shared.models import Receipt
    stored = [r.payload["text"] for r in db_session.query(Receipt).all()]
    assert all("Alex Morgan" not in t for t in stored)  # the ledger never holds the value


def test_no_restore_without_opt_in_or_for_another_user(client):
    _check(client, "I am Alex Morgan.")  # not opted in -> context origin
    assert _check(client, "Hi [NAME_1]", direction="outbound", restore=True)["cleaned_text"] == "Hi [NAME_1]"
    _check(client, "I am Priya Raman.", restore=True, session="sess_two")
    other = _check(client, "Hi [NAME_1]", direction="outbound", restore=True, session="sess_two", user="mallory")
    assert other["cleaned_text"] == "Hi [NAME_1]"


def test_tool_results_are_never_restored_to_the_sender(client):
    _check(client, "Row: Margaret Whitfield, (614) 555-0192", direction="outbound", scored=False, restore=True)
    reply = _check(client, "The patient is [NAME_1] at [PHONE_1].", direction="outbound", restore=True)
    assert reply["cleaned_text"] == "The patient is [NAME_1] at [PHONE_1]."


def test_partial_and_masked_styles(client):
    client.put("/admin/identifier-policy/hipaa/phone_number", json={"style": "partial", "keep_last": 4})
    client.put("/admin/identifier-policy/hipaa/email_address", json={"style": "masked"})
    r = _check(client, "Phone (555) 201-7788, email alex@example.com")
    assert r["cleaned_text"] == "Phone (•••) •••-7788, email [REDACTED_EMAIL]"
    assert redaction.partial("email_address", "alex.morgan@example.com", 4) == "a••••••••••@example.com"


def test_applies_to_limits_the_direction(client):
    client.put("/admin/identifier-policy/hipaa/phone_number", json={"applies_to": "inbound"})
    out = _check(client, "Call (555) 201-7788", direction="outbound")
    assert out["cleaned_text"] == "Call (555) 201-7788" and out["verdict"] == "log_only"
    assert _check(client, "Call (555) 201-7788")["cleaned_text"] == "Call [PHONE_1]"


def test_identifier_policy_endpoint_round_trip(client):
    client.put("/admin/compliance-pack/hipaa/phone_number", json={"action": "redact"})
    rows = client.put("/admin/identifier-policy/hipaa/phone_number", json={"style": "partial", "keep_last": 2, "restore_to_sender": False}).json()
    phone = next(r for r in rows if r["identifier"] == "phone_number")
    assert (phone["style"], phone["keep_last"], phone["restore_to_sender"], phone["placeholder"]) == ("partial", 2, False, "[PHONE_1]")
    assert client.put("/admin/identifier-policy/hipaa/phone_number", json={"keep_last": 40}).status_code == 400


def test_role_caps_what_is_revealed_and_needs_the_explicit_ask(client):
    assert {r["role_id"] for r in client.get("/admin/roles").json()} >= {"clinician", "auditor"}
    client.put("/admin/user-roles/dr_lee", json={"role_id": "clinician"})
    text = "Patient Margaret Whitfield, phone (614) 555-0192."
    without_ask = _check(client, text, direction="outbound", user="dr_lee")
    assert without_ask["cleaned_text"] == "Patient [NAME_1], phone [PHONE_1]."
    with_ask = _check(client, text, direction="outbound", user="dr_lee", ask=True)
    assert with_ask["cleaned_text"] == "Patient Margaret Whitfield, phone (•••) •••-0192."
    assert with_ask["model_text"] == "Patient [NAME_1], phone [PHONE_1]."  # the model side never changes


def test_auditor_role_reveals_nothing_even_when_asking(client):
    client.put("/admin/user-roles/aud", json={"role_id": "auditor"})
    r = _check(client, "Patient Margaret Whitfield", direction="outbound", user="aud", ask=True)
    assert r["cleaned_text"] == "Patient [NAME_1]"


def test_no_role_relaxes_block_or_hash(client):
    client.put("/admin/compliance-pack/hipaa/ssn_like", json={"action": "block"})
    client.put("/admin/compliance-pack/hipaa/medical_record_number", json={"action": "hash"})
    client.put("/admin/roles/everything", json={"label": "Everything", "default_level": "full"})
    client.put("/admin/user-roles/boss", json={"role_id": "everything"})
    assert _check(client, "SSN 123-45-6789", direction="outbound", user="boss", ask=True)["verdict"] == "block"
    hashed = _check(client, "Record MRN 00481923", direction="outbound", user="boss", ask=True)
    assert "[HASH:" in hashed["cleaned_text"] and "00481923" not in hashed["cleaned_text"]


def test_unknown_role_assignment_is_rejected_and_roles_validate_levels(client):
    assert client.put("/admin/user-roles/x", json={"role_id": "nope"}).status_code == 404
    assert client.put("/admin/roles/bad", json={"label": "Bad", "visibility": {"full_name": "everything"}}).status_code == 400


def test_reset_clears_placeholder_mappings(client):
    _check(client, "I am Alex Morgan.", restore=True)
    client.post("/admin/reset", json={"confirm": "RESET"})
    assert _check(client, "Hi [NAME_1]", direction="outbound", restore=True)["cleaned_text"] == "Hi [NAME_1]"
