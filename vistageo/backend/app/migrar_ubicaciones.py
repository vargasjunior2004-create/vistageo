"""Importa la primera URL de mapa de cada carpeta histórica."""

import argparse
import io
import re
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path, PurePosixPath
from urllib.parse import parse_qs, unquote, urlsplit
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

from sqlalchemy import BigInteger, column, select, text, update, values
from sqlalchemy.dialects.postgresql import insert

from app.database import session_factory
from app.inventario_historico import build_inventory
from app.models import AuditRecord, HistoricalSource, Location, LocationRevision

URL_PATTERN = re.compile(r"https?://[^\s<>\"']+|www\.[^\s<>\"']+", re.I)
COORDINATES = re.compile(r"^(-?\d{1,2}\.\d+),\s*(-?\d{1,3}\.\d+)")
AT_COORDINATES = re.compile(r"@(-?\d{1,2}\.\d+),(-?\d{1,3}\.\d+)")
RELATION_ID = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"


def is_map_url(url: str) -> bool:
    try:
        parsed = urlsplit(url if "://" in url else "https://" + url)
        host = (parsed.hostname or "").lower()
        if host in {"maps.app.goo.gl", "maps.google.com"} or host.startswith("maps.google."):
            return True
        if host == "goo.gl":
            return parsed.path.startswith("/maps")
        return (host == "google.com" or host.startswith("www.google.")) and parsed.path.startswith("/maps")
    except ValueError:
        return False


def first_map_url(data: bytes) -> str | None:
    with ZipFile(io.BytesIO(data)) as doc:
        infos = doc.infolist()
        if sum(info.file_size for info in infos) > 10 * 1024 * 1024:
            raise ValueError("Documento demasiado grande para procesar")
        if doc.testzip() is not None:
            raise BadZipFile("Documento con contenido dañado")
        names = doc.namelist()
        if "word/document.xml" not in names:
            raise ValueError("Documento sin contenido principal")
        parts = ["word/document.xml"] + [
            name for name in names if name.startswith("word/") and name.endswith(".xml") and name != "word/document.xml"
        ]
        for name in parts:
            part = PurePosixPath(name)
            rel_name = str(part.parent / "_rels" / (part.name + ".rels"))
            relationships: dict[str, str] = {}
            if rel_name in names:
                root = ElementTree.fromstring(doc.read(rel_name))
                for item in root:
                    if item.attrib.get("TargetMode") == "External" and item.attrib.get("Id") and item.attrib.get("Target"):
                        relationships[item.attrib["Id"]] = item.attrib["Target"]
            root = ElementTree.fromstring(doc.read(name))
            text_parts = []
            offset = 0
            candidates: list[tuple[int, int, str]] = []
            used_relationships = set()
            for element in root.iter():
                rel_id = element.attrib.get(RELATION_ID)
                if rel_id in relationships:
                    target = relationships[rel_id]
                    candidates.append((offset, len(candidates), target.strip()))
                    used_relationships.add(rel_id)
                if element.tag.rsplit("}", 1)[-1] in ("t", "instrText") and element.text:
                    text_parts.append(element.text)
                    offset += len(element.text)
            joined = "".join(text_parts)
            for match in URL_PATTERN.finditer(joined):
                candidates.append((match.start(), len(candidates), match.group().rstrip(".,;:)]}")))
            for rel_id, target in relationships.items():
                if rel_id not in used_relationships:
                    candidates.append((offset, len(candidates), target.strip()))
            for _, _, candidate in sorted(candidates):
                if is_map_url(candidate):
                    return candidate
    return None


def coordinates(url: str) -> tuple[Decimal | None, Decimal | None]:
    decoded = unquote(url)
    match = AT_COORDINATES.search(decoded)
    if match is None:
        parsed = urlsplit(decoded if "://" in decoded else "https://" + decoded)
        params = parse_qs(parsed.query)
        for key in ("q", "query", "ll", "center"):
            for value in params.get(key, []):
                match = COORDINATES.match(value.strip())
                if match is not None:
                    break
            if match is not None:
                break
    if match is None:
        return None, None
    latitude, longitude = Decimal(match.group(1)), Decimal(match.group(2))
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return None, None
    return latitude, longitude


@dataclass(frozen=True)
class LocationPlan:
    entries: list[dict]
    archive_sha256: str
    links: dict[str, tuple[str, str]]
    invalid_documents: int


def build_plan(path: Path) -> LocationPlan:
    first_links: dict[str, tuple[str, str]] = {}
    invalid_documents = 0

    def consume(name: str, data: bytes) -> None:
        nonlocal invalid_documents
        parts = PurePosixPath(name).parts
        if len(parts) < 3 or parts[1] in first_links:
            return
        try:
            url = first_map_url(data)
        except (BadZipFile, ElementTree.ParseError, KeyError, ValueError):
            invalid_documents += 1
            return
        if url is not None:
            first_links[parts[1]] = (name, url)

    entries, digest = build_inventory(path, consume)
    return LocationPlan(entries, digest, first_links, invalid_documents)


