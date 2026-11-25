import asyncio
import hashlib
import logging
import os
import secrets
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import func, literal, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, lazyload

from app.database import get_db
from app.models import AuditEvent, AuditRecord, AuthSession, Contract, HistoricalSource, Location, LocationRevision, Permission, PhotoOperation, Photograph, Role, UpdateReason, User, as_utc, now_utc
from app.schemas import ContractCreate, ContractRead, FieldLocationCreate, HistoricalSourceRead, LocationCreate, LocationRead, LocationRevisionCreate, LocationRevisionRead, LocationUpdate, LoginRequest, PasswordChange, PasswordReset, PermissionUpdate, PhotographReplace, RefreshRequest, RoleCreate, SessionRead, SessionUserRead, SharedLocationRequest, SharedLocationRead, UpdateReasonCreate, UpdateReasonEdit, UpdateReasonRead, UserCreate, UserRead, UserUpdate
from app.actualizacion_ubicacion import update_location
from app.fotografia import photo_version, recovery_loop, replace_photo
from app.registro_ubicacion import register_location
from app.enlaces_gps import resolve_map_url
from app.calidad_gps import gps_limits
from app.rate_limit import limiter, login_rate_limits
from app.security import ADMIN, LOCK_DURATION, MAX_ATTEMPTS, OFFICIAL_ROLES, PERMISSIONS, PERMISSION_MANAGERS, _revoke_session, current_session, current_user, dummy_hash, password_hash, require_admin, require_permission, require_permission_manager, revoke_all_sessions, token_hash, verify_password
from app.tokens import absolute_session_ttl, create_access_token, generate_refresh_token, hash_refresh_token, refresh_token_ttl, session_idle_ttl
from app.storage import BUCKET, Storage

load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False, interpolate=False)
@asynccontextmanager
async def lifespan(_app: FastAPI):
    task = None
    if os.environ.get("VISTAGEO_PHOTO_CLEANUP_ENABLED") == "true":
        task = asyncio.create_task(recovery_loop())
    try:
        yield
    finally:
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


EXPOSE_DOCS = _env_bool("VISTAGEO_EXPOSE_DOCS", False)
FORCE_HTTPS = _env_bool("FORCE_HTTPS", False)
HSTS_ENABLED = _env_bool("HSTS_ENABLED", FORCE_HTTPS)
TRUSTED_HOSTS = [h.strip() for h in os.environ.get("TRUSTED_HOSTS", "testserver,localhost,127.0.0.1,::1").split(",") if h.strip()]
MAX_REQUEST_BODY_BYTES = _env_int("MAX_REQUEST_BODY_BYTES", 10 * 1024 * 1024)

app = FastAPI(
    title="GEO VISTA: usuarios y roles",
    lifespan=lifespan,
    docs_url="/docs" if EXPOSE_DOCS else None,
    redoc_url="/redoc" if EXPOSE_DOCS else None,
    openapi_url="/openapi.json" if EXPOSE_DOCS else None,
)
origins = [origin.strip() for origin in os.environ.get("CORS_ORIGINS", "").split(",") if origin.strip()]
if "*" in origins:
    raise RuntimeError("CORS_ORIGINS requiere orígenes explícitos")

from starlette.middleware.httpsredirect import HTTPSRedirectMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

app.add_middleware(TrustedHostMiddleware, allowed_hosts=TRUSTED_HOSTS)
if FORCE_HTTPS:
    app.add_middleware(HTTPSRedirectMiddleware)
app.add_middleware(
    CORSMiddleware, allow_origins=origins, allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "X-Actividad-Usuario"],
    expose_headers=["X-Foto-Version"],
)


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > MAX_REQUEST_BODY_BYTES:
                    return JSONResponse(status_code=413, content={"detail": "Solicitud demasiado grande"})
            except ValueError:
                return JSONResponse(status_code=400, content={"detail": "Content-Length inválido"})
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=(self)")
    response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
    response.headers.setdefault("Cross-Origin-Resource-Policy", "same-site")
    response.headers.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
    if HSTS_ENABLED:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response


logger = logging.getLogger(__name__)


@app.exception_handler(RequestValidationError)
async def validation_error(_request: Request, error: RequestValidationError) -> JSONResponse:
    fields = [list(item["loc"]) for item in error.errors()]
    return JSONResponse(status_code=422, content={"detail": "Datos inválidos", "fields": fields})


def commit(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="El registro ya existe o está en uso") from exc


def audit(
    db: Session,
    action: str,
    actor: int | None = None,
    target: int | None = None,
    role_id: int | None = None,
    details: dict | None = None,
) -> None:
    db.add(AuditEvent(action=action, actor_id=actor, target_id=target, role_id=role_id, details=details))


def client_ip(request: Request) -> str:
    if os.environ.get("TRUST_PROXY_HEADERS", "").lower() == "true":
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[0].strip() or "unknown"
    return request.client.host if request.client else "unknown"


