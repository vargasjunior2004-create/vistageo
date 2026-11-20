import base64
import io
import os
import hashlib
import runpy
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

from app.database import create_database_engine, get_db
from app.fotografia import photo_version, replace_photo
from app.inventario_historico import save_inventory
from app.main import app, list_locations
from app.migrar_kardex import MigrationPlan, save_plan
from app.migrar_ubicaciones import LocationPlan, save_plan as save_location_plan
from app.migrar_fotografias import Photo, import_photo
from app.models import User
from app.registro_ubicacion import register_location
from app.schemas import FieldLocationCreate, PhotographReplace
from app.security import password_hash


@pytest.fixture
def db():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL no configurada para PostgreSQL desechable")
    if not url.startswith("postgresql+psycopg://"):
        raise ValueError("TEST_DATABASE_URL debe usar postgresql+psycopg")
    engine = create_engine(url)
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            yield connection
        finally:
            transaction.rollback()
    engine.dispose()


def rejected(db, sql, params=None):
    with pytest.raises(DBAPIError):
        with db.begin_nested():
            db.execute(text(sql), params or {})


def test_conexion_no_prepara_sentencias_incompatibles_con_pooler(db):
    engine = create_database_engine(os.environ["TEST_DATABASE_URL"])
    try:
        with engine.connect() as connection:
            assert connection.connection.driver_connection.prepare_threshold is None
            for _ in range(10):
                assert connection.execute(text("SELECT 1")).scalar_one() == 1
                connection.commit()
    finally:
        engine.dispose()


def create_user(db, name):
    role = db.execute(text("INSERT INTO roles (nombre) VALUES (:name) RETURNING id"), {"name": name}).scalar_one()
    return db.execute(text("""
        INSERT INTO usuarios (nombre_usuario, contrasena_hash, activo, rol_id,
            cambio_contrasena_obligatorio, intentos_fallidos, creado_en)
        VALUES (:name, 'hash-prueba', true, :role, false, 0, CURRENT_TIMESTAMP) RETURNING id
    """), {"name": name, "role": role}).scalar_one()


def create_location(db, kardex):
    db.execute(text("INSERT INTO contratos (kardex) VALUES (:k)"), {"k": kardex})
    return db.execute(text("INSERT INTO ubicaciones (kardex) VALUES (:k) RETURNING id"), {"k": kardex}).scalar_one()


def test_permisos_panel_migracion_con_roles_existentes(db):
    roles = ("ADMINISTRADOR", "GERENTE", "JEFE COMERCIAL", "TECNICO", "CAJERO", "CALL CENTER", "JEFE TECNICO")
    for role in roles:
        db.execute(text("INSERT INTO roles (nombre) VALUES (:name) ON CONFLICT DO NOTHING"), {"name": role})
    db.execute(text("INSERT INTO permisos (nombre) VALUES ('roles.consultar') ON CONFLICT DO NOTHING"))
    db.execute(text("""
        INSERT INTO rol_permisos (rol_id, permiso_id)
        SELECT roles.id, permisos.id FROM roles, permisos
        WHERE roles.nombre='TECNICO' AND permisos.nombre='roles.consultar'
        ON CONFLICT DO NOTHING
    """))
    migration = runpy.run_path(str(Path(__file__).parents[1] / "alembic/versions/0005_panel_permissions.py"))
    with Operations.context(MigrationContext.configure(db)):
        migration["upgrade"]()
        migration["upgrade"]()
    rows = db.execute(text("""
        SELECT roles.nombre, permisos.nombre FROM rol_permisos
        JOIN roles ON roles.id=rol_permisos.rol_id
        JOIN permisos ON permisos.id=rol_permisos.permiso_id
    """)).all()
    assigned = {(role, permission) for role, permission in rows}
    for role in ("GERENTE", "JEFE COMERCIAL", "TECNICO", "CAJERO", "CALL CENTER"):
        assert (role, "ubicaciones.consultar") in assigned
        assert (role, "ubicaciones.registrar") in assigned
    for role in ("GERENTE", "JEFE COMERCIAL"):
        assert (role, "usuarios.consultar") in assigned
        assert (role, "usuarios.gestionar") in assigned
    assert ("TECNICO", "roles.consultar") in assigned
    assert ("TECNICO", "usuarios.gestionar") not in assigned
    assert not any(role == "JEFE TECNICO" for role, _ in assigned)


def test_migracion_permiso_edicion_fotos_preserva_asignaciones(db):
    roles = ("TECNICO", "GERENTE", "JEFE COMERCIAL", "JEFE OPERATIVO", "JEFE TECNICO", "CAJERO", "CALL CENTER")
    for role in roles:
        db.execute(text("INSERT INTO roles (nombre) VALUES (:name) ON CONFLICT DO NOTHING"), {"name": role})
    for permission in ("ubicaciones.consultar", "ubicaciones.fotografia.editar"):
        db.execute(text("INSERT INTO permisos (nombre) VALUES (:name) ON CONFLICT DO NOTHING"), {"name": permission})
    migration = runpy.run_path(str(Path(__file__).parents[1] / "alembic/versions/0006_photo_edit_permission.py"))
    with Operations.context(MigrationContext.configure(db)):
        migration["upgrade"]()
        migration["upgrade"]()
    rows = db.execute(text("""
        SELECT roles.nombre, permisos.nombre FROM rol_permisos
        JOIN roles ON roles.id=rol_permisos.rol_id
        JOIN permisos ON permisos.id=rol_permisos.permiso_id
    """)).all()
    for role in roles:
        assert (role, "ubicaciones.consultar") in rows
        assert (role, "ubicaciones.fotografia.editar") in rows


