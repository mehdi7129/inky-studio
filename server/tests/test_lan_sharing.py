"""Transitive PHOTO invitations remain a LAN-only, media-only capability."""
from __future__ import annotations

from uuid import uuid4

import pytest

from inky_web import auth
from inky_web.photo_access import AccessError, PhotoAccessStore, Principal
from tests.test_lan_photo import bootstrap_invitation, rows
from tests.test_lan_photo import lan_store as source_lan_store
from tests.test_photo_access import claim, enroll_client, invitation, invited_client
from tests.test_photo_access import frame as source_frame

# Reuse the established stores and HTTPS application fixtures.
lan_store = source_lan_store
frame = source_frame


def first_media(value):
    initial = bootstrap_invitation()
    value.begin_lan_bootstrap(**initial)
    payload = claim(initial)
    return value.claim(**payload), payload


def test_lan_media_can_delegate_twice_without_creating_owner_or_reusing_secrets(lan_store):
    value, _ = lan_store
    first, first_payload = first_media(value)
    second_qr = invitation()
    value.invite(first, **second_qr)
    second_payload = claim(second_qr)
    second = value.claim(**second_payload)
    third_qr = invitation()
    value.invite(second, **third_qr)
    third_payload = claim(third_qr)
    third = value.claim(**third_payload)
    payloads = [first_payload, second_payload, third_payload]
    assert len({p["device_id"] for p in payloads}) == 3
    assert len({p["device_token"] for p in payloads}) == 3
    assert [row["role"] for row in rows(value, "devices")] == ["media"] * 3
    for actor, payload in zip([first, second, third], payloads, strict=True):
        assert value.authenticate(payload["device_id"], payload["device_token"]) == actor
        assert actor.role == "media" and value.can_invite(actor)
        assert payload["device_token"].encode() not in value.path.read_bytes()
        with pytest.raises(AccessError):
            value.devices(actor)
        with pytest.raises(AccessError):
            value.revoke_device(actor, first.device_id)
    with pytest.raises(AccessError):
        value.claim(**claim(second_qr))
    with pytest.raises(AccessError):
        value.begin_lan_bootstrap(**bootstrap_invitation())


@pytest.mark.parametrize("change", ["expired", "revoked", "issuer_revoked", "epoch", "restart"])
def test_lan_delegation_does_not_bypass_invitation_lifetime_or_issuer_authority(lan_store, change):
    value, clock = lan_store
    first, first_payload = first_media(value)
    invite = invitation()
    value.invite(first, **invite)
    if change == "expired":
        clock.wall += 300
        clock.mono += 300
    elif change == "revoked":
        value.revoke_invitation(first, invite["invitation_id"])
    elif change == "issuer_revoked":
        with value._transaction() as conn:
            conn.execute("UPDATE devices SET revoked=1 WHERE device_id=?", (first.device_id,))
    elif change == "epoch":
        clock.epoch = "b" * 64
    else:
        value = PhotoAccessStore(value.directory, lambda: clock.epoch, lan_bootstrap=True,
                                 clock=lambda: clock.wall, monotonic=lambda: clock.mono)
        assert value.authenticate(first_payload["device_id"], first_payload["device_token"]) == first
        assert value.can_invite(first)
        assert not value.lan_bootstrap_available()
        fresh = invitation()
        value.invite(first, **fresh)
        assert value.claim(**claim(fresh)).role == "media"
    with pytest.raises(AccessError):
        value.claim(**claim(invite))
    if change in {"issuer_revoked", "epoch"}:
        assert not value.can_invite(first)
        with pytest.raises(AccessError):
            value.invite(first, **invitation())


def test_lan_media_can_cancel_only_its_own_live_invitation(lan_store):
    value, _ = lan_store
    first, _ = first_media(value)
    second_qr = invitation()
    value.invite(first, **second_qr)
    second = value.claim(**claim(second_qr))
    first_draft, second_draft = invitation(), invitation()
    value.invite(first, **first_draft)
    value.invite(second, **second_draft)
    with pytest.raises(AccessError, match="forbidden"):
        value.revoke_invitation(first, second_draft["invitation_id"])
    assert value.claim(**claim(second_draft)).role == "media"
    value.revoke_invitation(first, first_draft["invitation_id"])
    value.revoke_invitation(first, first_draft["invitation_id"])
    # No live record exists for this UUID, including after a normal restart.
    value.revoke_invitation(first, str(uuid4()))
    with pytest.raises(AccessError):
        value.claim(**claim(first_draft))
    assert not value.can_invite(Principal(first.device_id, "owner", first.epoch))


