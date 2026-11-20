"""Add the update-reason catalog without altering existing locations."""

import sqlalchemy as sa
from alembic import op

revision = "0008_update_reasons"
down_revision = "0007_location_creation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "motivos_actualizacion",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("nombre", sa.String(160), nullable=False),
        sa.Column("activo", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.CheckConstraint("length(trim(nombre)) > 0", name="motivos_actualizacion_nombre_no_vacio"),
    )
    op.execute("ALTER TABLE public.motivos_actualizacion ENABLE ROW LEVEL SECURITY")
    op.execute("REVOKE ALL PRIVILEGES ON TABLE public.motivos_actualizacion FROM PUBLIC")
    op.execute("""
        DO $$
        DECLARE
            role_name text;
            sequence_name text;
        BEGIN
            sequence_name := pg_get_serial_sequence('public.motivos_actualizacion', 'id');
            IF sequence_name IS NULL THEN
                RAISE EXCEPTION 'No se encontró la secuencia de motivos';
            END IF;
            EXECUTE 'REVOKE ALL PRIVILEGES ON SEQUENCE ' || sequence_name || ' FROM PUBLIC';
            FOR role_name IN
                SELECT rolname FROM pg_roles WHERE rolname IN ('anon', 'authenticated', 'service_role')
            LOOP
                EXECUTE 'REVOKE ALL PRIVILEGES ON TABLE public.motivos_actualizacion FROM ' || quote_ident(role_name);
                EXECUTE 'REVOKE ALL PRIVILEGES ON SEQUENCE ' || sequence_name || ' FROM ' || quote_ident(role_name);
            END LOOP;
        END;
        $$
    """)


def downgrade() -> None:
    raise RuntimeError("No se permite una reversión destructiva automática")