def test_kardex_exactos_y_procedencia(db):
    for kardex in ("123", "123 ", "123-A", "abc", "ABC", "á", "a"):
        db.execute(text("INSERT INTO contratos (kardex) VALUES (:k)"), {"k": kardex})
    rejected(db, "INSERT INTO contratos (kardex) VALUES ('123')")
    rejected(db, "INSERT INTO contratos (kardex) VALUES ('   ')")
    rejected(db, "INSERT INTO ubicaciones (kardex) VALUES ('inexistente')")
    db.execute(text("INSERT INTO ubicaciones (kardex) VALUES ('123')"))
    rejected(db, "INSERT INTO ubicaciones (kardex) VALUES ('123')")
    source_id = db.execute(text("""
        INSERT INTO procedencia_historica (ruta_original, tipo, sha256)
        VALUES ('123/documento.docx', 'documento', :sha) RETURNING id
    """), {"sha": "a" * 64}).scalar_one()
    source = db.execute(text("SELECT kardex, estado_revision FROM procedencia_historica WHERE id=:id"), {"id": source_id}).one()
    assert source == (None, "PENDIENTE")
    rejected(db, "UPDATE procedencia_historica SET kardex='inexistente' WHERE id=:id", {"id": source_id})
    rejected(db, "UPDATE procedencia_historica SET sha256='no-valido' WHERE id=:id", {"id": source_id})
    db.execute(text("UPDATE procedencia_historica SET kardex='123' WHERE id=:id"), {"id": source_id})


def test_busqueda_parcial_en_postgresql_preserva_kardex_y_compara_unicode(db):
    actor_id = create_user(db, "ADMINISTRADOR")
    for kardex in ("Áb-1", "áb-1 ", "Ab-1", "X%_/-Y", "Xabc-Y"):
        create_location(db, kardex)
    factory = sessionmaker(bind=db, expire_on_commit=False, join_transaction_mode="create_savepoint")
    with factory() as session:
        actor = session.get(User, actor_id)
        search = lambda value: list_locations(
            kardex=None, limit=100, offset=0, actor=actor, db=session, kardex_contiene=value
        )
        assert [row.kardex for row in search("ÁB-1")] == ["Áb-1", "áb-1 "]
        assert [row.kardex for row in search("%_/")] == ["X%_/-Y"]
        assert [row.kardex for row in search("1 ")] == ["áb-1 "]
        assert [row.kardex for row in list_locations(
            kardex="Áb-1", limit=100, offset=0, actor=actor, db=session
        )] == ["Áb-1"]


def test_revision_actual_y_coordenadas(db):
    first = create_location(db, "revision-1")
    second = create_location(db, "revision-2")
    rejected(db, "INSERT INTO revisiones_ubicacion (ubicacion_id, latitud) VALUES (:id, 1)", {"id": first})
    rejected(db, "INSERT INTO revisiones_ubicacion (ubicacion_id, latitud, longitud) VALUES (:id, 91, 0)", {"id": first})
    revision = db.execute(text("""
        INSERT INTO revisiones_ubicacion (ubicacion_id, latitud, longitud)
        VALUES (:id, -16.5, -68.1) RETURNING id
    """), {"id": first}).scalar_one()
    rejected(db, "UPDATE ubicaciones SET revision_actual_id=:rev WHERE id=:id", {"rev": revision, "id": first})
    db.execute(text("UPDATE revisiones_ubicacion SET cerrada=true WHERE id=:rev"), {"rev": revision})
    rejected(db, "UPDATE ubicaciones SET revision_actual_id=:rev WHERE id=:id", {"rev": revision, "id": second})
    db.execute(text("UPDATE ubicaciones SET revision_actual_id=:rev WHERE id=:id"), {"rev": revision, "id": first})
    rejected(db, "UPDATE revisiones_ubicacion SET latitud=0 WHERE id=:rev", {"rev": revision})
    rejected(db, "DELETE FROM revisiones_ubicacion WHERE id=:rev", {"rev": revision})


