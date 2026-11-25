"""Add session metadata for JWT access and rotating refresh tokens."""

import sqlalchemy as sa
from alembic import op

revision = "0012_session_tokens"
down_revision = "0011_gps_quality"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sesiones", sa.Column("creado_en", sa.DateTime(timezone=True), nullable=True))
    op.add_column("sesiones", sa.Column("expira_en", sa.DateTime(timezone=True), nullable=True))
    op.add_column("sesiones", sa.Column("refresh_hash", sa.String(length=64), nullable=True))
    op.add_column("sesiones", sa.Column("refresh_expira_en", sa.DateTime(timezone=True), nullable=True))
    op.add_column("sesiones", sa.Column("refresh_anterior_hash", sa.String(length=64), nullable=True))
    op.add_column("sesiones", sa.Column("refresh_generacion", sa.Integer(), nullable=False, server_default=sa.text("0")))
    op.add_column("sesiones", sa.Column("revocada_en", sa.DateTime(timezone=True), nullable=True))
    op.add_column("sesiones", sa.Column("revocada_motivo", sa.String(length=80), nullable=True))
    op.create_unique_constraint("uq_sesiones_refresh_hash", "sesiones", ["refresh_hash"])
    op.create_index("ix_sesiones_refresh_anterior_hash", "sesiones", ["refresh_anterior_hash"], unique=False)

    op.execute(
        sa.text(
            """
            UPDATE sesiones
            SET creado_en = COALESCE(creado_en, ultima_actividad, CURRENT_TIMESTAMP),
                expira_en = COALESCE(expira_en, COALESCE(ultima_actividad, CURRENT_TIMESTAMP) + INTERVAL '7 days'),
                refresh_generacion = COALESCE(refresh_generacion, 0)
            """
        )
    )


def downgrade() -> None:
    raise RuntimeError("No se permite una reversión destructiva automática")
