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


def test_view_headers_allowed_but_unknown_headers_refused(proxy_client):
    # docs/adr/0016: x-request-unredacted / x-restore-to-sender may come from the
    # dashboard; what they reveal is capped server-side by the user's role.
    ok = _preflight(proxy_client, "http://localhost:8081", headers="content-type,x-request-unredacted,x-restore-to-sender")
    assert ok.status_code == 200
    assert _preflight(proxy_client, "http://localhost:8081", headers="content-type,x-something-else").status_code == 400
