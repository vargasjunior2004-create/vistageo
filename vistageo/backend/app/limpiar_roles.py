"""Revisar y aplicar la limpieza controlada del catálogo de roles."""

import argparse
import json

from sqlalchemy import column, delete, func, inspect, select, table, text
from sqlalchemy.orm import Session

from app.database import session_factory
from app.models import AuditEvent, Role, User, role_permissions
from app.security import ADMIN, OFFICIAL_ROLES

RETIRED_ROLES = {"CAJERO", "CALL CENTER", "JEFE COMERCIAL"}
OLD_MANAGER = "GERENTE"


def references(db: Session, target: str, ids: list[int], ignored: set[str]) -> list[dict]:
    if not ids:
        return []
    connection = db.connection()
    inspector = inspect(connection)
    if connection.dialect.name == "postgresql":
        foreign_keys = db.execute(text("""
            SELECT ns.nspname AS schema_name, source.relname AS table_name,
                   local_column.attname AS column_name
            FROM pg_constraint AS constraint_row
            JOIN pg_class AS source ON source.oid = constraint_row.conrelid
            JOIN pg_namespace AS ns ON ns.oid = source.relnamespace
            CROSS JOIN LATERAL unnest(constraint_row.conkey, constraint_row.confkey)
                AS keys(local_id, remote_id)
            JOIN pg_attribute AS local_column
                ON local_column.attrelid = source.oid AND local_column.attnum = keys.local_id
            JOIN pg_attribute AS remote_column
                ON remote_column.attrelid = constraint_row.confrelid AND remote_column.attnum = keys.remote_id
            WHERE constraint_row.contype = 'f' AND constraint_row.confrelid = to_regclass(:target)
              AND remote_column.attname = 'id'
        """), {"target": target}).all()
    else:
        foreign_keys = []
        for name in inspector.get_table_names():
            for fk in inspector.get_foreign_keys(name):
                if fk["referred_table"] != target:
                    continue
                foreign_keys.extend((None, name, local) for local, remote in
                                    zip(fk["constrained_columns"], fk["referred_columns"], strict=True)
                                    if remote == "id")
    result = []
    for schema, name, local in foreign_keys:
        if name in ignored and (schema is None or schema == inspector.default_schema_name):
            continue
        source = table(name, column(local), schema=schema)
        field = source.c[local]
        rows = db.execute(select(field, func.count()).where(field.in_(ids)).group_by(field)).all()
        result.extend({
            "tabla": f"{schema}.{name}" if schema else name,
            "columna": local, "id": value, "cantidad": count,
        } for value, count in rows)
    return result


def review(db: Session) -> dict:
    roles = list(db.scalars(select(Role).order_by(Role.id)).all())
    names = {role.name for role in roles}
    retired = [role for role in roles if role.name in RETIRED_ROLES]
    users = list(db.scalars(select(User).where(User.role_id.in_([r.id for r in retired])).order_by(User.id)).all())
    active_admin = db.scalar(
        select(func.count(User.id)).join(Role).where(Role.name == ADMIN, User.active.is_(True))
    )
    problems = []
    unknown = names - OFFICIAL_ROLES - RETIRED_ROLES - {OLD_MANAGER}
    if unknown:
        problems.append(f"Roles no previstos: {', '.join(sorted(unknown))}")
    if OLD_MANAGER in names and "GERENCIA" in names:
        problems.append("Existen GERENTE y GERENCIA; debe revisarse su consolidación manualmente")
    if not active_admin:
        problems.append("No se encontró un administrador activo")
    user_refs = references(db, "usuarios", [user.id for user in users], set())
    role_refs = references(db, "roles", [role.id for role in retired], {"usuarios", "rol_permisos"})
    if user_refs:
        problems.append("Hay usuarios de prueba referenciados; no se eliminará ningún dato")
    if role_refs:
        problems.append("Hay roles retirados referenciados; no se eliminará ningún dato")
    return {
        "roles_existentes": sorted(names),
        "roles_a_crear": sorted(OFFICIAL_ROLES - names - ({"GERENCIA"} if OLD_MANAGER in names else set())),
        "renombrar": {OLD_MANAGER: "GERENCIA"} if OLD_MANAGER in names else {},
        "roles_a_eliminar": [{"id": role.id, "nombre": role.name} for role in retired],
        "usuarios_candidatos": [{"id": user.id, "nombre": user.username, "rol": user.role.name} for user in users],
        "referencias_usuarios": user_refs,
        "referencias_roles": role_refs,
        "problemas": problems,
    }


def apply(db: Session, report: dict, approved_ids: set[int]) -> None:
    if report["problemas"]:
        raise ValueError("La revisión contiene problemas; no se realizaron cambios")
    candidate_ids = {user["id"] for user in report["usuarios_candidatos"]}
    if candidate_ids != approved_ids:
        raise ValueError("Los IDs aprobados deben coincidir exactamente con los candidatos revisados")
    retired_ids = [role["id"] for role in report["roles_a_eliminar"]]
    if candidate_ids:
        db.execute(delete(User).where(User.id.in_(candidate_ids)))
    if retired_ids:
        db.execute(delete(role_permissions).where(role_permissions.c.rol_id.in_(retired_ids)))
        db.execute(delete(Role).where(Role.id.in_(retired_ids)))
    if report["renombrar"]:
        manager = db.scalar(select(Role).where(Role.name == OLD_MANAGER))
        if manager is None:
            raise ValueError("El rol GERENTE cambió durante la revisión")
        manager.name = "GERENCIA"
    for name in report["roles_a_crear"]:
        db.add(Role(name=name))
    db.add(AuditEvent(action="LIMPIEZA_ROLES", details={
        "usuarios_eliminados": report["usuarios_candidatos"],
        "roles_eliminados": report["roles_a_eliminar"],
        "roles_creados": report["roles_a_crear"],
        "renombrar": report["renombrar"],
    }))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--aplicar", action="store_true", help="Aplicar después de revisar el informe")
    parser.add_argument("--usuario-id", type=int, action="append", default=[], help="ID de usuario de prueba aprobado; repetir por cada usuario")
    args = parser.parse_args()
    if not args.aplicar and args.usuario_id:
        parser.error("--usuario-id solo se usa con --aplicar")
    with session_factory()() as db:
        if args.aplicar and db.get_bind().dialect.name == "postgresql":
            db.execute(text("LOCK TABLE roles, usuarios, rol_permisos IN SHARE ROW EXCLUSIVE MODE"))
        report = review(db)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        if args.aplicar:
            try:
                apply(db, report, set(args.usuario_id))
                db.commit()
            except ValueError as exc:
                db.rollback()
                raise SystemExit(str(exc)) from exc
            print("Limpieza aplicada.")
        elif report["problemas"]:
            raise SystemExit("Revisión bloqueada; no se realizaron cambios.")


if __name__ == "__main__":
    main()
