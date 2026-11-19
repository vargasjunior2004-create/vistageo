"""Carga recuperable de las primeras fotografías históricas optimizadas."""

import argparse
import csv
import hashlib
import json
import sqlite3
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import quote
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import select, text
from sqlalchemy.exc import OperationalError, SQLAlchemyError

from app.database import session_factory
from app.inventario_historico import archive_records, file_type
from app.models import HistoricalSource, Location, PhotoOperation, Photograph
from app.optimizar_fotografias import sha256_file, verify_webp
from app.storage import BUCKET, Storage, StorageTransientError


@dataclass(frozen=True)
class Photo:
    kardex: str
    source_id: int
    location_id: int
    original_sha: str
    optimized_sha: str
    file: Path

    @property
    def key(self) -> str:
        return f"historicas/v1/{self.source_id}/{self.optimized_sha}.webp"

    @property
    def token(self) -> UUID:
        return uuid5(NAMESPACE_URL, f"geovista:{BUCKET}:{self.key}")


def build_plan(archive: Path, output: Path, report: Path) -> tuple[list[Photo], int]:
    archive = archive.resolve(strict=True)
    output = output.resolve(strict=True)
    archive_digest = sha256_file(archive)
    records = archive_records(archive)
    first = {}
    image_paths = set()
    for record in records:
        if record.get("Folder") != "-" or file_type(record["Path"]) != "imagen":
            continue
        parts = PurePosixPath(record["Path"]).parts
        if len(parts) < 3:
            raise ValueError("Imagen histórica sin carpeta de kardex")
        image_paths.add(record["Path"])
        first.setdefault(parts[1], record["Path"])
    with report.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    by_path = {row["ruta_original"]: row for row in rows}
    if len(by_path) != len(rows) or set(by_path) != image_paths:
        raise ValueError("El informe no coincide con los archivos del RAR")
    state_path = output / "estado.sqlite3"
    if state_path.is_symlink() or not state_path.is_file():
        raise ValueError("Falta el estado de optimización")
    with sqlite3.connect(f"file:{quote(str(state_path))}?mode=ro", uri=True) as state:
        settings_row = state.execute("SELECT valor FROM configuracion WHERE id=1").fetchone()
        if not settings_row or json.loads(settings_row[0]).get("archivo_sha256") != archive_digest:
            raise ValueError("El estado no corresponde a la huella del RAR")
        saved = {path: json.loads(data) for path, data in state.execute("SELECT ruta, datos FROM imagenes")}
    if set(saved) != image_paths:
        raise ValueError("El estado de optimización está incompleto")
    with session_factory()() as db:
        db.execute(text("SET TRANSACTION READ ONLY"))
        sources = db.execute(select(
            HistoricalSource.id, HistoricalSource.ruta_original, HistoricalSource.tipo,
            HistoricalSource.sha256, HistoricalSource.estado_revision, HistoricalSource.kardex,
        ).where(HistoricalSource.tipo == "imagen")).all()
        locations = dict(db.execute(select(Location.kardex, Location.id)).all())
    source_by_path = {s.ruta_original: s for s in sources}
    if len(source_by_path) != len(sources) or set(source_by_path) != image_paths:
        raise ValueError("La procedencia de imágenes no coincide con el RAR")
    result = []
    failed = 0
    for kardex, name in first.items():
        row, state_row, source = by_path[name], saved[name], source_by_path[name]
        if (row["kardex"] != kardex or source.kardex != kardex
                or source.estado_revision != "CONFIRMADO"
                or source.sha256 != row["sha256_original"] or kardex not in locations):
            raise ValueError("La asociación o huella de una fotografía no coincide con la procedencia")
        if any(str(state_row.get(field, "")) != row[field] for field in (
            "kardex", "ruta_original", "sha256_original", "sha256_optimizado",
            "ruta_optimizada", "dimensiones_finales", "peso_optimizado",
        )):
            raise ValueError("El informe y el estado de optimización no coinciden")
        if row["estado"] not in ("PROCESADA", "OMITIDA_REANUDADA"):
            if state_row["estado"] != "FALLIDA":
                raise ValueError("El informe y el estado de una fotografía no coinciden")
            failed += 1
            continue
        if state_row["estado"] not in ("PROCESADA", "OMITIDA_REANUDADA"):
            raise ValueError("El estado de optimización no confirma la fotografía")
        name_hash = hashlib.sha256(name.encode("utf-8")).hexdigest()
        if row["ruta_optimizada"] != f"imagenes/{name_hash}.webp":
            raise ValueError("Ruta de imagen optimizada inesperada")
        target = output / row["ruta_optimizada"]
        if target.parent.is_symlink():
            raise ValueError("El directorio de imágenes es un enlace simbólico")
        dimensions = tuple(int(value) for value in row["dimensiones_finales"].split("x"))
        if len(dimensions) != 2:
            raise ValueError("Dimensiones inválidas")
        verify_webp(target, row["sha256_optimizado"], dimensions)
        if target.stat().st_size != int(row["peso_optimizado"]):
            raise ValueError("El tamaño de la imagen optimizada no coincide")
        result.append(Photo(kardex, source.id, locations[kardex], source.sha256,
                            row["sha256_optimizado"], target))
    if sha256_file(archive) != archive_digest:
        raise ValueError("El archivo histórico cambió durante la preparación")
    return result, failed


