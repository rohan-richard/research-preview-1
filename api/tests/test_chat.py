import json

from tests.test_me import complete_onboarding


def test_token_needs_onboarding_then_consent(client, signed_in, fake_chat_server):
    headers = signed_in.headers
    first = client.get("/v1/chat/token", headers=headers)
    assert first.status_code == 409 and first.json()["error"]["code"] == "onboarding_required"

    complete_onboarding(client, headers)
    second = client.get("/v1/chat/token", headers=headers)
    assert second.status_code == 409
    assert second.json()["error"] == {"code": "consent_required", "message": "Allow the ai_chat consent first.", "scope": "ai_chat"}


def test_token_comes_from_the_chat_server_for_this_user(client, signed_in, fake_chat_server):
    headers = signed_in.headers
    complete_onboarding(client, headers)
    client.put("/v1/me/consents/ai_chat", json={"granted": True, "policy_version": "2026-09"}, headers=headers)
    reply = client.get("/v1/chat/token", headers=headers)
    assert reply.status_code == 200, reply.text
    assert reply.json() == {"access_token": "chat-jwt-1", "expires_in": 600, "socket_url": "ws://chat.test/chat/ws", "tenant": "rumi-chat"}

    paths = [call.url.path for call in fake_chat_server.calls]
    assert paths == ["/chat/onboardPerson", "/chat/generateToken"]
    sent = json.loads(fake_chat_server.calls[1].content)
    assert sent == {"api_key": "chat-test-key", "user_ref": signed_in.user["id"]}


def test_token_route_reports_a_chat_server_outage(client, signed_in, fake_chat_server):
    headers = signed_in.headers
    complete_onboarding(client, headers)
    client.put("/v1/me/consents/ai_chat", json={"granted": True, "policy_version": "2026-09"}, headers=headers)
    fake_chat_server.status = 500
    reply = client.get("/v1/chat/token", headers=headers)
    assert reply.status_code == 502 and reply.json()["error"]["code"] == "chat_server_unavailable"


def test_visit_prep_needs_its_own_tenant_key(client, signed_in, fake_chat_server, monkeypatch):
    headers = signed_in.headers
    complete_onboarding(client, headers)
    client.put("/v1/me/consents/ai_chat", json={"granted": True, "policy_version": "2026-09"}, headers=headers)
    assert client.get("/v1/chat/token?purpose=visit_prep", headers=headers).status_code == 503

    monkeypatch.setattr("app.chat.settings.chat_server_visit_prep_api_key", "visit-key")
    reply = client.get("/v1/chat/token?purpose=visit_prep", headers=headers)
    assert reply.status_code == 200 and reply.json()["tenant"] == "rumi-visit-prep"
    onboard = json.loads(fake_chat_server.calls[-2].content)
    assert onboard["api_key"] == "visit-key" and fake_chat_server.calls[-2].url.path == "/chat/onboardPerson"
    assert json.loads(fake_chat_server.calls[-1].content)["api_key"] == "visit-key"
