import asyncio
import hashlib
import logging
from collections.abc import Callable

from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import session_factory
from app.models import AuditRecord, Location, PhotoOperation, Photograph, User, now_utc
from app.registro_ubicacion import optimize_photo
from app.schemas import PhotographReplace
from app.storage import BUCKET, Storage

logger = logging.getLogger(__name__)


def photo_version(photo_id: int, bucket: str, key: str) -> str:
    return hashlib.sha256(f"{photo_id}\0{bucket}\0{key}".encode()).hexdigest()


def cleanup_operation(db: Session, operation_id: int, storage: Storage) -> str:
    operation = db.scalar(select(PhotoOperation).where(PhotoOperation.id == operation_id).with_for_update())
    if operation is None or operation.tipo != "REEMPLAZAR":
        raise RuntimeError("Operación de reemplazo inexistente")
    if operation.estado != "pendiente_limpieza":
        return operation.estado
    key = operation.limpieza_clave
    if operation.limpieza_bucket != BUCKET or key is None:
        raise RuntimeError("Clave de limpieza inválida")
    location = db.scalar(select(Location).where(Location.id == operation.ubicacion_id).with_for_update())
    if location is None:
        raise RuntimeError("Ubicación de limpieza inexistente")
    current = db.scalar(select(Photograph.id).where(
        Photograph.storage_bucket == BUCKET, Photograph.storage_clave == key
    ))
    if current is not None:
        operation.ultimo_error = "La clave de limpieza sigue siendo una fotografía vigente"
        operation.intentos += 1
        operation.actualizado_en = now_utc()
        db.commit()
        logger.error("La operación %s no puede limpiar una fotografía vigente", operation.id)
        return "pendiente_limpieza"
    try:
        storage.delete(key)
        if storage.get(key) is not None:
            raise RuntimeError("Storage todavía contiene la fotografía anterior")
    except RuntimeError as exc:
        operation.ultimo_error = "No se pudo confirmar la eliminación en Storage"
        operation.intentos += 1
        operation.actualizado_en = now_utc()
        db.commit()
        logger.error("Limpieza pendiente para operación %s: %s", operation.id, exc)
        return "pendiente_limpieza"
    operation.estado = "finalizada" if key == operation.anterior_clave else "cancelada"
    operation.ultimo_error = None
    operation.intentos += 1
    operation.actualizado_en = now_utc()
    db.commit()
    return operation.estado