def enforce_login_rate_limit(request: Request, username: str) -> None:
    ip_limit, ip_window, account_limit, account_window = login_rate_limits()
    ip = client_ip(request)
    allowed_ip, retry_ip = limiter.hit(f"login:ip:{ip}", ip_limit, ip_window)
    allowed_account, retry_account = limiter.hit(
        f"login:account:{username}", account_limit, account_window
    )
    if not allowed_ip or not allowed_account:
        retry_after = max(retry_ip, retry_account, 1)
        raise HTTPException(
            status_code=429,
            detail="Demasiados intentos de inicio de sesión. Intenta más tarde.",
            headers={"Retry-After": str(retry_after)},
        )


def revoke_sessions(db: Session, user_id: int, reason: str = "REVOCACION_MASIVA") -> None:
    revoke_all_sessions(db, user_id, reason)


def read_role(role: Role) -> dict:
    return {"id": role.id, "name": role.name, "permissions": sorted(p.name for p in role.permissions)}


def get_role(db: Session, role_id: int) -> Role:
    role = db.get(Role, role_id)
    if role is None:
        raise HTTPException(status_code=404, detail="Rol no encontrado")
    return role


def get_user(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    return user


def protect_privileged_roles(actor: User, *roles: Role) -> None:
    if any(role.name == ADMIN for role in roles):
        require_admin(actor)
    if any(role.name in PERMISSION_MANAGERS for role in roles):
        require_permission_manager(actor)


def protect_last_admin(db: Session, target: User, new_role: Role, active: bool) -> None:
    if target.role.name != ADMIN or not target.active or (new_role.name == ADMIN and active):
        return
    db.scalar(select(Role).where(Role.name == ADMIN).with_for_update())
    other_admin = db.scalar(
        select(User.id).join(Role).where(
            Role.name == ADMIN, User.active.is_(True), User.id != target.id
        ).limit(1)
    )
    if other_admin is None:
        raise HTTPException(status_code=409, detail="Debe quedar al menos un administrador activo")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/auth/login")
def login(data: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)) -> dict:
    enforce_login_rate_limit(request, data.username)
    user = db.scalar(
        select(User).options(lazyload(User.role)).where(User.username == data.username).with_for_update(of=User)
    )
    valid = verify_password(data.password.get_secret_value(), user.password_hash if user else dummy_hash)
    now = now_utc()
    locked = user is not None and user.locked_until is not None and as_utc(user.locked_until) > now
    if user is None or not user.active or locked or not valid:
        if user is not None and not locked and user.active:
            if user.locked_until is not None:
                user.failed_attempts = 0
                user.locked_until = None
            user.failed_attempts += 1
            if user.failed_attempts >= MAX_ATTEMPTS:
                user.locked_until = now + LOCK_DURATION
        audit(db, "INICIO_SESION_FALLIDO", target=user.id if user is not None else None)
        commit(db)
        raise HTTPException(status_code=401, detail="Credenciales inválidas", headers={"WWW-Authenticate": "Bearer"})
    user.failed_attempts = 0
    user.locked_until = None
    refresh_token = generate_refresh_token()
    legacy_token = secrets.token_urlsafe(32)
    session = AuthSession(
        token_hash=token_hash(legacy_token),
        user_id=user.id,
        last_activity=now,
        created_at=now,
        expires_at=now + absolute_session_ttl(),
        refresh_hash=hash_refresh_token(refresh_token),
        refresh_expires_at=min(now + refresh_token_ttl(), now + absolute_session_ttl()),
        refresh_generation=0,
    )
    db.add(session)
    db.flush()
    access_token, expires_in = create_access_token(session.id, user.id, now=now)
    audit(db, "INICIO_SESION", user.id, user.id, details={"sesion_id": session.id})
    commit(db)
    response.headers["Cache-Control"] = "no-store"
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": expires_in,
        "must_change_password": user.must_change_password,
    }


@app.get("/auth/me", response_model=SessionUserRead)
def me(auth: AuthSession = Depends(current_session)) -> SessionUserRead:
    user = auth.user
    return SessionUserRead(
        **UserRead.model_validate(user).model_dump(),
        role_name=user.role.name,
        permissions=sorted(permission.name for permission in user.role.permissions),
    )


@app.post("/auth/logout", status_code=204)
def logout(auth: AuthSession = Depends(current_session), db: Session = Depends(get_db)) -> Response:
    now = now_utc()
    _revoke_session(auth, now, "CIERRE_SESION")
    audit(db, "CIERRE_SESION", auth.user_id, auth.user_id, details={"sesion_id": auth.id})
    commit(db)
    return Response(status_code=204)