def test_fotografia_trazabilidad_y_auditoria(db):
    creator = create_user(db, "foto-creador")
    editor = create_user(db, "foto-editor")
    location = create_location(db, "foto-1")
    rejected(db, """
        INSERT INTO fotografias (ubicacion_id, storage_bucket, storage_clave, registrado_por)
        VALUES (:loc, 'fotos', 'foto-1', :user)
    """, {"loc": location, "user": creator})
    db.execute(text("SELECT set_config('app.usuario_id', :actor, true)"), {"actor": str(creator)})
    photo = db.execute(text("""
        INSERT INTO fotografias (ubicacion_id, storage_bucket, storage_clave, registrado_por)
        VALUES (:loc, 'fotos', 'foto-1', :user) RETURNING id
    """), {"loc": location, "user": editor}).scalar_one()
    rejected(db, """
        INSERT INTO fotografias (ubicacion_id, storage_bucket, storage_clave, registrado_por)
        VALUES (:loc, 'fotos', 'foto-2', :user)
    """, {"loc": location, "user": creator})
    db.execute(text("SELECT set_config('app.usuario_id', :actor, true)"), {"actor": str(editor)})
    rejected(db, "UPDATE fotografias SET registrado_por=:u WHERE id=:id", {"u": editor, "id": photo})
    db.execute(text("UPDATE fotografias SET sha256=:sha WHERE id=:id"), {"sha": "a" * 64, "id": photo})
    db.execute(text("UPDATE fotografias SET storage_clave='foto-nueva' WHERE id=:id"), {"id": photo})
    row = db.execute(text("SELECT registrado_por, actualizado_por, actualizado_en FROM fotografias WHERE id=:id"), {"id": photo}).one()
    assert row.registrado_por == creator and row.actualizado_por == editor and row.actualizado_en is not None
    db.execute(text("DELETE FROM fotografias WHERE id=:id"), {"id": photo})
    events = db.execute(text("SELECT accion, usuario_id, detalles FROM auditoria WHERE ubicacion_id=:loc ORDER BY id"), {"loc": location}).all()
    assert [(e.accion, e.usuario_id) for e in events] == [
        ("CREAR_FOTOGRAFIA", creator), ("ACTUALIZAR_FOTOGRAFIA", editor),
        ("REEMPLAZAR_FOTOGRAFIA", editor), ("ELIMINAR_FOTOGRAFIA", editor),
    ]
    assert all(e.detalles["fotografia_id"] == photo for e in events)
    rejected(db, "DELETE FROM auditoria WHERE ubicacion_id=:loc", {"loc": location})


def test_operacion_activa_y_clave_limpieza(db):
    user = create_user(db, "operacion-usuario")
    location = create_location(db, "operacion-1")
    sql = """
        INSERT INTO operaciones_fotografia
        (idempotencia, ubicacion_id, usuario_id, tipo, estado, nuevo_bucket, nueva_clave)
        VALUES (:token, :loc, :user, 'CREAR', 'preparada', 'fotos', :key)
    """
    params = {"token": uuid4(), "loc": location, "user": user, "key": "objeto-1"}
    db.execute(text(sql), params)
    rejected(db, sql, {"token": uuid4(), "loc": location, "user": user, "key": "objeto-2"})
    rejected(db, "UPDATE operaciones_fotografia SET limpieza_bucket='fotos', limpieza_clave='otro' WHERE idempotencia=:token", {"token": params["token"]})
    rejected(db, "DELETE FROM operaciones_fotografia WHERE idempotencia=:token", {"token": params["token"]})
    db.execute(text("UPDATE operaciones_fotografia SET estado='finalizada' WHERE idempotencia=:token"), {"token": params["token"]})
    db.execute(text(sql), {"token": uuid4(), "loc": location, "user": user, "key": "objeto-2"})


def test_foto_historica_exige_procedencia_y_modificaciones_exigen_actor(db):
    location = create_location(db, "historico-1")
    other = create_location(db, "historico-2")
    source = db.execute(text("""
        INSERT INTO procedencia_historica (ruta_original, tipo, sha256, kardex, estado_revision)
        VALUES ('raiz/historico-1/foto.jpg', 'imagen', :sha, 'historico-1', 'CONFIRMADO') RETURNING id
    """), {"sha": "a" * 64}).scalar_one()
    sql = """
        INSERT INTO fotografias (ubicacion_id, storage_bucket, storage_clave, sha256, sha256_original, procedencia_id)
        VALUES (:loc, 'fotos', :key, :optimized_sha, :sha, :source) RETURNING id
    """
    params = {"loc": location, "key": "hist-1", "sha": "a" * 64, "optimized_sha": "c" * 64, "source": source}
    rejected(db, sql, {**params, "source": None})
    rejected(db, sql, {**params, "sha": "b" * 64})
    rejected(db, sql, {**params, "loc": other})
    db.execute(text("UPDATE procedencia_historica SET estado_revision='PENDIENTE' WHERE id=:id"), {"id": source})
    rejected(db, sql, params)
    db.execute(text("UPDATE procedencia_historica SET estado_revision='CONFIRMADO' WHERE id=:id"), {"id": source})
    photo = db.execute(text(sql), params).scalar_one()
    event = db.execute(text("""
        SELECT accion, usuario_id, detalles FROM auditoria WHERE ubicacion_id=:loc
    """), {"loc": location}).one()
    assert event.accion == "IMPORTAR_FOTOGRAFIA_HISTORICA"
    assert event.usuario_id is None and event.detalles["procedencia_id"] == source
    rejected(db, "UPDATE fotografias SET storage_clave='otro' WHERE id=:id", {"id": photo})
    rejected(db, "DELETE FROM fotografias WHERE id=:id", {"id": photo})
    user = create_user(db, "editor-historico")
    db.execute(text("SELECT set_config('app.usuario_id', :actor, true)"), {"actor": str(user)})
    rejected(db, "UPDATE fotografias SET procedencia_id=NULL WHERE id=:id", {"id": photo})
    rejected(db, "UPDATE fotografias SET sha256_original=NULL WHERE id=:id", {"id": photo})
    db.execute(text("UPDATE fotografias SET storage_clave='otro' WHERE id=:id"), {"id": photo})
    assert db.execute(text("SELECT actualizado_por FROM fotografias WHERE id=:id"), {"id": photo}).scalar_one() == user