def replace_photo(
    location_id: int, data: PhotographReplace, actor: User, db: Session, storage: Storage,
    *, request_hash: str | None = None, validate: Callable[[Location], None] | None = None,
    publish: Callable[[Location], None] | None = None,
) -> str:
    content = optimize_photo(data.fotografia_base64)
    digest = hashlib.sha256(content).hexdigest()
    new_key = f"reemplazos/v1/{data.idempotencia}/{digest}.webp"
    operation = db.scalar(select(PhotoOperation).where(
        PhotoOperation.idempotencia == data.idempotencia
    ).with_for_update())
    location = db.scalar(select(Location).where(Location.id == location_id).with_for_update())
    if location is None:
        raise HTTPException(status_code=404, detail="Ubicación no encontrada")
    if operation is None:
        operation = db.scalar(select(PhotoOperation).where(
            PhotoOperation.idempotencia == data.idempotencia
        ))
        if operation is not None:
            db.rollback()
            operation = db.scalar(select(PhotoOperation).where(
                PhotoOperation.idempotencia == data.idempotencia
            ).with_for_update())
            location = db.scalar(select(Location).where(Location.id == location_id).with_for_update())
            if location is None:
                raise HTTPException(status_code=404, detail="Ubicación no encontrada")
    photo = db.scalar(select(Photograph).where(Photograph.ubicacion_id == location_id).with_for_update())
    if operation is None:
        if validate is not None:
            validate(location)
        if photo is None:
            raise HTTPException(status_code=404, detail="La ubicación no tiene fotografía para reemplazar")
        if photo.storage_bucket != BUCKET:
            raise HTTPException(status_code=409, detail="La fotografía requiere revisión")
        if photo_version(photo.id, photo.storage_bucket, photo.storage_clave) != data.version:
            raise HTTPException(status_code=412, detail="La fotografía cambió; vuelve a consultar antes de reemplazar")
        operation = PhotoOperation(
            idempotencia=data.idempotencia, ubicacion_id=location_id, usuario_id=actor.id,
            fotografia_id=photo.id, tipo="REEMPLAZAR", estado="preparada",
            solicitud_sha256=request_hash,
            nuevo_bucket=BUCKET, nueva_clave=new_key,
            anterior_bucket=photo.storage_bucket, anterior_clave=photo.storage_clave,
        )
        db.add(operation)
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(status_code=409, detail="Ya hay una operación de fotografía en curso") from exc
        operation = db.scalar(select(PhotoOperation).where(
            PhotoOperation.idempotencia == data.idempotencia
        ).with_for_update())
        location = db.scalar(select(Location).where(Location.id == location_id).with_for_update())
        photo = db.scalar(select(Photograph).where(Photograph.ubicacion_id == location_id).with_for_update())

    if (operation is None or operation.tipo != "REEMPLAZAR" or operation.ubicacion_id != location_id
            or operation.usuario_id != actor.id or operation.nueva_clave != new_key
            or operation.fotografia_id is None or operation.anterior_bucket is None or operation.anterior_clave is None
            or photo_version(operation.fotografia_id, operation.anterior_bucket, operation.anterior_clave) != data.version):
        raise HTTPException(status_code=409, detail="La operación no coincide con el reemplazo original")
    if operation.solicitud_sha256 is None and request_hash is not None and operation.estado in ("preparada", "objeto_listo"):
        if validate is not None:
            validate(location)
        operation.solicitud_sha256 = request_hash
    elif operation.solicitud_sha256 != request_hash:
        raise HTTPException(status_code=409, detail="La operación no coincide con la solicitud original")
    if operation.estado == "pendiente_limpieza":
        state = cleanup_operation(db, operation.id, storage)
        if operation.limpieza_clave != operation.anterior_clave or state == "cancelada":
            raise HTTPException(status_code=409, detail="El reemplazo fue cancelado; vuelve a consultar")
        return state
    if operation.estado == "finalizada":
        return "finalizada"
    if operation.estado not in ("preparada", "objeto_listo"):
        raise HTTPException(status_code=409, detail="El reemplazo requiere revisión")
    if (photo is None or photo.id != operation.fotografia_id
            or photo.storage_bucket != operation.anterior_bucket or photo.storage_clave != operation.anterior_clave):
        operation.estado = "pendiente_limpieza"
        operation.limpieza_bucket = BUCKET
        operation.limpieza_clave = new_key
        operation.ultimo_error = "La fotografía cambió antes de publicar"
        db.commit()
        raise HTTPException(status_code=409, detail="La fotografía cambió; el reemplazo requiere revisión")
    if validate is not None:
        validate(location)
    try:
        remote = storage.get(new_key)
        if remote is None:
            storage.put(new_key, content)
            remote = storage.get(new_key)
        if remote is None or hashlib.sha256(remote).hexdigest() != digest:
            raise RuntimeError("No se pudo verificar la fotografía nueva")
    except RuntimeError as exc:
        db.rollback()
        logger.error("Reemplazo de fotografía interrumpido: %s", exc)
        raise HTTPException(status_code=503, detail="Reemplazo pendiente; vuelve a intentar con los mismos datos") from exc

    old_sha = photo.sha256
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text("SELECT set_config('app.usuario_id', :actor, true)"), {"actor": str(actor.id)})
    if publish is not None:
        publish(location)
    photo.storage_bucket = BUCKET
    photo.storage_clave = new_key
    photo.sha256 = digest
    operation.estado = "pendiente_limpieza"
    operation.limpieza_bucket = operation.anterior_bucket
    operation.limpieza_clave = operation.anterior_clave
    operation.intentos += 1
    db.add(AuditRecord(
        usuario_id=actor.id, ubicacion_id=location_id, accion="CONFIRMAR_REEMPLAZO_FOTOGRAFIA",
        detalles={"fotografia_id": photo.id, "sha256_anterior": old_sha, "sha256_nuevo": digest,
                  "operacion": str(data.idempotencia)},
    ))
    db.commit()
    return cleanup_operation(db, operation.id, storage)


def recover_pending_replacements() -> None:
    factory = session_factory()
    with factory() as db:
        ids = list(db.scalars(select(PhotoOperation.id).where(
            PhotoOperation.tipo == "REEMPLAZAR", PhotoOperation.estado == "pendiente_limpieza"
        ).order_by(PhotoOperation.actualizado_en, PhotoOperation.id).limit(20)).all())
    if not ids:
        return
    storage = Storage()
    for operation_id in ids:
        try:
            with factory() as db:
                cleanup_operation(db, operation_id, storage)
        except (RuntimeError, SQLAlchemyError) as exc:
            logger.error("No se pudo recuperar la operación %s: %s", operation_id, exc)


async def recovery_loop() -> None:
    while True:
        try:
            await asyncio.to_thread(recover_pending_replacements)
        except (RuntimeError, SQLAlchemyError) as exc:
            logger.error("No se pudo iniciar la recuperación de fotografías: %s", exc)
        await asyncio.sleep(60)