def import_photo(photo: Photo, storage: Storage) -> str:
    factory = session_factory()
    created = False
    with factory.begin() as db:
        location = db.scalar(select(Location).where(Location.id == photo.location_id).with_for_update())
        source = db.get(HistoricalSource, photo.source_id)
        if (location is None or location.kardex != photo.kardex or source is None
                or source.kardex != photo.kardex or source.estado_revision != "CONFIRMADO"
                or source.tipo != "imagen" or source.sha256 != photo.original_sha):
            raise RuntimeError("La procedencia o ubicación cambió")
        operation = db.scalar(select(PhotoOperation).where(PhotoOperation.idempotencia == photo.token).with_for_update())
        current = db.scalar(select(Photograph).where(Photograph.ubicacion_id == photo.location_id))
        if operation is not None and operation.estado == "pendiente_limpieza":
            return "pendiente_limpieza"
        if current is not None:
            if operation is not None and operation.estado in ("preparada", "objeto_listo"):
                if current.storage_bucket == BUCKET and current.storage_clave == photo.key:
                    operation.estado = "finalizada"
                    operation.fotografia_id = current.id
                else:
                    operation.estado = "pendiente_limpieza"
                    operation.limpieza_bucket = BUCKET
                    operation.limpieza_clave = photo.key
                    operation.ultimo_error = "La ubicación ya tiene otra fotografía"
                    return "pendiente_limpieza"
            return "existente"
        if operation is None:
            operation = PhotoOperation(
                idempotencia=photo.token, ubicacion_id=photo.location_id, usuario_id=None,
                procedencia_id=photo.source_id, tipo="CREAR", estado="preparada",
                nuevo_bucket=BUCKET, nueva_clave=photo.key,
            )
            db.add(operation)
            db.flush()
            created = True
        elif (operation.ubicacion_id != photo.location_id or operation.procedencia_id != photo.source_id
              or operation.nuevo_bucket != BUCKET or operation.nueva_clave != photo.key
              or operation.estado not in ("preparada", "objeto_listo")):
            raise RuntimeError("La operación histórica existente no se puede reanudar")

    try:
        content = photo.file.read_bytes()
        if hashlib.sha256(content).hexdigest() != photo.optimized_sha:
            raise RuntimeError("La imagen optimizada cambió después de la validación")
        remote = storage.get(photo.key)
        if remote is not None and created:
            with factory.begin() as db:
                operation = db.scalar(select(PhotoOperation).where(PhotoOperation.idempotencia == photo.token).with_for_update())
                operation.estado = "cancelada"
                operation.ultimo_error = "La clave ya existía antes de subir el objeto"
            raise RuntimeError("La clave de Storage ya existía y no se sobrescribió")
        if remote is None:
            storage.put(photo.key, content)
            remote = storage.get(photo.key)
        if remote is None or hashlib.sha256(remote).hexdigest() != photo.optimized_sha:
            raise RuntimeError("El objeto remoto no coincide con la fotografía optimizada")
        with factory.begin() as db:
            operation = db.scalar(select(PhotoOperation).where(PhotoOperation.idempotencia == photo.token).with_for_update())
            if operation is None or operation.estado not in ("preparada", "objeto_listo"):
                raise RuntimeError("El estado de la operación cambió")
            operation.estado = "objeto_listo"
            operation.intentos += 1
            operation.ultimo_error = None
        with factory.begin() as db:
            db.execute(text("SELECT set_config('app.usuario_id', '', true)"))
            location = db.scalar(select(Location).where(Location.id == photo.location_id).with_for_update())
            operation = db.scalar(select(PhotoOperation).where(PhotoOperation.idempotencia == photo.token).with_for_update())
            if location is None or operation is None or operation.estado != "objeto_listo":
                raise RuntimeError("El estado de la operación cambió antes de publicar")
            current = db.scalar(select(Photograph).where(Photograph.ubicacion_id == photo.location_id))
            if current is not None:
                if current.storage_bucket == BUCKET and current.storage_clave == photo.key:
                    operation.estado = "finalizada"
                    operation.fotografia_id = current.id
                    return "existente"
                operation.estado = "pendiente_limpieza"
                operation.limpieza_bucket = BUCKET
                operation.limpieza_clave = photo.key
                operation.ultimo_error = "La ubicación ya tiene otra fotografía"
                return "pendiente_limpieza"
            image = Photograph(ubicacion_id=photo.location_id, storage_bucket=BUCKET,
                               storage_clave=photo.key, sha256=photo.optimized_sha,
                               sha256_original=photo.original_sha, procedencia_id=photo.source_id,
                               registrado_por=None)
            db.add(image)
            db.flush()
            operation.estado = "finalizada"
            operation.fotografia_id = image.id
        return "creada"
    except Exception as exc:
        try:
            with factory.begin() as db:
                operation = db.scalar(select(PhotoOperation).where(PhotoOperation.idempotencia == photo.token).with_for_update())
                if operation is not None and operation.estado in ("preparada", "objeto_listo"):
                    operation.intentos += 1
                    operation.ultimo_error = f"{type(exc).__name__}: operación interrumpida"
        except SQLAlchemyError as logging_error:
            raise exc from logging_error
        raise