def test_reemplazo_historico_preserva_procedencia_y_audita(db):
    actor_id = create_user(db, "ADMINISTRADOR")
    location_id = create_location(db, "historico-reemplazo")
    original_sha = "a" * 64
    old_content = b"foto anterior"
    old_sha = hashlib.sha256(old_content).hexdigest()
    source_id = db.execute(text("""
        INSERT INTO procedencia_historica (ruta_original, tipo, sha256, estado_revision, kardex)
        VALUES ('prueba/fachada.jpg', 'imagen', :sha, 'CONFIRMADO', 'historico-reemplazo') RETURNING id
    """), {"sha": original_sha}).scalar_one()
    photo_id = db.execute(text("""
        INSERT INTO fotografias (ubicacion_id, storage_bucket, storage_clave, sha256, sha256_original, procedencia_id)
        VALUES (:location, 'fachada', 'historica.webp', :sha, :original, :source) RETURNING id
    """), {"location": location_id, "sha": old_sha, "original": original_sha, "source": source_id}).scalar_one()
    objects = {"historica.webp": old_content}

    class FakeStorage:
        def get(self, key):
            return objects.get(key)

        def put(self, key, content):
            objects[key] = content

        def delete(self, key):
            objects.pop(key, None)

    image = io.BytesIO()
    Image.new("RGB", (10, 10), "green").save(image, format="JPEG")
    data = PhotographReplace(idempotencia=uuid4(), version=photo_version(photo_id, "fachada", "historica.webp"),
                             fotografia_base64=base64.b64encode(image.getvalue()).decode())
    factory = sessionmaker(bind=db, expire_on_commit=False, join_transaction_mode="create_savepoint")
    with factory() as session:
        actor = session.get(User, actor_id)
        assert replace_photo(location_id, data, actor, session, FakeStorage()) == "finalizada"
    row = db.execute(text("""
        SELECT storage_clave, sha256, sha256_original, procedencia_id, actualizado_por
        FROM fotografias WHERE id=:id
    """), {"id": photo_id}).one()
    assert row.sha256_original == original_sha and row.procedencia_id == source_id and row.actualizado_por == actor_id
    assert row.storage_clave in objects and row.sha256 == hashlib.sha256(objects[row.storage_clave]).hexdigest()
    assert "historica.webp" not in objects
    events = db.execute(text("SELECT accion, detalles FROM auditoria WHERE ubicacion_id=:id"), {"id": location_id}).all()
    assert "REEMPLAZAR_FOTOGRAFIA" in [event.accion for event in events]
    audit = next(event for event in events if event.accion == "CONFIRMAR_REEMPLAZO_FOTOGRAFIA")
    assert audit.detalles["sha256_anterior"] == old_sha and audit.detalles["sha256_nuevo"] == row.sha256


def test_operacion_historica_solo_permita_creacion_con_procedencia(db):
    location = create_location(db, "operacion-historica")
    source = db.execute(text("""
        INSERT INTO procedencia_historica (ruta_original, tipo, kardex, estado_revision)
        VALUES ('raiz/operacion-historica/foto.jpg', 'imagen', 'operacion-historica', 'CONFIRMADO') RETURNING id
    """)).scalar_one()
    sql = """
        INSERT INTO operaciones_fotografia
        (idempotencia, ubicacion_id, usuario_id, procedencia_id, tipo, estado, nuevo_bucket, nueva_clave)
        VALUES (:token, :loc, NULL, :source, 'CREAR', 'preparada', 'fotos', 'historica')
    """
    params = {"token": uuid4(), "loc": location, "source": source}
    rejected(db, sql, {**params, "source": None})
    db.execute(text(sql), params)
    rejected(db, "UPDATE operaciones_fotografia SET procedencia_id=NULL WHERE idempotencia=:token", {"token": params["token"]})


def test_importacion_foto_reanuda_despues_de_fallo_y_audita(db, monkeypatch, tmp_path):
    factory = sessionmaker(bind=db, expire_on_commit=False, join_transaction_mode="create_savepoint")
    monkeypatch.setattr("app.migrar_fotografias.session_factory", lambda: factory)
    location = create_location(db, "carga-foto")
    source = db.execute(text("""
        INSERT INTO procedencia_historica (ruta_original, tipo, sha256, kardex, estado_revision)
        VALUES ('raiz/carga-foto/a.jpg', 'imagen', :sha, 'carga-foto', 'CONFIRMADO') RETURNING id
    """), {"sha": "a" * 64}).scalar_one()
    image = tmp_path / "image.webp"
    image.write_bytes(b"webp simulado")
    photo = Photo("carga-foto", source, location, "a" * 64, hashlib.sha256(image.read_bytes()).hexdigest(), image)

    class StorageFake:
        content = None
        fail_once = True

        def get(self, key):
            return self.content

        def put(self, key, content):
            self.content = content
            if self.fail_once:
                self.fail_once = False
                raise RuntimeError("conexión interrumpida")

    storage = StorageFake()
    with pytest.raises(RuntimeError, match="interrumpida"):
        import_photo(photo, storage)
    assert db.execute(text("SELECT estado FROM operaciones_fotografia WHERE idempotencia=:id"), {"id": photo.token}).scalar_one() == "preparada"
    assert db.execute(text("SELECT count(*) FROM fotografias WHERE ubicacion_id=:id"), {"id": location}).scalar_one() == 0
    assert import_photo(photo, storage) == "creada"
    assert import_photo(photo, storage) == "existente"
    saved = db.execute(text("""
        SELECT registrado_por, procedencia_id, sha256_original, sha256 FROM fotografias WHERE ubicacion_id=:id
    """), {"id": location}).one()
    assert saved == (None, source, photo.original_sha, photo.optimized_sha)
    assert db.execute(text("SELECT estado FROM operaciones_fotografia WHERE idempotencia=:id"), {"id": photo.token}).scalar_one() == "finalizada"
    assert db.execute(text("SELECT count(*) FROM auditoria WHERE accion='IMPORTAR_FOTOGRAFIA_HISTORICA' AND ubicacion_id=:id"), {"id": location}).scalar_one() == 1


