"""Prepare user, role and session tables; not applied automatically."""

from alembic import op
import sqlalchemy as sa

revision = "0001_users_roles"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "roles",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("nombre", sa.String(80), nullable=False, unique=True),
    )
    op.create_table(
        "permisos",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("nombre", sa.String(80), nullable=False, unique=True),
    )
    op.create_table(
        "rol_permisos",
        sa.Column("rol_id", sa.BigInteger(), sa.ForeignKey("roles.id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("permiso_id", sa.BigInteger(), sa.ForeignKey("permisos.id", ondelete="RESTRICT"), primary_key=True),
    )
    op.create_table(
        "usuarios",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("nombre_usuario", sa.String(100), nullable=False, unique=True),
        sa.Column("contrasena_hash", sa.String(255), nullable=False),
        sa.Column("activo", sa.Boolean(), nullable=False),
        sa.Column("rol_id", sa.BigInteger(), sa.ForeignKey("roles.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("cambio_contrasena_obligatorio", sa.Boolean(), nullable=False),
        sa.Column("intentos_fallidos", sa.Integer(), nullable=False),
        sa.Column("bloqueado_hasta", sa.DateTime(timezone=True)),
        sa.Column("creado_en", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "sesiones",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("usuario_id", sa.BigInteger(), sa.ForeignKey("usuarios.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("ultima_actividad", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revocada", sa.Boolean(), nullable=False),
    )
    op.create_index("ix_sesiones_usuario_id", "sesiones", ["usuario_id"])
    op.create_table(
        "auditoria_usuarios",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("actor_id", sa.BigInteger(), sa.ForeignKey("usuarios.id", ondelete="RESTRICT")),
        sa.Column("objetivo_id", sa.BigInteger(), sa.ForeignKey("usuarios.id", ondelete="RESTRICT")),
        sa.Column("rol_id", sa.BigInteger(), sa.ForeignKey("roles.id", ondelete="RESTRICT")),
        sa.Column("accion", sa.String(80), nullable=False),
        sa.Column("detalles", sa.JSON()),
        sa.Column("ocurrido_en", sa.DateTime(timezone=True), nullable=False),
    )
    op.execute("""
        CREATE FUNCTION impedir_edicion_auditoria_usuarios() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'No se permite modificar o eliminar auditoría';
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER auditoria_usuarios_inmutable
        BEFORE UPDATE OR DELETE ON auditoria_usuarios
        FOR EACH ROW EXECUTE FUNCTION impedir_edicion_auditoria_usuarios()
    """)


def downgrade() -> None:
    raise RuntimeError("No se permite una reversión destructiva automática")
