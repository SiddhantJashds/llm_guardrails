"""SWE#1 Day1 #2: the proxy writes redacted text back into what it forwards
and returns, not just computes it (MOCKED_VS_PRODUCTION.md "Proxy payload rewriting")."""
SSN = "123-45-6789"


def _post(client, messages):
    return client.post("/v1/chat/completions", json={"model": "m", "messages": messages}, headers={"x-user-id": "u1"})


def test_inbound_phi_is_redacted_before_reaching_upstream(proxy_client):
    _post(proxy_client, [{"role": "user", "content": f"My SSN is {SSN}"}])
    forwarded = proxy_client.upstream_requests[0]["messages"][0]["content"]
    assert SSN not in forwarded


def test_inbound_phi_in_earlier_message_is_redacted_and_roles_preserved(proxy_client):
    _post(proxy_client, [
        {"role": "user", "content": f"SSN {SSN}"},
        {"role": "assistant", "content": "noted"},
        {"role": "user", "content": "thanks"},
    ])
    forwarded = proxy_client.upstream_requests[0]["messages"]
    assert [m["role"] for m in forwarded] == ["user", "assistant", "user"]
    assert SSN not in forwarded[0]["content"]
    assert forwarded[1]["content"] == "noted" and forwarded[2]["content"] == "thanks"


def test_outbound_phi_is_redacted_in_returned_completion(proxy_client):
    proxy_client.upstream_reply["content"] = f"Patient SSN is {SSN}"
    resp = _post(proxy_client, [{"role": "user", "content": "hello"}])
    assert SSN not in resp.json()["choices"][0]["message"]["content"]


def test_clean_traffic_passes_through_unchanged(proxy_client):
    proxy_client.upstream_reply["content"] = "all good"
    resp = _post(proxy_client, [{"role": "user", "content": "hello"}])
    assert proxy_client.upstream_requests[0]["messages"][0]["content"] == "hello"
    assert resp.json()["choices"][0]["message"]["content"] == "all good"


def test_inbound_phi_in_text_parts_content_is_redacted(proxy_client):
    _post(proxy_client, [{"role": "user", "content": [{"type": "text", "text": f"SSN {SSN}"}, {"type": "image_url", "image_url": {"url": "http://x/y.png"}}]}])
    parts = proxy_client.upstream_requests[0]["messages"][0]["content"]
    assert SSN not in parts[0]["text"]
    assert parts[1] == {"type": "image_url", "image_url": {"url": "http://x/y.png"}}


def test_every_completion_choice_is_checked_not_just_the_first(proxy_client, monkeypatch):
    import httpx
    from fastapi.testclient import TestClient  # noqa: F401

    def two_choices(request):
        return httpx.Response(200, json={"choices": [
            {"index": 0, "message": {"role": "assistant", "content": "fine"}},
            {"index": 1, "message": {"role": "assistant", "content": f"SSN {SSN}"}},
        ]})

    proxy_client.set_upstream(two_choices)
    resp = _post(proxy_client, [{"role": "user", "content": "hello"}])
    contents = [c["message"]["content"] for c in resp.json()["choices"]]
    assert contents[0] == "fine"
    assert SSN not in contents[1]


def _tool_call(args):
    return {"id": "c1", "type": "function", "function": {"name": "lookup_patient", "arguments": args}}


def test_outbound_tool_call_arguments_are_redacted_and_stay_valid_json(proxy_client):
    import json
    import httpx

    def tool_call_reply(request):
        return httpx.Response(200, json={"choices": [{"index": 0, "message": {
            "role": "assistant", "content": None, "tool_calls": [_tool_call(json.dumps({"query": f"SSN {SSN}"}))]}}]})

    proxy_client.set_upstream(tool_call_reply)
    resp = _post(proxy_client, [{"role": "user", "content": "hello"}])
    msg = resp.json()["choices"][0]["message"]
    assert msg["content"] is None
    args = msg["tool_calls"][0]["function"]["arguments"]
    assert SSN not in args
    assert "query" in json.loads(args)


def test_inbound_history_tool_call_arguments_are_redacted(proxy_client):
    import json
    _post(proxy_client, [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": None, "tool_calls": [_tool_call(json.dumps({"query": f"SSN {SSN}"}))]},
    ])
    forwarded = proxy_client.upstream_requests[0]["messages"][1]
    assert SSN not in forwarded["tool_calls"][0]["function"]["arguments"]
    assert forwarded["content"] is None


def test_request_with_no_checkable_text_is_not_blocked(proxy_client):
    resp = _post(proxy_client, [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": "http://x/y.png"}}]}])
    assert resp.status_code == 200


def test_completion_with_null_content_and_no_tool_calls_is_not_blocked(proxy_client):
    import httpx
    proxy_client.set_upstream(lambda r: httpx.Response(200, json={"choices": [{"index": 0, "message": {"role": "assistant", "content": None}}]}))
    resp = _post(proxy_client, [{"role": "user", "content": "hello"}])
    assert resp.status_code == 200


def test_name_split_across_two_messages_does_not_cause_a_false_block(proxy_client):
    resp = _post(proxy_client, [{"role": "user", "content": "Patient is John"}, {"role": "user", "content": "Smith was admitted"}])
    assert resp.status_code == 200


def test_user_typing_a_separator_like_string_does_not_block_their_own_request(proxy_client):
    resp = _post(proxy_client, [{"role": "user", "content": "a\n\x1e\nb"}, {"role": "user", "content": "c"}])
    assert resp.status_code == 200


def test_upstream_error_status_is_passed_through_not_returned_as_200(proxy_client):
    import httpx
    proxy_client.set_upstream(lambda r: httpx.Response(429, json={"error": {"message": "rate limited"}}))
    resp = _post(proxy_client, [{"role": "user", "content": "hello"}])
    assert resp.status_code == 429
