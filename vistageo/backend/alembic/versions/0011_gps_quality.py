"""Preserve GPS measurement metadata without changing historical records."""

import sqlalchemy as sa
from alembic import op

revision = "0011_gps_quality"
down_revision = "0010_coordinate_methods"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ubicaciones", sa.Column("precision_metros", sa.Float(), nullable=True))
    op.add_column("ubicaciones", sa.Column("capturado_en", sa.DateTime(timezone=True), nullable=True))
    op.add_column("ubicaciones", sa.Column("capturado_por", sa.BigInteger(), nullable=True))
    op.create_foreign_key("ubicaciones_capturado_por_fk", "ubicaciones", "usuarios", ["capturado_por"], ["id"], ondelete="RESTRICT")
    op.add_column("revisiones_ubicacion", sa.Column("precision_metros", sa.Float(), nullable=True))


def downgrade() -> None:
    raise RuntimeError("No se permite una reversión destructiva automática")
