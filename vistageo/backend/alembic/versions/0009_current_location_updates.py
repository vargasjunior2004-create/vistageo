"""Store current GPS separately from immutable historical revisions."""

import sqlalchemy as sa
from alembic import op

revision = "0009_current_location_updates"
down_revision = "0008_update_reasons"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ubicaciones", sa.Column("latitud", sa.Numeric(), nullable=True))
    op.add_column("ubicaciones", sa.Column("longitud", sa.Numeric(), nullable=True))
    op.add_column("ubicaciones", sa.Column("url_gps", sa.Text(), nullable=True))
    op.add_column("ubicaciones", sa.Column("version", sa.Integer(), server_default="0", nullable=False))
    op.create_check_constraint(
        "ubicaciones_coordenadas_validas", "ubicaciones",
        "(latitud IS NULL AND longitud IS NULL) OR "
        "(latitud IS NOT NULL AND longitud IS NOT NULL AND latitud BETWEEN -90 AND 90 AND longitud BETWEEN -180 AND 180)",
    )
    op.execute("""
        UPDATE ubicaciones AS location
        SET latitud = revision.latitud, longitud = revision.longitud, url_gps = revision.url_gps
        FROM revisiones_ubicacion AS revision
        WHERE revision.id = location.revision_actual_id AND revision.ubicacion_id = location.id
    """)
    op.add_column("operaciones_fotografia", sa.Column("solicitud_sha256", sa.String(64), nullable=True))
    op.execute("""
        CREATE FUNCTION proteger_solicitud_fotografia() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF OLD.solicitud_sha256 IS NOT NULL AND NEW.solicitud_sha256 IS DISTINCT FROM OLD.solicitud_sha256 THEN
                RAISE EXCEPTION 'No se permite cambiar la solicitud de la operación';
            END IF;
            IF OLD.solicitud_sha256 IS NULL AND NEW.solicitud_sha256 IS NOT NULL
               AND OLD.estado NOT IN ('preparada', 'objeto_listo') THEN
                RAISE EXCEPTION 'No se puede asociar una solicitud a una operación terminada';
            END IF;
            RETURN NEW;
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER solicitud_fotografia_protegida BEFORE UPDATE OF solicitud_sha256 ON operaciones_fotografia
        FOR EACH ROW EXECUTE FUNCTION proteger_solicitud_fotografia()
    """)
    op.execute("REVOKE ALL PRIVILEGES ON FUNCTION public.proteger_solicitud_fotografia() FROM PUBLIC")
    op.execute("""
        DO $$
        DECLARE role_name text;
        BEGIN
            FOR role_name IN
                SELECT rolname FROM pg_roles WHERE rolname IN ('anon', 'authenticated', 'service_role')
            LOOP
                EXECUTE 'REVOKE ALL PRIVILEGES ON FUNCTION public.proteger_solicitud_fotografia() FROM ' || quote_ident(role_name);
            END LOOP;
        END;
        $$
    """)
    op.add_column("auditoria", sa.Column("motivo_id", sa.BigInteger(), nullable=True))
    op.add_column("auditoria", sa.Column("operacion_id", sa.Uuid(), nullable=True))
    op.create_foreign_key("auditoria_motivo_fk", "auditoria", "motivos_actualizacion", ["motivo_id"], ["id"], ondelete="RESTRICT")
    op.create_unique_constraint("auditoria_operacion_unica", "auditoria", ["operacion_id"])
    op.execute("INSERT INTO permisos (nombre) VALUES ('ubicaciones.gps.editar') ON CONFLICT (nombre) DO NOTHING")


def downgrade() -> None:
    raise RuntimeError("No se permite una reversión destructiva automática")