def test_importacion_no_sobrescribe_objeto_existente(db, monkeypatch, tmp_path):
    factory = sessionmaker(bind=db, expire_on_commit=False, join_transaction_mode="create_savepoint")
    monkeypatch.setattr("app.migrar_fotografias.session_factory", lambda: factory)
    location = create_location(db, "colision-foto")
    source = db.execute(text("""
        INSERT INTO procedencia_historica (ruta_original, tipo, sha256, kardex, estado_revision)
        VALUES ('raiz/colision-foto/a.jpg', 'imagen', :sha, 'colision-foto', 'CONFIRMADO') RETURNING id
    """), {"sha": "a" * 64}).scalar_one()
    image = tmp_path / "image.webp"
    image.write_bytes(b"webp simulado")
    photo = Photo("colision-foto", source, location, "a" * 64, hashlib.sha256(image.read_bytes()).hexdigest(), image)

    class ExistingStorage:
        def get(self, key):
            return b"objeto ajeno"

        def put(self, key, content):
            raise AssertionError("No debe sobrescribirse")

    with pytest.raises(RuntimeError, match="ya existía"):
        import_photo(photo, ExistingStorage())
    assert db.execute(text("SELECT estado FROM operaciones_fotografia WHERE idempotencia=:id"), {"id": photo.token}).scalar_one() == "cancelada"
    assert db.execute(text("SELECT count(*) FROM fotografias WHERE ubicacion_id=:id"), {"id": location}).scalar_one() == 0


def test_foto_actual_concurrente_no_se_reemplaza_y_queda_limpieza_pendiente(db, monkeypatch, tmp_path):
    factory = sessionmaker(bind=db, expire_on_commit=False, join_transaction_mode="create_savepoint")
    monkeypatch.setattr("app.migrar_fotografias.session_factory", lambda: factory)
    location = create_location(db, "concurrente-foto")
    actor = create_user(db, "editor-concurrente")
    source = db.execute(text("""
        INSERT INTO procedencia_historica (ruta_original, tipo, sha256, kardex, estado_revision)
        VALUES ('raiz/concurrente-foto/a.jpg', 'imagen', :sha, 'concurrente-foto', 'CONFIRMADO') RETURNING id
    """), {"sha": "a" * 64}).scalar_one()
    image = tmp_path / "image.webp"
    image.write_bytes(b"webp simulado")
    photo = Photo("concurrente-foto", source, location, "a" * 64, hashlib.sha256(image.read_bytes()).hexdigest(), image)

    class ConcurrentStorage:
        content = None

        def get(self, key):
            return self.content

        def put(self, key, content):
            self.content = content
            db.execute(text("SELECT set_config('app.usuario_id', :actor, true)"), {"actor": str(actor)})
            db.execute(text("""
                INSERT INTO fotografias (ubicacion_id, storage_bucket, storage_clave, registrado_por)
                VALUES (:id, 'fotos', 'foto-actual', :actor)
            """), {"id": location, "actor": actor})

    storage = ConcurrentStorage()
    assert import_photo(photo, storage) == "pendiente_limpieza"
    assert import_photo(photo, storage) == "pendiente_limpieza"
    assert db.execute(text("SELECT storage_clave FROM fotografias WHERE ubicacion_id=:id"), {"id": location}).scalar_one() == "foto-actual"
    state = db.execute(text("""
        SELECT estado, limpieza_clave FROM operaciones_fotografia WHERE idempotencia=:id
    """), {"id": photo.token}).one()
    assert state == ("pendiente_limpieza", photo.key)
    assert storage.content == image.read_bytes()


