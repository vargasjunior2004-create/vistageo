from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import AuthSession, Permission, Role, User, now_utc
from app.security import PERMISSIONS, password_hash, token_hash
from app.tokens import create_access_token, generate_refresh_token, hash_refresh_token


@pytest.fixture
def api():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        roles = [Role(name=name) for name in ("ADMINISTRADOR", "TECNICO")]
        db.add_all(roles + [Permission(name=name) for name in sorted(PERMISSIONS)])
        db.flush()
        db.add_all([
            User(username="ADMIN", password_hash=password_hash("TESTPASS1"), role_id=roles[0].id, must_change_password=False),
            User(username="TECH", password_hash=password_hash("TESTPASS3"), role_id=roles[1].id, must_change_password=False),
        ])
        db.commit()

    def override_db():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as client:
        yield client, factory
    app.dependency_overrides.clear()
    engine.dispose()


def login(client, username="admin", password="testpass1"):
    response = client.post("/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200
    return response.json()


def auth_headers(access_token):
    return {"Authorization": f"Bearer {access_token}"}


def test_login_returns_jwt_refresh_and_expires(api):
    client, _ = api
    body = login(client)
    assert body["token_type"] == "bearer"
    assert body["access_token"].count(".") == 2
    assert isinstance(body["refresh_token"], str) and len(body["refresh_token"]) > 20
    assert body["expires_in"] > 0
    assert body["must_change_password"] is False


def test_access_jwt_works_for_me(api):
    client, _ = api
    body = login(client)
    me = client.get("/auth/me", headers=auth_headers(body["access_token"]))
    assert me.status_code == 200
    assert me.json()["username"] == "ADMIN"


def test_expired_access_jwt_is_rejected(api):
    client, factory = api
    body = login(client)
    with factory() as db:
        session = db.scalar(select(AuthSession).order_by(AuthSession.id.desc()))
        token, _ = create_access_token(session.id, session.user_id, now=datetime.now(timezone.utc) - timedelta(minutes=30))
    response = client.get("/auth/me", headers=auth_headers(token))
    assert response.status_code == 401


def test_tampered_access_jwt_is_rejected(api):
    client, _ = api
    body = login(client)
    token = body["access_token"]
    tampered = token[:-2] + ("A" if token[-1] != "A" else "B")
    response = client.get("/auth/me", headers=auth_headers(tampered))
    assert response.status_code == 401


def test_revoked_session_rejects_access_jwt(api):
    client, factory = api
    body = login(client)
    headers = auth_headers(body["access_token"])
    assert client.post("/auth/logout", headers=headers).status_code == 204
    assert client.get("/auth/me", headers=headers).status_code == 401


def test_refresh_rotates_tokens(api):
    client, _ = api
    body = login(client)
    refreshed = client.post("/auth/refresh", json={"refresh_token": body["refresh_token"]})
    assert refreshed.status_code == 200
    data = refreshed.json()
    assert data["access_token"].count(".") == 2
    assert data["refresh_token"] != body["refresh_token"]
    assert client.get("/auth/me", headers=auth_headers(data["access_token"])).status_code == 200


def test_refresh_reuse_revokes_session(api):
    client, _ = api
    body = login(client)
    first = client.post("/auth/refresh", json={"refresh_token": body["refresh_token"]})
    assert first.status_code == 200
    reuse = client.post("/auth/refresh", json={"refresh_token": body["refresh_token"]})
    assert reuse.status_code == 401
    # El refresh nuevo también debe quedar inválido porque se revocó la sesión.
    new_refresh = first.json()["refresh_token"]
    assert client.post("/auth/refresh", json={"refresh_token": new_refresh}).status_code == 401


def test_expired_refresh_is_rejected(api):
    client, factory = api
    body = login(client)
    with factory() as db:
        session = db.scalar(select(AuthSession).order_by(AuthSession.id.desc()))
        session.refresh_expires_at = now_utc() - timedelta(minutes=1)
        db.commit()
    response = client.post("/auth/refresh", json={"refresh_token": body["refresh_token"]})
    assert response.status_code == 401


def test_refresh_for_deactivated_user_is_rejected(api):
    client, factory = api
    body = login(client, "tech", "testpass3")
    with factory() as db:
        user = db.scalar(select(User).where(User.username == "TECH"))
        user.active = False
        db.commit()
    response = client.post("/auth/refresh", json={"refresh_token": body["refresh_token"]})
    assert response.status_code == 401


def test_logout_revokes_refresh(api):
    client, _ = api
    body = login(client)
    assert client.post("/auth/logout", headers=auth_headers(body["access_token"])).status_code == 204
    assert client.post("/auth/refresh", json={"refresh_token": body["refresh_token"]}).status_code == 401


def test_delete_all_sessions_revokes_refresh(api):
    client, _ = api
    body = login(client)
    headers = auth_headers(body["access_token"])
    assert client.delete("/auth/sessions", headers=headers).status_code == 204
    assert client.post("/auth/refresh", json={"refresh_token": body["refresh_token"]}).status_code == 401


def test_delete_other_users_session_returns_404(api):
    client, factory = api
    admin = login(client, "admin", "testpass1")
    tech = login(client, "tech", "testpass3")
    with factory() as db:
        tech_session = db.scalar(select(AuthSession).where(AuthSession.user_id == select(User.id).where(User.username == "TECH").scalar_subquery()).order_by(AuthSession.id.desc()))
        tech_session_id = tech_session.id
    response = client.delete(f"/auth/sessions/{tech_session_id}", headers=auth_headers(admin["access_token"]))
    assert response.status_code == 404
    # La sesión del técnico sigue válida.
    assert client.get("/auth/me", headers=auth_headers(tech["access_token"])).status_code == 200


def test_absolute_expiry_rejects_session(api):
    client, factory = api
    body = login(client)
    with factory() as db:
        session = db.scalar(select(AuthSession).order_by(AuthSession.id.desc()))
        session.expires_at = now_utc() - timedelta(seconds=1)
        db.commit()
    response = client.get("/auth/me", headers=auth_headers(body["access_token"]))
    assert response.status_code == 401


def test_legacy_opaque_token_still_works(api):
    client, factory = api
    with factory() as db:
        user = db.scalar(select(User).where(User.username == "ADMIN"))
        raw = "legacy-token-for-test"
        session = AuthSession(
            token_hash=token_hash(raw),
            user_id=user.id,
            last_activity=now_utc(),
            created_at=now_utc(),
            expires_at=now_utc() + timedelta(hours=1),
            revoked=False,
        )
        db.add(session)
        db.commit()
    response = client.get("/auth/me", headers={"Authorization": f"Bearer {raw}"})
    assert response.status_code == 200
    assert response.json()["username"] == "ADMIN"


def test_temporary_password_allows_only_password_flow(api):
    client, factory = api
    with factory() as db:
        role = db.scalar(select(Role).where(Role.name == "TECNICO"))
        user = User(username="TEMP", password_hash=password_hash("TESTPASS9"), role_id=role.id, must_change_password=True)
        db.add(user)
        db.commit()
    body = login(client, "temp", "testpass9")
    headers = auth_headers(body["access_token"])
    me = client.get("/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["must_change_password"] is True
    assert client.get("/usuarios", headers=headers).status_code == 403
    assert client.post("/auth/password", headers=headers, json={"current_password": "TESTPASS9", "new_password": "NEWPASS99"}).status_code == 204


def test_admin_can_revoke_user_sessions(api):
    client, _ = api
    admin = login(client, "admin", "testpass1")
    tech = login(client, "tech", "testpass3")
    tech_id = client.get("/auth/me", headers=auth_headers(tech["access_token"])).json()["id"]
    response = client.post(f"/usuarios/{tech_id}/revocar-sesiones", headers=auth_headers(admin["access_token"]))
    assert response.status_code == 204
    assert client.get("/auth/me", headers=auth_headers(tech["access_token"])).status_code == 401
    assert client.post("/auth/refresh", json={"refresh_token": tech["refresh_token"]}).status_code == 401


def test_login_rate_limit_returns_429(api, monkeypatch):
    client, _ = api
    monkeypatch.setenv("LOGIN_RATE_LIMIT_IP", "2")
    monkeypatch.setenv("LOGIN_RATE_LIMIT_ACCOUNT", "2")
    monkeypatch.setenv("LOGIN_RATE_LIMIT_IP_WINDOW_SECONDS", "60")
    monkeypatch.setenv("LOGIN_RATE_LIMIT_ACCOUNT_WINDOW_SECONDS", "60")
    assert client.post("/auth/login", json={"username": "admin", "password": "wrong"}).status_code == 401
    assert client.post("/auth/login", json={"username": "admin", "password": "wrong"}).status_code == 401
    blocked = client.post("/auth/login", json={"username": "admin", "password": "wrong"})
    assert blocked.status_code == 429
    assert blocked.headers.get("retry-after") is not None
