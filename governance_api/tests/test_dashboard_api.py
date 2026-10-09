import json
import sys
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # allow `import data_pipeline`

from authority.engine import AuthorityEngine
from data_pipeline.ingestion.token_usage_pipeline import ingest_event
from receipts.writer import write_receipt
from shared.models import Receipt


def _receipt(db, session_id="sess1", user_id="u1", agent_id="a1", parent=None, decision_type="compliance",
             verdict="allow", reason=None, ref_id="hipaa"):
    return write_receipt(db, user_id=user_id, session_id=session_id, agent_id=agent_id, parent_agent_id=parent,
                         decision_type=decision_type, verdict=verdict, reason=reason, ref_id=ref_id)


def _seed_capped_session(db):
    engine = AuthorityEngine(db)
    engine.get_or_create("orch", "sess1", None)
    engine.apply_signal("orch", "sess1", "phi_in_output")  # 100 -> 80
    _receipt(db, agent_id="orch", verdict="redact", reason="full_name, email_address")
    engine.get_or_create("child", "sess1", "orch")  # capped start: 80
    engine.apply_signal("child", "sess1", "phi_in_output_low_confidence")
    _receipt(db, agent_id="child", parent="orch", verdict="redact", reason="full_name")


def test_timestamps_carry_utc_offset(client, db_session):
    _seed_capped_session(db_session)
    body = client.get("/dashboard/session/sess1").json()
    assert body["first_seen"].endswith("+00:00")
    assert all(item["timestamp"].endswith("+00:00") for item in body["timeline"])


def test_session_detail_orders_agents_by_delegation_and_recovers_capped_start(client, db_session):
    _seed_capped_session(db_session)
    agents = client.get("/dashboard/session/sess1").json()["agents"]
    assert [a["agent_id"] for a in agents] == ["orch", "child"]
    child = agents[1]
    assert child["depth"] == 1 and child["parent_agent_id"] == "orch"
    assert child["initial_score"] == 80.0
    assert child["trajectory"][-1]["score"] == child["current_score"]


def test_session_detail_reports_chain_ok_then_tampered(client, db_session):
    _seed_capped_session(db_session)
    assert client.get("/dashboard/session/sess1").json()["chain"]["ok"] is True
    row = db_session.query(Receipt).filter(Receipt.session_id == "sess1").first()
    row.reason = "nothing to see here"
    db_session.commit()
    chain = client.get("/dashboard/session/sess1").json()["chain"]
    assert chain["ok"] is False and chain["problem"] == "hash" and chain["broken_receipt_id"] == row.receipt_id


def test_session_detail_counts_tokens_per_agent(client, db_session):
    _seed_capped_session(db_session)
    ingest_event("u1", "sess1", "orch", tokens_in=100, tokens_out=40)
    ingest_event("u1", "sess1", "child", tokens_in=10, tokens_out=5)
    body = client.get("/dashboard/session/sess1").json()
    by_id = {a["agent_id"]: a for a in body["agents"]}
    assert (by_id["orch"]["tokens_in"], by_id["child"]["tokens_out"]) == (100, 5)
    assert (body["tokens_in"], body["tokens_out"]) == (110, 45)


def test_log_only_is_not_listed_as_a_violation(client, db_session):
    _receipt(db_session, verdict="log_only", reason="consent_purpose_flag")
    agent = client.get("/dashboard/session/sess1").json()["agents"][0]
    assert agent["violations"] == [] and agent["flags"] == 0


def test_user_profile_is_live_without_rollup(client, db_session):
    _receipt(db_session, user_id="dash_user", verdict="redact", reason="full_name")
    _receipt(db_session, user_id="dash_user")
    ingest_event("dash_user", "sess1", "a1", tokens_in=70, tokens_out=30)
    body = client.get("/dashboard/user/dash_user").json()
    assert body["profile"]["total_tokens_in"] == 70
    assert body["profile"]["violation_count"] == 1
    assert isinstance(body["profile"]["composite_rating"], float)
    assert body["outcomes"]["redact"] == 1
    assert body["sessions"][0]["session_id"] == "sess1"
    assert body["token_series"][0]["tokens_out"] == 30