def save_plan(plan: LocationPlan) -> tuple[int, int]:
    expected = Counter((item["ruta_original"], item["tipo"], item["sha256"]) for item in plan.entries)
    with session_factory()() as db:
        db.execute(text("LOCK TABLE ubicaciones, revisiones_ubicacion, procedencia_historica IN SHARE ROW EXCLUSIVE MODE"))
        sources = list(db.scalars(select(HistoricalSource)).all())
        if Counter((item.ruta_original, item.tipo, item.sha256) for item in sources) != expected:
            raise RuntimeError("La procedencia en la base no coincide con el archivo verificado")
        by_path = {item.ruta_original: item for item in sources}
        locations = {item.kardex: item for item in db.scalars(select(Location).with_for_update()).all()}
        candidates = []
        skipped = 0
        for kardex, (source_path, url) in plan.links.items():
            source = by_path.get(source_path)
            location = locations.get(kardex)
            if source is None or source.kardex != kardex or source.estado_revision != "CONFIRMADO" or location is None:
                raise RuntimeError("Falta una asociación o ubicación para un documento histórico")
            if (location.revision_actual_id is not None or location.latitud is not None
                    or location.longitud is not None or location.url_gps is not None):
                skipped += 1
                continue
            latitude, longitude = coordinates(url)
            candidates.append((location.id, source.id, url, latitude, longitude))
        created = 0
        for start in range(0, len(candidates), 250):
            batch = candidates[start:start + 250]
            source_ids = {location_id: source_id for location_id, source_id, _, _, _ in batch}
            rows = [
                {"ubicacion_id": location_id, "url_gps": url, "latitud": latitude, "longitud": longitude,
                 "responsable_id": None, "cerrada": True}
                for location_id, _, url, latitude, longitude in batch
            ]
            revisions = db.execute(
                insert(LocationRevision).values(rows).returning(LocationRevision.id, LocationRevision.ubicacion_id)
            ).all()
            updates = values(
                column("ubicacion_id", BigInteger), column("revision_id", BigInteger), name="nuevas_revisiones",
            ).data([(location_id, revision_id) for revision_id, location_id in revisions])
            table = Location.__table__
            db.execute(
                update(table).where(table.c.id == updates.c.ubicacion_id)
                .values(
                    revision_actual_id=updates.c.revision_id,
                    latitud=select(LocationRevision.latitud).where(LocationRevision.id == updates.c.revision_id).scalar_subquery(),
                    longitud=select(LocationRevision.longitud).where(LocationRevision.id == updates.c.revision_id).scalar_subquery(),
                    url_gps=select(LocationRevision.url_gps).where(LocationRevision.id == updates.c.revision_id).scalar_subquery(),
                )
            )
            db.execute(insert(AuditRecord), [
                {"ubicacion_id": location_id, "accion": "IMPORTAR_UBICACION_HISTORICA",
                 "detalles": {"revision_id": revision_id, "procedencia_id": source_ids[location_id], "origen": "cli"}}
                for revision_id, location_id in revisions
            ])
            created += len(revisions)
        if created:
            db.add(AuditRecord(
                accion="MIGRAR_UBICACIONES_HISTORICAS",
                detalles={"archivo_sha256": plan.archive_sha256, "ubicaciones_creadas": created,
                          "ubicaciones_omitidas": skipped, "documentos_invalidos": plan.invalid_documents, "origen": "cli"},
            ))
        db.commit()
        return created, skipped


def main() -> None:
    parser = argparse.ArgumentParser(description="Importar la primera ubicación GPS histórica")
    parser.add_argument("archivo", type=Path)
    parser.add_argument("--aplicar", action="store_true")
    parser.add_argument("--sha256-esperado")
    parser.add_argument("--archivos-esperados", type=int)
    parser.add_argument("--ubicaciones-esperadas", type=int)
    args = parser.parse_args()
    if args.aplicar and (args.sha256_esperado is None or args.archivos_esperados is None or args.ubicaciones_esperadas is None):
        parser.error("--aplicar requiere la huella y cantidades obtenidas en la simulación")
    plan = build_plan(args.archivo.resolve(strict=True))
    print(f"Simulación: {len(plan.links)} ubicaciones con enlace; {len(plan.entries)} archivos; {plan.invalid_documents} documentos inválidos; SHA-256: {plan.archive_sha256}")
    if not args.aplicar:
        print("No se guardaron registros.")
        return
    if (plan.archive_sha256, len(plan.entries), len(plan.links)) != (
        args.sha256_esperado, args.archivos_esperados, args.ubicaciones_esperadas,
    ):
        raise SystemExit("La fuente no coincide con la simulación; no se guardó nada.")
    created, skipped = save_plan(plan)
    print(f"Guardadas: {created} ubicaciones; ya existentes y conservadas: {skipped}.")


if __name__ == "__main__":
    main()
