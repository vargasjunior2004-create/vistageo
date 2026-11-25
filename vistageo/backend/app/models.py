from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    JSON, BigInteger, Boolean, CheckConstraint, Column, DateTime, Float, ForeignKey,
    ForeignKeyConstraint, Identity, Index, Integer, Numeric, String, Table, Text,
    UniqueConstraint, Uuid, text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


pk_type = BigInteger().with_variant(Integer, "sqlite")

role_permissions = Table(
    "rol_permisos",
    Base.metadata,
    Column("rol_id", pk_type, ForeignKey("roles.id", ondelete="RESTRICT"), primary_key=True),
    Column("permiso_id", pk_type, ForeignKey("permisos.id", ondelete="RESTRICT"), primary_key=True),
)
Index("rol_permisos_por_permiso", role_permissions.c.permiso_id)


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(pk_type, primary_key=True)
    name: Mapped[str] = mapped_column("nombre", String(80), unique=True, nullable=False)
    permissions: Mapped[list["Permission"]] = relationship(
        secondary=role_permissions, lazy="selectin"
    )


class Permission(Base):
    __tablename__ = "permisos"

    id: Mapped[int] = mapped_column(pk_type, primary_key=True)
    name: Mapped[str] = mapped_column("nombre", String(80), unique=True, nullable=False)


