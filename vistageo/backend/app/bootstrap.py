import getpass
import hmac

from sqlalchemy import func, select, text

from app.database import session_factory
from app.models import AuditEvent, Permission, Role, User
from app.schemas import validate_password
from app.security import ADMIN, PERMISSION_MANAGERS, PERMISSIONS, password_hash

INITIAL_ROLES = PERMISSION_MANAGERS | {
    "JEFE TECNICO", "TECNICO", "CAJERO", "CALL CENTER",
}


def main() -> None:
    password = getpass.getpass("Contraseña inicial para JUNIOR: ")
    confirmation = getpass.getpass("Repita la contraseña: ")
    if not hmac.compare_digest(password.upper().encode("utf-8"), confirmation.upper().encode("utf-8")):
        raise SystemExit("Las contraseñas no coinciden")
    try:
        password = validate_password(password)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    with session_factory()() as db:
        db.execute(text("LOCK TABLE usuarios IN EXCLUSIVE MODE"))
        if db.scalar(select(func.count(User.id))):
            raise SystemExit("La inicialización requiere una base sin usuarios")
        for name in sorted(INITIAL_ROLES):
            if db.scalar(select(Role).where(Role.name == name)) is None:
                db.add(Role(name=name))
        for name in sorted(PERMISSIONS):
            if db.scalar(select(Permission).where(Permission.name == name)) is None:
                db.add(Permission(name=name))
        db.flush()
        for role in db.scalars(select(Role)).all():
            names = set()
            if role.name in {"GERENTE", "JEFE COMERCIAL", "TECNICO", "CAJERO", "CALL CENTER"}:
                names.update({"ubicaciones.consultar", "ubicaciones.registrar"})
            if role.name in {"GERENTE", "JEFE COMERCIAL"}:
                names.update({"usuarios.consultar", "usuarios.gestionar"})
            if names:
                role.permissions = list(db.scalars(select(Permission).where(Permission.name.in_(names))).all())
        admin = db.scalar(select(Role).where(Role.name == ADMIN))
        if admin is None:
            raise RuntimeError("No se pudo preparar el rol administrador")
        user = User(username="JUNIOR", password_hash=password_hash(password), role_id=admin.id, must_change_password=True)
        db.add(user)
        db.flush()
        db.add(AuditEvent(actor_id=user.id, target_id=user.id, action="INICIALIZAR_ADMINISTRADOR"))
        db.commit()
    print("Cuenta inicial creada; debe cambiar su contraseña al iniciar sesión.")


if __name__ == "__main__":
    main()
