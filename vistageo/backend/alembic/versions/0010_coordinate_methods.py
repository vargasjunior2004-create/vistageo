"""Store coordinate method without inferring historical provenance."""

import sqlalchemy as sa
from alembic import op

revision = "0010_coordinate_methods"
down_revision = "0009_current_location_updates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table, prefix in (
        ("ubicaciones", "ubicaciones"),
        ("revisiones_ubicacion", "revisiones"),
    ):
        op.add_column(table, sa.Column("metodo_coordenadas", sa.String(32), nullable=True))
        op.create_check_constraint(
            f"{prefix}_metodo_valido", table,
            "metodo_coordenadas IS NULL OR metodo_coordenadas IN ('GPS_DISPOSITIVO', 'ENLACE_COMPARTIDO')",
        )
        op.create_check_constraint(
            f"{prefix}_metodo_contenido", table,
            "metodo_coordenadas IS NULL OR (latitud IS NOT NULL AND longitud IS NOT NULL AND "
            "((metodo_coordenadas = 'GPS_DISPOSITIVO' AND url_gps IS NULL) OR "
            "(metodo_coordenadas = 'ENLACE_COMPARTIDO' AND url_gps IS NOT NULL AND length(trim(url_gps)) > 0)))",
        )


def downgrade() -> None:
    raise RuntimeError("No se permite una reversión destructiva automática")
