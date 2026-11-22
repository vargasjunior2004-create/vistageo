import asyncio
import base64
import hashlib
import io
from datetime import datetime, timedelta, timezone
from threading import Event
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import AuditEvent, AuditRecord, AuthSession, Contract, HistoricalSource, Location, LocationRevision, Permission, PhotoOperation, Photograph, Role, User, as_utc
from app.security import PERMISSIONS, password_hash
from app.unified import create_unified_app

GPS_SAMPLE = {"precision_metros": 8.25, "capturado_en": "2026-01-01T12:00:00Z"}


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


def test_catalogo_motivos_permisos_y_desactivacion(api):
    client, factory = api
    admin = headers(client)
    manager = headers(client, "manager", "testpass2")
    tech = headers(client, "tech", "testpass3")
    assert client.post("/motivos-actualizacion", headers=tech, json={"nombre": "Traslado"}).status_code == 403
    assert client.get("/motivos-actualizacion?todos=true", headers=tech).status_code == 403
    assert client.get("/motivos-actualizacion", headers=tech).status_code == 403
    with factory() as db:
        db.scalar(select(Role).where(Role.name == "TECNICO")).permissions = [
            db.scalar(select(Permission).where(Permission.name == "ubicaciones.consultar"))
        ]
        db.commit()
    assert client.post("/motivos-actualizacion", headers=manager, json={"nombre": "   "}).status_code == 422
    created = client.post("/motivos-actualizacion", headers=manager, json={"nombre": " Traslado "})
    assert created.status_code == 201
    reason = created.json()
    assert reason["nombre"] == "Traslado" and reason["activo"] is True
    path = f"/motivos-actualizacion/{reason['id']}"
    assert client.put(path, headers=tech, json={"nombre": "Obra", "activo": False}).status_code == 403
    assert client.put(path, headers=admin, json={"nombre": "Obra", "activo": False}).status_code == 200
    assert client.get("/motivos-actualizacion", headers=tech).json() == []
    assert client.get("/motivos-actualizacion?todos=true", headers=manager).json() == [
        {"id": reason["id"], "nombre": "Obra", "activo": False}
    ]
    assert client.put(path, headers=manager, json={"nombre": "Obra", "activo": True}).status_code == 200
    assert client.get("/motivos-actualizacion", headers=tech).json()[0]["id"] == reason["id"]
    assert client.delete(path, headers=admin).status_code == 405


def test_actualizacion_con_motivo_permisos_reintento_y_auditoria(api, monkeypatch):
    client, factory = api
    objects = {"anterior.webp": b"original"}

    class FakeStorage:
        def get(self, key):
            return objects.get(key)
        def put(self, key, content):
            objects[key] = content
        def delete(self, key):
            objects.pop(key, None)

    monkeypatch.setattr("app.main.Storage", FakeStorage)
    admin = headers(client)
    tech = headers(client, "tech", "testpass3")
    reason = client.post("/motivos-actualizacion", headers=admin, json={"nombre": "Traslado"}).json()
    with factory() as db:
        user = db.scalar(select(User).where(User.username == "ADMIN"))
        db.add(Contract(kardex="ACT-1"))
        db.flush()
        location = Location(kardex="ACT-1", latitud=1, longitud=2, url_gps="https://maps.google.com/old")
        db.add(location)
        db.flush()
        db.add(Photograph(ubicacion_id=location.id, storage_bucket="fachada", storage_clave="anterior.webp",
                          registrado_por=user.id))
        db.commit()
        location_id = location.id
        role = db.scalar(select(Role).where(Role.name == "TECNICO"))
        role.permissions = list(db.scalars(select(Permission).where(Permission.name.in_(
            ["ubicaciones.consultar", "ubicaciones.gps.editar"]
        ))).all())
        db.commit()
    path = f"/ubicaciones/{location_id}/actualizacion"
    body = {"idempotencia": str(uuid4()), "version": 0, "motivo_id": reason["id"],
            "latitud": "-16", "longitud": "-68", "observacion": "Nueva calle", **GPS_SAMPLE}
    assert client.put(path, headers=tech, json={**body, "precision_metros": 20.01}).status_code == 422
    assert client.put(path, headers=tech, json={**body, "precision_metros": None}).status_code == 422
    assert client.put(path, headers=tech, json={**body, "motivo_id": 999}).status_code == 409
    assert client.put(path, headers=tech, json=body).json() == {"estado": "finalizada"}
    assert client.put(path, headers=tech, json=body).json() == {"estado": "finalizada"}
    assert client.put(path, headers=tech, json={**body, "observacion": "otra"}).status_code == 409
    assert client.put(path, headers=tech, json={**body, "idempotencia": str(uuid4())}).status_code == 412
    result = client.get(f"/ubicaciones/{location_id}", headers=tech).json()
    assert result["latitud"] == "-16.0000000000" and result["url_gps"] is None and result["version"] == 1
    assert result["precision_metros"] == GPS_SAMPLE["precision_metros"]
    assert result["metodo_coordenadas"] == "GPS_DISPOSITIVO" and result["capturado_por"] is not None
    image = io.BytesIO()
    Image.new("RGB", (20, 10), "blue").save(image, format="JPEG")
    photo_version = client.get(f"/ubicaciones/{location_id}/fotografia", headers=tech).headers["x-foto-version"]
    both = {"idempotencia": str(uuid4()), "version": 1, "motivo_id": reason["id"],
            "latitud": "3", "longitud": "4", "foto_version": photo_version, **GPS_SAMPLE,
            "fotografia_base64": base64.b64encode(image.getvalue()).decode()}
    assert client.put(path, headers=tech, json=both).status_code == 403
    assert client.put(path, headers=admin, json=both).json() == {"estado": "finalizada"}
    assert client.put(path, headers=admin, json=both).json() == {"estado": "finalizada"}
    assert "anterior.webp" not in objects
    assert client.put(f"/motivos-actualizacion/{reason['id']}", headers=admin,
                      json={"nombre": "Renombrado", "activo": False}).status_code == 200
    history = client.get(f"/ubicaciones/{location_id}/actualizaciones", headers=tech).json()
    assert len(history) == 2 and all(row["motivo"] == "Traslado" for row in history)
    assert any(row["fachada"] and row["gps"] for row in history)
    assert all(row["precision_metros"] == GPS_SAMPLE["precision_metros"] for row in history)
    assert client.put(path, headers=tech, json={**body, "idempotencia": str(uuid4()), "version": 2}).status_code == 409
    with factory() as db:
        loc = db.get(Location, location_id)
        assert loc.latitud == 3 and loc.longitud == 4 and loc.revision_actual_id is None