def test_registro_campo_en_postgresql_preserva_auditoria_y_reintentos(db):
    actor_id = create_user(db, "campo-operador")
    factory = sessionmaker(bind=db, expire_on_commit=False, join_transaction_mode="create_savepoint")
    image = io.BytesIO()
    Image.new("RGB", (20, 10), "blue").save(image, format="JPEG")
    data = FieldLocationCreate(
        kardex="campo Ab-1 ", idempotencia=uuid4(), latitud="-16.5", longitud="-68.1",
        fotografia_base64=base64.b64encode(image.getvalue()).decode(),
    )

    class FakeStorage:
        content = None

        def get(self, key):
            return self.content

        def put(self, key, content):
            self.content = content

    with factory() as session:
        actor = session.get(User, actor_id)
        location = register_location(data, actor, session, FakeStorage())
        assert location.kardex == data.kardex
        assert location.revision_actual_id is not None
        assert location.creado_por == actor_id and location.creado_en is not None
        rejected(db, "UPDATE ubicaciones SET creado_por=NULL WHERE id=:id", {"id": location.id})
        rejected(db, "UPDATE ubicaciones SET creado_en=CURRENT_TIMESTAMP + interval '1 day' WHERE id=:id", {"id": location.id})
        assert db.execute(text("SELECT registrado_por FROM fotografias WHERE ubicacion_id=:id"), {"id": location.id}).scalar_one() == actor_id
        assert db.execute(text("SELECT count(*) FROM auditoria WHERE usuario_id=:actor AND ubicacion_id=:id AND accion='CREAR_FOTOGRAFIA'"),
                          {"actor": actor_id, "id": location.id}).scalar_one() == 1


def test_api_usuarios_y_roles_en_postgresql(db, monkeypatch):
    objects = {"foto-original.webp": b"original"}

    class FakeStorage:
        def get(self, key):
            return objects.get(key)
        def put(self, key, content):
            objects[key] = content
        def delete(self, key):
            objects.pop(key, None)

    monkeypatch.setattr("app.main.Storage", FakeStorage)
    admin_role = db.execute(text("INSERT INTO roles (nombre) VALUES ('ADMINISTRADOR') RETURNING id")).scalar_one()
    tech_role = db.execute(text("INSERT INTO roles (nombre) VALUES ('TECNICO') RETURNING id")).scalar_one()
    for permission in ("usuarios.consultar", "usuarios.gestionar", "roles.consultar"):
        db.execute(text("INSERT INTO permisos (nombre) VALUES (:name) ON CONFLICT DO NOTHING"), {"name": permission})
        permission_id = db.execute(text("SELECT id FROM permisos WHERE nombre=:name"), {"name": permission}).scalar_one()
        db.execute(text("INSERT INTO rol_permisos (rol_id, permiso_id) VALUES (:role, :permission)"), {"role": admin_role, "permission": permission_id})
    db.execute(text("""
        INSERT INTO usuarios (nombre_usuario, contrasena_hash, activo, rol_id,
            cambio_contrasena_obligatorio, intentos_fallidos, creado_en)
        VALUES ('ADMIN-PRUEBA', :hash, true, :role, false, 0, CURRENT_TIMESTAMP)
    """), {"hash": password_hash("TESTPASS1"), "role": admin_role})
    factory = sessionmaker(bind=db, expire_on_commit=False, join_transaction_mode="create_savepoint")

    def override_db():
        with factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    try:
        with TestClient(app) as client:
            response = client.post("/auth/login", json={"username": "admin-prueba", "password": "testpass1"})
            assert response.status_code == 200
            headers = {"Authorization": f"Bearer {response.json()['access_token']}"}
            assert client.get("/roles", headers=headers).status_code == 200
            created = client.post("/usuarios", headers=headers, json={
                "username": "tecnico-prueba", "password": "testpass2", "role_id": tech_role,
            })
            assert created.status_code == 201
            assert created.json()["username"] == "TECNICO-PRUEBA"
            assert client.get("/usuarios", headers=headers).status_code == 200
            assert client.post("/contratos", headers=headers, json={"kardex": "a-1"}).status_code == 201
            location = client.post("/ubicaciones", headers=headers, json={"kardex": "a-1"})
            assert location.status_code == 201
            location_id = location.json()["id"]
            url = f"/ubicaciones/{location_id}/revisiones"
            assert client.post(url, headers=headers, json={"latitud": -16.5, "longitud": -68.1}).status_code == 410
            reason = client.post("/motivos-actualizacion", headers=headers, json={"nombre": "Corrección"}).json()
            body = {"idempotencia": str(uuid4()), "version": 0, "motivo_id": reason["id"],
                    "latitud": -16.5, "longitud": -68.1}
            update_path = f"/ubicaciones/{location_id}/actualizacion"
            assert client.put(update_path, headers=headers, json=body).status_code == 200
            assert client.put(update_path, headers=headers, json=body).status_code == 200
            assert client.get(f"/ubicaciones/{location_id}", headers=headers).json()["revision_actual_id"] is None
            actor_id = db.execute(text("SELECT id FROM usuarios WHERE nombre_usuario='ADMIN-PRUEBA'")).scalar_one()
            db.execute(text("SELECT set_config('app.usuario_id', :actor, true)"), {"actor": str(actor_id)})
            db.execute(text("""
                INSERT INTO fotografias (ubicacion_id, storage_bucket, storage_clave, registrado_por)
                VALUES (:id, 'fachada', 'foto-original.webp', :actor)
            """), {"id": location_id, "actor": actor_id})
            photo_path = f"/ubicaciones/{location_id}/fotografia"
            photo_version = client.get(photo_path, headers=headers).headers["x-foto-version"]
            image = io.BytesIO()
            Image.new("RGB", (10, 10), "green").save(image, format="JPEG")
            both = {"idempotencia": str(uuid4()), "version": 1, "motivo_id": reason["id"],
                    "latitud": -15, "longitud": -67, "foto_version": photo_version,
                    "fotografia_base64": base64.b64encode(image.getvalue()).decode()}
            assert client.put(update_path, headers=headers, json=both).json() == {"estado": "finalizada"}
            assert client.put(update_path, headers=headers, json=both).json() == {"estado": "finalizada"}
            assert "foto-original.webp" not in objects
            events = client.get(f"/ubicaciones/{location_id}/actualizaciones", headers=headers).json()
            assert len(events) == 2 and events[0]["motivo"] == "Corrección"
            rejected(db, "UPDATE auditoria SET detalles='{}' WHERE id=:id", {"id": events[0]["id"]})
            rejected(db, "DELETE FROM auditoria WHERE id=:id", {"id": events[0]["id"]})
            rejected(db, "UPDATE operaciones_fotografia SET solicitud_sha256='different' WHERE idempotencia=CAST(:id AS uuid)",
                     {"id": both["idempotencia"]})
            source_id = db.execute(text("""
                INSERT INTO procedencia_historica (ruta_original, tipo)
                VALUES ('raiz/a-1/documento.docx', 'documento') RETURNING id
            """)).scalar_one()
            source = client.get("/procedencia", headers=headers, params={"carpeta": "raiz/a-1"})
            assert source.status_code == 200 and source.json()[0]["id"] == source_id
            linked = client.put(f"/procedencia/{source_id}/contrato", headers=headers, json={"kardex": "a-1"})
            assert linked.status_code == 200 and linked.json()["estado_revision"] == "CONFIRMADO"
            unlinked = client.delete(f"/procedencia/{source_id}/contrato", headers=headers)
            assert unlinked.status_code == 200 and unlinked.json()["kardex"] is None
        assert db.execute(text("SELECT count(*) FROM auditoria_usuarios WHERE accion='CREAR_USUARIO'")).scalar_one() == 1
        assert db.execute(text("SELECT count(*) FROM auditoria WHERE accion='CONFIRMAR_CONTRATO_PROCEDENCIA'")).scalar_one() == 1
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_inventario_es_atomico_y_no_repite_carga(db, monkeypatch):
    factory = sessionmaker(bind=db, expire_on_commit=False, join_transaction_mode="create_savepoint")
    monkeypatch.setattr("app.inventario_historico.session_factory", lambda: factory)
    entries = [{
        "ruta_original": "original/123/doc.docx", "tipo": "documento",
        "sha256": "a" * 64, "estado_revision": "PENDIENTE", "kardex": None,
    }]
    save_inventory(entries, "b" * 64)
    assert db.execute(text("SELECT count(*) FROM procedencia_historica WHERE kardex IS NULL AND estado_revision='PENDIENTE'")).scalar_one() == 1
    assert db.execute(text("SELECT count(*) FROM auditoria WHERE accion='INVENTARIAR_FUENTE_HISTORICA'")).scalar_one() == 1
    with pytest.raises(RuntimeError, match="no está vacía"):
        save_inventory(entries, "b" * 64)
    assert db.execute(text("SELECT count(*) FROM procedencia_historica")).scalar_one() == 1


