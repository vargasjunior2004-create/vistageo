import hashlib

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.calidad_gps import validate_gps_measurement
from app.fotografia import replace_photo
from app.models import AuditRecord, Location, PhotoOperation, UpdateReason, User, now_utc
from app.schemas import LocationUpdate, PhotographReplace
from app.storage import Storage


def update_location(
    location_id: int, data: LocationUpdate, actor: User, db: Session, storage: Storage | None,
) -> str:
    added_fields = {"precision_metros", "capturado_en"} - data.model_fields_set
    request_hash = hashlib.sha256(data.model_dump_json(exclude=added_fields).encode()).hexdigest()

    def previous() -> AuditRecord | None:
        event = db.scalar(select(AuditRecord).where(AuditRecord.operacion_id == data.idempotencia))
        if event is not None and (
            event.usuario_id != actor.id or event.ubicacion_id != location_id
            or not event.detalles or event.detalles.get("solicitud_sha256") != request_hash
        ):
            raise HTTPException(status_code=409, detail="La operación no coincide con la solicitud original")
        return event

    def validate(location: Location) -> None:
        if location.version != data.version:
            raise HTTPException(status_code=412, detail="La ubicación cambió; vuelve a consultar")
        reason = db.scalar(select(UpdateReason).where(UpdateReason.id == data.motivo_id).with_for_update())
        if reason is None or not reason.activo:
            raise HTTPException(status_code=409, detail="El motivo no está activo; selecciona otro o contacta a un administrador")

    def publish(location: Location) -> None:
        reason = db.get(UpdateReason, data.motivo_id)
        if reason is None:
            raise RuntimeError("Motivo de actualización inexistente")
        if data.latitud is not None:
            location.latitud = data.latitud
            location.longitud = data.longitud
            location.url_gps = None
            location.metodo_coordenadas = "GPS_DISPOSITIVO" if data.precision_metros is not None else None
            location.precision_metros = data.precision_metros
            location.capturado_en = data.capturado_en
            location.capturado_por = actor.id
        location.version += 1
        db.add(AuditRecord(
            usuario_id=actor.id, ubicacion_id=location.id, accion="ACTUALIZAR_DATOS_UBICACION",
            motivo_id=reason.id, operacion_id=data.idempotencia, ocurrido_en=now_utc(),
            detalles={
                "kardex": location.kardex, "motivo": reason.nombre,
                "observacion": data.observacion, "fachada": data.fotografia_base64 is not None,
                "gps": data.latitud is not None, "solicitud_sha256": request_hash,
                "latitud": str(data.latitud) if data.latitud is not None else None,
                "longitud": str(data.longitud) if data.longitud is not None else None,
                "precision_metros": data.precision_metros,
                "capturado_en": data.capturado_en.isoformat() if data.capturado_en else None,
                "metodo_coordenadas": location.metodo_coordenadas if data.latitud is not None else None,
            },
        ))

    if data.fotografia_base64 is not None:
        if storage is None or data.foto_version is None:
            raise RuntimeError("Storage o versión de fotografía no disponibles")
        prior = previous()
        pending = db.scalar(select(PhotoOperation).where(PhotoOperation.idempotencia == data.idempotencia))
        if data.latitud is not None and prior is None and not (
            pending is not None and pending.usuario_id == actor.id and pending.ubicacion_id == location_id
            and pending.solicitud_sha256 == request_hash
        ):
            validate_gps_measurement(data.precision_metros, data.capturado_en)
        return replace_photo(
            location_id,
            PhotographReplace(idempotencia=data.idempotencia, version=data.foto_version, fotografia_base64=data.fotografia_base64),
            actor, db, storage, request_hash=request_hash, validate=validate, publish=publish,
        )

    location = db.scalar(select(Location).where(Location.id == location_id).with_for_update())
    if location is None:
        raise HTTPException(status_code=404, detail="Ubicación no encontrada")
    if previous() is not None:
        return "finalizada"
    if data.latitud is not None:
        validate_gps_measurement(data.precision_metros, data.capturado_en)
    if db.scalar(select(PhotoOperation.id).where(PhotoOperation.idempotencia == data.idempotencia)) is not None:
        raise HTTPException(status_code=409, detail="La operación no coincide con la solicitud original")
    if db.scalar(select(PhotoOperation.id).where(
        PhotoOperation.ubicacion_id == location_id,
        PhotoOperation.estado.in_(("preparada", "objeto_listo", "pendiente_limpieza")),
    )) is not None:
        raise HTTPException(status_code=409, detail="Hay una operación de fotografía pendiente; complétala antes de actualizar")
    validate(location)
    publish(location)
    db.commit()
    return "finalizada"