def test_fallo_auditoria_no_publica_foto_ni_gps_y_permite_reintentar(api, monkeypatch):
    client, factory = api
    objects = {"anterior.webp": b"original"}

    class FakeStorage:
        def get(self, key):
            return objects.get(key)
        def put(self, key, content):
            objects[key] = content
        def delete(self, key):
            objects.pop(key, None)

    monkeypatch.setattr("app.main.Storage", FakeStorage)
    auth = headers(client)
    reason = client.post("/motivos-actualizacion", headers=auth, json={"nombre": "Corrección"}).json()
    with factory() as db:
        actor = db.scalar(select(User).where(User.username == "ADMIN"))
        db.add(Contract(kardex="rollback"))
        db.flush()
        loc = Location(kardex="rollback", latitud=1, longitud=2)
        db.add(loc)
        db.flush()
        db.add(Photograph(ubicacion_id=loc.id, storage_bucket="fachada", storage_clave="anterior.webp",
                          registrado_por=actor.id))
        db.commit()
        location_id = loc.id
    image = io.BytesIO()
    Image.new("RGB", (10, 10), "green").save(image, format="JPEG")
    photo_path = f"/ubicaciones/{location_id}/fotografia"
    body = {"idempotencia": str(uuid4()), "version": 0, "motivo_id": reason["id"],
            "latitud": 3, "longitud": 4, **GPS_SAMPLE,
            "foto_version": client.get(photo_path, headers=auth).headers["x-foto-version"],
            "fotografia_base64": base64.b64encode(image.getvalue()).decode()}

    def reject_audit(_mapper, _connection, target):
        if target.accion == "ACTUALIZAR_DATOS_UBICACION":
            raise RuntimeError("fallo de auditoría simulado")

    event.listen(AuditRecord, "before_insert", reject_audit)
    try:
        with pytest.raises(RuntimeError, match="fallo de auditoría"):
            client.put(f"/ubicaciones/{location_id}/actualizacion", headers=auth, json=body)
    finally:
        event.remove(AuditRecord, "before_insert", reject_audit)
    with factory() as db:
        location = db.get(Location, location_id)
        assert location.latitud == 1 and location.longitud == 2 and location.version == 0
        assert db.scalar(select(Photograph)).storage_clave == "anterior.webp"
        assert db.scalar(select(PhotoOperation)).estado == "preparada"
        assert db.scalar(select(AuditRecord).where(AuditRecord.accion == "ACTUALIZAR_DATOS_UBICACION")) is None
    monkeypatch.setenv("GPS_LIMITE_BUENA", "6")
    monkeypatch.setenv("GPS_LIMITE_ACEPTABLE", "7")
    assert client.put(f"/ubicaciones/{location_id}/actualizacion", headers=auth, json=body).json() == {"estado": "finalizada"}
    assert "anterior.webp" not in objects


def test_borrador_antiguo_incompleto_se_completa_con_motivo(api, monkeypatch):
    from app.fotografia import replace_photo
    from app.schemas import PhotographReplace

    client, factory = api
    objects = {"anterior.webp": b"original"}

    class FakeStorage:
        fail = True
        def get(self, key):
            return objects.get(key)
        def put(self, key, content):
            if self.fail:
                raise RuntimeError("interrupción")
            objects[key] = content
        def delete(self, key):
            objects.pop(key, None)

    monkeypatch.setattr("app.main.Storage", FakeStorage)
    auth = headers(client)
    reason = client.post("/motivos-actualizacion", headers=auth, json={"nombre": "Corrección"}).json()
    with factory() as db:
        actor = db.scalar(select(User).where(User.username == "ADMIN"))
        db.add(Contract(kardex="legacy"))
        db.flush()
        loc = Location(kardex="legacy")
        db.add(loc)
        db.flush()
        db.add(Photograph(ubicacion_id=loc.id, storage_bucket="fachada", storage_clave="anterior.webp", registrado_por=actor.id))
        db.commit()
        location_id = loc.id
        image = io.BytesIO()
        Image.new("RGB", (10, 10), "green").save(image, format="JPEG")
        legacy = {"idempotencia": str(uuid4()),
                  "version": client.get(f"/ubicaciones/{location_id}/fotografia", headers=auth).headers["x-foto-version"],
                  "fotografia_base64": base64.b64encode(image.getvalue()).decode()}
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as interrupted:
            replace_photo(location_id, PhotographReplace(**legacy), actor, db, FakeStorage())
        assert interrupted.value.status_code == 503
    FakeStorage.fail = False
    assert client.put(f"/ubicaciones/{location_id}/fotografia", headers=auth, json=legacy).status_code == 409
    body = {"idempotencia": legacy["idempotencia"], "version": 0, "motivo_id": reason["id"],
            "foto_version": legacy["version"], "fotografia_base64": legacy["fotografia_base64"]}
    assert client.put(f"/ubicaciones/{location_id}/actualizacion", headers=auth, json=body).json() == {"estado": "finalizada"}
    assert len(client.get(f"/ubicaciones/{location_id}/actualizaciones", headers=auth).json()) == 1


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