def test_migracion_de_carpetas_es_exacta_y_repetible(db, monkeypatch):
    factory = sessionmaker(bind=db, expire_on_commit=False, join_transaction_mode="create_savepoint")
    monkeypatch.setattr("app.migrar_kardex.session_factory", lambda: factory)
    entries = [
        {"ruta_original": "raiz/abc/doc.docx", "tipo": "documento", "sha256": "a" * 64},
        {"ruta_original": "raiz/ABC/foto.jpg", "tipo": "imagen", "sha256": "b" * 64},
        {"ruta_original": "raiz/desktop.ini", "tipo": "otro", "sha256": "c" * 64},
    ]
    for entry in entries:
        db.execute(text("""
            INSERT INTO procedencia_historica (ruta_original, tipo, sha256)
            VALUES (:ruta_original, :tipo, :sha256)
        """), entry)
    db.execute(text("INSERT INTO contratos (kardex) VALUES ('abc')"))
    db.execute(text("INSERT INTO ubicaciones (kardex) VALUES ('abc')"))
    plan = MigrationPlan("raiz", ["abc", "ABC", "vacio"], entries, "d" * 64)
    assert save_plan(plan) == (2, 2, 2)
    assert save_plan(plan) == (0, 0, 0)
    assert db.execute(text("SELECT count(*) FROM contratos")).scalar_one() == 3
    assert db.execute(text("SELECT count(*) FROM ubicaciones")).scalar_one() == 3
    assert db.execute(text("SELECT count(*) FROM procedencia_historica WHERE estado_revision='CONFIRMADO'")).scalar_one() == 2
    assert db.execute(text("SELECT count(*) FROM procedencia_historica WHERE kardex IS NULL AND estado_revision='PENDIENTE'")).scalar_one() == 1
    assert db.execute(text("SELECT count(*) FROM auditoria WHERE accion='MIGRAR_KARDEX_HISTORICOS'")).scalar_one() == 1