def test_existing_session_and_user_fields_still_present(client, db_session):
    _seed_capped_session(db_session)
    session = client.get("/dashboard/session/sess1").json()
    assert {"agent_id", "current_score", "history", "violations", "denied_calls"} <= set(session["agents"][0])
    user = client.get("/dashboard/user/u1").json()
    assert {"total_tokens_in", "total_tokens_out", "composite_rating", "effective_use_score", "violation_count"} <= set(user["profile"])
    assert {"verdict", "decision_type", "timestamp", "reason"} <= set(user["recent_decisions"][0])


def test_user_and_session_ids_with_special_characters_round_trip(client, db_session):
    odd = "a b#c?d%e"
    _receipt(db_session, session_id=odd, user_id=odd)
    assert client.get("/dashboard/user/" + quote(odd, safe="")).json()["user_id"] == odd
    assert client.get("/dashboard/session/" + quote(odd, safe="")).json()["decisions"] == 1


def test_every_list_endpoint_is_well_formed_on_empty_db(client):
    overview = client.get("/dashboard/overview").json()
    assert overview["totals"]["decisions"] == 0 and overview["chain"]["sessions_checked"] == 0
    assert overview["activity"]["buckets"] == [] and overview["recent_sessions"] == []
    assert client.get("/dashboard/feed").json() == {"items": []}
    assert client.get("/dashboard/sessions").json() == {"items": [], "total": 0}
    assert client.get("/dashboard/users").json() == {"items": [], "total": 0}
    assert client.get("/dashboard/ledger").json()["total"] == 0
    assert client.get("/dashboard/session/nope").json()["agents"] == []


def test_overview_totals_identifiers_and_chain(client, db_session):
    _seed_capped_session(db_session)
    _receipt(db_session, session_id="sess2", user_id="u2", decision_type="authority", verdict="deny", ref_id="send_email")
    ingest_event("u2", "sess2", "a1", tokens_in=5, tokens_out=7)
    body = client.get("/dashboard/overview").json()
    t = body["totals"]
    assert (t["decisions"], t["redactions"], t["denials"], t["sessions"], t["users"], t["tokens_out"]) == (3, 2, 1, 2, 2, 7)
    assert body["identifiers"][0] == {"type": "full_name", "count": 2}
    assert body["chain"] == {"sessions_checked": 2, "sessions_ok": 2, "broken": []}
    assert body["recent_sessions"][0]["session_id"] == "sess2"


def test_feed_is_newest_first_and_capped(client, db_session):
    for i in range(5):
        _receipt(db_session, ref_id=f"r{i}")
    items = client.get("/dashboard/feed?limit=3").json()["items"]
    assert [i["ref_id"] for i in items] == ["r4", "r3", "r2"]


def test_sessions_filters_by_q_user_and_flagged(client, db_session):
    _seed_capped_session(db_session)
    _receipt(db_session, session_id="quiet", user_id="bob")
    assert client.get("/dashboard/sessions").json()["total"] == 2
    assert [s["session_id"] for s in client.get("/dashboard/sessions?flagged=true").json()["items"]] == ["sess1"]
    assert [s["session_id"] for s in client.get("/dashboard/sessions?user_id=bob").json()["items"]] == ["quiet"]
    assert [s["session_id"] for s in client.get("/dashboard/sessions?q=CHILD").json()["items"]] == ["sess1"]


def test_users_list_has_live_rating(client, db_session):
    _receipt(db_session, user_id="u1", verdict="redact", reason="full_name")
    _receipt(db_session, user_id="u1")
    items = client.get("/dashboard/users").json()["items"]
    assert items[0]["user_id"] == "u1" and items[0]["redactions"] == 1
    assert 0.0 < items[0]["composite_rating"] < 100.0


