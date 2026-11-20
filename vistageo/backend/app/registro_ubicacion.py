import base64
import binascii
import hashlib
import io
import logging

from fastapi import HTTPException
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import AuditRecord, Contract, Location, LocationRevision, PhotoOperation, Photograph, User, now_utc
from app.schemas import FieldLocationCreate
from app.storage import BUCKET, Storage

logger = logging.getLogger(__name__)


def optimize_photo(encoded: str) -> bytes:
    try:
        original = base64.b64decode(encoded, validate=True)
        if not original or len(original) > 8 * 1024 * 1024:
            raise ValueError("Tamaño de fotografía inválido")
        with Image.open(io.BytesIO(original)) as image:
            if image.format not in {"JPEG", "PNG", "WEBP"} or image.width * image.height > 32_000_000:
                raise ValueError("Formato o dimensiones no admitidos")
            if getattr(image, "n_frames", 1) != 1:
                raise ValueError("No se admiten imágenes animadas")
            image = ImageOps.exif_transpose(image)
            image.thumbnail((1600, 1600))
            output = io.BytesIO()
            image.convert("RGB").save(output, "WEBP", quality=80)
            return output.getvalue()
    except (ValueError, binascii.Error, OSError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
        raise HTTPException(status_code=422, detail="Fotografía inválida o demasiado grande") from exc


def register_location(data: FieldLocationCreate, actor: User, db: Session, storage: Storage) -> Location:
    content = optimize_photo(data.fotografia_base64)
    digest = hashlib.sha256(content).hexdigest()
    key = f"registros/v1/{data.idempotencia}/{digest}.webp"
    operation = db.scalar(select(PhotoOperation).where(PhotoOperation.idempotencia == data.idempotencia).with_for_update())
    if operation is None:
        if db.scalar(select(Location.id).where(Location.kardex == data.kardex)) is not None:
            raise HTTPException(status_code=409, detail="El kardex ya tiene una ubicación")
        contract = db.get(Contract, data.kardex)
        if contract is None:
            db.add(Contract(kardex=data.kardex))
            db.add(AuditRecord(usuario_id=actor.id, accion="CREAR_CONTRATO", detalles={"kardex": data.kardex}))
        location = Location(kardex=data.kardex, creado_por=actor.id, creado_en=now_utc())
        db.add(location)
        try:
            db.flush()
            revision = LocationRevision(
                ubicacion_id=location.id, latitud=data.latitud, longitud=data.longitud,
                responsable_id=actor.id, cerrada=True,
            )
            db.add(revision)
            db.flush()
            operation = PhotoOperation(
                idempotencia=data.idempotencia, ubicacion_id=location.id, usuario_id=actor.id,
                tipo="CREAR", estado="preparada", nuevo_bucket=BUCKET, nueva_clave=key,
            )
            db.add(operation)
            db.add(AuditRecord(usuario_id=actor.id, ubicacion_id=location.id, accion="PREPARAR_REGISTRO_UBICACION",
                               detalles={"revision_id": revision.id, "operacion": str(data.idempotencia)}))
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(status_code=409, detail="El kardex ya tiene una ubicación o está en uso") from exc
        operation = db.scalar(select(PhotoOperation).where(PhotoOperation.idempotencia == data.idempotencia).with_for_update())

    location = db.get(Location, operation.ubicacion_id)
    revision = db.scalar(select(LocationRevision).where(LocationRevision.ubicacion_id == operation.ubicacion_id)
                         .order_by(LocationRevision.id).limit(1))
    if (location is None or revision is None or location.kardex != data.kardex
            or operation.usuario_id != actor.id or operation.nueva_clave != key
            or revision.latitud != data.latitud or revision.longitud != data.longitud):
        raise HTTPException(status_code=409, detail="La operación no coincide con el registro original")
    if operation.estado == "finalizada":
        return location
    if operation.estado not in ("preparada", "objeto_listo"):
        raise HTTPException(status_code=409, detail="La operación requiere revisión")

    try:
        remote = storage.get(key)
        if remote is None:
            storage.put(key, content)
            remote = storage.get(key)
        if remote is None or hashlib.sha256(remote).hexdigest() != digest:
            raise RuntimeError("No se pudo verificar el objeto en Storage")
    except RuntimeError as exc:
        db.rollback()
        logger.error("No se pudo completar la operación de fotografía: %s", exc)
        raise HTTPException(status_code=503, detail="Registro pendiente; vuelve a intentar con los mismos datos") from exc

    location = db.scalar(select(Location).where(Location.id == operation.ubicacion_id).with_for_update())
    revision = db.scalar(select(LocationRevision).where(LocationRevision.ubicacion_id == location.id)
                         .order_by(LocationRevision.id).limit(1))
    if operation.estado == "finalizada":
        return location
    existing_photo = db.scalar(select(Photograph.id).where(Photograph.ubicacion_id == location.id))
    if operation.estado not in ("preparada", "objeto_listo") or existing_photo is not None or location.revision_actual_id is not None:
        if operation.estado in ("preparada", "objeto_listo"):
            operation.estado = "pendiente_limpieza"
            operation.limpieza_bucket = BUCKET
            operation.limpieza_clave = key
            operation.ultimo_error = "La ubicación cambió antes de publicar"
            db.commit()
        raise HTTPException(status_code=409, detail="La ubicación cambió; la operación requiere revisión")
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        db.execute(text("SELECT set_config('app.usuario_id', :actor, true)"), {"actor": str(actor.id)})
    photo = Photograph(ubicacion_id=location.id, storage_bucket=BUCKET, storage_clave=key,
                       sha256=digest, registrado_por=actor.id)
    db.add(photo)
    db.flush()
    location.revision_actual_id = revision.id
    location.latitud = revision.latitud
    location.longitud = revision.longitud
    location.url_gps = revision.url_gps
    operation.fotografia_id = photo.id
    operation.estado = "finalizada"
    operation.intentos += 1
    db.add(AuditRecord(usuario_id=actor.id, ubicacion_id=location.id, accion="REGISTRAR_UBICACION",
                       detalles={"revision_id": revision.id}))
    db.commit()
    return location
