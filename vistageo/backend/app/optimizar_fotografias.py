"""Optimización local del RAR histórico; no accede a PostgreSQL ni Storage."""

import argparse
import csv
import fcntl
import hashlib
import io
import json
import os
import sqlite3
import warnings
from pathlib import Path, PurePosixPath
from uuid import uuid4

from PIL import Image, ImageOps, UnidentifiedImageError, __version__ as pillow_version

from app.inventario_historico import archive_records, build_inventory, file_type

MAX_DIMENSION = 1600
QUALITY = 80
VERSION = 1
FIELDS = (
    "kardex", "ruta_original", "ruta_optimizada", "formato_original",
    "peso_original", "peso_optimizado", "dimensiones_originales",
    "dimensiones_finales", "porcentaje_reduccion", "estado", "error",
    "sha256_original", "sha256_optimizado", "duplicado_de",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def image_info(data: bytes) -> tuple[str, tuple[int, int], Image.Image]:
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(io.BytesIO(data)) as original:
            if getattr(original, "n_frames", 1) != 1:
                raise ValueError("No se convierten imágenes con múltiples fotogramas")
            original.load()
            fmt = original.format or "DESCONOCIDO"
            dimensions = original.size
            image = ImageOps.exif_transpose(original)
            image.thumbnail((MAX_DIMENSION, MAX_DIMENSION), Image.Resampling.LANCZOS)
            if image.mode not in ("RGB", "RGBA"):
                image = image.convert("RGBA" if "transparency" in image.info or "A" in image.getbands() else "RGB")
            return fmt, dimensions, image


def verify_webp(path: Path, expected_hash: str, expected_size: tuple[int, int]) -> None:
    if path.is_symlink() or not path.is_file() or path.stat().st_size == 0:
        raise ValueError("El archivo optimizado falta, está vacío o es un enlace")
    if sha256_file(path) != expected_hash:
        raise ValueError("La huella del archivo optimizado no coincide")
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(path) as image:
            image.load()
            if image.format != "WEBP" or image.size != expected_size or max(image.size) > MAX_DIMENSION:
                raise ValueError("El archivo optimizado tiene formato o dimensiones inválidos")
            if image.info.get("exif") or image.info.get("xmp") or image.info.get("icc_profile"):
                raise ValueError("El archivo optimizado contiene metadatos inesperados")


def publish(path: Path, data: bytes) -> None:
    temporary = path.parent / f".{uuid4().hex}.tmp"
    try:
        with temporary.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path, follow_symlinks=False)
        except FileExistsError:
            if path.is_symlink() or not path.is_file() or sha256_file(path) != hashlib.sha256(data).hexdigest():
                raise ValueError("Existe un archivo diferente en la ruta de salida; no se sobrescribió")
    finally:
        temporary.unlink(missing_ok=True)


