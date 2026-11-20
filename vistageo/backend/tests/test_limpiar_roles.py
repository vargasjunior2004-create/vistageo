import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.limpiar_roles import apply, review
from app.models import AuditEvent, Contract, Location, Permission, Role, User
from app.security import OFFICIAL_ROLES, password_hash, verify_password


@pytest.fixture
def db():
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, expire_on_commit=False)() as session:
        admin = Role(name="ADMINISTRADOR")
        manager = Role(name="GERENTE")
        obsolete = Role(name="CAJERO")
        permission = Permission(name="usuarios.consultar")
        manager.permissions = [permission]
        session.add_all([admin, manager, obsolete])
        session.flush()
        session.add_all([
            User(username="ADMIN", password_hash=password_hash("TESTPASS1"), role_id=admin.id, active=True),
            User(username="PRUEBA", password_hash="test", role_id=obsolete.id, active=True),
        ])
        session.commit()
        yield session
    engine.dispose()


def test_limpieza_preserva_administrador_permisos_y_datos(db):
    admin = db.scalar(select(User).where(User.username == "ADMIN"))
    admin_id, original_hash = admin.id, admin.password_hash
    manager_id = db.scalar(select(Role.id).where(Role.name == "GERENTE"))
    db.add(Contract(kardex="123"))
    db.flush()
    db.add(Location(kardex="123", creado_por=admin_id))
    db.commit()
    report = review(db)
    candidate_id = report["usuarios_candidatos"][0]["id"]
    with pytest.raises(ValueError, match="IDs aprobados"):
        apply(db, report, set())
    apply(db, report, {candidate_id})
    db.commit()
    assert set(db.scalars(select(Role.name))) == OFFICIAL_ROLES
    assert db.get(User, candidate_id) is None
    assert db.get(User, admin_id).password_hash == original_hash
    assert verify_password("TESTPASS1", db.get(User, admin_id).password_hash)
    manager = db.get(Role, manager_id)
    assert manager.name == "GERENCIA"
    assert [p.name for p in manager.permissions] == ["usuarios.consultar"]
    assert db.scalar(select(Location).where(Location.kardex == "123")).creado_por == admin_id
    assert review(db)["problemas"] == []


@pytest.mark.parametrize("reference", ["location", "audit_user", "audit_role"])
def test_limpieza_bloquea_referencias_sin_borrar(db, reference):
    user = db.scalar(select(User).where(User.username == "PRUEBA"))
    if reference == "location":
        db.add(Contract(kardex="123"))
        db.flush()
        db.add(Location(kardex="123", creado_por=user.id))
    elif reference == "audit_user":
        db.add(AuditEvent(action="PRUEBA", target_id=user.id))
    else:
        db.add(AuditEvent(action="PRUEBA", role_id=user.role_id))
    db.commit()
    report = review(db)
    assert report["problemas"]
    assert report["referencias_roles" if reference == "audit_role" else "referencias_usuarios"]
    with pytest.raises(ValueError, match="contiene problemas"):
        apply(db, report, {user.id})
    assert db.get(User, user.id) is not None
    assert db.scalar(select(Role).where(Role.name == "CAJERO")) is not None


def test_roles_no_previstos_y_colision_de_gerencia_bloquean_limpieza(db):
    db.add_all([Role(name="OTRO"), Role(name="GERENCIA")])
    db.commit()
    report = review(db)
    assert len(report["problemas"]) == 2
    with pytest.raises(ValueError, match="contiene problemas"):
        apply(db, report, {user["id"] for user in report["usuarios_candidatos"]})
