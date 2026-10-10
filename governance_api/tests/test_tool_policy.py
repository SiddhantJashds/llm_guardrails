"""Combined HIPAA+DPDP scanning and the tool-call policy gates
(authority/tool_policy.py): scope, human approval, external recipients,
consent, and blocked identifiers in arguments -- plus the allowed controls."""
import pytest


@pytest.fixture
def seeded(client):
    for pack, ident, action in [("hipaa", "ssn_like", "block"), ("dpdp", "aadhaar_like", "block"), ("dpdp", "pan_like", "hash")]:
        client.put(f"/admin/compliance-pack/{pack}/{ident}", json={"action": action})
    client.put("/admin/tool-thresholds/delete_file", json={"threshold": 101})
    client.put("/admin/tool-thresholds/send_email", json={"threshold": 80})
    client.put("/admin/tool-thresholds/schedule_appointment", json={"threshold": 60})
    return client


def _tool(client, tool, args=None, declared=None, agent="a1", session="sess_tp"):
    body = {"identity": {"user_id": "u", "session_id": session, "agent_id": agent, "parent_agent_id": None}, "tool_id": tool}
    if args is not None:
        body["tool_args"] = args
    if declared is not None:
        body["declared_tools"] = declared
    return client.post("/governance/tool-check", json=body).json()


def _scan(client, text, direction="inbound", scored=True, pack="hipaa+dpdp"):
    return client.post("/governance/compliance-check", json={
        "identity": {"user_id": "u", "session_id": "sess_scan", "agent_id": "a1", "parent_agent_id": None},
        "text": text, "direction": direction, "pack_id": pack, "apply_score": scored,
    }).json()


def test_combined_pack_catches_hipaa_and_dpdp_in_one_text(seeded):
    r = _scan(seeded, "Card 4111 1111 1111 1111, PAN ABCDE1234F, UPI arjun.d@examplepay")
    assert r["verdict"] in ("redact", "hash")
    for raw in ("4111 1111 1111 1111", "ABCDE1234F", "arjun.d@examplepay"):
        assert raw not in r["cleaned_text"]
    assert _scan(seeded, "SSN 123-45-6789 and Aadhaar 9123 4567 8901")["verdict"] == "block"


def test_tool_results_mask_instead_of_block(seeded):
    r = _scan(seeded, "Record: SSN 123-45-6789, Aadhaar 9123 4567 8901, phone (555) 201-7788", direction="outbound", scored=False)
    assert r["verdict"] == "redact"
    assert "123-45-6789" not in r["cleaned_text"] and "9123 4567 8901" not in r["cleaned_text"]


def test_undeclared_tool_is_denied_with_a_receipt(seeded):
    r = _tool(seeded, "delete_file", {"filename": "x.csv"}, declared=["read_database"])
    assert r["allowed"] is False and "declared tools" in r["reason"] and r["receipt_id"]


def test_destructive_tool_needs_human_approval_even_at_full_trust(seeded):
    r = _tool(seeded, "delete_file", {"filename": "audit_log_2025.csv"}, declared=["delete_file"])
    assert r["allowed"] is False and "human approval" in r["reason"]


def test_email_outside_allowed_domains_is_denied(seeded):
    for to in ("drsmith@gmail.com", "partner@clinic-abroad.example.co.uk"):
        r = _tool(seeded, "send_email", {"to": to, "body": "Diagnosis attached."})
        assert r["allowed"] is False and "outside the allowed domains" in r["reason"], to


def test_email_to_allowed_domain_and_appointment_are_allowed(seeded):
    assert _tool(seeded, "send_email", {"to": "margaret.whitfield@example.com", "body": "Reminder: appointment on Friday."})["allowed"] is True
    # Exact domain match: a subdomain or look-alike is external.
    assert _tool(seeded, "send_email", {"to": "nurse@mail.example.com", "body": "Shift update."})["allowed"] is False
    assert _tool(seeded, "schedule_appointment", {"mrn": "MRN-000900130", "date": "2026-11-02"})["allowed"] is True


