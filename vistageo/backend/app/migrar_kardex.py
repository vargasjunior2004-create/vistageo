"""Crea contratos y ubicaciones vacías a partir de las carpetas del RAR."""

import argparse
from collections import Counter
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from sqlalchemy import bindparam, select, text, update
from sqlalchemy.dialects.postgresql import insert

from app.database import session_factory
from app.inventario_historico import archive_records, build_inventory
from app.models import AuditRecord, Contract, HistoricalSource, Location


@dataclass(frozen=True)
class MigrationPlan:
    root: str
    kardexes: list[str]
    entries: list[dict]
    archive_sha256: str


def build_plan(path: Path) -> MigrationPlan:
    entries, digest = build_inventory(path)
    roots: set[str] = set()
    kardexes: list[str] = []
    for record in archive_records(path):
        if record.get("Folder") != "+":
            continue
        parts = PurePosixPath(record["Path"]).parts
        if len(parts) == 2:
            roots.add(parts[0])
            kardexes.append(parts[1])
    if len(roots) != 1 or not kardexes or len(set(kardexes)) != len(kardexes):
        raise ValueError("Las carpetas principales no forman una lista única de kardex")
    if any(not kardex.strip() or "\x00" in kardex for kardex in kardexes):
        raise ValueError("Existe un nombre de carpeta que no puede ser kardex")
    return MigrationPlan(roots.pop(), kardexes, entries, digest)


def save_plan(plan: MigrationPlan) -> tuple[int, int, int]:
    expected = Counter((item["ruta_original"], item["tipo"], item["sha256"]) for item in plan.entries)
    with session_factory()() as db:
        db.execute(text("LOCK TABLE contratos, ubicaciones, procedencia_historica IN SHARE ROW EXCLUSIVE MODE"))
        sources = list(db.scalars(select(HistoricalSource).with_for_update()).all())
        actual = Counter((item.ruta_original, item.tipo, item.sha256) for item in sources)
        if actual != expected:
            raise RuntimeError("La procedencia en la base no coincide con el archivo verificado")
        allowed = set(plan.kardexes)
        links = []
        for item in sources:
            parts = PurePosixPath(item.ruta_original).parts
            if len(parts) < 3 or parts[0] != plan.root or parts[1] not in allowed:
                continue
            kardex = parts[1]
            if item.kardex not in (None, kardex) or item.estado_revision not in ("PENDIENTE", "CONFIRMADO"):
                raise RuntimeError("Una procedencia ya contiene una asociación o estado incompatible")
            if item.kardex != kardex or item.estado_revision != "CONFIRMADO":
                links.append({"source_id": item.id, "target_kardex": kardex})
        created_contracts = created_locations = 0
        for start in range(0, len(plan.kardexes), 500):
            batch = plan.kardexes[start:start + 500]
            contracts = insert(Contract).values([{"kardex": kardex} for kardex in batch])
            created_contracts += len(db.scalars(
                contracts.on_conflict_do_nothing(index_elements=["kardex"]).returning(Contract.kardex)
            ).all())
            locations = insert(Location).values([{"kardex": kardex} for kardex in batch])
            created_locations += len(db.scalars(
                locations.on_conflict_do_nothing(index_elements=["kardex"]).returning(Location.id)
            ).all())
        if links:
            table = HistoricalSource.__table__
            statement = (
                update(table).where(table.c.id == bindparam("source_id"))
                .values(kardex=bindparam("target_kardex"), estado_revision="CONFIRMADO")
            )
            db.execute(statement, links)
        if created_contracts or created_locations or links:
            db.add(AuditRecord(
                accion="MIGRAR_KARDEX_HISTORICOS",
                detalles={
                    "archivo_sha256": plan.archive_sha256,
                    "contratos_creados": created_contracts,
                    "ubicaciones_creadas": created_locations,
                    "procedencias_asociadas": len(links),
                    "origen": "cli",
                },
            ))
        db.commit()
        return created_contracts, created_locations, len(links)


def main() -> None:
    parser = argparse.ArgumentParser(description="Preparar contratos a partir de carpetas históricas")
    parser.add_argument("archivo", type=Path)
    parser.add_argument("--aplicar", action="store_true")
    parser.add_argument("--sha256-esperado")
    parser.add_argument("--kardex-esperados", type=int)
    parser.add_argument("--archivos-esperados", type=int)
    args = parser.parse_args()
    if args.aplicar and (args.sha256_esperado is None or args.kardex_esperados is None or args.archivos_esperados is None):
        parser.error("--aplicar requiere la huella y cantidades obtenidas en la simulación")
    plan = build_plan(args.archivo.resolve(strict=True))
    print(f"Simulación: {len(plan.kardexes)} kardex; {len(plan.entries)} archivos; SHA-256: {plan.archive_sha256}")
    if not args.aplicar:
        print("No se guardaron registros.")
        return
    if (plan.archive_sha256, len(plan.kardexes), len(plan.entries)) != (
        args.sha256_esperado, args.kardex_esperados, args.archivos_esperados,
    ):
        raise SystemExit("La fuente no coincide con la simulación; no se guardó nada.")
    contracts, locations, links = save_plan(plan)
    print(f"Guardados: {contracts} contratos nuevos, {locations} ubicaciones vacías y {links} asociaciones.")


if __name__ == "__main__":
    main()
