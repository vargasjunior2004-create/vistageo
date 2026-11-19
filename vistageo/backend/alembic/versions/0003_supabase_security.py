"""Protect GEO VISTA tables from Supabase client roles.

Revision ID: 0003_supabase_security
Revises: 0002_locations
"""

from alembic import op

revision = "0003_supabase_security"
down_revision = "0002_locations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        DO $$
        DECLARE
            table_name text;
            role_name text;
            sequence_name text;
            function_name text;
            tables text[] := ARRAY[
                'alembic_version', 'roles', 'permisos', 'rol_permisos',
                'usuarios', 'sesiones', 'auditoria_usuarios', 'contratos',
                'procedencia_historica', 'ubicaciones', 'actividades',
                'auditoria', 'fotografias', 'operaciones_fotografia',
                'revisiones_ubicacion'
            ];
            identity_tables text[] := ARRAY[
                'roles', 'permisos', 'usuarios', 'sesiones',
                'auditoria_usuarios', 'procedencia_historica', 'ubicaciones',
                'actividades', 'auditoria', 'fotografias',
                'operaciones_fotografia', 'revisiones_ubicacion'
            ];
            functions text[] := ARRAY[
                'impedir_edicion_auditoria_usuarios',
                'proteger_revision_cerrada', 'verificar_revision_actual',
                'preparar_fotografia', 'auditar_fotografia',
                'proteger_operacion_fotografia', 'impedir_edicion_auditoria'
            ];
        BEGIN
            FOREACH table_name IN ARRAY tables LOOP
                EXECUTE 'ALTER TABLE public.' || quote_ident(table_name) || ' ENABLE ROW LEVEL SECURITY';
                EXECUTE 'REVOKE ALL PRIVILEGES ON TABLE public.' || quote_ident(table_name) || ' FROM PUBLIC';
                FOR role_name IN
                    SELECT rolname FROM pg_roles WHERE rolname IN ('anon', 'authenticated', 'service_role')
                LOOP
                    EXECUTE 'REVOKE ALL PRIVILEGES ON TABLE public.' || quote_ident(table_name) || ' FROM ' || quote_ident(role_name);
                END LOOP;
            END LOOP;
            FOREACH table_name IN ARRAY identity_tables LOOP
                sequence_name := pg_get_serial_sequence('public.' || quote_ident(table_name), 'id');
                IF sequence_name IS NULL THEN
                    RAISE EXCEPTION 'No se encontró una secuencia de identidad';
                END IF;
                EXECUTE 'REVOKE ALL PRIVILEGES ON SEQUENCE ' || sequence_name || ' FROM PUBLIC';
                FOR role_name IN
                    SELECT rolname FROM pg_roles WHERE rolname IN ('anon', 'authenticated', 'service_role')
                LOOP
                    EXECUTE 'REVOKE ALL PRIVILEGES ON SEQUENCE ' || sequence_name || ' FROM ' || quote_ident(role_name);
                END LOOP;
            END LOOP;
            FOREACH function_name IN ARRAY functions LOOP
                EXECUTE 'REVOKE ALL PRIVILEGES ON FUNCTION public.' || quote_ident(function_name) || '() FROM PUBLIC';
                FOR role_name IN
                    SELECT rolname FROM pg_roles WHERE rolname IN ('anon', 'authenticated', 'service_role')
                LOOP
                    EXECUTE 'REVOKE ALL PRIVILEGES ON FUNCTION public.' || quote_ident(function_name) || '() FROM ' || quote_ident(role_name);
                END LOOP;
            END LOOP;
        END;
        $$
    """)


def downgrade() -> None:
    raise RuntimeError("No se permite una reversión destructiva automática")
