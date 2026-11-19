"""Allow traceable historical photo imports without inventing an actor."""

import sqlalchemy as sa
from alembic import op

revision = "0004_historical_photos"
down_revision = "0003_supabase_security"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("fotografias", "operaciones_fotografia"):
        op.add_column(table, sa.Column("procedencia_id", sa.BigInteger(), nullable=True))
        op.create_foreign_key(
            f"{table}_procedencia_fk", table, "procedencia_historica",
            ["procedencia_id"], ["id"], ondelete="RESTRICT",
        )
    op.add_column("fotografias", sa.Column("sha256_original", sa.Text(), nullable=True))
    op.create_check_constraint(
        "fotografias_sha256_original_valido", "fotografias",
        "sha256_original IS NULL OR sha256_original ~ '^[0-9a-f]{64}$'",
    )
    op.alter_column("fotografias", "registrado_por", nullable=True)
    op.alter_column("operaciones_fotografia", "usuario_id", nullable=True)
    op.create_check_constraint(
        "fotografias_actor_o_procedencia", "fotografias",
        "registrado_por IS NOT NULL OR procedencia_id IS NOT NULL",
    )
    op.create_check_constraint(
        "operaciones_foto_actor_o_procedencia", "operaciones_fotografia",
        "usuario_id IS NOT NULL OR (tipo = 'CREAR' AND procedencia_id IS NOT NULL)",
    )
    op.execute("""
        CREATE OR REPLACE FUNCTION preparar_fotografia() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE actor bigint;
        BEGIN
            actor := NULLIF(current_setting('app.usuario_id', true), '')::bigint;
            IF TG_OP = 'INSERT' AND actor IS NULL AND NEW.procedencia_id IS NOT NULL THEN
                IF NOT EXISTS (
                    SELECT 1 FROM procedencia_historica p
                    JOIN ubicaciones u ON u.kardex = p.kardex
                    WHERE p.id = NEW.procedencia_id AND u.id = NEW.ubicacion_id
                      AND p.estado_revision = 'CONFIRMADO' AND p.tipo = 'imagen'
                      AND p.sha256 IS NOT NULL AND p.sha256 = NEW.sha256_original
                      AND NEW.sha256 IS NOT NULL
                ) THEN
                    RAISE EXCEPTION 'Procedencia histórica incompatible con la fotografía';
                END IF;
                NEW.registrado_por := NULL;
                NEW.registrado_en := clock_timestamp();
                NEW.actualizado_por := NULL;
                NEW.actualizado_en := NULL;
                RETURN NEW;
            END IF;
            IF actor IS NULL THEN
                RAISE EXCEPTION 'Falta el usuario autenticado para modificar la fotografía';
            END IF;
            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            ELSIF TG_OP = 'INSERT' THEN
                IF NEW.procedencia_id IS NOT NULL OR NEW.sha256_original IS NOT NULL THEN
                    RAISE EXCEPTION 'La procedencia histórica solo se usa en importaciones';
                END IF;
                NEW.registrado_por := actor;
                NEW.registrado_en := clock_timestamp();
                NEW.actualizado_por := NULL;
                NEW.actualizado_en := NULL;
            ELSE
                IF (NEW.id, NEW.ubicacion_id, NEW.registrado_por, NEW.registrado_en, NEW.procedencia_id, NEW.sha256_original)
                   IS DISTINCT FROM
                   (OLD.id, OLD.ubicacion_id, OLD.registrado_por, OLD.registrado_en, OLD.procedencia_id, OLD.sha256_original) THEN
                    RAISE EXCEPTION 'No se permite cambiar la identidad ni el registro original';
                END IF;
                NEW.actualizado_por := actor;
                NEW.actualizado_en := clock_timestamp();
            END IF;
            RETURN NEW;
        END;
        $$
    """)
    op.execute("""
        CREATE OR REPLACE FUNCTION auditar_fotografia() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
            actor bigint := NULLIF(current_setting('app.usuario_id', true), '')::bigint;
            accion_evento text;
            foto_id bigint;
            ubicacion_evento bigint;
            fuente_id bigint;
        BEGIN
            IF TG_OP = 'INSERT' THEN
                accion_evento := CASE WHEN actor IS NULL THEN 'IMPORTAR_FOTOGRAFIA_HISTORICA'
                                      ELSE 'CREAR_FOTOGRAFIA' END;
                foto_id := NEW.id;
                ubicacion_evento := NEW.ubicacion_id;
                fuente_id := NEW.procedencia_id;
            ELSIF TG_OP = 'DELETE' THEN
                accion_evento := 'ELIMINAR_FOTOGRAFIA';
                foto_id := OLD.id;
                ubicacion_evento := OLD.ubicacion_id;
                fuente_id := OLD.procedencia_id;
            ELSE
                IF (NEW.storage_bucket, NEW.storage_clave) IS DISTINCT FROM
                   (OLD.storage_bucket, OLD.storage_clave) THEN
                    accion_evento := 'REEMPLAZAR_FOTOGRAFIA';
                ELSE
                    accion_evento := 'ACTUALIZAR_FOTOGRAFIA';
                END IF;
                foto_id := NEW.id;
                ubicacion_evento := NEW.ubicacion_id;
                fuente_id := NEW.procedencia_id;
            END IF;
            INSERT INTO auditoria (usuario_id, ubicacion_id, accion, ocurrido_en, detalles)
            VALUES (actor, ubicacion_evento, accion_evento, clock_timestamp(),
                    jsonb_build_object('fotografia_id', foto_id, 'procedencia_id', fuente_id,
                        'sha256_original', CASE WHEN TG_OP = 'DELETE' THEN OLD.sha256_original ELSE NEW.sha256_original END,
                        'sha256_almacenado', CASE WHEN TG_OP = 'DELETE' THEN OLD.sha256 ELSE NEW.sha256 END));
            RETURN NULL;
        END;
        $$
    """)
    op.execute("""
        CREATE OR REPLACE FUNCTION proteger_operacion_fotografia() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'No se permite eliminar operaciones de fotografía';
            END IF;
            IF (NEW.id, NEW.idempotencia, NEW.ubicacion_id, NEW.usuario_id, NEW.tipo,
                NEW.nuevo_bucket, NEW.nueva_clave, NEW.anterior_bucket, NEW.anterior_clave, NEW.creado_en,
                NEW.procedencia_id)
               IS DISTINCT FROM
               (OLD.id, OLD.idempotencia, OLD.ubicacion_id, OLD.usuario_id, OLD.tipo,
                OLD.nuevo_bucket, OLD.nueva_clave, OLD.anterior_bucket, OLD.anterior_clave, OLD.creado_en,
                OLD.procedencia_id) THEN
                RAISE EXCEPTION 'No se permite cambiar la identidad de una operación';
            END IF;
            IF OLD.fotografia_id IS NOT NULL AND NEW.fotografia_id IS DISTINCT FROM OLD.fotografia_id THEN
                RAISE EXCEPTION 'No se permite cambiar la fotografía de una operación';
            END IF;
            NEW.actualizado_en := clock_timestamp();
            RETURN NEW;
        END;
        $$
    """)


def downgrade() -> None:
    raise RuntimeError("No se permite una reversión destructiva automática")