@app.post("/auth/refresh")
def refresh_session(data: RefreshRequest, response: Response, db: Session = Depends(get_db)) -> dict:
    refresh_hash = hash_refresh_token(data.refresh_token)
    now = now_utc()
    session = db.scalar(
        select(AuthSession).options(lazyload(AuthSession.user)).where(AuthSession.refresh_hash == refresh_hash).with_for_update(of=AuthSession)
    )
    if session is None:
        reused = db.scalar(
            select(AuthSession).options(lazyload(AuthSession.user)).where(AuthSession.previous_refresh_hash == refresh_hash).with_for_update(of=AuthSession)
        )
        if reused is not None:
            revoke_sessions(db, reused.user_id, "REUTILIZACION_REFRESH")
            audit(db, "REUTILIZACION_REFRESH", reused.user_id, reused.user_id, details={"sesion_id": reused.id})
            commit(db)
        raise HTTPException(status_code=401, detail="Sesión inválida o vencida", headers={"WWW-Authenticate": "Bearer"})
    if session.revoked or not session.user.active:
        raise HTTPException(status_code=401, detail="Sesión inválida o vencida", headers={"WWW-Authenticate": "Bearer"})
    if session.expires_at is not None and as_utc(session.expires_at) <= now:
        _revoke_session(session, now, "EXPIRACION_ABSOLUTA")
        audit(db, "SESION_VENCIDA", session.user_id, session.user_id, details={"motivo": "EXPIRACION_ABSOLUTA", "sesion_id": session.id})
        commit(db)
        raise HTTPException(status_code=401, detail="Sesión inválida o vencida", headers={"WWW-Authenticate": "Bearer"})
    if session.refresh_expires_at is not None and as_utc(session.refresh_expires_at) <= now:
        _revoke_session(session, now, "REFRESH_EXPIRADO")
        audit(db, "SESION_VENCIDA", session.user_id, session.user_id, details={"motivo": "REFRESH_EXPIRADO", "sesion_id": session.id})
        commit(db)
        raise HTTPException(status_code=401, detail="Sesión inválida o vencida", headers={"WWW-Authenticate": "Bearer"})
    if now - as_utc(session.last_activity) >= session_idle_ttl():
        _revoke_session(session, now, "INACTIVIDAD")
        audit(db, "SESION_VENCIDA", session.user_id, session.user_id, details={"motivo": "INACTIVIDAD", "sesion_id": session.id})
        commit(db)
        raise HTTPException(status_code=401, detail="Sesión inválida o vencida", headers={"WWW-Authenticate": "Bearer"})

    new_refresh = generate_refresh_token()
    session.previous_refresh_hash = session.refresh_hash
    session.refresh_hash = hash_refresh_token(new_refresh)
    session.refresh_generation = (session.refresh_generation or 0) + 1
    session.refresh_expires_at = min(now + refresh_token_ttl(), as_utc(session.expires_at)) if session.expires_at else now + refresh_token_ttl()
    access_token, expires_in = create_access_token(session.id, session.user_id, now=now)
    audit(db, "RENOVAR_SESION", session.user_id, session.user_id, details={"sesion_id": session.id})
    commit(db)
    response.headers["Cache-Control"] = "no-store"
    return {
        "access_token": access_token,
        "refresh_token": new_refresh,
        "token_type": "bearer",
        "expires_in": expires_in,
    }


@app.get("/auth/sessions", response_model=list[SessionRead])
def list_sessions(auth: AuthSession = Depends(current_session), db: Session = Depends(get_db)) -> list[SessionRead]:
    sessions = list(db.scalars(
        select(AuthSession).where(AuthSession.user_id == auth.user_id, AuthSession.revoked.is_(False)).order_by(AuthSession.last_activity.desc(), AuthSession.id.desc())
    ).all())
    return [
        SessionRead(
            id=item.id,
            creado_en=item.created_at,
            ultima_actividad=item.last_activity,
            expira_en=item.expires_at,
            actual=item.id == auth.id,
        )
        for item in sessions
    ]


@app.delete("/auth/sessions/{session_id}", status_code=204)
def revoke_own_session(session_id: int, auth: AuthSession = Depends(current_session), db: Session = Depends(get_db)) -> Response:
    session = db.scalar(
        select(AuthSession).where(AuthSession.id == session_id, AuthSession.user_id == auth.user_id).with_for_update(of=AuthSession)
    )
    if session is None:
        raise HTTPException(status_code=404, detail="Sesión no encontrada")
    if not session.revoked:
        _revoke_session(session, now_utc(), "REVOCACION_USUARIO")
        audit(db, "REVOCAR_SESION", auth.user_id, auth.user_id, details={"sesion_id": session.id})
        commit(db)
    return Response(status_code=204)


@app.delete("/auth/sessions", status_code=204)
def revoke_own_sessions(auth: AuthSession = Depends(current_session), db: Session = Depends(get_db)) -> Response:
    revoke_sessions(db, auth.user_id, "REVOCACION_TOTAL_USUARIO")
    audit(db, "REVOCAR_SESIONES", auth.user_id, auth.user_id)
    commit(db)
    return Response(status_code=204)