def test_unified_starts_photo_recovery_when_enabled(tmp_path, monkeypatch):
    started = Event()

    async def recovery():
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setenv("VISTAGEO_PHOTO_CLEANUP_ENABLED", "true")
    monkeypatch.setattr("app.main.recovery_loop", recovery)
    (tmp_path / "index.html").write_text("<html>frontend</html>")
    (tmp_path / "assets").mkdir()
    with TestClient(create_unified_app(tmp_path)):
        assert started.wait(timeout=2)


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


def test_photo_storage_errors_are_not_reported_as_missing(api, monkeypatch, caplog):
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
    from app.storage import Storage
    monkeypatch.setattr("app.main.Storage", Storage)
    monkeypatch.setattr("app.storage.database_url", lambda: (
        "postgresql+psycopg://postgres.abcdefghijklmnopqrst:password-test@pool.example/postgres"
        "?sslmode=verify-full&sslrootcert=ca"
    ))
    monkeypatch.setenv("SUPABASE_URL", "https://abcdefghijklmnopqrst.supabase.co/storage/v1")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "sb_secret_test")
    response = client.get(f"/ubicaciones/{location_id}/fotografia", headers=headers(client))
    assert response.status_code == 502
    assert response.json()["detail"] == "Fotografía no disponible"
    assert "SUPABASE_URL contiene componentes adicionales" in caplog.text
    assert "password-test" not in caplog.text and "sb_secret_test" not in caplog.text


def test_reemplazo_fotografia_exige_permisos_y_preserva_ubicacion(api, monkeypatch):
    client, factory = api
    objects = {"anterior.webp": b"foto anterior"}

    class FakeStorage:
        def get(self, key):
            return objects.get(key)

        def put(self, key, content):
            objects[key] = content

        def delete(self, key):
            objects.pop(key, None)

    monkeypatch.setattr("app.main.Storage", FakeStorage)
    with factory() as db:
        admin_id = db.scalar(select(User.id).where(User.username == "ADMIN"))
        db.add_all([Contract(kardex="Ab-1 "), Contract(kardex="sin-foto")])
        db.flush()
        created_at = datetime(2026, 1, 2, tzinfo=timezone.utc)
        location, empty = Location(kardex="Ab-1 ", creado_por=admin_id, creado_en=created_at), Location(kardex="sin-foto")
        db.add_all([location, empty])
        db.flush()
        revision = LocationRevision(ubicacion_id=location.id, latitud=-16, longitud=-68, cerrada=True)
        db.add(revision)
        db.flush()
        location.revision_actual_id = revision.id
        db.add(Photograph(ubicacion_id=location.id, storage_bucket="fachada", storage_clave="anterior.webp",
                          sha256=hashlib.sha256(objects["anterior.webp"]).hexdigest(), registrado_por=admin_id))
        db.commit()
        location_id, empty_id, revision_id = location.id, empty.id, revision.id
    image = io.BytesIO()
    Image.new("RGB", (20, 10), "blue").save(image, format="JPEG")
    auth = headers(client, "tech", "testpass3")
    reason = client.post("/motivos-actualizacion", headers=headers(client), json={"nombre": "Corrección"}).json()
    body = {"idempotencia": str(uuid4()), "version": 0, "motivo_id": reason["id"], "foto_version": "0" * 64,
            "fotografia_base64": base64.b64encode(image.getvalue()).decode()}
    path = f"/ubicaciones/{location_id}/actualizacion"
    photo_path = f"/ubicaciones/{location_id}/fotografia"
    assert client.put(path, headers=auth, json=body).status_code == 403
    with factory() as db:
        db.scalar(select(Role).where(Role.name == "TECNICO")).permissions = [
            db.scalar(select(Permission).where(Permission.name == "ubicaciones.fotografia.editar"))
        ]
        db.commit()
    assert client.put(path, headers=auth, json=body).status_code == 403
    with factory() as db:
        db.scalar(select(Role).where(Role.name == "TECNICO")).permissions = list(db.scalars(select(Permission).where(
            Permission.name.in_(["ubicaciones.fotografia.editar", "ubicaciones.consultar"])
        )).all())
        db.commit()
    response = client.get(photo_path, headers=auth)
    body["foto_version"] = response.headers["x-foto-version"]
    assert client.put(path, headers=auth, json={**body, "latitud": 0}).status_code == 422
    assert client.put(f"/ubicaciones/{empty_id}/actualizacion", headers=auth, json=body).status_code == 404
    assert client.put(photo_path, headers=auth, json={"idempotencia": body["idempotencia"],
                      "version": body["foto_version"], "fotografia_base64": body["fotografia_base64"]}).status_code == 409
    assert client.put(path, headers=auth, json=body).json() == {"estado": "finalizada"}
    assert "anterior.webp" not in objects
    assert client.put(path, headers=auth, json=body).json() == {"estado": "finalizada"}
    assert client.put(path, headers=auth, json={**body, "idempotencia": str(uuid4())}).status_code == 412
    updated = client.get(photo_path, headers=auth)
    assert updated.status_code == 200 and updated.headers["x-foto-version"] != body["foto_version"]
    with factory() as db:
        photo = db.scalar(select(Photograph).where(Photograph.ubicacion_id == location_id))
        location = db.get(Location, location_id)
        assert location.kardex == "Ab-1 " and location.revision_actual_id == revision_id
        assert location.creado_por == admin_id and location.creado_en.replace(tzinfo=timezone.utc) == created_at
        assert photo.storage_clave in objects and photo.sha256 == hashlib.sha256(objects[photo.storage_clave]).hexdigest()
        audit = db.scalar(select(AuditRecord).where(AuditRecord.accion == "CONFIRMAR_REEMPLAZO_FOTOGRAFIA"))
        assert audit.detalles["sha256_anterior"] == hashlib.sha256(b"foto anterior").hexdigest()


