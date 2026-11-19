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
from app.models import AuditEvent, AuditRecord, AuthSession, Contract, HistoricalSource, Location, LocationRevision, Permission, Photograph, Role, User, as_utc, now_utc
from app.schemas import ContractCreate, ContractRead, FieldLocationCreate, HistoricalSourceRead, LocationCreate, LocationRead, LocationRevisionCreate, LocationRevisionRead, LoginRequest, PasswordChange, PasswordReset, PermissionUpdate, PhotographReplace, RoleCreate, SessionUserRead, UserCreate, UserRead, UserUpdate
from app.fotografia import photo_version, recovery_loop, replace_photo
from app.registro_ubicacion import register_location
from app.security import ADMIN, LOCK_DURATION, MAX_ATTEMPTS, PERMISSIONS, PERMISSION_MANAGERS, current_session, current_user, dummy_hash, password_hash, require_admin, require_permission, require_permission_manager, token_hash, verify_password
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


app = FastAPI(title="GEO VISTA: usuarios y roles", lifespan=lifespan)
origins = [origin.strip() for origin in os.environ.get("CORS_ORIGINS", "").split(",") if origin.strip()]
if "*" in origins:
    raise RuntimeError("CORS_ORIGINS requiere orígenes explícitos")
app.add_middleware(
    CORSMiddleware, allow_origins=origins, allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "X-Actividad-Usuario"],
    expose_headers=["X-Foto-Version"],
)
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


def revoke_sessions(db: Session, user_id: int) -> None:
    db.execute(update(AuthSession).where(AuthSession.user_id == user_id).values(revoked=True))


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


@app.post("/auth/login")
def login(data: LoginRequest, response: Response, db: Session = Depends(get_db)) -> dict:
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
    token = secrets.token_urlsafe(32)
    db.add(AuthSession(token_hash=token_hash(token), user_id=user.id, last_activity=now))
    audit(db, "INICIO_SESION", user.id, user.id)
    commit(db)
    response.headers["Cache-Control"] = "no-store"
    return {"access_token": token, "token_type": "bearer", "must_change_password": user.must_change_password}


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
    auth.revoked = True
    audit(db, "CIERRE_SESION", auth.user_id, auth.user_id)
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
    revoke_sessions(db, user.id)
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
    role = get_role(db, data.role_id)
    protect_privileged_roles(actor, role)
    user = User(username=data.username, password_hash=password_hash(data.password.get_secret_value()), role_id=role.id, must_change_password=True)
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
    role = get_role(db, data.role_id) if data.role_id is not None else user.role
    protect_privileged_roles(actor, user.role, role)
    active = data.active if data.active is not None else user.active
    protect_last_admin(db, user, role, active)
    before = {"username": user.username, "role_id": user.role_id, "active": user.active}
    if data.username is not None:
        user.username = data.username
    if data.role_id is not None:
        user.role_id = role.id
    user.active = active
    if not active:
        revoke_sessions(db, user.id)
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
    protect_privileged_roles(actor, user.role)
    if verify_password(data.temporary_password.get_secret_value(), user.password_hash):
        raise HTTPException(status_code=400, detail="La nueva contraseña debe ser diferente")
    user.password_hash = password_hash(data.temporary_password.get_secret_value())
    user.must_change_password = True
    user.failed_attempts = 0
    user.locked_until = None
    revoke_sessions(db, user.id)
    audit(db, "RESTABLECER_CONTRASENA", actor.id, user.id)
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
    role = get_role(db, role_id)
    if role.name in PERMISSION_MANAGERS or data.name in PERMISSION_MANAGERS:
        raise HTTPException(status_code=403, detail="No se pueden renombrar roles protegidos")
    old_name = role.name
    role.name = data.name
    audit(db, "RENOMBRAR_ROL", actor.id, role_id=role.id, details={"antes": old_name, "despues": data.name})
    commit(db)
    return read_role(role)


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
    location = Location(kardex=data.kardex)
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


@app.get("/ubicaciones", response_model=list[LocationRead])
def list_locations(
    kardex: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    actor: User = Depends(current_user),
    db: Session = Depends(get_db),
    kardex_contiene: str | None = None,
) -> list[Location]:
    if kardex is not None and kardex_contiene is None and actor.role.name != ADMIN and "ubicaciones.consultar" not in {p.name for p in actor.role.permissions}:
        require_permission(actor, "ubicaciones.registrar")
    else:
        require_permission(actor, "ubicaciones.consultar")
    if kardex is not None and kardex_contiene is not None:
        raise HTTPException(status_code=422, detail="Usa solo un filtro de kardex")
    query = select(Location).order_by(Location.id).limit(limit).offset(offset)
    if kardex is not None:
        validate_kardex_query(kardex)
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
    return list(db.scalars(query).all())


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
    try:
        storage = Storage()
    except RuntimeError as exc:
        logger.error("Storage no está disponible: %s", exc)
        raise HTTPException(status_code=503, detail="No se pudo preparar Storage") from exc
    return {"estado": replace_photo(location_id, data, actor, db, storage)}


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
    location = db.scalar(select(Location).where(Location.id == location_id).with_for_update())
    if location is None:
        raise HTTPException(status_code=404, detail="Ubicación no encontrada")
    previous_id = location.revision_actual_id
    revision = LocationRevision(
        ubicacion_id=location.id, url_gps=data.url_gps, latitud=data.latitud, longitud=data.longitud,
        fecha_evento=data.fecha_evento, responsable_id=actor.id, cerrada=True,
    )
    db.add(revision)
    db.flush()
    location.revision_actual_id = revision.id
    db.add(AuditRecord(
        usuario_id=actor.id, ubicacion_id=location.id, accion="ACTUALIZAR_UBICACION",
        detalles={"revision_id": revision.id, "revision_anterior_id": previous_id},
    ))
    commit(db)
    return revision


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
