"""Add configurable field-work permissions and approved initial assignments."""

from alembic import op

revision = "0005_panel_permissions"
down_revision = "0004_historical_photos"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        INSERT INTO permisos (nombre)
        VALUES ('ubicaciones.consultar'), ('ubicaciones.registrar'),
               ('usuarios.consultar'), ('usuarios.gestionar')
        ON CONFLICT (nombre) DO NOTHING
    """)
    op.execute("""
        INSERT INTO rol_permisos (rol_id, permiso_id)
        SELECT roles.id, permisos.id FROM roles CROSS JOIN permisos
        WHERE (roles.nombre IN ('GERENTE', 'JEFE COMERCIAL', 'TECNICO', 'CAJERO', 'CALL CENTER')
               AND permisos.nombre IN ('ubicaciones.consultar', 'ubicaciones.registrar'))
           OR (roles.nombre IN ('GERENTE', 'JEFE COMERCIAL')
               AND permisos.nombre IN ('usuarios.consultar', 'usuarios.gestionar'))
        ON CONFLICT DO NOTHING
    """)


def downgrade() -> None:
    raise RuntimeError("No se permite una reversión destructiva automática")