def test_reemplazo_reintenta_limpieza_sin_borrar_foto_vigente(api, monkeypatch):
    from app.fotografia import cleanup_operation, recover_pending_replacements

    client, factory = api
    objects = {"anterior.webp": b"foto anterior"}

    class FakeStorage:
        fail = True
        deleted = []

        def get(self, key):
            return objects.get(key)

        def put(self, key, content):
            objects[key] = content

        def delete(self, key):
            self.deleted.append(key)
            if self.fail:
                raise RuntimeError("Storage interrumpido")
            objects.pop(key, None)

    monkeypatch.setattr("app.main.Storage", FakeStorage)
    monkeypatch.setattr("app.fotografia.Storage", FakeStorage)
    monkeypatch.setattr("app.fotografia.session_factory", lambda: factory)
    with factory() as db:
        user = db.scalar(select(User).where(User.username == "ADMIN"))
        db.add(Contract(kardex="test-limpieza"))
        db.flush()
        location = Location(kardex="test-limpieza")
        db.add(location)
        db.flush()
        db.add(Photograph(ubicacion_id=location.id, storage_bucket="fachada", storage_clave="anterior.webp",
                          registrado_por=user.id))
        db.commit()
        location_id = location.id
    auth = headers(client)
    photo_path = f"/ubicaciones/{location_id}/fotografia"
    path = f"/ubicaciones/{location_id}/actualizacion"
    version = client.get(photo_path, headers=auth).headers["x-foto-version"]
    reason = client.post("/motivos-actualizacion", headers=auth, json={"nombre": "Corrección"}).json()
    image = io.BytesIO()
    Image.new("RGB", (10, 10), "red").save(image, format="JPEG")
    body = {"idempotencia": str(uuid4()), "version": 0, "foto_version": version, "motivo_id": reason["id"],
            "fotografia_base64": base64.b64encode(image.getvalue()).decode()}
    assert client.put(path, headers=auth, json=body).json() == {"estado": "pendiente_limpieza"}
    with factory() as db:
        operation = db.scalar(select(PhotoOperation))
        photo = db.scalar(select(Photograph))
        current_key = photo.storage_clave
        assert operation.limpieza_clave == "anterior.webp" and current_key in objects
        operation.limpieza_clave = current_key
        db.commit()
        assert cleanup_operation(db, operation.id, FakeStorage()) == "pendiente_limpieza"
        assert current_key not in FakeStorage.deleted
        operation.limpieza_clave = "anterior.webp"
        db.commit()
    FakeStorage.fail = False
    recover_pending_replacements()
    with factory() as db:
        assert db.scalar(select(PhotoOperation)).estado == "finalizada"
    assert "anterior.webp" not in objects and current_key in objects
    assert client.put(path, headers=auth, json=body).json() == {"estado": "finalizada"}


