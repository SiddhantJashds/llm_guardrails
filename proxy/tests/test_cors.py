"""The dashboard chat drawer calls the proxy from the browser: only the
dashboard's origins and the identity/pack headers may pass the preflight."""

ALLOWED = "content-type,x-user-id,x-session-id,x-agent-id,x-compliance-pack"


def _preflight(client, origin, headers=ALLOWED):
    return client.options(
        "/v1/chat/completions",
        headers={"Origin": origin, "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": headers},
    )


def test_dashboard_origin_preflight_allowed(proxy_client):
    resp = _preflight(proxy_client, "http://localhost:8081")
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:8081"


def test_foreign_origin_preflight_refused(proxy_client):
    resp = _preflight(proxy_client, "http://evil.test")
    assert "access-control-allow-origin" not in resp.headers


def test_unredacted_header_not_allowed_from_browser(proxy_client):
    resp = _preflight(proxy_client, "http://localhost:8081", headers="content-type,x-request-unredacted")
    assert resp.status_code == 400