def test_migracion_rechaza_inventario_distinto(db, monkeypatch):
    factory = sessionmaker(bind=db, expire_on_commit=False, join_transaction_mode="create_savepoint")
    monkeypatch.setattr("app.migrar_kardex.session_factory", lambda: factory)
    plan = MigrationPlan("raiz", ["123"], [
        {"ruta_original": "raiz/123/foto.jpg", "tipo": "imagen", "sha256": "a" * 64},
    ], "b" * 64)
    with pytest.raises(RuntimeError, match="no coincide"):
        save_plan(plan)
    assert db.execute(text("SELECT count(*) FROM contratos")).scalar_one() == 0


def test_importacion_gps_no_sobrescribe_ubicaciones(db, monkeypatch):
    factory = sessionmaker(bind=db, expire_on_commit=False, join_transaction_mode="create_savepoint")
    monkeypatch.setattr("app.migrar_ubicaciones.session_factory", lambda: factory)
    first = create_location(db, "123")
    second = create_location(db, "456")
    current = db.execute(text("""
        INSERT INTO revisiones_ubicacion (ubicacion_id, url_gps, cerrada)
        VALUES (:id, 'https://maps.google.com/actual', true) RETURNING id
    """), {"id": second}).scalar_one()
    db.execute(text("UPDATE ubicaciones SET revision_actual_id=:rev WHERE id=:id"), {"rev": current, "id": second})
    entries = []
    for kardex in ("123", "456"):
        entry = {"ruta_original": f"raiz/{kardex}/doc.docx", "tipo": "documento", "sha256": "a" * 64}
        entries.append(entry)
        db.execute(text("""
            INSERT INTO procedencia_historica (ruta_original, tipo, sha256, kardex, estado_revision)
            VALUES (:ruta_original, :tipo, :sha256, :kardex, 'CONFIRMADO')
        """), {**entry, "kardex": kardex})
    plan = LocationPlan(entries, "b" * 64, {
        "123": ("raiz/123/doc.docx", "https://maps.google.com/?q=-16.5,-68.1"),
        "456": ("raiz/456/doc.docx", "https://maps.google.com/historico"),
    }, 0)
    assert save_location_plan(plan) == (1, 1)
    assert save_location_plan(plan) == (0, 2)
    revision = db.execute(text("""
        SELECT r.latitud, r.longitud, r.responsable_id, r.cerrada
        FROM ubicaciones u JOIN revisiones_ubicacion r ON r.id=u.revision_actual_id WHERE u.id=:id
    """), {"id": first}).one()
    assert (str(revision.latitud), str(revision.longitud), revision.responsable_id, revision.cerrada) == ("-16.5", "-68.1", None, True)
    assert db.execute(text("SELECT revision_actual_id FROM ubicaciones WHERE id=:id"), {"id": second}).scalar_one() == current
    assert db.execute(text("SELECT count(*) FROM auditoria WHERE accion='IMPORTAR_UBICACION_HISTORICA'")).scalar_one() == 1


def test_tablas_y_objetos_no_son_accesibles_a_roles_supabase(db):
    roles = db.execute(text("""
        SELECT rolname FROM pg_roles WHERE rolname IN ('anon', 'authenticated', 'service_role')
        ORDER BY rolname
    """)).scalars().all()
    if roles != ["anon", "authenticated", "service_role"]:
        pytest.skip("La base desechable no tiene los roles de Supabase simulados")
    tables = [
        "alembic_version", "roles", "permisos", "rol_permisos", "usuarios", "sesiones",
        "auditoria_usuarios", "contratos", "procedencia_historica", "ubicaciones",
        "actividades", "auditoria", "fotografias", "operaciones_fotografia", "revisiones_ubicacion", "motivos_actualizacion",
    ]
    privileges = ["SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"]
    if int(db.execute(text("SHOW server_version_num")).scalar_one()) >= 170000:
        privileges.append("MAINTAIN")
    for table in tables:
        assert db.execute(text("""
            SELECT c.relrowsecurity FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname='public' AND c.relname=:table
        """), {"table": table}).scalar_one()
        for role in roles:
            for privilege in privileges:
                allowed = db.execute(text("SELECT has_table_privilege(:role, :table, :privilege)"), {
                    "role": role, "table": "public." + table, "privilege": privilege,
                }).scalar_one()
                assert not allowed, (role, table, privilege)
    sequences = db.execute(text("""
        SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='public' AND c.relkind='S' AND c.relname = ANY(:names)
    """), {"names": [name + "_id_seq" for name in tables]}).scalars().all()
    assert len(sequences) == 13
    for role in roles:
        for sequence in sequences:
            for privilege in ("USAGE", "SELECT", "UPDATE"):
                assert not db.execute(text("SELECT has_sequence_privilege(:role, :seq, :privilege)"), {
                    "role": role, "seq": "public." + sequence, "privilege": privilege,
                }).scalar_one()
        for function in (
            "impedir_edicion_auditoria_usuarios", "proteger_revision_cerrada",
            "verificar_revision_actual", "preparar_fotografia", "auditar_fotografia", "proteger_creacion_ubicacion",
            "proteger_operacion_fotografia", "impedir_edicion_auditoria", "proteger_solicitud_fotografia",
        ):
            assert not db.execute(text("SELECT has_function_privilege(:role, :function, 'EXECUTE')"), {
                "role": role, "function": f"public.{function}()",
            }).scalar_one()
    with db.begin_nested():
        db.execute(text("SET LOCAL ROLE anon"))
        rejected(db, "SELECT * FROM public.usuarios")
        db.execute(text("RESET ROLE"))
