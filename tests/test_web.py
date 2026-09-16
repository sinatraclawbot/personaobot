import re
import time
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, func
from app.auth import hasher
from app.models import Draft, Job, LoginSession, Membership, Profile, User
from conftest import make_profile


@pytest.fixture
def client(db):
    from app.main import app

    return TestClient(app, follow_redirects=False)


def account(db, admin=True, email="admin@example.test"):
    user = User(email=email, password_hash=hasher.hash("a-long-test-password"), admin=admin)
    db.add(user)
    db.commit()
    return user


def login(client, email="admin@example.test"):
    page = client.get("/login")
    csrf = re.search(r'name="csrf" value="([^"]+)"', page.text).group(1)
    result = client.post(
        "/login",
        data={"email": email, "password": "a-long-test-password", "csrf": csrf},
        headers={"origin": "http://testserver"},
    )
    assert result.status_code == 303
    page = client.get("/")
    return re.search(r'name="csrf" value="([^"]+)"', page.text).group(1)


def test_auth_required(client):
    assert client.get("/").status_code == 303


def test_login_logout_and_csrf(client, db):
    account(db)
    csrf = login(client)
    assert client.get("/").status_code == 200
    assert client.post("/logout").status_code == 403
    assert client.post("/logout", data={"csrf": csrf}, headers={"origin": "https://evil.test"}).status_code == 403
    assert client.post("/logout", data={"csrf": csrf}, headers={"origin": "http://testserver"}).status_code == 303
    assert client.get("/").status_code == 303


def test_server_side_membership_isolation(client, db):
    p1, _, v1 = make_profile(db)
    p2, _, v2 = make_profile(db, 102, "Anna")
    user = account(db, False)
    db.add(Membership(user_id=user.id, profile_id=p1.id))
    db.commit()
    csrf = login(client)
    assert client.get("/profiles/" + p1.id).status_code == 200
    assert client.get("/profiles/" + p2.id).status_code == 404
    assert client.get(f"/profiles/{p1.id}/conversations/{v2.id}").status_code == 404
    assert client.get("/operations").status_code == 403
    assert (
        client.post(
            f"/profiles/{p2.id}/conversations/{v2.id}/reply",
            data={"csrf": csrf, "text": "test"},
            headers={"origin": "http://testserver"},
        ).status_code
        == 404
    )


def test_webhook_auth_and_dedup(client, db):
    from app.config import settings

    payload = {
        "update_id": 99,
        "business_connection": {
            "id": "cid",
            "user": {"id": 123},
            "user_chat_id": 123,
            "is_enabled": True,
            "rights": {"can_reply": True},
            "date": 1,
        },
    }
    assert client.post("/webhooks/telegram", json=payload).status_code == 403
    headers = {"x-telegram-bot-api-secret-token": settings().telegram_webhook_secret}
    assert client.post("/webhooks/telegram", json=payload, headers=headers).status_code == 200
    assert client.post("/webhooks/telegram", json=payload, headers=headers).status_code == 200
    assert db.scalar(select(func.count()).select_from(Job)) == 1
    assert client.post("/webhooks/telegram", json={"update_id": True}, headers=headers).status_code == 422
    assert client.post("/webhooks/telegram", content=b"x" * 262145, headers=headers).status_code == 413


def test_approve_once_and_stale_rejection(client, db, scope):
    from test_pipeline import create_draft

    p, _, v = scope
    account(db)
    csrf = login(client)
    draft, _ = create_draft(db, p, v, "pending")
    url = f"/profiles/{p.id}/conversations/{v.id}/drafts/{draft.id}"
    form = {"csrf": csrf, "action": "approve", "text": "A considered reply"}
    headers = {"origin": "http://testserver"}
    assert client.post(url, data=form, headers=headers).status_code == 303
    assert client.post(url, data=form, headers=headers).status_code == 409
    db.expire_all()
    assert db.get(Draft, draft.id).approved_by is not None
    draft2, _ = create_draft(db, p, v, "pending")
    v.revision += 1
    db.commit()
    assert (
        client.post(f"/profiles/{p.id}/conversations/{v.id}/drafts/{draft2.id}", data=form, headers=headers).status_code
        == 409
    )


def test_stored_html_is_escaped(client, db, scope):
    p, _, v = scope
    v.client_name = "<script>alert(1)</script>"
    db.commit()
    account(db)
    login(client)
    page = client.get(f"/profiles/{p.id}/conversations/{v.id}")
    assert "&lt;script&gt;" in page.text and "<script>alert(1)</script>" not in page.text
    assert "frame-ancestors 'none'" in page.headers["content-security-policy"]


def test_login_rate_limit_persists(client, db):
    account(db)
    client.get("/login")
    csrf = client.cookies.get("login_csrf")
    for _ in range(10):
        response = client.post(
            "/login",
            data={"email": "admin@example.test", "password": "wrong", "csrf": csrf},
            headers={"origin": "http://testserver"},
        )
        assert response.status_code == 401
    assert (
        client.post(
            "/login",
            data={"email": "admin@example.test", "password": "wrong", "csrf": csrf},
            headers={"origin": "http://testserver"},
        ).status_code
        == 429
    )


def test_profile_form_and_pages_render(client, db):
    account(db)
    csrf = login(client)
    from app.schemas import ProfileConfig

    form = {
        "csrf": csrf,
        "name": "Maya",
        "owner_telegram_id": "909",
        "mode": "approval",
        **ProfileConfig().model_dump(),
    }
    result = client.post("/profiles/new", data=form, headers={"origin": "http://testserver"})
    assert result.status_code == 303
    assert client.get(result.headers["location"]).status_code == 200
    assert client.get("/operations").status_code == 200
    assert db.scalar(select(Profile.name)) == "Maya"


def test_expired_session_rejected(client, db):
    account(db)
    login(client)
    login_session = db.scalar(select(LoginSession))
    login_session.expires = time.time() - 1
    db.commit()
    assert client.get("/").status_code == 303


def test_operator_review_note_is_persisted(client, db, scope):
    from app.models import Conversation

    p, _, v = scope
    account(db)
    csrf = login(client)
    result = client.post(
        f"/profiles/{p.id}/conversations/{v.id}/state",
        data={"csrf": csrf, "action": "pause", "note": "Client asked to continue tomorrow."},
        headers={"origin": "http://testserver"},
    )
    assert result.status_code == 303
    db.expire_all()
    assert db.get(Conversation, v.id).review_note == "Client asked to continue tomorrow."


def test_referrer_policy_preserves_same_origin_form_headers(client):
    assert client.get("/login").headers["referrer-policy"] == "same-origin"
