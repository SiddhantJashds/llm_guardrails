"""Route-level tests -- these catch the class of bug that unit tests miss:
one role's change to a shared signature (e.g. `required_threshold(db, tool_id)`)
breaking another role's call site. Run these before merging anything that
touches shared/, authority/, compliance/, or access_control/.
"""
import pytest

import compliance.engine as compliance_engine
from tests.conftest import make_identity


def test_tool_check_allows_a_fresh_agent(client):
    resp = client.post("/governance/tool-check", json={"identity": make_identity(), "tool_id": "sql_query_tool"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["allowed"] is True
    assert body["current_score"] == 100.0
    # Tests run against a fresh, unseeded DB (scripts/init_db.py's YAML seeding
    # doesn't run here) -- this is authority/policy_gates.py's DEFAULT_THRESHOLD
    # fallback, not the data_pipeline/config/tool_thresholds.yaml value.
    assert body["required_threshold"] == 60.0
    assert body["receipt_id"]


def test_tool_check_denies_once_score_drops_below_threshold(client, db_session):
    from authority.engine import AuthorityEngine

    identity = make_identity(agent_id="repeat_offender")
    engine = AuthorityEngine(db_session)
    engine.get_or_create(identity["agent_id"], identity["session_id"], None)
    engine.apply_signal(identity["agent_id"], "phi_in_output")  # 100 -> 80
    engine.apply_signal(identity["agent_id"], "phi_in_output")  # 80 -> 60
    engine.apply_signal(identity["agent_id"], "phi_in_output")  # 60 -> 40 (below the 60 default threshold)

    resp = client.post("/governance/tool-check", json={"identity": identity, "tool_id": "sql_query_tool"})
    body = resp.json()
    assert body["allowed"] is False
    assert "below required" in body["reason"]


def test_admin_updated_threshold_takes_effect_on_next_tool_check(client):
    client.put("/admin/tool-thresholds/sql_query_tool", json={"threshold": 10.0})
    resp = client.post(
        "/governance/tool-check", json={"identity": make_identity(agent_id="new_agent"), "tool_id": "sql_query_tool"}
    )
    assert resp.json()["required_threshold"] == 10.0


def test_admin_pack_action_change_is_reflected_in_get(client):
    client.put("/admin/compliance-pack/hipaa/phone_number", json={"action": "block"})
    resp = client.get("/admin/compliance-pack/hipaa")
    rows = {r["identifier"]: r["action"] for r in resp.json()}
    assert rows["phone_number"] == "block"


def test_admin_pack_action_rejects_a_made_up_action(client):
    resp = client.put("/admin/compliance-pack/hipaa/phone_number", json={"action": "silently_ignore"})
    assert resp.status_code == 422


def test_cors_allows_the_dashboards_cross_origin_fetch(client):
    # The dashboard is served from a different port than governance_api and
    # fetches it directly from the browser -- without CORS enabled this is
    # silently blocked by the browser (curl/TestClient alone won't catch it).
    resp = client.get("/dashboard/session/sess1", headers={"Origin": "http://localhost:8080"})
    assert resp.headers.get("access-control-allow-origin") == "*"


def test_admin_user_override_default_is_restrictive(client):
    resp = client.get("/admin/users/brand_new_user")
    assert resp.json() == {"user_id": "brand_new_user", "allow_unredacted": False, "tool_overrides": None}


def test_admin_grant_then_list_shows_it(client):
    client.put("/admin/users/u1", json={"allow_unredacted": True})
    resp = client.get("/admin/users")
    users = {u["user_id"]: u["allow_unredacted"] for u in resp.json()}
    assert users["u1"] is True


def test_dashboard_session_attributes_denied_call_to_the_right_agent(client, db_session):
    from authority.engine import AuthorityEngine

    identity = make_identity(agent_id="offender", session_id="sess_dashboard_test")
    engine = AuthorityEngine(db_session)
    engine.get_or_create(identity["agent_id"], identity["session_id"], None)
    for _ in range(3):
        engine.apply_signal(identity["agent_id"], "phi_in_output")  # 100 -> 40, below the 60 default threshold

    client.post("/governance/tool-check", json={"identity": identity, "tool_id": "sql_query_tool"})

    resp = client.get("/dashboard/session/sess_dashboard_test")
    agents = {a["agent_id"]: a for a in resp.json()["agents"]}
    assert len(agents["offender"]["denied_calls"]) == 1


def test_dashboard_user_view_reflects_written_receipts(client):
    identity = make_identity(user_id="dash_user")
    client.post("/governance/tool-check", json={"identity": identity, "tool_id": "sql_query_tool"})

    resp = client.get("/dashboard/user/dash_user")
    body = resp.json()
    assert body["user_id"] == "dash_user"
    assert len(body["recent_decisions"]) == 1


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Detectors aren't wired into compliance/engine.py yet (see its "
        "_run_detectors TODO and docs/MOCKED_VS_PRODUCTION.md). This SHOULD "
        "start passing once the Data Scientist wires detectors.hipaa.identifiers "
        "in -- when it does, remove this xfail marker and check the item off "
        "in docs/PROGRESS.md (Data Scientist, Day 1, item 4)."
    ),
)
def test_compliance_check_actually_catches_phi_once_detectors_are_wired(client):
    resp = client.post(
        "/governance/compliance-check",
        json={
            "identity": make_identity(),
            "direction": "outbound",
            "text": "Patient phone is 555-123-4567",
            "pack_id": "hipaa",
        },
    )
    body = resp.json()
    assert body["verdict"] != "allow"
    assert "555-123-4567" not in body["cleaned_text"]