def test_reemplazo_con_fallo_de_carga_conserva_foto_anterior(api, monkeypatch):
    client, factory = api
    objects = {"anterior.webp": b"original"}

    class FakeStorage:
        fail = True

        def get(self, key):
            return objects.get(key)

        def put(self, key, content):
            if self.fail:
                raise RuntimeError("interrupción de carga")
            objects[key] = content

        def delete(self, key):
            objects.pop(key, None)

    monkeypatch.setattr("app.main.Storage", FakeStorage)
    with factory() as db:
        actor_id = db.scalar(select(User.id).where(User.username == "ADMIN"))
        db.add(Contract(kardex="fallo-carga"))
        db.flush()
        location = Location(kardex="fallo-carga")
        db.add(location)
        db.flush()
        db.add(Photograph(ubicacion_id=location.id, storage_bucket="fachada",
                          storage_clave="anterior.webp", registrado_por=actor_id))
        db.commit()
        location_id = location.id
    auth = headers(client)
    photo_path = f"/ubicaciones/{location_id}/fotografia"
    path = f"/ubicaciones/{location_id}/actualizacion"
    version = client.get(photo_path, headers=auth).headers["x-foto-version"]
    reason = client.post("/motivos-actualizacion", headers=auth, json={"nombre": "Corrección"}).json()
    image = io.BytesIO()
    Image.new("RGB", (10, 10), "blue").save(image, format="JPEG")
    body = {"idempotencia": str(uuid4()), "version": 0, "foto_version": version, "motivo_id": reason["id"],
            "fotografia_base64": base64.b64encode(image.getvalue()).decode()}
    assert client.put(path, headers=auth, json=body).status_code == 503
    assert objects == {"anterior.webp": b"original"}
    with factory() as db:
        assert db.scalar(select(Photograph)).storage_clave == "anterior.webp"
        assert db.scalar(select(PhotoOperation)).estado == "preparada"
    FakeStorage.fail = False
    assert client.put(path, headers=auth, json=body).json() == {"estado": "finalizada"}
    assert "anterior.webp" not in objects


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
            "fotografia_base64": base64.b64encode(image.getvalue()).decode(), "metodo_coordenadas": "GPS_DISPOSITIVO", "coordenadas_confirmadas": True, **GPS_SAMPLE}
    assert client.post("/registro-ubicacion", headers=auth, json={**body, "creado_por": 1}).status_code == 422
    assert client.post("/registro-ubicacion", headers=auth, json={**body, "creado_en": "2000-01-01T00:00:00Z"}).status_code == 422
    assert client.get("/configuracion-gps", headers=auth).json() == {
        "excelente": 5, "buena": 10, "aceptable": 20, "baja": 50,
    }
    assert client.post("/registro-ubicacion", headers=auth, json={**body, "precision_metros": 20.01}).status_code == 422
    assert client.post("/registro-ubicacion", headers=auth, json={**body, "precision_metros": None}).status_code == 422
    assert client.post("/registro-ubicacion", headers=auth, json={**body, "capturado_en": None}).status_code == 422
    start = datetime.now(timezone.utc)
    assert client.post("/registro-ubicacion", headers=auth, json=body).status_code == 503
    with factory() as db:
        location = db.scalar(select(Location).where(Location.kardex == body["kardex"]))
        assert location is not None and location.revision_actual_id is None
        assert db.scalar(select(Photograph)) is None
        assert db.scalar(select(PhotoOperation)).estado == "preparada"
        db.scalar(select(Role).where(Role.name == "GERENTE")).permissions = [
            db.scalar(select(Permission).where(Permission.name == "ubicaciones.registrar"))
        ]
        db.commit()
    register_only = headers(client, "manager", "testpass2")
    pending = client.get("/ubicaciones", headers=register_only, params={"kardex": body["kardex"]}).json()[0]
    assert pending["registro_pendiente"] is True
    assert pending["creado_por_nombre"] is None and pending["creado_en"] is None
    assert client.get("/ubicaciones", headers=register_only, params={"kardex_contiene": "aB"}).status_code == 403
    assert client.get("/ubicaciones", headers=auth, params={"kardex_contiene": "aB"}).json()[0]["registro_pendiente"] is True
    assert client.post("/registro-ubicacion", headers=auth, json={**body, "latitud": "0"}).status_code == 409
    response = client.post("/registro-ubicacion", headers=auth, json=body)
    assert response.status_code == 201
    assert response.json()["kardex"] == "aB-1 "
    assert response.json()["metodo_coordenadas"] == "GPS_DISPOSITIVO"
    assert response.json()["precision_metros"] == GPS_SAMPLE["precision_metros"]
    assert response.json()["creado_por_nombre"] == "TECH"
    assert start <= as_utc(datetime.fromisoformat(response.json()["creado_en"])) <= datetime.now(timezone.utc)
    assert client.post("/registro-ubicacion", headers=auth, json=body).status_code == 201
    assert client.post("/registro-ubicacion", headers=auth, json={**body, "precision_metros": 9}).status_code == 409
    assert client.post("/registro-ubicacion", headers=auth, json={**body, "idempotencia": str(uuid4())}).status_code == 409
    with factory() as db:
        photo = db.scalar(select(Photograph))
        revision = db.get(LocationRevision, response.json()["revision_actual_id"])
        assert photo.registrado_por == revision.responsable_id
        assert revision.metodo_coordenadas == "GPS_DISPOSITIVO" and revision.url_gps is None
        assert revision.precision_metros == GPS_SAMPLE["precision_metros"] and revision.fecha_evento is not None
        assert db.get(Location, response.json()["id"]).creado_por == revision.responsable_id
        assert len(db.scalars(select(Photograph)).all()) == 1
        assert db.scalar(select(PhotoOperation)).estado == "finalizada"
    result = client.get("/ubicaciones", headers=auth, params={"kardex_contiene": "b-1"}).json()[0]
    assert result["kardex"] == "aB-1 " and result["creado_por_nombre"] == "TECH"
    assert result["registro_pendiente"] is False
    assert result["creado_en"] == response.json()["creado_en"]
    assert client.get(f"/ubicaciones/{response.json()['id']}/fotografia", headers=auth).status_code == 200
    assert client.get("/usuarios", headers=auth).status_code == 403
    admin = headers(client)
    reason = client.post("/motivos-actualizacion", headers=admin, json={"nombre": "Cambio"}).json()
    assert client.put(f"/ubicaciones/{response.json()['id']}/actualizacion", headers=admin,
                      json={"idempotencia": str(uuid4()), "version": 0, "motivo_id": reason["id"],
                            "latitud": 1, "longitud": 2, **GPS_SAMPLE}).status_code == 200
    updated = client.get(f"/ubicaciones/{response.json()['id']}", headers=auth).json()
    assert updated["creado_por_nombre"] == "TECH" and updated["creado_en"] == result["creado_en"]