class User(Base):
    __tablename__ = "usuarios"

    id: Mapped[int] = mapped_column(pk_type, primary_key=True)
    username: Mapped[str] = mapped_column("nombre_usuario", String(100), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column("contrasena_hash", String(255), nullable=False)
    active: Mapped[bool] = mapped_column("activo", Boolean, default=True, nullable=False)
    role_id: Mapped[int] = mapped_column("rol_id", ForeignKey("roles.id", ondelete="RESTRICT"), nullable=False)
    role: Mapped[Role] = relationship(lazy="joined")
    must_change_password: Mapped[bool] = mapped_column("cambio_contrasena_obligatorio", Boolean, default=True, nullable=False)
    failed_attempts: Mapped[int] = mapped_column("intentos_fallidos", Integer, default=0, nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column("bloqueado_hasta", DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column("creado_en", DateTime(timezone=True), default=now_utc, nullable=False)


class AuthSession(Base):
    __tablename__ = "sesiones"

    id: Mapped[int] = mapped_column(pk_type, primary_key=True)
    token_hash: Mapped[str] = mapped_column("token_hash", String(64), unique=True, nullable=False)
    user_id: Mapped[int] = mapped_column("usuario_id", ForeignKey("usuarios.id", ondelete="RESTRICT"), index=True, nullable=False)
    user: Mapped[User] = relationship(lazy="joined")
    last_activity: Mapped[datetime] = mapped_column("ultima_actividad", DateTime(timezone=True), default=now_utc, nullable=False)
    revoked: Mapped[bool] = mapped_column("revocada", Boolean, default=False, nullable=False)
    created_at: Mapped[datetime | None] = mapped_column("creado_en", DateTime(timezone=True), default=now_utc)
    expires_at: Mapped[datetime | None] = mapped_column("expira_en", DateTime(timezone=True))
    refresh_hash: Mapped[str | None] = mapped_column("refresh_hash", String(64), unique=True)
    refresh_expires_at: Mapped[datetime | None] = mapped_column("refresh_expira_en", DateTime(timezone=True))
    previous_refresh_hash: Mapped[str | None] = mapped_column("refresh_anterior_hash", String(64))
    refresh_generation: Mapped[int] = mapped_column("refresh_generacion", Integer, default=0, server_default=text("0"), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column("revocada_en", DateTime(timezone=True))
    revoked_reason: Mapped[str | None] = mapped_column("revocada_motivo", String(80))


class AuditEvent(Base):
    __tablename__ = "auditoria_usuarios"

    id: Mapped[int] = mapped_column(pk_type, primary_key=True)
    actor_id: Mapped[int | None] = mapped_column("actor_id", ForeignKey("usuarios.id", ondelete="RESTRICT"))
    target_id: Mapped[int | None] = mapped_column("objetivo_id", ForeignKey("usuarios.id", ondelete="RESTRICT"))
    role_id: Mapped[int | None] = mapped_column("rol_id", ForeignKey("roles.id", ondelete="RESTRICT"))
    action: Mapped[str] = mapped_column("accion", String(80), nullable=False)
    details: Mapped[dict | None] = mapped_column("detalles", JSON)
    created_at: Mapped[datetime] = mapped_column("ocurrido_en", DateTime(timezone=True), default=now_utc, nullable=False)


exact_text = Text(collation="C").with_variant(Text(collation="BINARY"), "sqlite")
json_type = JSON().with_variant(JSONB(), "postgresql")


class Contract(Base):
    __tablename__ = "contratos"
    __table_args__ = (
        CheckConstraint("length(trim(kardex)) > 0", name="contratos_kardex_no_vacio"),
    )

    kardex: Mapped[str] = mapped_column(exact_text, primary_key=True)


class Location(Base):
    __tablename__ = "ubicaciones"
    __table_args__ = (
        ForeignKeyConstraint(
            ["revision_actual_id", "id"], ["revisiones_ubicacion.id", "revisiones_ubicacion.ubicacion_id"],
            name="ubicaciones_revision_propia", use_alter=True, ondelete="RESTRICT",
        ),
        CheckConstraint(
            "(latitud IS NULL AND longitud IS NULL) OR "
            "(latitud IS NOT NULL AND longitud IS NOT NULL AND latitud BETWEEN -90 AND 90 AND longitud BETWEEN -180 AND 180)",
            name="ubicaciones_coordenadas_validas",
        ),
        CheckConstraint(
            "metodo_coordenadas IS NULL OR metodo_coordenadas IN ('GPS_DISPOSITIVO', 'ENLACE_COMPARTIDO')",
            name="ubicaciones_metodo_valido",
        ),
        CheckConstraint(
            "metodo_coordenadas IS NULL OR (latitud IS NOT NULL AND longitud IS NOT NULL AND "
            "((metodo_coordenadas = 'GPS_DISPOSITIVO' AND url_gps IS NULL) OR "
            "(metodo_coordenadas = 'ENLACE_COMPARTIDO' AND url_gps IS NOT NULL AND length(trim(url_gps)) > 0)))",
            name="ubicaciones_metodo_contenido",
        ),
    )

    id: Mapped[int] = mapped_column(pk_type, Identity(), primary_key=True)
    kardex: Mapped[str] = mapped_column(exact_text, ForeignKey("contratos.kardex", ondelete="RESTRICT"), unique=True)
    revision_actual_id: Mapped[int | None] = mapped_column(pk_type)
    latitud: Mapped[Decimal | None] = mapped_column(Numeric)
    longitud: Mapped[Decimal | None] = mapped_column(Numeric)
    url_gps: Mapped[str | None] = mapped_column(Text)
    metodo_coordenadas: Mapped[str | None] = mapped_column(String(32))
    precision_metros: Mapped[float | None] = mapped_column(Float)
    capturado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    capturado_por: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id", ondelete="RESTRICT"))
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    creado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    creado_por: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id", ondelete="RESTRICT"))
    creador: Mapped[User | None] = relationship(lazy="selectin", foreign_keys=[creado_por])

    @property
    def creado_por_nombre(self) -> str | None:
        return self.creador.username if self.creador else None


class LocationRevision(Base):
    __tablename__ = "revisiones_ubicacion"
    __table_args__ = (
        UniqueConstraint("id", "ubicacion_id", name="revisiones_id_ubicacion_unicos"),
        CheckConstraint(
            "(latitud IS NULL AND longitud IS NULL) OR "
            "(latitud IS NOT NULL AND longitud IS NOT NULL AND latitud BETWEEN -90 AND 90 AND longitud BETWEEN -180 AND 180)",
            name="revisiones_coordenadas_validas",
        ),
        CheckConstraint("url_gps IS NULL OR length(trim(url_gps)) > 0", name="revisiones_url_no_vacia"),
        CheckConstraint(
            "metodo_coordenadas IS NULL OR metodo_coordenadas IN ('GPS_DISPOSITIVO', 'ENLACE_COMPARTIDO')",
            name="revisiones_metodo_valido",
        ),
        CheckConstraint(
            "metodo_coordenadas IS NULL OR (latitud IS NOT NULL AND longitud IS NOT NULL AND "
            "((metodo_coordenadas = 'GPS_DISPOSITIVO' AND url_gps IS NULL) OR "
            "(metodo_coordenadas = 'ENLACE_COMPARTIDO' AND url_gps IS NOT NULL AND length(trim(url_gps)) > 0)))",
            name="revisiones_metodo_contenido",
        ),
        Index("revisiones_por_ubicacion", "ubicacion_id", text("registrado_en DESC"), text("id DESC")),
    )

    id: Mapped[int] = mapped_column(pk_type, Identity(), primary_key=True)
    ubicacion_id: Mapped[int] = mapped_column(ForeignKey("ubicaciones.id", ondelete="RESTRICT"))
    url_gps: Mapped[str | None] = mapped_column(Text)
    metodo_coordenadas: Mapped[str | None] = mapped_column(String(32))
    latitud: Mapped[Decimal | None] = mapped_column(Numeric)
    longitud: Mapped[Decimal | None] = mapped_column(Numeric)
    fecha_evento: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    precision_metros: Mapped[float | None] = mapped_column(Float)
    registrado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP"))
    responsable_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id", ondelete="RESTRICT"))
    cerrada: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))


class Photograph(Base):
    __tablename__ = "fotografias"
    __table_args__ = (
        CheckConstraint("length(trim(storage_bucket)) > 0", name="fotografias_bucket_no_vacio"),
        CheckConstraint("length(trim(storage_clave)) > 0", name="fotografias_clave_no_vacia"),
        CheckConstraint("sha256 IS NULL OR sha256 ~ '^[0-9a-f]{64}$'", name="fotografias_sha256_valido").ddl_if(dialect="postgresql"),
        CheckConstraint(
            "registrado_por IS NOT NULL OR procedencia_id IS NOT NULL",
            name="fotografias_actor_o_procedencia",
        ),
        CheckConstraint(
            "sha256_original IS NULL OR sha256_original ~ '^[0-9a-f]{64}$'",
            name="fotografias_sha256_original_valido",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "(actualizado_por IS NULL AND actualizado_en IS NULL) OR (actualizado_por IS NOT NULL AND actualizado_en IS NOT NULL)",
            name="fotografias_actualizacion_completa",
        ),
    )

    id: Mapped[int] = mapped_column(pk_type, Identity(), primary_key=True)
    ubicacion_id: Mapped[int] = mapped_column(ForeignKey("ubicaciones.id", ondelete="RESTRICT"), unique=True)
    storage_bucket: Mapped[str] = mapped_column(Text)
    storage_clave: Mapped[str] = mapped_column(Text, unique=True)
    sha256: Mapped[str | None] = mapped_column(Text)
    sha256_original: Mapped[str | None] = mapped_column(Text)
    registrado_por: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id", ondelete="RESTRICT"))
    procedencia_id: Mapped[int | None] = mapped_column(ForeignKey("procedencia_historica.id", ondelete="RESTRICT"))
    registrado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP"))
    actualizado_por: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id", ondelete="RESTRICT"))
    actualizado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PhotoOperation(Base):
    __tablename__ = "operaciones_fotografia"
    __table_args__ = (
        CheckConstraint("tipo IN ('CREAR', 'REEMPLAZAR', 'ELIMINAR')", name="operaciones_foto_tipo"),
        CheckConstraint("estado IN ('preparada', 'objeto_listo', 'pendiente_limpieza', 'finalizada', 'cancelada')", name="operaciones_foto_estado"),
        CheckConstraint("intentos >= 0", name="operaciones_foto_intentos"),
        CheckConstraint(
            "(tipo = 'CREAR' AND nuevo_bucket IS NOT NULL AND nueva_clave IS NOT NULL AND anterior_bucket IS NULL AND anterior_clave IS NULL) OR "
            "(tipo = 'REEMPLAZAR' AND nuevo_bucket IS NOT NULL AND nueva_clave IS NOT NULL AND anterior_bucket IS NOT NULL AND anterior_clave IS NOT NULL) OR "
            "(tipo = 'ELIMINAR' AND nuevo_bucket IS NULL AND nueva_clave IS NULL AND anterior_bucket IS NOT NULL AND anterior_clave IS NOT NULL)",
            name="operaciones_foto_claves",
        ),
        CheckConstraint(
            "(limpieza_bucket IS NULL AND limpieza_clave IS NULL) OR "
            "(limpieza_bucket IS NOT NULL AND limpieza_clave IS NOT NULL AND "
            "(COALESCE(limpieza_bucket = nuevo_bucket AND limpieza_clave = nueva_clave, false) OR "
            "COALESCE(limpieza_bucket = anterior_bucket AND limpieza_clave = anterior_clave, false)))",
            name="operaciones_foto_limpieza",
        ),
        CheckConstraint("estado <> 'pendiente_limpieza' OR limpieza_clave IS NOT NULL", name="operaciones_foto_limpieza_pendiente"),
        CheckConstraint("tipo <> 'REEMPLAZAR' OR nueva_clave <> anterior_clave", name="operaciones_foto_clave_nueva"),
        CheckConstraint(
            "usuario_id IS NOT NULL OR (tipo = 'CREAR' AND procedencia_id IS NOT NULL)",
            name="operaciones_foto_actor_o_procedencia",
        ),
        Index("operaciones_foto_una_activa_por_ubicacion", "ubicacion_id", unique=True,
              postgresql_where=text("estado IN ('preparada', 'objeto_listo', 'pendiente_limpieza')"),
              sqlite_where=text("estado IN ('preparada', 'objeto_listo', 'pendiente_limpieza')")),
    )

    id: Mapped[int] = mapped_column(pk_type, Identity(), primary_key=True)
    idempotencia: Mapped[UUID] = mapped_column(Uuid, unique=True)
    solicitud_sha256: Mapped[str | None] = mapped_column(String(64))
    ubicacion_id: Mapped[int] = mapped_column(ForeignKey("ubicaciones.id", ondelete="RESTRICT"))
    usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id", ondelete="RESTRICT"))
    procedencia_id: Mapped[int | None] = mapped_column(ForeignKey("procedencia_historica.id", ondelete="RESTRICT"))
    fotografia_id: Mapped[int | None] = mapped_column(pk_type)
    tipo: Mapped[str] = mapped_column(Text)
    estado: Mapped[str] = mapped_column(Text)
    nuevo_bucket: Mapped[str | None] = mapped_column(Text)
    nueva_clave: Mapped[str | None] = mapped_column(Text, unique=True)
    anterior_bucket: Mapped[str | None] = mapped_column(Text)
    anterior_clave: Mapped[str | None] = mapped_column(Text)
    limpieza_bucket: Mapped[str | None] = mapped_column(Text)
    limpieza_clave: Mapped[str | None] = mapped_column(Text)
    intentos: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    ultimo_error: Mapped[str | None] = mapped_column(Text)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP"))
    actualizado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP"))


class Activity(Base):
    __tablename__ = "actividades"
    __table_args__ = (
        CheckConstraint("length(trim(tipo)) > 0", name="actividades_tipo_no_vacio"),
        CheckConstraint("fin_en IS NULL OR fin_en >= inicio_en", name="actividades_intervalo_valido"),
        Index("actividades_por_usuario_fecha", "usuario_id", text("inicio_en DESC")),
        Index("actividades_por_fecha", text("inicio_en DESC")),
        Index("actividades_por_ubicacion", "ubicacion_id"),
    )

    id: Mapped[int] = mapped_column(pk_type, Identity(), primary_key=True)
    usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id", ondelete="RESTRICT"))
    ubicacion_id: Mapped[int | None] = mapped_column(ForeignKey("ubicaciones.id", ondelete="RESTRICT"))
    tipo: Mapped[str] = mapped_column(Text)
    inicio_en: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    fin_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditRecord(Base):
    __tablename__ = "auditoria"
    __table_args__ = (
        CheckConstraint("length(trim(accion)) > 0", name="auditoria_accion_no_vacia"),
        CheckConstraint(
            "accion NOT IN ('CREAR_FOTOGRAFIA', 'ACTUALIZAR_FOTOGRAFIA', 'REEMPLAZAR_FOTOGRAFIA', 'ELIMINAR_FOTOGRAFIA') OR (usuario_id IS NOT NULL AND ubicacion_id IS NOT NULL)",
            name="auditoria_fotografia_actor_y_ubicacion",
        ),
        Index("auditoria_por_usuario_fecha", "usuario_id", text("ocurrido_en DESC")),
        Index("auditoria_por_fecha", text("ocurrido_en DESC")),
        Index("auditoria_por_ubicacion_fecha", "ubicacion_id", text("ocurrido_en DESC")),
    )

    id: Mapped[int] = mapped_column(pk_type, Identity(), primary_key=True)
    usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id", ondelete="RESTRICT"))
    ubicacion_id: Mapped[int | None] = mapped_column(ForeignKey("ubicaciones.id", ondelete="RESTRICT"))
    accion: Mapped[str] = mapped_column(Text)
    ocurrido_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP"))
    detalles: Mapped[dict | None] = mapped_column(json_type)
    motivo_id: Mapped[int | None] = mapped_column(ForeignKey("motivos_actualizacion.id", ondelete="RESTRICT"))
    operacion_id: Mapped[UUID | None] = mapped_column(Uuid, unique=True)


class UpdateReason(Base):
    __tablename__ = "motivos_actualizacion"
    __table_args__ = (
        CheckConstraint("length(trim(nombre)) > 0", name="motivos_actualizacion_nombre_no_vacio"),
    )

    id: Mapped[int] = mapped_column(pk_type, Identity(), primary_key=True)
    nombre: Mapped[str] = mapped_column(String(160), nullable=False)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))


class HistoricalSource(Base):
    __tablename__ = "procedencia_historica"
    __table_args__ = (
        CheckConstraint("length(trim(ruta_original)) > 0", name="procedencia_ruta_no_vacia"),
        CheckConstraint("length(trim(tipo)) > 0", name="procedencia_tipo_no_vacio"),
        CheckConstraint("length(trim(estado_revision)) > 0", name="procedencia_estado_no_vacio"),
        CheckConstraint("sha256 IS NULL OR sha256 ~ '^[0-9a-f]{64}$'", name="procedencia_sha256_valido").ddl_if(dialect="postgresql"),
        Index("procedencia_por_kardex", "kardex"),
    )

    id: Mapped[int] = mapped_column(pk_type, Identity(), primary_key=True)
    ruta_original: Mapped[str] = mapped_column(Text)
    tipo: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str | None] = mapped_column(Text)
    estado_revision: Mapped[str] = mapped_column(Text, server_default=text("'PENDIENTE'"))
    kardex: Mapped[str | None] = mapped_column(exact_text, ForeignKey("contratos.kardex", ondelete="RESTRICT"))
