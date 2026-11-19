import hashlib
import secrets
from datetime import timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session, lazyload

from app.database import get_db
from app.models import AuditEvent, AuthSession, User, as_utc, now_utc

ADMIN = "ADMINISTRADOR"
PERMISSION_MANAGERS = {ADMIN, "GERENTE", "JEFE COMERCIAL", "JEFE OPERATIVO"}
PERMISSIONS = {
    "usuarios.consultar", "usuarios.gestionar", "roles.consultar", "roles.gestionar",
    "ubicaciones.consultar", "ubicaciones.registrar",
}
SESSION_IDLE = timedelta(minutes=10)
LOCK_DURATION = timedelta(minutes=15)
MAX_ATTEMPTS = 5

hasher = PasswordHasher()
dummy_hash = hasher.hash(secrets.token_urlsafe(32))
bearer = HTTPBearer(auto_error=False)


def password_hash(password: str) -> str:
    return hasher.hash(password.upper())


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        return hasher.verify(stored_hash, password.upper())
    except VerifyMismatchError:
        return False
    except (VerificationError, InvalidHashError) as exc:
        raise RuntimeError("El hash almacenado es inválido") from exc


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def require_admin(user: User) -> None:
    if user.role.name != ADMIN:
        raise HTTPException(status_code=403, detail="No autorizado")


def require_permission(user: User, permission: str) -> None:
    if user.role.name != ADMIN and permission not in {p.name for p in user.role.permissions}:
        raise HTTPException(status_code=403, detail="No autorizado")


def require_permission_manager(user: User) -> None:
    if user.role.name not in PERMISSION_MANAGERS:
        raise HTTPException(status_code=403, detail="No autorizado")


def current_session(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
    user_activity: bool = Header(default=False, alias="X-Actividad-Usuario"),
) -> AuthSession:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Sesión inválida o vencida",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise unauthorized
    session = db.scalar(
        select(AuthSession)
        .options(lazyload(AuthSession.user))
        .where(AuthSession.token_hash == token_hash(credentials.credentials))
        .with_for_update(of=AuthSession)
    )
    if session is None or session.revoked or not session.user.active:
        raise unauthorized
    now = now_utc()
    if now - as_utc(session.last_activity) >= SESSION_IDLE:
        session.revoked = True
        db.add(AuditEvent(action="SESION_VENCIDA", actor_id=session.user_id, target_id=session.user_id))
        db.commit()
        raise unauthorized
    if user_activity:
        session.last_activity = now
        db.commit()
    return session


def current_user(auth: AuthSession = Depends(current_session)) -> User:
    if auth.user.must_change_password:
        raise HTTPException(status_code=403, detail="Debe cambiar la contraseña temporal")
    return auth.user