def test_field_registration_checks_permissions_and_invalid_photo_before_writes(api, monkeypatch):
    client, factory = api
    auth = headers(client, "tech", "testpass3")

    class FakeStorage:
        pass

    monkeypatch.setattr("app.main.Storage", FakeStorage)
    body = {"idempotencia": str(uuid4()), "kardex": "nuevo", "latitud": 1, "longitud": 2,
            "fotografia_base64": "aW52YWxpZG8=", "metodo_coordenadas": "GPS_DISPOSITIVO", "coordenadas_confirmadas": True}
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


def test_gps_quality_limits_are_configurable_and_enforced(api, monkeypatch):
    client, factory = api
    objects = {}

    class FakeStorage:
        def get(self, key):
            return objects.get(key)

        def put(self, key, content):
            objects[key] = content

    monkeypatch.setattr("app.main.Storage", FakeStorage)
    monkeypatch.setenv("GPS_LIMITE_ACEPTABLE", "15")
    auth = headers(client)
    assert client.get("/configuracion-gps", headers=auth).json()["aceptable"] == 15
    image = io.BytesIO()
    Image.new("RGB", (10, 10), "blue").save(image, format="JPEG")
    body = {
        "idempotencia": str(uuid4()), "kardex": "CALIDAD", "latitud": 1, "longitud": 2,
        "fotografia_base64": base64.b64encode(image.getvalue()).decode(),
        "metodo_coordenadas": "GPS_DISPOSITIVO", "coordenadas_confirmadas": True, **GPS_SAMPLE,
    }
    assert client.post("/registro-ubicacion", headers=auth, json={**body, "precision_metros": 15.0001}).status_code == 422
    assert client.post("/registro-ubicacion", headers=auth, json={**body, "precision_metros": -1}).status_code == 422
    result = client.post("/registro-ubicacion", headers=auth, json={**body, "precision_metros": 15})
    assert result.status_code == 201 and result.json()["precision_metros"] == 15
    with factory() as db:
        assert db.scalar(select(LocationRevision)).precision_metros == 15


@pytest.mark.parametrize("short", [False, True])
def test_shared_registration_requires_photo_and_preserves_provenance(api, monkeypatch, short):
    client, factory = api
    with factory() as db:
        db.scalar(select(Role).where(Role.name == "GERENTE")).permissions = list(db.scalars(
            select(Permission).where(Permission.name.in_(["ubicaciones.registrar", "ubicaciones.consultar"]))
        ))
        db.commit()
    objects = {}

    class FakeStorage:
        def get(self, key):
            return objects.get(key)

        def put(self, key, content):
            objects[key] = content

    monkeypatch.setattr("app.main.Storage", FakeStorage)
    monkeypatch.setattr("app.enlaces_gps.redirect_location", lambda _: "https://www.google.com/maps?q=-16.5,-68.1")
    auth = headers(client, "manager", "testpass2")
    denied = headers(client, "tech", "testpass3")
    url = "https://maps.app.goo.gl/abc" if short else "https://www.google.com/maps?q=-16.5,-68.1"
    assert client.post("/registro-ubicacion/interpretar-enlace", headers=denied, json={"url_gps": url}).status_code == 403
    preview = client.post("/registro-ubicacion/interpretar-enlace", headers=auth, json={"url_gps": url})
    assert preview.status_code == 200 and preview.json() == {"latitud": "-16.5", "longitud": "-68.1"}
    image = io.BytesIO()
    Image.new("RGB", (20, 10), "blue").save(image, format="JPEG")
    body = {
        "idempotencia": str(uuid4()), "kardex": "COMPARTIDO",
        "latitud": "-16.5", "longitud": "-68.1", "metodo_coordenadas": "ENLACE_COMPARTIDO",
        "url_gps": url, "fotografia_base64": base64.b64encode(image.getvalue()).decode(), "coordenadas_confirmadas": True,
    }
    assert client.post("/registro-ubicacion", headers=denied, json=body).status_code == 403
    assert client.post("/registro-ubicacion", headers=auth, json={k: v for k, v in body.items() if k != "metodo_coordenadas"}).status_code == 422
    assert client.post("/registro-ubicacion", headers=auth, json={k: v for k, v in body.items() if k != "fotografia_base64"}).status_code == 422
    assert client.post("/registro-ubicacion", headers=auth, json={k: v for k, v in body.items() if k != "coordenadas_confirmadas"}).status_code == 422
    assert client.post("/registro-ubicacion", headers=auth, json={**body, "coordenadas_confirmadas": False}).status_code == 422
    assert client.post("/registro-ubicacion", headers=auth, json={**body, "latitud": "91"}).status_code == 422
    assert client.post("/registro-ubicacion", headers=auth, json={**body, "latitud": "0"}).status_code == 422
    assert client.post("/registro-ubicacion", headers=auth, json={**body, "metodo_coordenadas": "GPS_DISPOSITIVO"}).status_code == 422
    assert client.post("/registro-ubicacion", headers=auth, json={**body, "precision_metros": 0}).status_code == 422
    result = client.post("/registro-ubicacion", headers=auth, json=body)
    assert result.status_code == 201
    location = result.json()
    assert location["metodo_coordenadas"] == "ENLACE_COMPARTIDO" and location["url_gps"] == url
    assert location["precision_metros"] is None and location["capturado_en"] is None
    assert client.get(f"/ubicaciones/{location['id']}/fotografia", headers=auth).status_code == 200
    revision = client.get(f"/ubicaciones/{location['id']}/revisiones", headers=auth).json()[0]
    assert revision["metodo_coordenadas"] == "ENLACE_COMPARTIDO" and revision["url_gps"] == url
    assert revision["precision_metros"] is None and revision["fecha_evento"] is None
    monkeypatch.setattr("app.enlaces_gps.redirect_location", lambda _: pytest.fail("No debe resolverse un reintento"))
    assert client.post("/registro-ubicacion", headers=auth, json=body).status_code == 201
    assert client.post("/registro-ubicacion", headers=auth, json={**body, "url_gps": url + "x"}).status_code == 409
    admin = headers(client)
    reason = client.post("/motivos-actualizacion", headers=admin, json={"nombre": "Traslado"}).json()
    assert client.put(f"/ubicaciones/{location['id']}/actualizacion", headers=admin, json={
        "idempotencia": str(uuid4()), "version": 0, "motivo_id": reason["id"], "latitud": 1, "longitud": 2, **GPS_SAMPLE,
    }).status_code == 200
    current = client.get(f"/ubicaciones/{location['id']}", headers=auth).json()
    assert current["metodo_coordenadas"] == "GPS_DISPOSITIVO" and current["url_gps"] is None
    assert client.get(f"/ubicaciones/{location['id']}/revisiones", headers=auth).json()[0]["url_gps"] == url


