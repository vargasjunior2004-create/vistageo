import base64
import hashlib
import io
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import AuditEvent, AuditRecord, AuthSession, Contract, HistoricalSource, Location, LocationRevision, Permission, PhotoOperation, Photograph, Role, User
from app.security import PERMISSIONS, password_hash
from app.unified import create_unified_app


@pytest.fixture
def api():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        roles = [Role(name=name) for name in ("ADMINISTRADOR", "GERENTE", "TECNICO")]
        db.add_all(roles + [Permission(name=name) for name in sorted(PERMISSIONS)])
        db.flush()
        db.add_all([
            User(username="ADMIN", password_hash=password_hash("TESTPASS1"), role_id=roles[0].id, must_change_password=False),
            User(username="MANAGER", password_hash=password_hash("TESTPASS2"), role_id=roles[1].id, must_change_password=False),
            User(username="TECH", password_hash=password_hash("TESTPASS3"), role_id=roles[2].id, must_change_password=False),
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


def login(client, username, password):
    return client.post("/auth/login", json={"username": username, "password": password})


def headers(client, username="admin", password="testpass1"):
    response = login(client, username, password)
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_unified_serves_frontend_and_preserves_api_routes(api, tmp_path):
    _, _factory = api
    (tmp_path / "index.html").write_text("<html>frontend</html>")
    (tmp_path / "service-worker.js").write_text("worker")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text("app")
    with TestClient(create_unified_app(tmp_path)) as client:
        for path in ("/", "/login", "/usuarios", "/jornada/fotos"):
            response = client.get(path)
            assert response.status_code == 200 and response.text == "<html>frontend</html>"
            assert response.headers["cache-control"] == "no-cache"
        assert client.head("/").status_code == 200
        assert client.get("/api/usuarios").status_code == 401
        assert client.get("/api/inexistente").status_code == 404
        token = client.post("/api/auth/login", json={"username": "admin", "password": "testpass1"})
        assert token.status_code == 200
        auth = {"Authorization": f"Bearer {token.json()['access_token']}"}
        assert client.get("/api/auth/me", headers=auth).json()["username"] == "ADMIN"
        assert client.get("/api/docs").status_code == 200
        assert client.get("/assets/app.js").text == "app"
        assert client.get("/assets/missing.js").status_code == 404
        assert client.get("/missing.js").status_code == 404
        assert client.get("/service-worker.js").headers["cache-control"] == "no-cache"


def test_unified_rejects_missing_frontend(tmp_path):
    with pytest.raises(RuntimeError, match="frontend no está disponible"):
        with TestClient(create_unified_app(tmp_path)):
            pass


def test_login_logout_and_uniform_failures(api):
    client, _ = api
    wrong = login(client, "admin", "incorrect")
    unknown = login(client, "no-existe", "incorrect")
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()
    auth = headers(client)
    assert client.get("/auth/me", headers=auth).json()["username"] == "ADMIN"
    assert client.post("/auth/logout", headers=auth).status_code == 204
    assert client.get("/auth/me", headers=auth).status_code == 401
    assert client.get("/usuarios").status_code == 401


def test_session_profile_does_not_require_role_listing_permission(api):
    client, factory = api
    with factory() as db:
        tech = db.scalar(select(User).where(User.username == "TECH"))
        tech.must_change_password = True
        db.commit()
    auth = headers(client, "tech", "testpass3")
    response = client.get("/auth/me", headers=auth)
    assert response.status_code == 200
    assert response.json()["must_change_password"] is True
    assert response.json()["role_name"] == "TECNICO"
    assert response.json()["permissions"] == []
    assert client.get("/roles", headers=auth).status_code == 403


def test_private_photo_read_requires_admin_and_checks_integrity(api, monkeypatch):
    client, factory = api
    content = b"test-webp"
    with factory() as db:
        admin_id = db.scalar(select(User.id).where(User.username == "ADMIN"))
        db.add(Contract(kardex="Ab-1"))
        db.flush()
        location = Location(kardex="Ab-1")
        db.add(location)
        db.flush()
        location_id = location.id
        db.add(Photograph(ubicacion_id=location_id, storage_bucket="fachada", storage_clave="test.webp",
                          sha256=hashlib.sha256(content).hexdigest(), registrado_por=admin_id))
        db.commit()

    calls = []

    class FakeStorage:
        def get(self, key):
            calls.append(key)
            return content

    monkeypatch.setattr("app.main.Storage", FakeStorage)
    path = f"/ubicaciones/{location_id}/fotografia"
    assert client.get(path).status_code == 401
    assert client.get(path, headers=headers(client, "tech", "testpass3")).status_code == 403
    assert calls == []
    admin = headers(client)
    response = client.get(path, headers=admin)
    assert response.status_code == 200 and response.content == content
    assert response.headers["content-type"] == "image/webp"
    assert response.headers["cache-control"] == "private, no-store"
    assert calls == ["test.webp"]
    content = b"tampered"
    assert client.get(path, headers=admin).status_code == 502
    assert client.get("/ubicaciones/99999/fotografia", headers=admin).status_code == 404


def test_photo_storage_errors_are_not_reported_as_missing(api, monkeypatch):
    client, factory = api
    with factory() as db:
        admin_id = db.scalar(select(User.id).where(User.username == "ADMIN"))
        db.add(Contract(kardex="foto"))
        db.flush()
        location = Location(kardex="foto")
        db.add(location)
        db.flush()
        location_id = location.id
        db.add(Photograph(ubicacion_id=location_id, storage_bucket="fachada", storage_clave="missing.webp",
                          registrado_por=admin_id))
        db.commit()

    class MissingStorage:
        def get(self, key):
            return None

    monkeypatch.setattr("app.main.Storage", MissingStorage)
    assert client.get(f"/ubicaciones/{location_id}/fotografia", headers=headers(client)).status_code == 502


def test_field_registration_retry_is_idempotent_and_keeps_exact_kardex(api, monkeypatch):
    client, factory = api
    with factory() as db:
        role = db.scalar(select(Role).where(Role.name == "TECNICO"))
        role.permissions = list(db.scalars(select(Permission).where(
            Permission.name.in_(["ubicaciones.consultar", "ubicaciones.registrar"])
        )).all())
        db.commit()
    objects = {}

    class FakeStorage:
        fail = True

        def get(self, key):
            return objects.get(key)

        def put(self, key, content):
            if FakeStorage.fail:
                FakeStorage.fail = False
                raise RuntimeError("interrupción simulada")
            objects[key] = content

    monkeypatch.setattr("app.main.Storage", FakeStorage)
    auth = headers(client, "tech", "testpass3")
    image = io.BytesIO()
    Image.new("RGB", (20, 10), "blue").save(image, format="JPEG")
    body = {"idempotencia": str(uuid4()), "kardex": "aB-1 ", "latitud": "-16.5", "longitud": "-68.1",
            "fotografia_base64": base64.b64encode(image.getvalue()).decode()}
    assert client.post("/registro-ubicacion", headers=auth, json=body).status_code == 503
    with factory() as db:
        location = db.scalar(select(Location).where(Location.kardex == body["kardex"]))
        assert location is not None and location.revision_actual_id is None
        assert db.scalar(select(Photograph)) is None
        assert db.scalar(select(PhotoOperation)).estado == "preparada"
    assert client.post("/registro-ubicacion", headers=auth, json={**body, "latitud": "0"}).status_code == 409
    response = client.post("/registro-ubicacion", headers=auth, json=body)
    assert response.status_code == 201
    assert response.json()["kardex"] == "aB-1 "
    assert client.post("/registro-ubicacion", headers=auth, json=body).status_code == 201
    assert client.post("/registro-ubicacion", headers=auth, json={**body, "idempotencia": str(uuid4())}).status_code == 409
    with factory() as db:
        photo = db.scalar(select(Photograph))
        revision = db.get(LocationRevision, response.json()["revision_actual_id"])
        assert photo.registrado_por == revision.responsable_id
        assert len(db.scalars(select(Photograph)).all()) == 1
        assert db.scalar(select(PhotoOperation)).estado == "finalizada"
    assert client.get("/ubicaciones", headers=auth, params={"kardex": "aB-1 "}).json()[0]["kardex"] == "aB-1 "
    assert client.get(f"/ubicaciones/{response.json()['id']}/fotografia", headers=auth).status_code == 200
    assert client.get("/usuarios", headers=auth).status_code == 403


def test_field_registration_checks_permissions_and_invalid_photo_before_writes(api, monkeypatch):
    client, factory = api
    auth = headers(client, "tech", "testpass3")

    class FakeStorage:
        pass

    monkeypatch.setattr("app.main.Storage", FakeStorage)
    body = {"idempotencia": str(uuid4()), "kardex": "nuevo", "latitud": 1, "longitud": 2,
            "fotografia_base64": "aW52YWxpZG8="}
    assert client.post("/registro-ubicacion", headers=auth, json=body).status_code == 403
    with factory() as db:
        role = db.scalar(select(Role).where(Role.name == "TECNICO"))
        role.permissions = [db.scalar(select(Permission).where(Permission.name == "ubicaciones.registrar"))]
        db.commit()
    assert client.post("/registro-ubicacion", headers=auth, json=body).status_code == 422
    assert client.get("/ubicaciones", headers=auth).status_code == 403
    assert client.get("/ubicaciones", headers=auth, params={"kardex": "nuevo"}).status_code == 200
    with factory() as db:
        assert db.scalar(select(Contract)) is None


@pytest.mark.parametrize("matching", [True, False])
def test_field_registration_recovers_when_object_already_uploaded(api, monkeypatch, matching):
    client, factory = api
    with factory() as db:
        role = db.scalar(select(Role).where(Role.name == "TECNICO"))
        role.permissions = [db.scalar(select(Permission).where(Permission.name == "ubicaciones.registrar"))]
        db.commit()
    image = io.BytesIO()
    Image.new("RGB", (20, 10), "blue").save(image, format="JPEG")
    encoded = base64.b64encode(image.getvalue()).decode()
    from app.registro_ubicacion import optimize_photo

    content = optimize_photo(encoded) if matching else b"objeto ajeno"

    class FakeStorage:
        def get(self, key):
            return content

        def put(self, key, data):
            pytest.fail("No debe sobrescribirse un objeto existente")

    monkeypatch.setattr("app.main.Storage", FakeStorage)
    auth = headers(client, "tech", "testpass3")
    body = {"idempotencia": str(uuid4()), "kardex": "carrera", "latitud": 1, "longitud": 2,
            "fotografia_base64": encoded}
    assert client.post("/registro-ubicacion", headers=auth, json=body).status_code == (201 if matching else 503)
    with factory() as db:
        assert db.scalar(select(PhotoOperation)).estado == ("finalizada" if matching else "preparada")
        photo = db.scalar(select(Photograph))
        if matching:
            assert photo.sha256 == hashlib.sha256(content).hexdigest()
        else:
            assert photo is None


def test_lockout_by_account_and_expiry(api, monkeypatch):
    client, _ = api
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    monkeypatch.setattr("app.main.now_utc", lambda: now)
    for _ in range(5):
        assert login(client, "admin", "wrongpass").status_code == 401
    assert login(client, "admin", "testpass1").status_code == 401
    monkeypatch.setattr("app.main.now_utc", lambda: now + timedelta(minutes=15))
    assert login(client, "admin", "testpass1").status_code == 200


def test_session_expiration_and_explicit_activity(api, monkeypatch):
    client, factory = api
    now = datetime.now(timezone.utc)
    monkeypatch.setattr("app.security.now_utc", lambda: now)
    auth = headers(client)
    with factory() as db:
        session = db.scalar(select(AuthSession))
        session.last_activity = now - timedelta(minutes=9)
        db.commit()
    assert client.get("/auth/me", headers=auth).status_code == 200
    with factory() as db:
        saved = db.scalar(select(AuthSession)).last_activity
        assert saved.replace(tzinfo=timezone.utc) == now - timedelta(minutes=9)
    assert client.get("/auth/me", headers={**auth, "X-Actividad-Usuario": "true"}).status_code == 200
    monkeypatch.setattr("app.security.now_utc", lambda: now + timedelta(minutes=10))
    assert client.get("/auth/me", headers=auth).status_code == 401


def test_admin_create_normalization_permissions_and_validation_redaction(api):
    client, factory = api
    admin = headers(client)
    technician = headers(client, "tech", "testpass3")
    with factory() as db:
        role_id = db.scalar(select(Role.id).where(Role.name == "TECNICO"))
    payload = {"username": "nuevo", "password": "NEWPASS9", "role_id": role_id}
    assert client.post("/usuarios", headers=technician, json=payload).status_code == 403
    created = client.post("/usuarios", headers=admin, json=payload)
    assert created.status_code == 201
    assert created.json()["username"] == "NUEVO"
    assert "password" not in created.json()
    assert client.post("/usuarios", headers=admin, json={**payload, "username": "NUEVO"}).status_code == 409
    bad = client.post("/usuarios", headers=admin, json={**payload, "password": "short"})
    assert bad.status_code == 422
    assert "short" not in bad.text
    assert client.patch(f"/usuarios/{created.json()['id']}", headers=admin, json={}).status_code == 422
    assert client.patch(f"/usuarios/{created.json()['id']}", headers=admin, json={"active": "false"}).status_code == 422


def test_deactivation_revokes_sessions_and_keeps_audit(api):
    client, factory = api
    admin = headers(client)
    technician = headers(client, "tech", "testpass3")
    with factory() as db:
        user_id = db.scalar(select(User.id).where(User.username == "TECH"))
    response = client.patch(f"/usuarios/{user_id}", headers=admin, json={"active": False})
    assert response.status_code == 200
    assert client.get("/auth/me", headers=technician).status_code == 401
    assert login(client, "tech", "testpass3").status_code == 401
    with factory() as db:
        event = db.scalar(select(AuditEvent).where(AuditEvent.action == "DESACTIVAR_USUARIO"))
        assert event.target_id == user_id
        assert event.details["antes"]["active"] is True
        assert event.details["despues"]["active"] is False


def test_reset_requires_change_and_revokes_old_sessions(api):
    client, factory = api
    admin = headers(client)
    technician = headers(client, "tech", "testpass3")
    with factory() as db:
        user_id = db.scalar(select(User.id).where(User.username == "TECH"))
    reset = client.post(
        f"/usuarios/{user_id}/restablecer-contrasena",
        headers=admin,
        json={"temporary_password": "TEMPASS8"},
    )
    assert reset.status_code == 204
    assert client.get("/auth/me", headers=technician).status_code == 401
    assert login(client, "tech", "testpass3").status_code == 401
    temporary = headers(client, "tech", "tempass8")
    assert client.get("/usuarios", headers=temporary).status_code == 403
    assert client.post("/auth/password", headers=temporary, json={
        "current_password": "tempass8", "new_password": "FINALPASS9"
    }).status_code == 204
    assert client.get("/auth/me", headers=temporary).status_code == 401
    assert login(client, "tech", "finalpass9").status_code == 200


def test_role_permissions_and_admin_escalation_boundaries(api):
    client, factory = api
    manager = headers(client, "manager", "testpass2")
    technician = headers(client, "tech", "testpass3")
    with factory() as db:
        admin_id = db.scalar(select(Role.id).where(Role.name == "ADMINISTRADOR"))
        manager_id = db.scalar(select(Role.id).where(Role.name == "GERENTE"))
        manager_user_id = db.scalar(select(User.id).where(User.username == "MANAGER"))
        tech_id = db.scalar(select(Role.id).where(Role.name == "TECNICO"))
    assert client.put(f"/roles/{tech_id}/permisos", headers=technician, json={"permissions": []}).status_code == 403
    assert client.put(f"/roles/{admin_id}/permisos", headers=manager, json={"permissions": []}).status_code == 403
    assert client.put(f"/roles/{tech_id}/permisos", headers=manager, json={"permissions": ["usuarios.consultar"]}).status_code == 200
    assert client.get("/usuarios", headers=technician).status_code == 200
    assert client.post("/usuarios", headers=technician, json={
        "username": "other", "password": "EXAMPLE9", "role_id": admin_id
    }).status_code == 403
    assert client.put(f"/roles/{tech_id}/permisos", headers=manager, json={"permissions": ["usuarios.gestionar"]}).status_code == 200
    assert client.post("/usuarios", headers=technician, json={
        "username": "other", "password": "EXAMPLE9", "role_id": admin_id
    }).status_code == 403
    assert client.post("/usuarios", headers=technician, json={
        "username": "other", "password": "EXAMPLE9", "role_id": manager_id
    }).status_code == 403
    assert client.post(f"/usuarios/{manager_user_id}/restablecer-contrasena", headers=technician,
                       json={"temporary_password": "EXAMPLE9"}).status_code == 403
    assert client.patch(f"/roles/{tech_id}", headers=technician, json={"name": "ADMINISTRADOR"}).status_code == 403
    with factory() as db:
        event = db.scalar(select(AuditEvent).where(AuditEvent.action == "ACTUALIZAR_PERMISOS").order_by(AuditEvent.id.desc()))
        assert event.role_id == tech_id
        assert event.details["despues"] == ["usuarios.gestionar"]


def test_cannot_deactivate_last_administrator(api):
    client, factory = api
    admin = headers(client)
    with factory() as db:
        user_id = db.scalar(select(User.id).where(User.username == "ADMIN"))
    assert client.patch(f"/usuarios/{user_id}", headers=admin, json={"active": False}).status_code == 409


def test_unicode_uppercase_is_consistent_for_creation_and_login(api):
    client, factory = api
    admin = headers(client)
    with factory() as db:
        role_id = db.scalar(select(Role.id).where(Role.name == "TECNICO"))
    payload = {"username": "maña", "password": "contraseña9", "role_id": role_id}
    assert client.post("/usuarios", headers=admin, json=payload).status_code == 201
    assert client.post("/usuarios", headers=admin, json={**payload, "username": "MAÑA"}).status_code == 409
    assert login(client, "MAÑA", "CONTRASEÑA9").status_code == 200


def test_only_permission_managers_can_modify_role_permissions(api):
    client, factory = api
    manager = headers(client, "manager", "testpass2")
    technician = headers(client, "tech", "testpass3")
    with factory() as db:
        role_id = db.scalar(select(Role.id).where(Role.name == "TECNICO"))
    assert client.put(f"/roles/{role_id}/permisos", headers=technician, json={"permissions": []}).status_code == 403
    assert client.put(f"/roles/{role_id}/permisos", headers=manager, json={"permissions": ["desconocido"]}).status_code == 422
    assert client.put(f"/roles/{role_id}/permisos", headers=manager, json={"permissions": ["roles.consultar"]}).status_code == 200


def test_openapi_masks_password_fields(api):
    client, _ = api
    schemas = client.get("/openapi.json").json()["components"]["schemas"]
    for model, fields in {
        "LoginRequest": ["password"],
        "UserCreate": ["password"],
        "PasswordChange": ["current_password", "new_password"],
        "PasswordReset": ["temporary_password"],
    }.items():
        for field in fields:
            assert schemas[model]["properties"][field]["format"] == "password"


def test_contratos_respetan_kardex_y_solo_administrador(api):
    client, factory = api
    admin = headers(client)
    manager = headers(client, "manager", "testpass2")
    assert client.get("/contratos").status_code == 401
    assert client.post("/contratos", headers=manager, json={"kardex": "a-1"}).status_code == 403
    assert client.get("/contratos", headers=manager).status_code == 403
    for kardex in ("a-1", "A-1", "a-1 ", "a-1.1"):
        response = client.post("/contratos", headers=admin, json={"kardex": kardex})
        assert response.status_code == 201
        assert response.json()["kardex"] == kardex
    assert client.post("/contratos", headers=admin, json={"kardex": "a-1"}).status_code == 409
    assert client.post("/contratos", headers=admin, json={"kardex": "  "}).status_code == 422
    assert client.get("/contratos", headers=admin, params={"kardex": "a\x00b"}).status_code == 422
    assert client.get("/contratos", headers=admin, params={"kardex": "a-1 "}).json() == [{"kardex": "a-1 "}]
    with factory() as db:
        assert len(db.scalars(select(AuditRecord).where(AuditRecord.accion == "CREAR_CONTRATO")).all()) == 4


def test_ubicaciones_guardan_historial_y_auditoria(api):
    client, factory = api
    admin = headers(client)
    technician = headers(client, "tech", "testpass3")
    assert client.post("/ubicaciones", headers=admin, json={"kardex": "missing"}).status_code == 404
    assert client.post("/contratos", headers=admin, json={"kardex": "123-1"}).status_code == 201
    assert client.post("/ubicaciones", headers=technician, json={"kardex": "123-1"}).status_code == 403
    location = client.post("/ubicaciones", headers=admin, json={"kardex": "123-1"})
    assert location.status_code == 201
    location_id = location.json()["id"]
    assert client.post("/ubicaciones", headers=admin, json={"kardex": "123-1"}).status_code == 409
    assert client.get("/ubicaciones", headers=admin, params={"kardex": "123-1"}).json()[0]["id"] == location_id
    assert client.get("/ubicaciones", headers=admin, params={"kardex": "123-1 "}).json() == []
    assert client.get("/ubicaciones", headers=technician).status_code == 403
    url = f"/ubicaciones/{location_id}/revisiones"
    assert client.post(url, headers=admin, json={"latitud": -16}).status_code == 422
    assert client.post(url, headers=admin, json={"latitud": 91, "longitud": 0}).status_code == 422
    assert client.post(url, headers=admin, json={"url_gps": "no-es-una-url"}).status_code == 422
    assert client.post(url, headers=admin, json={}).status_code == 422
    first = client.post(url, headers=admin, json={"url_gps": "https://maps.example/one"})
    second = client.post(url, headers=admin, json={"latitud": -16.5, "longitud": -68.1})
    assert first.status_code == second.status_code == 201
    assert first.json()["cerrada"] and second.json()["cerrada"]
    assert client.get(f"/ubicaciones/{location_id}", headers=admin).json()["revision_actual_id"] == second.json()["id"]
    assert [r["id"] for r in client.get(url, headers=admin).json()] == [second.json()["id"], first.json()["id"]]
    assert client.get(url, headers=technician).status_code == 403
    with factory() as db:
        events = db.scalars(select(AuditRecord).where(AuditRecord.ubicacion_id == location_id).order_by(AuditRecord.id)).all()
        assert [event.accion for event in events] == ["CREAR_UBICACION", "ACTUALIZAR_UBICACION", "ACTUALIZAR_UBICACION"]
        assert events[-1].detalles["revision_anterior_id"] == first.json()["id"]


def test_consulta_de_procedencia_requiere_administrador_y_filtra_ruta_exacta(api):
    client, factory = api
    with factory() as db:
        db.add_all([
            HistoricalSource(ruta_original="raiz/123_%/foto.jpg", tipo="imagen", estado_revision="PENDIENTE"),
            HistoricalSource(ruta_original="raiz/123_A/foto.jpg", tipo="imagen", estado_revision="PENDIENTE"),
            HistoricalSource(ruta_original="raiz/123_%/documento.docx", tipo="documento", estado_revision="PENDIENTE"),
        ])
        db.commit()
    admin = headers(client)
    technician = headers(client, "tech", "testpass3")
    assert client.get("/procedencia").status_code == 401
    assert client.get("/procedencia", headers=technician).status_code == 403
    result = client.get("/procedencia", headers=admin, params={"carpeta": "raiz/123_%", "tipo": "imagen"})
    assert result.status_code == 200
    assert [item["ruta_original"] for item in result.json()] == ["raiz/123_%/foto.jpg"]
    assert result.json()[0]["kardex"] is None
    assert client.get("/procedencia", headers=admin, params={"carpeta": "raiz/123_%", "limit": 1}).json()[0]["id"] == result.json()[0]["id"]
    assert client.get("/procedencia", headers=admin, params={"carpeta": "\x00"}).status_code == 422
    assert client.get("/procedencia/999", headers=admin).status_code == 404


def test_asociacion_de_procedencia_es_manual_auditada_y_reversible(api):
    client, factory = api
    with factory() as db:
        source = HistoricalSource(ruta_original="raiz/123/foto.jpg", tipo="imagen", estado_revision="PENDIENTE")
        db.add(source)
        db.commit()
        source_id = source.id
        admin_id = db.scalar(select(User.id).where(User.username == "ADMIN"))
    admin = headers(client)
    technician = headers(client, "tech", "testpass3")
    endpoint = f"/procedencia/{source_id}/contrato"
    assert client.put(endpoint, headers=technician, json={"kardex": "a-1"}).status_code == 403
    assert client.put(endpoint, headers=admin, json={"kardex": "a-1"}).status_code == 404
    for kardex in ("a-1", "A-1"):
        assert client.post("/contratos", headers=admin, json={"kardex": kardex}).status_code == 201
    first = client.put(endpoint, headers=admin, json={"kardex": "a-1"})
    assert first.status_code == 200
    assert (first.json()["kardex"], first.json()["estado_revision"]) == ("a-1", "CONFIRMADO")
    assert client.put(endpoint, headers=admin, json={"kardex": "a-1"}).status_code == 200
    assert client.put(endpoint, headers=admin, json={"kardex": "A-1"}).json()["kardex"] == "A-1"
    assert client.get("/procedencia", headers=admin, params={"kardex": "A-1", "estado": "CONFIRMADO"}).json()[0]["id"] == source_id
    assert client.delete(endpoint, headers=technician).status_code == 403
    removed = client.delete(endpoint, headers=admin)
    assert (removed.json()["kardex"], removed.json()["estado_revision"]) == (None, "PENDIENTE")
    assert client.delete(endpoint, headers=admin).status_code == 200
    assert client.get("/ubicaciones", headers=admin).json() == []
    with factory() as db:
        events = db.scalars(select(AuditRecord).where(AuditRecord.accion.in_(
            ["CONFIRMAR_CONTRATO_PROCEDENCIA", "RETIRAR_CONTRATO_PROCEDENCIA"]
        )).order_by(AuditRecord.id)).all()
        assert [event.accion for event in events] == [
            "CONFIRMAR_CONTRATO_PROCEDENCIA", "CONFIRMAR_CONTRATO_PROCEDENCIA", "RETIRAR_CONTRATO_PROCEDENCIA",
        ]
        assert all(event.usuario_id == admin_id and event.detalles["procedencia_id"] == source_id for event in events)
        assert events[1].detalles["antes"]["kardex"] == "a-1"
        assert events[2].detalles["despues"] == {"kardex": None, "estado": "PENDIENTE"}
        db.get(HistoricalSource, source_id).estado_revision = "OTRO"
        db.commit()
    assert client.put(endpoint, headers=admin, json={"kardex": "a-1"}).status_code == 409
    assert client.delete(endpoint, headers=admin).status_code == 409
