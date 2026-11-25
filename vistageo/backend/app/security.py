import hashlib
import secrets
from datetime import timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select, update
from sqlalchemy.orm import Session, lazyload

from app.database import get_db
from app.models import AuditEvent, AuthSession, User, as_utc, now_utc
from app.tokens import TokenError, decode_access_token, looks_like_jwt, session_idle_ttl

ADMIN = "ADMINISTRADOR"
OFFICIAL_ROLES = {ADMIN, "GERENCIA", "JEFE OPERATIVO", "JEFE TECNICO", "TECNICO"}
PERMISSION_MANAGERS = {ADMIN, "GERENCIA", "GERENTE", "JEFE COMERCIAL", "JEFE OPERATIVO"}
PERMISSIONS = {
    "usuarios.consultar", "usuarios.gestionar", "roles.consultar", "roles.gestionar",
    "ubicaciones.consultar", "ubicaciones.registrar", "ubicaciones.fotografia.editar", "ubicaciones.gps.editar",
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


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Sesión inválida o vencida",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _session_from_credentials(db: Session, token: str) -> AuthSession | None:
    if looks_like_jwt(token):
        try:
            claims = decode_access_token(token)
        except TokenError:
            return None
        session = db.scalar(
            select(AuthSession)
            .options(lazyload(AuthSession.user))
            .where(AuthSession.id == claims.session_id)
            .with_for_update(of=AuthSession)
        )
        if session is None or session.user_id != claims.subject:
            return None
        return session
    return db.scalar(
        select(AuthSession)
        .options(lazyload(AuthSession.user))
        .where(AuthSession.token_hash == token_hash(token))
        .with_for_update(of=AuthSession)
    )


def _revoke_session(session: AuthSession, now, reason: str) -> None:
    session.revoked = True
    session.revoked_at = now
    session.revoked_reason = reason


def revoke_session(db: Session, session: AuthSession, reason: str, actor_id: int | None = None, target_id: int | None = None) -> None:
    now = now_utc()
    _revoke_session(session, now, reason)
    db.add(AuditEvent(action="CIERRE_SESION", actor_id=actor_id, target_id=target_id, details={"motivo": reason, "sesion_id": session.id}))


def revoke_all_sessions(db: Session, user_id: int, reason: str = "REVOCACION_MASIVA") -> None:
    now = now_utc()
    db.execute(
        update(AuthSession)
        .where(AuthSession.user_id == user_id, AuthSession.revoked.is_(False))
        .values(revoked=True, revoked_at=now, revoked_reason=reason)
    )


def current_session(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
    user_activity: bool = Header(default=False, alias="X-Actividad-Usuario"),
) -> AuthSession:
    unauthorized = _unauthorized()
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise unauthorized
    session = _session_from_credentials(db, credentials.credentials)
    if session is None or session.revoked or not session.user.active:
        raise unauthorized
    now = now_utc()
    if session.expires_at is not None and as_utc(session.expires_at) <= now:
        _revoke_session(session, now, "EXPIRACION_ABSOLUTA")
        db.add(AuditEvent(action="SESION_VENCIDA", actor_id=session.user_id, target_id=session.user_id, details={"motivo": "EXPIRACION_ABSOLUTA", "sesion_id": session.id}))
        db.commit()
        raise unauthorized
    if now - as_utc(session.last_activity) >= session_idle_ttl():
        _revoke_session(session, now, "INACTIVIDAD")
        db.add(AuditEvent(action="SESION_VENCIDA", actor_id=session.user_id, target_id=session.user_id, details={"motivo": "INACTIVIDAD", "sesion_id": session.id}))
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