def test_consent_withdrawn_blocks_contact_by_email_or_name(seeded):
    seeded.put("/admin/consent/priya.patel@example.com", json={"status": "WITHDRAWN", "label": "Priya Patel"})
    seeded.put("/admin/consent/Ananya Rao", json={"status": "EXPIRED", "label": "Ananya Rao"})
    r = _tool(seeded, "send_email", {"to": "priya.patel@example.com", "body": "Reminder"})
    assert r["allowed"] is False and "consent withdrawn" in r["reason"]
    r = _tool(seeded, "schedule_appointment", {"mrn": "MRN-000900126", "date": "2026-11-02", "note": "for Ananya Rao"})
    assert r["allowed"] is False and "consent expired" in r["reason"]
    # Reads stay allowed: staff must be able to look a person up (e.g. to process erasure).
    assert _tool(seeded, "read_database", {"query": "Ananya Rao"})["allowed"] is True
    # A placeholder recipient is resolved from the session vault before the check.
    _scan(seeded, "email priya.patel@example.com", pack="hipaa+dpdp")
    r = _tool(seeded, "send_email", {"to": "[EMAIL_1]", "body": "Reminder"}, session="sess_scan")
    assert r["allowed"] is False and "consent withdrawn" in r["reason"]
    assert {c["subject"] for c in seeded.get("/admin/consent").json()} == {"priya.patel@example.com", "ananya rao"}


def test_blocked_identifiers_cannot_travel_in_tool_arguments(seeded):
    r = _tool(seeded, "send_email", {"to": "billing@example.com", "body": "Patient SSN 123-45-6789"})
    assert r["allowed"] is False and "ssn_like" in r["reason"]


def test_user_typed_lookup_keys_reach_the_model_but_other_identifiers_do_not(seeded):
    ident = {"user_id": "u", "session_id": "sess_keys", "agent_id": "orchestrator", "parent_agent_id": None}
    def check(text, agent="orchestrator", **kw):
        body = {"identity": {**ident, "agent_id": agent}, "text": text, "direction": "inbound", "pack_id": "hipaa+dpdp", "pass_sender_keys": True, **kw}
        return seeded.post("/governance/compliance-check", json=body).json()["cleaned_text"]

    first = check("Look up Priya Patel's record, email priya.patel@example.com, MRN-000900124, SSN-free. Card 4111 1111 1111 1111", restore_to_sender=True)
    assert "Priya Patel" in first and "priya.patel@example.com" in first and "MRN-000900124" in first
    assert "4111 1111 1111 1111" not in first
    later = check("Find the patient Priya Patel and also Margaret Whitfield (MRN-000481923).", agent="data_agent")
    assert "Priya Patel" in later
    assert "Margaret Whitfield" not in later and "MRN-000481923" not in later  # not typed by this user
    other_user = seeded.post("/governance/compliance-check", json={
        "identity": {**ident, "user_id": "someone_else"}, "text": "Priya Patel", "direction": "inbound",
        "pack_id": "hipaa+dpdp", "pass_sender_keys": True}).json()["cleaned_text"]
    assert "Priya Patel" not in other_user


def test_model_echoing_the_users_own_name_is_masked_but_not_penalised(seeded):
    ident = {"user_id": "u", "session_id": "sess_echo", "agent_id": "orchestrator", "parent_agent_id": None}
    seeded.post("/governance/compliance-check", json={"identity": ident, "text": "Find Margaret Whitfield and email margaret@example.com",
                                                      "direction": "inbound", "pack_id": "hipaa+dpdp", "pass_sender_keys": True, "restore_to_sender": True})
    for _ in range(4):
        r = seeded.post("/governance/compliance-check", json={"identity": ident, "text": "Dear Margaret Whitfield, see you on Friday.",
                                                              "direction": "outbound", "pack_id": "hipaa+dpdp"}).json()
        assert "Margaret Whitfield" not in r["cleaned_text"]
    assert _tool(seeded, "send_email", {"to": "margaret@example.com", "body": "Reminder"}, agent="orchestrator", session="sess_echo")["allowed"] is True