def test_ledger_filters_and_paginates(client, db_session):
    for i in range(7):
        _receipt(db_session, ref_id=f"r{i}", verdict="redact" if i % 2 else "allow", reason="full_name" if i % 2 else None)
    page1 = client.get("/dashboard/ledger?limit=4").json()
    page2 = client.get("/dashboard/ledger?limit=4&offset=4").json()
    assert page1["total"] == page2["total"] == 7
    assert not {i["receipt_id"] for i in page1["items"]} & {i["receipt_id"] for i in page2["items"]}
    assert client.get("/dashboard/ledger?verdict=redact").json()["total"] == 3
    assert client.get("/dashboard/ledger?q=full_name").json()["total"] == 3


def _report(started_at, status="PASS"):
    return {
        "started_at": started_at, "duration_s": 1.0, "edition": "sample", "users": {"alice": "alice-1"},
        "base_url": "x", "governance_url": "http://localhost:8080", "governance_reachable_at_start": True,
        "scenarios_run": [1], "totals": {"PASS": 1, "FAIL": 0, "SKIP": 0}, "per_user_summary": {},
        "scenarios": [{"number": 1, "name": "Normal workflow", "user": "alice-1", "role": "alice", "status": status,
                       "reason": "ok", "duration_s": 1.0, "requests": [], "session_ids": ["s-1"],
                       "hook_log": [{"hook": "a"}, {"hook": "b"}], "checks": []}],
    }


def test_bench_runs_list_detail_and_hook_events(client, tmp_path, monkeypatch):
    monkeypatch.setenv("BENCH_REPORTS_DIR", str(tmp_path))
    (tmp_path / "old.json").write_text(json.dumps(_report("2026-10-09T07:00:00+00:00")))
    (tmp_path / "new.json").write_text(json.dumps(_report("2026-10-09T09:00:00+00:00", "FAIL")))
    (tmp_path / "broken.json").write_text("{not json")
    runs = client.get("/dashboard/bench/runs").json()
    assert runs["available"] is True and [r["name"] for r in runs["items"]] == ["new.json", "old.json"]
    detail = client.get("/dashboard/bench/runs/new.json").json()
    assert detail["scenarios"][0]["hook_events"] == 2 and "hook_log" not in detail["scenarios"][0]


def test_bench_run_rejects_traversal_and_bad_names(client, tmp_path, monkeypatch):
    monkeypatch.setenv("BENCH_REPORTS_DIR", str(tmp_path / "reports"))
    (tmp_path / "reports").mkdir()
    (tmp_path / "secret.json").write_text("{}")
    for name in ("..%2Fsecret.json", "x.txt", "a%20b.json", "nope.json"):
        assert client.get(f"/dashboard/bench/runs/{name}").status_code == 404


def test_bench_missing_dir_is_unavailable_not_error(client, tmp_path, monkeypatch):
    monkeypatch.setenv("BENCH_REPORTS_DIR", str(tmp_path / "missing"))
    assert client.get("/dashboard/bench/runs").json() == {"available": False, "dir": str(tmp_path / "missing"), "items": []}


def test_config_reports_proxy_url_from_env(client, monkeypatch):
    monkeypatch.setenv("PROXY_PUBLIC_URL", "http://localhost:8002")
    assert client.get("/dashboard/config").json()["proxy_url"] == "http://localhost:8002"


def test_bench_matrix_status_and_scenario_hooks(client, tmp_path, monkeypatch):
    monkeypatch.setenv("BENCH_REPORTS_DIR", str(tmp_path))
    (tmp_path / "run.json").write_text(json.dumps(_report("2026-10-09T09:00:00+00:00", "FAIL")))
    item = client.get("/dashboard/bench/runs").json()["items"][0]
    assert item["scenario_status"] == [{"number": 1, "name": "Normal workflow", "status": "FAIL"}]
    assert client.get("/dashboard/bench/runs/run.json/scenarios/0/hooks").json() == {"items": [{"hook": "a"}, {"hook": "b"}]}
    assert client.get("/dashboard/bench/runs/run.json/scenarios/5/hooks").status_code == 404


