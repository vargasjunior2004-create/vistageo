"""Preserve original creator and creation time for locations."""

import sqlalchemy as sa
from alembic import op

revision = "0007_location_creation"
down_revision = "0006_photo_edit_permission"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ubicaciones", sa.Column("creado_en", sa.DateTime(timezone=True), nullable=True))
    op.add_column("ubicaciones", sa.Column("creado_por", sa.BigInteger(), nullable=True))
    op.create_foreign_key("ubicaciones_creador_fk", "ubicaciones", "usuarios", ["creado_por"], ["id"], ondelete="RESTRICT")
    op.execute("""
        WITH confirmed AS (
            SELECT ubicacion_id, MIN(usuario_id) AS usuario_id, MIN(ocurrido_en) AS ocurrido_en
            FROM auditoria
            WHERE accion IN ('PREPARAR_REGISTRO_UBICACION', 'CREAR_UBICACION')
              AND ubicacion_id IS NOT NULL
            GROUP BY ubicacion_id
            HAVING COUNT(*) = 1 AND COUNT(usuario_id) = 1
        )
        UPDATE ubicaciones AS location
        SET creado_por = confirmed.usuario_id, creado_en = confirmed.ocurrido_en
        FROM confirmed
        WHERE location.id = confirmed.ubicacion_id
    """)
    op.execute("""
        CREATE FUNCTION proteger_creacion_ubicacion() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF (NEW.creado_en, NEW.creado_por) IS DISTINCT FROM (OLD.creado_en, OLD.creado_por) THEN
                RAISE EXCEPTION 'No se permite modificar la creación de la ubicación';
            END IF;
            RETURN NEW;
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER ubicaciones_proteger_creacion
        BEFORE UPDATE OF creado_en, creado_por ON ubicaciones
        FOR EACH ROW EXECUTE FUNCTION proteger_creacion_ubicacion()
    """)
    op.execute("""
        REVOKE ALL PRIVILEGES ON FUNCTION public.proteger_creacion_ubicacion() FROM PUBLIC
    """)
    op.execute("""
        DO $$
        DECLARE role_name text;
        BEGIN
            FOR role_name IN
                SELECT rolname FROM pg_roles WHERE rolname IN ('anon', 'authenticated', 'service_role')
            LOOP
                EXECUTE 'REVOKE ALL PRIVILEGES ON FUNCTION public.proteger_creacion_ubicacion() FROM ' || quote_ident(role_name);
            END LOOP;
        END;
        $$
    """)


def downgrade() -> None:
    raise RuntimeError("No se permite una reversión destructiva automática")
