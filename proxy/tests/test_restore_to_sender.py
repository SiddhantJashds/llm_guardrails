"""docs/adr/0016 through the proxy: the model only ever sees placeholders;
with x-restore-to-sender the user gets their own values back in the reply."""


def _ask(client, content, reply, headers):
    client.upstream_reply["content"] = reply
    return client.post(
        "/v1/chat/completions",
        json={"model": "m", "messages": [{"role": "system", "content": "Be brief."}, {"role": "user", "content": content}]},
        headers={"x-user-id": "alex", "x-session-id": "sess_restore", **headers},
    )


def test_model_sees_placeholder_and_user_gets_own_name_back(proxy_client):
    from compliance import vault

    vault.clear()
    resp = _ask(proxy_client, "Hello, my name is Alex Morgan.", "Hello, [NAME_1]!", {"x-restore-to-sender": "true"})
    sent = proxy_client.upstream_requests[-1]["messages"][-1]["content"]
    assert sent == "Hello, my name is [NAME_1]."
    assert resp.json()["choices"][0]["message"]["content"] == "Hello, Alex Morgan!"


def test_without_the_header_the_reply_keeps_placeholders(proxy_client):
    from compliance import vault

    vault.clear()
    resp = _ask(proxy_client, "Hello, my name is Alex Morgan.", "Hello, [NAME_1]!", {})
    assert resp.json()["choices"][0]["message"]["content"] == "Hello, [NAME_1]!"