def test_legacy_pending_draft_keeps_closed_revision_and_retries(api, monkeypatch):
    client, factory = api
    objects = {}

    class FakeStorage:
        failures = 2

        def get(self, key):
            return objects.get(key)

        def put(self, key, content):
            if FakeStorage.failures:
                FakeStorage.failures -= 1
                raise RuntimeError("Storage no disponible")
            objects[key] = content

    monkeypatch.setattr("app.main.Storage", FakeStorage)
    auth = headers(client)
    image = io.BytesIO()
    Image.new("RGB", (20, 10), "blue").save(image, format="JPEG")
    body = {
        "idempotencia": str(uuid4()), "kardex": "BORRADOR",
        "latitud": 1, "longitud": 2, "metodo_coordenadas": "GPS_DISPOSITIVO",
        "coordenadas_confirmadas": True, "fotografia_base64": base64.b64encode(image.getvalue()).decode(), **GPS_SAMPLE,
    }
    assert client.post("/registro-ubicacion", headers=auth, json=body).status_code == 503
    with factory() as db:
        original = db.scalar(select(LocationRevision))
        original.metodo_coordenadas = None
        original.precision_metros = None
        original.fecha_evento = None
        db.commit()
    body = {key: value for key, value in body.items() if key not in GPS_SAMPLE}
    assert client.post("/registro-ubicacion", headers=auth, json=body).status_code == 503
    assert client.post("/registro-ubicacion", headers=auth, json=body).status_code == 201
    with factory() as db:
        revisions = db.scalars(select(LocationRevision).order_by(LocationRevision.id)).all()
        assert [row.metodo_coordenadas for row in revisions] == [None, "GPS_DISPOSITIVO"]
        assert db.scalar(select(Location)).revision_actual_id == revisions[-1].id
        assert db.scalar(select(Photograph)) is not None


def test_creator_metadata_requires_location_consult_permission(api):
    client, factory = api
    with factory() as db:
        tech = db.scalar(select(User).where(User.username == "TECH"))
        tech.role.permissions = [db.scalar(select(Permission).where(Permission.name == "ubicaciones.registrar"))]
        db.add(Contract(kardex="privado"))
        db.add(Contract(kardex="historico"))
        db.flush()
        db.add(Location(kardex="privado", creado_por=tech.id, creado_en=datetime.now(timezone.utc)))
        db.add(Location(kardex="historico"))
        db.commit()
    auth = headers(client, "tech", "testpass3")
    result = client.get("/ubicaciones", headers=auth, params={"kardex": "privado"}).json()[0]
    assert result["creado_por_nombre"] is None and result["creado_en"] is None
    assert client.get("/ubicaciones", headers=auth, params={"kardex_contiene": "priv"}).status_code == 403
    admin = headers(client)
    historical = client.get("/ubicaciones", headers=admin, params={"kardex": "historico"}).json()[0]
    assert historical["creado_por_nombre"] is None and historical["creado_en"] is None


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
            "fotografia_base64": encoded, "metodo_coordenadas": "GPS_DISPOSITIVO", "coordenadas_confirmadas": True, **GPS_SAMPLE}
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


def test_catalogo_solo_permite_roles_oficiales(api):
    client, factory = api
    admin = headers(client)
    assert client.post("/roles", headers=admin, json={"name": "CAJERO"}).status_code == 422
    created = client.post("/roles", headers=admin, json={"name": "JEFE TECNICO"})
    assert created.status_code == 201
    assert client.patch(f"/roles/{created.json()['id']}", headers=admin, json={"name": "OTRO"}).status_code == 403
    with factory() as db:
        retired = Role(name="CAJERO")
        db.add(retired)
        db.commit()
        retired_id = retired.id
    assert client.post("/usuarios", headers=admin, json={
        "username": "OTRO", "password": "NEWPASS9", "role_id": retired_id,
    }).status_code == 409


