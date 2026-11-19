"""Inventario del RAR sin extraer ni modificar los archivos originales."""

import argparse
import ctypes
import hashlib
import os
import subprocess
import zlib
from collections.abc import Callable
from pathlib import Path, PurePosixPath

from sqlalchemy import func, insert, select, text

from app.database import session_factory
from app.models import AuditRecord, HistoricalSource


def archive_records(path: Path) -> list[dict[str, str]]:
    result = subprocess.run(
        ["7z", "l", "-slt", "-ba", "-sccUTF-8", str(path)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if result.returncode:
        raise RuntimeError(f"No se pudo listar el archivo con 7z (código {result.returncode})")
    listing = result.stdout.decode("utf-8")
    records = []
    for block in listing.split("\n\n"):
        record = dict(line.split(" = ", 1) for line in block.splitlines() if " = " in line)
        if "Path" in record:
            records.append(record)
    return records


def list_archive(path: Path) -> dict[str, tuple[int, str]]:
    entries = {}
    for record in archive_records(path):
        if record.get("Folder") != "-":
            continue
        name, size, crc = record.get("Path"), record.get("Size"), record.get("CRC")
        if not name or not size or not crc or name in entries:
            raise ValueError("El inventario contiene una ruta repetida o metadatos incompletos")
        entries[name] = (int(size), crc.upper())
    if not entries:
        raise ValueError("El archivo no contiene archivos inventariables")
    return entries


def file_type(name: str) -> str:
    extension = PurePosixPath(name).suffix.lower()
    if extension == ".docx":
        return "documento"
    if extension in {".jpg", ".jpeg", ".png"}:
        return "imagen"
    return "otro"


def read_archive(
    path: Path, expected: dict[str, tuple[int, str]],
    on_document: Callable[[str, bytes], None] | None = None,
    on_image: Callable[[str, bytes | None], None] | None = None,
) -> list[dict]:
    lib = ctypes.CDLL("libarchive.so.13")
    pointer = ctypes.c_void_p
    lib.archive_read_new.restype = pointer
    for name in ("archive_read_support_filter_all", "archive_read_support_format_all", "archive_read_data_skip", "archive_read_free"):
        getattr(lib, name).argtypes = [pointer]
    lib.archive_read_open_filename.argtypes = [pointer, ctypes.c_char_p, ctypes.c_size_t]
    lib.archive_read_next_header.argtypes = [pointer, ctypes.POINTER(pointer)]
    lib.archive_entry_pathname.argtypes = [pointer]
    lib.archive_entry_pathname.restype = ctypes.c_char_p
    lib.archive_entry_filetype.argtypes = [pointer]
    lib.archive_entry_filetype.restype = ctypes.c_uint
    lib.archive_entry_symlink.argtypes = [pointer]
    lib.archive_entry_symlink.restype = ctypes.c_char_p
    lib.archive_entry_hardlink.argtypes = [pointer]
    lib.archive_entry_hardlink.restype = ctypes.c_char_p
    lib.archive_read_data.argtypes = [pointer, pointer, ctypes.c_size_t]
    lib.archive_read_data.restype = ctypes.c_ssize_t

    reader = lib.archive_read_new()
    if not reader:
        raise RuntimeError("No se pudo inicializar libarchive")
    entries = []
    seen = set()
    try:
        if lib.archive_read_support_filter_all(reader) != 0 or lib.archive_read_support_format_all(reader) != 0:
            raise RuntimeError("No se pudo configurar libarchive")
        if lib.archive_read_open_filename(reader, os.fsencode(path), 10240) != 0:
            raise RuntimeError("No se pudo abrir el archivo histórico")
        buffer = ctypes.create_string_buffer(1024 * 1024)
        while True:
            entry = pointer()
            status = lib.archive_read_next_header(reader, ctypes.byref(entry))
            if status == 1:
                break
            if status != 0:
                raise RuntimeError(f"Error al leer cabecera del archivo (código {status})")
            raw_name = lib.archive_entry_pathname(entry)
            if not raw_name:
                raise ValueError("Entrada histórica sin ruta")
            name = raw_name.decode("utf-8")
            kind = lib.archive_entry_filetype(entry)
            if kind == 0o040000:
                if lib.archive_read_data_skip(reader) != 0:
                    raise RuntimeError("Error al omitir directorio del archivo")
                continue
            if kind != 0o100000 or lib.archive_entry_symlink(entry) or lib.archive_entry_hardlink(entry):
                raise ValueError("El archivo contiene una entrada que no es un archivo regular")
            if name in seen or name not in expected:
                raise ValueError("Las entradas del archivo no coinciden con el inventario")
            seen.add(name)
            digest = hashlib.sha256()
            crc = size = 0
            document = bytearray() if on_document is not None and file_type(name) == "documento" else None
            image = bytearray() if on_image is not None and file_type(name) == "imagen" and expected[name][0] <= 50 * 1024 * 1024 else None
            while True:
                length = lib.archive_read_data(reader, buffer, len(buffer))
                if length == 0:
                    break
                if length < 0:
                    raise RuntimeError("Error al leer el contenido de una entrada histórica")
                chunk = buffer.raw[:length]
                digest.update(chunk)
                crc = zlib.crc32(chunk, crc)
                size += length
                if document is not None:
                    document.extend(chunk)
                if image is not None:
                    if size > 50 * 1024 * 1024:
                        raise ValueError("La imagen excede el tamaño indicado en el inventario")
                    image.extend(chunk)
            if (size, f"{crc:08X}") != expected[name]:
                raise ValueError("El tamaño o CRC de una entrada histórica no coincide")
            if document is not None and on_document is not None:
                on_document(name, bytes(document))
            if on_image is not None and file_type(name) == "imagen":
                on_image(name, bytes(image) if image is not None else None)
            entries.append({
                "ruta_original": name, "tipo": file_type(name), "sha256": digest.hexdigest(),
                "estado_revision": "PENDIENTE", "kardex": None,
            })
    finally:
        if lib.archive_read_free(reader) != 0:
            raise RuntimeError("No se pudo cerrar el archivo histórico correctamente")
    if seen != set(expected):
        raise ValueError("El archivo no contiene todas las entradas listadas")
    return entries


def build_inventory(
    path: Path,
    on_document: Callable[[str, bytes], None] | None = None,
    on_image: Callable[[str, bytes | None], None] | None = None,
) -> tuple[list[dict], str]:
    before = path.stat()
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    entries = read_archive(path, list_archive(path), on_document, on_image)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
        raise RuntimeError("El archivo histórico cambió durante el inventario")
    return entries, digest.hexdigest()


def save_inventory(entries: list[dict], archive_sha256: str) -> None:
    with session_factory()() as db:
        db.execute(text("LOCK TABLE procedencia_historica IN EXCLUSIVE MODE"))
        if db.scalar(select(func.count()).select_from(HistoricalSource)):
            raise RuntimeError("La procedencia histórica no está vacía; no se repetirá la carga")
        db.execute(insert(HistoricalSource), entries)
        db.add(AuditRecord(
            accion="INVENTARIAR_FUENTE_HISTORICA",
            detalles={"archivo_sha256": archive_sha256, "archivos": len(entries), "origen": "cli"},
        ))
        db.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description="Inventariar archivos históricos sin importar su contenido")
    parser.add_argument("archivo", type=Path)
    parser.add_argument("--aplicar", action="store_true", help="Guardar el inventario en la base configurada")
    parser.add_argument("--sha256-esperado", help="Huella SHA-256 obtenida en la simulación")
    parser.add_argument("--cantidad-esperada", type=int, help="Cantidad de archivos obtenida en la simulación")
    args = parser.parse_args()
    if args.aplicar and (args.sha256_esperado is None or args.cantidad_esperada is None):
        parser.error("--aplicar requiere --sha256-esperado y --cantidad-esperada de la simulación")
    entries, digest = build_inventory(args.archivo.resolve(strict=True))
    print(f"Inventario verificado: {len(entries)} archivos; SHA-256 del archivo: {digest}")
    if args.aplicar:
        if digest != args.sha256_esperado or len(entries) != args.cantidad_esperada:
            raise SystemExit("El archivo o la cantidad no coinciden con la simulación; no se guardó nada.")
        save_inventory(entries, digest)
        print("Inventario guardado; todos los registros quedan pendientes y sin kardex asociado.")
    else:
        print("Simulación completada; no se guardaron registros.")


if __name__ == "__main__":
    main()