@app.post("/auth/password", status_code=204)
def change_password(data: PasswordChange, auth: AuthSession = Depends(current_session), db: Session = Depends(get_db)) -> Response:
    user = auth.user
    if not verify_password(data.current_password.get_secret_value(), user.password_hash):
        raise HTTPException(status_code=400, detail="No fue posible cambiar la contraseña")
    if verify_password(data.new_password.get_secret_value(), user.password_hash):
        raise HTTPException(status_code=400, detail="La nueva contraseña debe ser diferente")
    user.password_hash = password_hash(data.new_password.get_secret_value())
    user.must_change_password = False
    revoke_sessions(db, user.id, "CAMBIO_CONTRASENA")
    audit(db, "CAMBIO_CONTRASENA", user.id, user.id)
    commit(db)
    return Response(status_code=204)


@app.get("/usuarios", response_model=list[UserRead])
def list_users(actor: User = Depends(current_user), db: Session = Depends(get_db)) -> list[User]:
    require_permission(actor, "usuarios.consultar")
    return list(db.scalars(select(User).order_by(User.id)).all())


@app.post("/usuarios", response_model=UserRead, status_code=201)
def create_user(data: UserCreate, actor: User = Depends(current_user), db: Session = Depends(get_db)) -> User:
    require_permission(actor, "usuarios.gestionar")
    require_admin(actor)
    role = get_role(db, data.role_id)
    protect_privileged_roles(actor, role)
    if role.name not in OFFICIAL_ROLES:
        raise HTTPException(status_code=409, detail="El rol no pertenece al catálogo oficial")
    user = User(username=data.username, password_hash=password_hash(data.password.get_secret_value()), role_id=role.id, must_change_password=False)
    db.add(user)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="El usuario ya existe") from exc
    audit(db, "CREAR_USUARIO", actor.id, user.id)
    commit(db)
    return user


@app.get("/usuarios/{user_id}", response_model=UserRead)
def show_user(user_id: int, actor: User = Depends(current_user), db: Session = Depends(get_db)) -> User:
    require_permission(actor, "usuarios.consultar")
    return get_user(db, user_id)


@app.patch("/usuarios/{user_id}", response_model=UserRead)
def edit_user(user_id: int, data: UserUpdate, actor: User = Depends(current_user), db: Session = Depends(get_db)) -> User:
    require_permission(actor, "usuarios.gestionar")
    user = get_user(db, user_id)
    if user.id == actor.id and (data.role_id is not None or data.active is not None):
        raise HTTPException(status_code=403, detail="No puedes modificar tu propio rol ni estado")
    role = get_role(db, data.role_id) if data.role_id is not None else user.role
    if data.role_id is not None and role.id != user.role_id:
        require_admin(actor)
    protect_privileged_roles(actor, user.role, role)
    if data.role_id is not None and role.name not in OFFICIAL_ROLES:
        raise HTTPException(status_code=409, detail="El rol no pertenece al catálogo oficial")
    active = data.active if data.active is not None else user.active
    protect_last_admin(db, user, role, active)
    before = {"username": user.username, "role_id": user.role_id, "active": user.active}
    if data.username is not None:
        user.username = data.username
    if data.role_id is not None:
        user.role_id = role.id
    user.active = active
    if not active:
        revoke_sessions(db, user.id, "DESACTIVACION_USUARIO")
    action = "ACTUALIZAR_USUARIO"
    if before["active"] and not active:
        action = "DESACTIVAR_USUARIO"
    elif not before["active"] and active:
        action = "ACTIVAR_USUARIO"
    audit(db, action, actor.id, user.id, details={
        "antes": before, "despues": {"username": user.username, "role_id": user.role_id, "active": user.active}
    })
    commit(db)
    return user


@app.post("/usuarios/{user_id}/restablecer-contrasena", status_code=204)
def reset_password(user_id: int, data: PasswordReset, actor: User = Depends(current_user), db: Session = Depends(get_db)) -> Response:
    require_permission(actor, "usuarios.gestionar")
    user = get_user(db, user_id)
    if user.id == actor.id:
        raise HTTPException(status_code=403, detail="Usa /auth/password para cambiar tu propia contraseña")
    protect_privileged_roles(actor, user.role)
    if verify_password(data.temporary_password.get_secret_value(), user.password_hash):
        raise HTTPException(status_code=400, detail="La nueva contraseña debe ser diferente")
    user.password_hash = password_hash(data.temporary_password.get_secret_value())
    user.must_change_password = True
    user.failed_attempts = 0
    user.locked_until = None
    revoke_sessions(db, user.id, "RESTABLECER_CONTRASENA")
    audit(db, "RESTABLECER_CONTRASENA", actor.id, user.id)
    commit(db)
    return Response(status_code=204)


@app.post("/usuarios/{user_id}/revocar-sesiones", status_code=204)
def revoke_user_sessions(user_id: int, actor: User = Depends(current_user), db: Session = Depends(get_db)) -> Response:
    require_permission(actor, "usuarios.gestionar")
    user = get_user(db, user_id)
    protect_privileged_roles(actor, user.role)
    revoke_sessions(db, user.id, "REVOCACION_ADMINISTRATIVA")
    audit(db, "REVOCAR_SESIONES_USUARIO", actor.id, user.id)
    commit(db)
    return Response(status_code=204)