def process(archive: Path, output: Path) -> tuple[Path, Path, dict]:
    archive = archive.resolve(strict=True)
    output = output.resolve()
    if not archive.is_file() or archive.is_relative_to(output) or output.is_relative_to(archive.parent):
        raise ValueError("La salida debe estar fuera del directorio de los originales")
    digest = sha256_file(archive)
    records = archive_records(archive)
    roots = {PurePosixPath(r["Path"]).parts[0] for r in records
             if r.get("Folder") == "+" and len(PurePosixPath(r["Path"]).parts) == 2}
    folders = {PurePosixPath(r["Path"]).parts[1] for r in records
               if r.get("Folder") == "+" and len(PurePosixPath(r["Path"]).parts) == 2}
    photos = {r["Path"]: int(r["Size"]) for r in records
              if r.get("Folder") == "-" and file_type(r["Path"]) == "imagen"}
    if len(roots) != 1 or not folders or not photos:
        raise ValueError("No se pudo identificar la raíz, las carpetas de kardex o las imágenes")
    root = roots.pop()
    output.mkdir(mode=0o700, parents=True, exist_ok=True)
    state = output / "estado.sqlite3"
    if state.is_symlink() or (not state.exists() and any(output.iterdir())):
        raise ValueError("La salida ya contiene archivos ajenos al proceso")
    objects = output / "imagenes"
    if objects.is_symlink():
        raise ValueError("El directorio de imágenes no puede ser un enlace simbólico")
    objects.mkdir(mode=0o700, exist_ok=True)
    lock_path = output / ".bloqueo"
    if lock_path.is_symlink():
        raise ValueError("El bloqueo no puede ser un enlace simbólico")
    with lock_path.open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("Ya hay un proceso usando esta salida") from exc
        with sqlite3.connect(state) as db:
            db.execute("CREATE TABLE IF NOT EXISTS configuracion (id INTEGER PRIMARY KEY CHECK (id = 1), valor TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS imagenes (ruta TEXT PRIMARY KEY, datos TEXT NOT NULL)")
            config = json.dumps({"archivo_sha256": digest, "version": VERSION, "pillow": pillow_version,
                                 "dimension": MAX_DIMENSION, "calidad": QUALITY}, sort_keys=True)
            saved = db.execute("SELECT valor FROM configuracion WHERE id=1").fetchone()
            if saved is not None and saved[0] != config:
                raise ValueError("La salida pertenece a otro archivo o configuración; use otro directorio")
            db.execute("INSERT OR IGNORE INTO configuracion VALUES (1, ?)", (config,))
            db.commit()
            observed = set()
            statuses = {}

            def consume(name: str, data: bytes | None) -> None:
                observed.add(name)
                parts = PurePosixPath(name).parts
                kardex = parts[1] if len(parts) >= 3 and parts[0] == root and parts[1] in folders else ""
                original_sha = hashlib.sha256(data).hexdigest() if data is not None else ""
                output_name = hashlib.sha256(name.encode("utf-8")).hexdigest() + ".webp"
                target = objects / output_name
                previous = db.execute("SELECT datos FROM imagenes WHERE ruta=?", (name,)).fetchone()
                old = json.loads(previous[0]) if previous else None
                row = {field: "" for field in FIELDS}
                row.update(kardex=kardex, ruta_original=name, peso_original=photos[name],
                           sha256_original=original_sha)
                try:
                    if not kardex:
                        raise ValueError("No hay carpeta de kardex confirmada para esta ruta")
                    if data is None:
                        raise ValueError("Imagen superior al límite de lectura de 50 MiB")
                    if not data:
                        raise ValueError("Imagen original vacía")
                    if old and old["estado"] in ("PROCESADA", "OMITIDA_REANUDADA"):
                        if old["sha256_original"] != original_sha:
                            raise ValueError("La huella original cambió")
                        dimensions = tuple(int(x) for x in old["dimensiones_finales"].split("x"))
                        verify_webp(target, old["sha256_optimizado"], dimensions)
                        row = old
                        row["estado"] = "OMITIDA_REANUDADA"
                    else:
                        fmt, original_size, image = image_info(data)
                        row["formato_original"] = fmt
                        row["dimensiones_originales"] = f"{original_size[0]}x{original_size[1]}"
                        row["dimensiones_finales"] = f"{image.width}x{image.height}"
                        encoded = io.BytesIO()
                        image.save(encoded, format="WEBP", quality=QUALITY, method=4)
                        content = encoded.getvalue()
                        optimized_sha = hashlib.sha256(content).hexdigest()
                        publish(target, content)
                        verify_webp(target, optimized_sha, image.size)
                        row.update(ruta_optimizada=f"imagenes/{output_name}", peso_optimizado=len(content),
                                   sha256_optimizado=optimized_sha, estado="PROCESADA")
                        row["porcentaje_reduccion"] = round((1 - len(content) / len(data)) * 100, 2)
                except (OSError, ValueError, UnidentifiedImageError,
                        Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
                    row.update(estado="FALLIDA", error=f"{type(exc).__name__}: {exc}")
                db.execute("INSERT INTO imagenes (ruta, datos) VALUES (?, ?) ON CONFLICT(ruta) DO UPDATE SET datos=excluded.datos",
                           (name, json.dumps(row, ensure_ascii=False)))
                db.commit()
                statuses[name] = row
                if len(statuses) % 100 == 0:
                    print(f"Imágenes revisadas: {len(statuses)}/{len(photos)}", flush=True)

            entries, verified_sha = build_inventory(archive, on_image=consume)
            if verified_sha != digest or sha256_file(archive) != digest or observed != set(photos):
                raise RuntimeError("El archivo histórico o el inventario cambiaron durante el proceso")
            if len([item for item in entries if item["tipo"] == "imagen"]) != len(photos):
                raise RuntimeError("El número de imágenes no coincide con el inventario")
            first_hash = {}
            for name in photos:
                row = statuses[name]
                if row["sha256_original"]:
                    row["duplicado_de"] = first_hash.get(row["sha256_original"], "")
                    first_hash.setdefault(row["sha256_original"], name)
            successful = [r for r in statuses.values() if r["estado"] != "FALLIDA"]
            original_success = sum(r["peso_original"] for r in successful)
            optimized = sum(r["peso_optimizado"] for r in successful)
            summary = {
                "imagenes_totales": len(photos),
                "procesadas": sum(r["estado"] == "PROCESADA" for r in statuses.values()),
                "omitidas_reanudacion": sum(r["estado"] == "OMITIDA_REANUDADA" for r in statuses.values()),
                "fallidas": sum(r["estado"] == "FALLIDA" for r in statuses.values()),
                "peso_original_total_bytes": sum(photos.values()),
                "peso_original_exitosas_bytes": original_success,
                "peso_optimizado_bytes": optimized,
                "espacio_ahorrado_bytes": original_success - optimized,
                "reduccion_porcentaje": round((1 - optimized / original_success) * 100, 2) if original_success else None,
                "sha256_archivo_original": digest,
            }
            run = uuid4().hex
            csv_path = output / f"informe-{run}.csv"
            summary_path = output / f"resumen-{run}.json"
            with csv_path.open("x", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=FIELDS)
                writer.writeheader()
                writer.writerows(statuses[name] for name in photos)
            with summary_path.open("x", encoding="utf-8") as stream:
                json.dump(summary, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
            return csv_path, summary_path, summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Optimizar fotografías históricas localmente, sin subirlas")
    parser.add_argument("archivo", type=Path)
    parser.add_argument("salida", type=Path)
    args = parser.parse_args()
    previous_umask = os.umask(0o077)
    try:
        report, summary_file, summary = process(args.archivo, args.salida)
    finally:
        os.umask(previous_umask)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"Informe: {report}\nResumen: {summary_file}")
    if summary["fallidas"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