def test_roles_oficiales_asignables_y_gerencia_conserva_controles(api):
    client, factory = api
    admin = headers(client)
    manager = headers(client, "manager", "testpass2")
    with factory() as db:
        db.scalar(select(Role).where(Role.name == "GERENTE")).name = "GERENCIA"
        db.add_all([Role(name="JEFE OPERATIVO"), Role(name="JEFE TECNICO")])
        db.commit()
        roles = [(role.id, role.name) for role in db.scalars(select(Role)).all()]
    assert client.get("/permisos", headers=manager).status_code == 200
    for role_id, name in roles:
        created = client.post("/usuarios", headers=admin, json={
            "username": f"TEST_{role_id}", "password": "NEWPASS9", "role_id": role_id,
        })
        assert created.status_code == 201, name
        assert created.json()["role_id"] == role_id


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


def test_busqueda_parcial_literal_paginada_y_permisos(api):
    client, factory = api
    names = ["Ab-1", "ab-1 ", "X%_/-Y", "Xabc-Y"] + [f"abc-{n:03}" for n in range(35)]
    with factory() as db:
        db.add_all([Contract(kardex=name) for name in names])
        db.flush()
        db.add_all([Location(kardex=name) for name in names])
        db.scalar(select(Role).where(Role.name == "TECNICO")).permissions = [
            db.scalar(select(Permission).where(Permission.name == "ubicaciones.registrar"))
        ]
        db.scalar(select(Role).where(Role.name == "GERENTE")).permissions = [
            db.scalar(select(Permission).where(Permission.name == "ubicaciones.consultar"))
        ]
        db.commit()
    tech = headers(client, "tech", "testpass3")
    manager = headers(client, "manager", "testpass2")
    assert client.get("/ubicaciones", params={"kardex_contiene": "ab"}).status_code == 401
    assert client.get("/ubicaciones", headers=tech, params={"kardex": "Ab-1"}).json()[0]["kardex"] == "Ab-1"
    assert client.get("/ubicaciones", headers=tech, params={"kardex_contiene": "ab"}).status_code == 403
    assert client.get("/ubicaciones", headers=tech, params={"kardex": "Ab-1", "kardex_contiene": "ab"}).status_code == 403
    for query in ("%_", "_/", "/", "%"):
        result = client.get("/ubicaciones", headers=manager, params={"kardex_contiene": query})
        assert result.status_code == 200
        assert [row["kardex"] for row in result.json()] == ["X%_/-Y"]
    result = client.get("/ubicaciones", headers=manager, params={"kardex_contiene": "B-1"})
    assert [row["kardex"] for row in result.json()] == ["Ab-1", "ab-1 "]
    assert [row["kardex"] for row in client.get("/ubicaciones", headers=manager, params={"kardex_contiene": "1 "}).json()] == ["ab-1 "]
    assert client.get("/ubicaciones", headers=manager, params={"kardex": "ab-1"}).json() == []
    assert client.get("/ubicaciones", headers=tech, params={"kardex": "   "}).status_code == 422
    assert client.get("/ubicaciones", headers=manager, params={"kardex_contiene": " "}).status_code == 200
    assert client.get("/ubicaciones", headers=manager, params={"kardex_contiene": ""}).status_code == 422
    assert client.get("/ubicaciones", headers=manager, params={"kardex_contiene": "a\x00"}).status_code == 422
    assert client.get("/ubicaciones", headers=manager, params={"kardex": "Ab-1", "kardex_contiene": "ab"}).status_code == 422
    first = client.get("/ubicaciones", headers=manager, params={"kardex_contiene": "ABC-0", "limit": 25, "offset": 0}).json()
    second = client.get("/ubicaciones", headers=manager, params={"kardex_contiene": "ABC-0", "limit": 25, "offset": 25}).json()
    assert len(first) == 25 and len(second) == 10
    assert [row["kardex"] for row in first + second] == names[4:]
    assert all(row["registro_pendiente"] is False for row in first + second)


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
    with factory() as db:
        first = LocationRevision(ubicacion_id=location_id, url_gps="https://maps.example/one", cerrada=True)
        db.add(first)
        db.flush()
        db.get(Location, location_id).revision_actual_id = first.id
        db.get(Location, location_id).url_gps = first.url_gps
        db.commit()
        first_id = first.id
    assert client.post(url, headers=admin, json={"latitud": -16.5, "longitud": -68.1}).status_code == 410
    reason = client.post("/motivos-actualizacion", headers=admin, json={"nombre": "Cambio"}).json()
    assert client.put(f"/ubicaciones/{location_id}/actualizacion", headers=admin, json={
        "idempotencia": str(uuid4()), "version": 0, "motivo_id": reason["id"], "latitud": -16.5, "longitud": -68.1, **GPS_SAMPLE,
    }).status_code == 200
    assert client.get(f"/ubicaciones/{location_id}", headers=admin).json()["revision_actual_id"] == first_id
    assert [r["id"] for r in client.get(url, headers=admin).json()] == [first_id]
    assert client.get(url, headers=technician).status_code == 403
    with factory() as db:
        events = db.scalars(select(AuditRecord).where(AuditRecord.ubicacion_id == location_id).order_by(AuditRecord.id)).all()
        assert [event.accion for event in events] == ["CREAR_UBICACION", "ACTUALIZAR_DATOS_UBICACION"]


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