@app.get("/roles")
def list_roles(actor: User = Depends(current_user), db: Session = Depends(get_db)) -> list[dict]:
    if actor.role.name not in PERMISSION_MANAGERS:
        require_permission(actor, "roles.consultar")
    return [read_role(role) for role in db.scalars(select(Role).order_by(Role.id)).all()]


@app.post("/roles", status_code=201)
def create_role(data: RoleCreate, actor: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    require_permission(actor, "roles.gestionar")
    if data.name not in OFFICIAL_ROLES:
        raise HTTPException(status_code=422, detail="Solo se permiten roles oficiales")
    if data.name in PERMISSION_MANAGERS:
        require_admin(actor)
    role = Role(name=data.name)
    db.add(role)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="El rol ya existe") from exc
    audit(db, "CREAR_ROL", actor.id, role_id=role.id)
    commit(db)
    return read_role(role)


@app.patch("/roles/{role_id}")
def rename_role(role_id: int, data: RoleCreate, actor: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    require_permission(actor, "roles.gestionar")
    get_role(db, role_id)
    raise HTTPException(status_code=403, detail="El catálogo de roles oficiales no se puede renombrar")


@app.get("/permisos")
def list_permissions(actor: User = Depends(current_user)) -> list[str]:
    require_permission_manager(actor)
    return sorted(PERMISSIONS)


@app.put("/roles/{role_id}/permisos")
def set_permissions(role_id: int, data: PermissionUpdate, actor: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    require_permission_manager(actor)
    role = get_role(db, role_id)
    if role.name == ADMIN:
        require_admin(actor)
    if role.id == actor.role_id and actor.role.name != ADMIN:
        raise HTTPException(status_code=403, detail="No puedes modificar los permisos de tu propio rol")
    if not set(data.permissions).issubset(PERMISSIONS):
        raise HTTPException(status_code=422, detail="Permiso desconocido")
    permissions = list(db.scalars(select(Permission).where(Permission.name.in_(data.permissions))).all())
    if len(permissions) != len(data.permissions):
        raise HTTPException(status_code=409, detail="El catálogo de permisos no está inicializado")
    before = sorted(p.name for p in role.permissions)
    role.permissions = permissions
    audit(db, "ACTUALIZAR_PERMISOS", actor.id, role_id=role.id,
          details={"antes": before, "despues": sorted(data.permissions)})
    commit(db)
    return read_role(role)


@app.get("/contratos", response_model=list[ContractRead])
def list_contracts(
    kardex: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    actor: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[Contract]:
    if kardex is not None and actor.role.name != ADMIN and "ubicaciones.consultar" not in {p.name for p in actor.role.permissions}:
        require_permission(actor, "ubicaciones.registrar")
    else:
        require_permission(actor, "ubicaciones.consultar")
    query = select(Contract).order_by(Contract.kardex).limit(limit).offset(offset)
    if kardex is not None:
        validate_kardex_query(kardex)
        query = query.where(Contract.kardex == kardex)
    return list(db.scalars(query).all())


def validate_kardex_query(kardex: str) -> None:
    if "\x00" in kardex:
        raise HTTPException(status_code=422, detail="Kardex inválido")


@app.post("/contratos", response_model=ContractRead, status_code=201)
def create_contract(data: ContractCreate, actor: User = Depends(current_user), db: Session = Depends(get_db)) -> Contract:
    require_admin(actor)
    contract = Contract(kardex=data.kardex)
    db.add(contract)
    db.add(AuditRecord(usuario_id=actor.id, accion="CREAR_CONTRATO", detalles={"kardex": data.kardex}))
    commit(db)
    return contract


@app.post("/ubicaciones", response_model=LocationRead, status_code=201)
def create_location(data: LocationCreate, actor: User = Depends(current_user), db: Session = Depends(get_db)) -> Location:
    require_admin(actor)
    if db.get(Contract, data.kardex) is None:
        raise HTTPException(status_code=404, detail="Contrato no encontrado")
    location = Location(kardex=data.kardex, creado_por=actor.id, creado_en=now_utc())
    db.add(location)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="La ubicación ya existe o el contrato no está disponible") from exc
    db.add(AuditRecord(usuario_id=actor.id, ubicacion_id=location.id, accion="CREAR_UBICACION"))
    commit(db)
    return location


@app.post("/registro-ubicacion", response_model=LocationRead, status_code=201)
def create_field_location(data: FieldLocationCreate, actor: User = Depends(current_user), db: Session = Depends(get_db)) -> Location:
    require_permission(actor, "ubicaciones.registrar")
    try:
        storage = Storage()
    except RuntimeError as exc:
        logger.error("Storage no está disponible: %s", exc)
        raise HTTPException(status_code=503, detail="No se pudo preparar Storage") from exc
    return register_location(data, actor, db, storage)


@app.post("/registro-ubicacion/interpretar-enlace", response_model=SharedLocationRead)
def interpret_shared_location(data: SharedLocationRequest, actor: User = Depends(current_user)) -> SharedLocationRead:
    require_permission(actor, "ubicaciones.registrar")
    try:
        latitude, longitude = resolve_map_url(data.url_gps)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return SharedLocationRead(latitud=latitude, longitud=longitude)


@app.get("/configuracion-gps")
def read_gps_configuration(_actor: User = Depends(current_user)) -> dict[str, float]:
    return gps_limits()


@app.get("/motivos-actualizacion", response_model=list[UpdateReasonRead])
def list_update_reasons(
    todos: bool = False, actor: User = Depends(current_user), db: Session = Depends(get_db),
) -> list[UpdateReason]:
    if todos:
        require_permission_manager(actor)
    else:
        require_permission(actor, "ubicaciones.consultar")
    query = select(UpdateReason).order_by(UpdateReason.nombre, UpdateReason.id)
    if not todos:
        query = query.where(UpdateReason.activo.is_(True))
    return list(db.scalars(query).all())


@app.post("/motivos-actualizacion", response_model=UpdateReasonRead, status_code=201)
def create_update_reason(
    data: UpdateReasonCreate, actor: User = Depends(current_user), db: Session = Depends(get_db),
) -> UpdateReason:
    require_permission_manager(actor)
    reason = UpdateReason(nombre=data.nombre, activo=True)
    db.add(reason)
    db.flush()
    audit(db, "CREAR_MOTIVO_ACTUALIZACION", actor.id, details={"motivo_id": reason.id, "nombre": reason.nombre})
    commit(db)
    return reason


@app.put("/motivos-actualizacion/{reason_id}", response_model=UpdateReasonRead)
def edit_update_reason(
    reason_id: int, data: UpdateReasonEdit, actor: User = Depends(current_user), db: Session = Depends(get_db),
) -> UpdateReason:
    require_permission_manager(actor)
    reason = db.scalar(select(UpdateReason).where(UpdateReason.id == reason_id).with_for_update())
    if reason is None:
        raise HTTPException(status_code=404, detail="Motivo no encontrado")
    before = {"nombre": reason.nombre, "activo": reason.activo}
    reason.nombre, reason.activo = data.nombre, data.activo
    audit(db, "EDITAR_MOTIVO_ACTUALIZACION", actor.id, details={
        "motivo_id": reason.id, "antes": before, "despues": {"nombre": reason.nombre, "activo": reason.activo},
    })
    commit(db)
    return reason


@app.get("/ubicaciones", response_model=list[LocationRead])
def list_locations(
    kardex: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    actor: User = Depends(current_user),
    db: Session = Depends(get_db),
    kardex_contiene: str | None = None,
) -> list[LocationRead]:
    can_consult = actor.role.name == ADMIN or "ubicaciones.consultar" in {p.name for p in actor.role.permissions}
    if kardex is not None and kardex_contiene is None and not can_consult:
        require_permission(actor, "ubicaciones.registrar")
    else:
        require_permission(actor, "ubicaciones.consultar")
    if kardex is not None and kardex_contiene is not None:
        raise HTTPException(status_code=422, detail="Usa solo un filtro de kardex")
    query = select(Location).order_by(Location.id).limit(limit).offset(offset)
    if kardex is not None:
        validate_kardex_query(kardex)
        if not kardex.strip():
            raise HTTPException(status_code=422, detail="Kardex inválido")
        query = query.where(Location.kardex == kardex)
    if kardex_contiene is not None:
        validate_kardex_query(kardex_contiene)
        if not kardex_contiene:
            raise HTTPException(status_code=422, detail="Ingresa una parte del kardex")
        if db.get_bind().dialect.name == "postgresql":
            # La colación ICU permite comparar Unicode sin alterar la identidad exacta del kardex.
            search_column = func.lower(Location.kardex.collate("und-x-icu"))
            search_text = func.lower(literal(kardex_contiene).collate("und-x-icu"))
            query = query.where(func.strpos(search_column, search_text) > 0)
        else:
            query = query.where(Location.kardex.icontains(kardex_contiene, autoescape=True))
    locations = db.scalars(query).all()
    pending_ids = set(db.scalars(select(PhotoOperation.ubicacion_id).where(
        PhotoOperation.ubicacion_id.in_([location.id for location in locations]),
        PhotoOperation.tipo == "CREAR",
        PhotoOperation.estado.in_(("preparada", "objeto_listo", "pendiente_limpieza")),
    )).all()) if locations else set()
    result = []
    for location in locations:
        if can_consult:
            row = LocationRead.model_validate(location)
        else:
            row = LocationRead(id=location.id, kardex=location.kardex, revision_actual_id=location.revision_actual_id)
        row.registro_pendiente = location.id in pending_ids
        result.append(row)
    return result


@app.get("/ubicaciones/{location_id}", response_model=LocationRead)
def read_location(location_id: int, actor: User = Depends(current_user), db: Session = Depends(get_db)) -> Location:
    require_permission(actor, "ubicaciones.consultar")
    location = db.get(Location, location_id)
    if location is None:
        raise HTTPException(status_code=404, detail="Ubicación no encontrada")
    return location


@app.get("/ubicaciones/{location_id}/fotografia")
def read_location_photo(location_id: int, actor: User = Depends(current_user), db: Session = Depends(get_db)) -> Response:
    require_permission(actor, "ubicaciones.consultar")
    if db.get(Location, location_id) is None:
        raise HTTPException(status_code=404, detail="Ubicación no encontrada")
    photo = db.scalar(select(Photograph).where(Photograph.ubicacion_id == location_id))
    if photo is None:
        raise HTTPException(status_code=404, detail="La ubicación no tiene fotografía")
    if photo.storage_bucket != BUCKET:
        logger.error("Bucket inesperado para la fotografía %s", photo.id)
        raise HTTPException(status_code=502, detail="Fotografía no disponible")
    try:
        content = Storage().get(photo.storage_clave)
    except RuntimeError as exc:
        logger.error("Error al consultar Storage: %s", exc)
        raise HTTPException(status_code=502, detail="Fotografía no disponible") from exc
    if not content or (photo.sha256 and hashlib.sha256(content).hexdigest() != photo.sha256):
        logger.error("Fotografía %s ausente o con huella incorrecta en Storage", photo.id)
        raise HTTPException(status_code=502, detail="Fotografía no disponible")
    return Response(content, media_type="image/webp", headers={
        "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff",
        "X-Foto-Version": photo_version(photo.id, photo.storage_bucket, photo.storage_clave),
    })


@app.put("/ubicaciones/{location_id}/fotografia")
def update_location_photo(
    location_id: int, data: PhotographReplace, actor: User = Depends(current_user), db: Session = Depends(get_db),
) -> dict[str, str]:
    require_permission(actor, "ubicaciones.consultar")
    require_permission(actor, "ubicaciones.fotografia.editar")
    operation = db.scalar(select(PhotoOperation).where(PhotoOperation.idempotencia == data.idempotencia))
    if operation is None or operation.solicitud_sha256 is not None or operation.estado not in ("finalizada", "pendiente_limpieza"):
        raise HTTPException(status_code=409, detail="El reemplazo requiere motivo; usa el formulario de actualización")
    try:
        storage = Storage()
    except RuntimeError as exc:
        logger.error("Storage no está disponible: %s", exc)
        raise HTTPException(status_code=503, detail="No se pudo preparar Storage") from exc
    return {"estado": replace_photo(location_id, data, actor, db, storage)}


@app.put("/ubicaciones/{location_id}/actualizacion")
def update_location_data(
    location_id: int, data: LocationUpdate, actor: User = Depends(current_user), db: Session = Depends(get_db),
) -> dict[str, str]:
    require_permission(actor, "ubicaciones.consultar")
    if data.fotografia_base64 is not None:
        require_permission(actor, "ubicaciones.fotografia.editar")
    if data.latitud is not None:
        require_permission(actor, "ubicaciones.gps.editar")
    storage = None
    if data.fotografia_base64 is not None:
        try:
            storage = Storage()
        except RuntimeError as exc:
            logger.error("Storage no está disponible: %s", exc)
            raise HTTPException(status_code=503, detail="No se pudo preparar Storage") from exc
    return {"estado": update_location(location_id, data, actor, db, storage)}


@app.get("/ubicaciones/{location_id}/actualizaciones")
def list_location_updates(
    location_id: int, limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0), actor: User = Depends(current_user), db: Session = Depends(get_db),
) -> list[dict]:
    require_permission(actor, "ubicaciones.consultar")
    if db.get(Location, location_id) is None:
        raise HTTPException(status_code=404, detail="Ubicación no encontrada")
    rows = db.execute(
        select(AuditRecord, User.username).join(User, User.id == AuditRecord.usuario_id)
        .where(AuditRecord.ubicacion_id == location_id, AuditRecord.accion == "ACTUALIZAR_DATOS_UBICACION")
        .order_by(AuditRecord.ocurrido_en.desc(), AuditRecord.id.desc()).limit(limit).offset(offset)
    ).all()
    return [{
        "id": event.id, "usuario": username, "fecha": event.ocurrido_en,
        "kardex": event.detalles["kardex"], "motivo": event.detalles["motivo"],
        "observacion": event.detalles["observacion"], "fachada": event.detalles["fachada"],
        "gps": event.detalles["gps"],
        "latitud": event.detalles.get("latitud"), "longitud": event.detalles.get("longitud"),
        "precision_metros": event.detalles.get("precision_metros"),
        "capturado_en": event.detalles.get("capturado_en"),
        "metodo_coordenadas": event.detalles.get("metodo_coordenadas"),
    } for event, username in rows]


@app.get("/ubicaciones/{location_id}/revisiones", response_model=list[LocationRevisionRead])
def list_location_revisions(
    location_id: int,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    revision_id: int | None = Query(default=None, gt=0),
    actor: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[LocationRevision]:
    require_permission(actor, "ubicaciones.consultar")
    if db.get(Location, location_id) is None:
        raise HTTPException(status_code=404, detail="Ubicación no encontrada")
    query = select(LocationRevision).where(LocationRevision.ubicacion_id == location_id)
    if revision_id is not None:
        query = query.where(LocationRevision.id == revision_id)
    return list(db.scalars(query.order_by(LocationRevision.registrado_en.desc(), LocationRevision.id.desc())
                           .limit(limit).offset(offset)).all())


@app.post("/ubicaciones/{location_id}/revisiones", response_model=LocationRevisionRead, status_code=201)
def create_location_revision(
    location_id: int, data: LocationRevisionCreate, actor: User = Depends(current_user), db: Session = Depends(get_db),
) -> LocationRevision:
    require_admin(actor)
    raise HTTPException(status_code=410, detail="Las actualizaciones requieren motivo; usa el formulario de actualización")


@app.get("/procedencia", response_model=list[HistoricalSourceRead])
def list_historical_sources(
    carpeta: str | None = None,
    estado: str | None = None,
    kardex: str | None = None,
    tipo: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    actor: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[HistoricalSource]:
    require_admin(actor)
    query = select(HistoricalSource).order_by(HistoricalSource.id).limit(limit).offset(offset)
    for value in (carpeta, estado, kardex, tipo):
        if value is not None and "\x00" in value:
            raise HTTPException(status_code=422, detail="Filtro inválido")
    if carpeta is not None:
        if not carpeta.strip():
            raise HTTPException(status_code=422, detail="Carpeta inválida")
        prefix = carpeta if carpeta.endswith("/") else carpeta + "/"
        query = query.where(func.substr(HistoricalSource.ruta_original, 1, len(prefix)) == prefix)
    if estado is not None:
        query = query.where(HistoricalSource.estado_revision == estado)
    if kardex is not None:
        query = query.where(HistoricalSource.kardex == kardex)
    if tipo is not None:
        query = query.where(HistoricalSource.tipo == tipo)
    return list(db.scalars(query).all())


def historical_source(source_id: int, db: Session, *, lock: bool = False) -> HistoricalSource:
    query = select(HistoricalSource).where(HistoricalSource.id == source_id)
    if lock:
        query = query.with_for_update()
    source = db.scalar(query)
    if source is None:
        raise HTTPException(status_code=404, detail="Procedencia no encontrada")
    return source


@app.get("/procedencia/{source_id}", response_model=HistoricalSourceRead)
def read_historical_source(
    source_id: int, actor: User = Depends(current_user), db: Session = Depends(get_db),
) -> HistoricalSource:
    require_admin(actor)
    return historical_source(source_id, db)


@app.put("/procedencia/{source_id}/contrato", response_model=HistoricalSourceRead)
def confirm_historical_contract(
    source_id: int, data: ContractCreate, actor: User = Depends(current_user), db: Session = Depends(get_db),
) -> HistoricalSource:
    require_admin(actor)
    source = historical_source(source_id, db, lock=True)
    if source.estado_revision not in ("PENDIENTE", "CONFIRMADO"):
        raise HTTPException(status_code=409, detail="Estado de revisión no compatible")
    if db.get(Contract, data.kardex) is None:
        raise HTTPException(status_code=404, detail="Contrato no encontrado")
    if source.kardex == data.kardex and source.estado_revision == "CONFIRMADO":
        return source
    previous = {"kardex": source.kardex, "estado": source.estado_revision}
    source.kardex = data.kardex
    source.estado_revision = "CONFIRMADO"
    db.add(AuditRecord(
        usuario_id=actor.id, accion="CONFIRMAR_CONTRATO_PROCEDENCIA",
        detalles={"procedencia_id": source.id, "antes": previous,
                  "despues": {"kardex": source.kardex, "estado": source.estado_revision}},
    ))
    commit(db)
    return source


@app.delete("/procedencia/{source_id}/contrato", response_model=HistoricalSourceRead)
def unconfirm_historical_contract(
    source_id: int, actor: User = Depends(current_user), db: Session = Depends(get_db),
) -> HistoricalSource:
    require_admin(actor)
    source = historical_source(source_id, db, lock=True)
    if source.estado_revision not in ("PENDIENTE", "CONFIRMADO"):
        raise HTTPException(status_code=409, detail="Estado de revisión no compatible")
    if source.kardex is None and source.estado_revision == "PENDIENTE":
        return source
    previous = {"kardex": source.kardex, "estado": source.estado_revision}
    source.kardex = None
    source.estado_revision = "PENDIENTE"
    db.add(AuditRecord(
        usuario_id=actor.id, accion="RETIRAR_CONTRATO_PROCEDENCIA",
        detalles={"procedencia_id": source.id, "antes": previous,
                  "despues": {"kardex": None, "estado": "PENDIENTE"}},
    ))
    commit(db)
    return source
