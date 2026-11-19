"""Add configurable permission for replacing official photographs."""

from alembic import op

revision = "0006_photo_edit_permission"
down_revision = "0005_panel_permissions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        INSERT INTO permisos (nombre) VALUES ('ubicaciones.fotografia.editar')
        ON CONFLICT (nombre) DO NOTHING
    """)
    op.execute("""
        INSERT INTO rol_permisos (rol_id, permiso_id)
        SELECT roles.id, permisos.id FROM roles CROSS JOIN permisos
        WHERE roles.nombre IN ('TECNICO', 'GERENTE', 'JEFE COMERCIAL', 'JEFE OPERATIVO',
                               'JEFE TECNICO', 'CAJERO', 'CALL CENTER')
          AND permisos.nombre IN ('ubicaciones.consultar', 'ubicaciones.fotografia.editar')
        ON CONFLICT DO NOTHING
    """)


def downgrade() -> None:
    raise RuntimeError("No se permite una reversión destructiva automática")