def import_with_retries(photo: Photo, storage: Storage) -> str:
    for attempt in range(8):
        try:
            return import_photo(photo, storage)
        except (OperationalError, StorageTransientError) as exc:
            if attempt == 7:
                raise RuntimeError("Se agotaron los reintentos de conexión") from exc
            delay = min(2 ** attempt, 30)
            print(f"Conexión interrumpida; reintentando en {delay} segundos.", flush=True)
            time.sleep(delay)
    raise AssertionError("Bucle de reintentos terminado inesperadamente")


def run(photos: list[Photo], storage: Storage) -> dict[str, int]:
    counts = {"creada": 0, "existente": 0, "pendiente_limpieza": 0}
    iterator = iter(photos)
    with ThreadPoolExecutor(max_workers=4) as executor:
        pending = {executor.submit(import_with_retries, photo, storage) for photo in [next(iterator, None) for _ in range(4)] if photo}
        while pending:
            finished, pending = wait(pending, return_when=FIRST_COMPLETED)
            for future in finished:
                status = future.result()
                counts[status] += 1
                if sum(counts.values()) % 100 == 0:
                    print(f"Fotografías revisadas: {sum(counts.values())}/{len(photos)}", flush=True)
                if status == "pendiente_limpieza":
                    raise RuntimeError("Una fotografía existente requiere revisar una operación de limpieza")
                photo = next(iterator, None)
                if photo is not None:
                    pending.add(executor.submit(import_with_retries, photo, storage))
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description="Preparar o cargar primeras fotografías históricas")
    parser.add_argument("archivo", type=Path)
    parser.add_argument("salida", type=Path)
    parser.add_argument("informe", type=Path)
    parser.add_argument("--aplicar", action="store_true")
    parser.add_argument("--sha256-esperado")
    parser.add_argument("--candidatas-esperadas", type=int)
    parser.add_argument("--fallidas-esperadas", type=int)
    args = parser.parse_args()
    if args.aplicar and (args.sha256_esperado is None or args.candidatas_esperadas is None or args.fallidas_esperadas is None):
        parser.error("--aplicar requiere la huella y cantidades obtenidas de la simulación")
    digest = sha256_file(args.archivo.resolve(strict=True))
    if args.aplicar and digest != args.sha256_esperado:
        raise SystemExit("La huella de la fuente no coincide; no se subieron objetos")
    photos, failed = build_plan(args.archivo, args.salida, args.informe)
    if sha256_file(args.archivo) != digest:
        raise SystemExit("La fuente cambió durante la preparación; no se subieron objetos")
    print(f"Candidatas válidas: {len(photos)}; primeras imágenes fallidas: {failed}; SHA-256: {digest}", flush=True)
    if not args.aplicar:
        print("Simulación completada; no se subieron objetos.")
        return
    if (len(photos), failed) != (args.candidatas_esperadas, args.fallidas_esperadas):
        raise SystemExit("Las cantidades no coinciden; no se subieron objetos")
    storage = Storage()
    storage.check_bucket(max((photo.file.stat().st_size for photo in photos), default=0))
    if not photos:
        print("No hay fotografías válidas para cargar.")
        return
    first = import_with_retries(photos[0], storage)
    if first == "pendiente_limpieza":
        raise RuntimeError("La carga inicial requiere revisar una operación de limpieza")
    print(f"Carga inicial verificada: {first}", flush=True)
    counts = run(photos[1:], storage)
    counts[first] += 1
    print("Resultado:", json.dumps(counts, ensure_ascii=False))


if __name__ == "__main__":
    main()