def _check(client, text, direction="inbound", user_id="u1", session_id="sess_c", agent_id="a1", apply_score=True):
    return client.post("/governance/compliance-check", json={
        "identity": {"user_id": user_id, "session_id": session_id, "agent_id": agent_id, "parent_agent_id": None},
        "direction": direction, "text": text, "pack_id": "hipaa", "apply_score": apply_score,
    }).json()


def test_conversation_stores_only_redacted_text_and_dedupes_history(client):
    _check(client, "Call me at 555-123-4567")
    _check(client, "Sure, noted.", direction="outbound")
    _check(client, "Call me at 555-123-4567")  # memory-mode replay of the same history
    _check(client, "Row: phone 555-987-6543", direction="outbound", apply_score=False)
    body = client.get("/dashboard/session/sess_c").json()
    turns = body["conversation"]
    assert [t["kind"] for t in turns] == ["input", "output", "tool_result"]
    assert "555-123-4567" not in json.dumps(body) and "555-987-6543" not in json.dumps(body)
    assert "[REDACTED]" in turns[0]["text"]
    assert body["chain"]["ok"] is True  # payload is outside the hashed decision


def test_unredacted_override_still_stores_redacted_text(client):
    client.put("/admin/users/vip", json={"allow_unredacted": True})
    resp = client.post("/governance/compliance-check", json={
        "identity": {"user_id": "vip", "session_id": "sess_vip", "agent_id": "a1", "parent_agent_id": None},
        "direction": "outbound", "text": "Patient phone is 555-123-4567", "pack_id": "hipaa", "request_unredacted": True,
    }).json()
    assert "555-123-4567" in resp["cleaned_text"]  # caller got raw text back...
    stored = client.get("/dashboard/session/sess_vip").json()["conversation"][0]["text"]
    assert "555-123-4567" not in stored  # ...but the receipt never holds it


def test_reset_requires_confirmation_and_keeps_policy_settings(client, db_session):
    _seed_capped_session(db_session)
    ingest_event("u1", "sess1", "orch", tokens_in=1, tokens_out=1)
    client.put("/admin/tool-thresholds/send_email", json={"threshold": 80})
    assert client.post("/admin/reset", json={"confirm": "yes"}).status_code == 400
    assert client.get("/dashboard/overview").json()["totals"]["decisions"] == 2
    deleted = client.post("/admin/reset", json={"confirm": "RESET"}).json()["deleted"]
    assert deleted["receipts"] == 2 and deleted["agent_trust_state"] == 2 and deleted["token_usage_events"] == 1
    totals = client.get("/dashboard/overview").json()["totals"]
    assert (totals["decisions"], totals["sessions"], totals["tokens_in"]) == (0, 0, 0)
    assert {t["tool_id"]: t["threshold"] for t in client.get("/admin/tool-thresholds").json()}["send_email"] == 80


def test_playground_rejects_unknown_app_and_reports_unreachable_bench(client, monkeypatch):
    import httpx
    from routes import playground

    monkeypatch.setenv("BENCH_APP_URL", "http://127.0.0.1:9")
    assert client.post("/playground/bench/nope", json={"user_id": "u", "message": "hi"}).status_code == 404
    resp = client.post("/playground/bench/rag", json={"user_id": "u", "message": "hi"})
    assert resp.status_code == 502 and "not reachable" in resp.json()["detail"]
    assert client.get("/playground/bench/health").json()["available"] is False

    sent = {}

    def fake_post(url, json, timeout):
        sent.update(url=url, json=json)
        return httpx.Response(200, json={"answer": "ok", "session_id": "s-1", "retrieved_sources": []})

    monkeypatch.setattr(playground.httpx, "post", fake_post)
    body = client.post("/playground/bench/rag", json={"user_id": "alice", "message": "Who is Margaret?"}).json()
    assert body["session_id"] == "s-1"
    assert sent == {"url": "http://127.0.0.1:9/ask", "json": {"user_id": "alice", "question": "Who is Margaret?"}}