@pytest.fixture
def lan_api(frame):
    client, app = frame
    previous = app.state.photo_access
    value = PhotoAccessStore(previous.directory, previous._epoch, gate=previous._gate,
                             lan_bootstrap=True)
    app.state.photo_access = value
    app.state.sessions.principal_validator = value.valid
    initial = bootstrap_invitation()
    value.begin_lan_bootstrap(**initial)
    payload = claim(initial)
    response = client.post("/api/auth/invitations/claim", json=payload)
    assert response.status_code == 200 and response.json()["can_invite"] is True
    return client, app, payload


def test_lan_api_delegates_to_another_media_and_that_device_can_share_again(lan_api):
    client, _, first_payload = lan_api
    for _ in range(2):
        invite = invitation()
        response = client.post("/api/auth/invitations", json=invite)
        assert response.status_code == 200 and response.json()["role"] == "media"
        assert invite["invitation_token"] not in response.text
        assert response.headers["cache-control"] == "no-store"
        client.cookies.clear()
        payload = claim(invite)
        response = client.post("/api/auth/invitations/claim", json=payload)
        assert response.status_code == 200
        assert response.json()["role"] == "media" and response.json()["can_invite"] is True
        assert "Secure" in response.headers["set-cookie"]
        assert payload["device_token"] not in response.text
        assert first_payload["device_token"] not in response.text
        assert client.post("/api/auth/device-session", json={
            key: payload[key] for key in ("device_id", "device_token")
        }).json()["can_invite"] is True


@pytest.mark.parametrize(("method", "path"), [
    ("POST", "/api/auth/password"), ("POST", "/api/auth/devices/enroll"),
    ("GET", "/api/auth/devices"), ("GET", "/api/auth/devices/example"),
    ("DELETE", "/api/auth/devices/example"), ("GET", "/api/auth/invitations"),
    ("GET", "/api/provisioning/capabilities"), ("POST", "/api/provisioning/adoption/window"),
    ("POST", "/api/provisioning/wifi/confirm"), ("POST", "/api/system/update"),
    ("GET", "/api/future-admin-route"), ("DELETE", "/api/auth/invitations/other/extra"),
])
def test_lan_delegation_never_grants_owner_or_future_routes(lan_api, method, path):
    client, _, _ = lan_api
    response = client.request(method, path, json={})
    assert response.status_code == 403
    assert response.headers["cache-control"] == "no-store"
    assert client.post("/api/settings", json={"saturation": 2}).status_code == 403


def test_lan_api_revocation_is_scoped_to_the_authenticated_issuer(lan_api):
    client, _, first_payload = lan_api
    first_cookie = client.cookies.get(auth.COOKIE_NAME)
    invite = invitation()
    assert client.post("/api/auth/invitations", json=invite).status_code == 200
    client.cookies.clear()
    second_payload = claim(invite)
    assert client.post("/api/auth/invitations/claim", json=second_payload).status_code == 200
    second_invite = invitation()
    assert client.post("/api/auth/invitations", json=second_invite).status_code == 200
    client.cookies.clear()
    client.cookies.set(auth.COOKIE_NAME, first_cookie)
    assert client.delete(f"/api/auth/invitations/{second_invite['invitation_id']}").status_code == 403
    own = invitation()
    assert client.post("/api/auth/invitations", json=own).status_code == 200
    assert client.delete(f"/api/auth/invitations/{own['invitation_id']}").status_code == 200
    assert client.delete(f"/api/auth/invitations/{uuid4()}").status_code == 200
    client.cookies.clear()
    assert client.post("/api/auth/invitations/claim", json=claim(own)).status_code == 401
    response = client.post("/api/auth/device-session", json={
        key: first_payload[key] for key in ("device_id", "device_token")
    })
    assert response.status_code == 200 and response.json()["can_invite"] is True


def test_ordinary_photo_session_advertises_no_media_delegation(frame):
    client, app = frame
    owner = enroll_client(client, app)
    assert client.post("/api/auth/device-session", json={
        key: owner[key] for key in ("device_id", "device_token")
    }).json()["can_invite"] is True
    payload, _ = invited_client(client)
    assert client.post("/api/auth/invitations", json=invitation()).status_code == 403
    reply = client.post("/api/auth/device-session", json={
        key: payload[key] for key in ("device_id", "device_token")
    })
    assert reply.status_code == 200 and reply.json()["can_invite"] is False

