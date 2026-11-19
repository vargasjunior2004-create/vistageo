from datetime import datetime
from decimal import Decimal
from typing import Self
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, SecretStr, StrictBool, field_validator, model_validator


def normalize_username(value: str) -> str:
    if value != value.strip() or not value:
        raise ValueError("El usuario no puede estar vacío ni tener espacios externos")
    normalized = value.upper()
    if len(normalized) > 100:
        raise ValueError("El usuario no puede exceder 100 caracteres")
    return normalized


def validate_password(value: str) -> str:
    normalized = value.upper()
    if len(normalized) < 8 or len(normalized) > 256 or not normalized.strip():
        raise ValueError("La contraseña debe tener entre 8 y 256 caracteres y no ser solo espacios")
    return normalized


def validate_secret(value: SecretStr) -> SecretStr:
    return SecretStr(validate_password(value.get_secret_value()))


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LoginRequest(RequestModel):
    username: str = Field(min_length=1, max_length=100)
    password: SecretStr = Field(min_length=1, max_length=256)

    _username = field_validator("username")(normalize_username)


class UserCreate(RequestModel):
    username: str = Field(min_length=1, max_length=100)
    password: SecretStr = Field(min_length=1, max_length=256)
    role_id: int = Field(gt=0, strict=True)

    _username = field_validator("username")(normalize_username)
    _password = field_validator("password")(validate_secret)


class UserUpdate(RequestModel):
    username: str | None = Field(default=None, min_length=1, max_length=100)
    role_id: int | None = Field(default=None, gt=0, strict=True)
    active: StrictBool | None = None

    @field_validator("username")
    @classmethod
    def username_is_normalized(cls, value: str | None) -> str | None:
        return normalize_username(value) if value is not None else None

    @model_validator(mode="after")
    def changes_required(self) -> Self:
        if not self.model_fields_set or any(getattr(self, name) is None for name in self.model_fields_set):
            raise ValueError("Se requiere al menos un campo válido")
        return self


class PasswordChange(RequestModel):
    current_password: SecretStr = Field(min_length=1, max_length=256)
    new_password: SecretStr = Field(min_length=1, max_length=256)

    _new_password = field_validator("new_password")(validate_secret)


class PasswordReset(RequestModel):
    temporary_password: SecretStr = Field(min_length=1, max_length=256)

    _password = field_validator("temporary_password")(validate_secret)


class RoleCreate(RequestModel):
    name: str = Field(min_length=1, max_length=80)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized or len(normalized) > 80:
            raise ValueError("Nombre de rol inválido")
        return normalized


class PermissionUpdate(RequestModel):
    permissions: list[str] = Field(max_length=100)

    @field_validator("permissions")
    @classmethod
    def unique_permissions(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("No se permiten permisos duplicados")
        return value


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    active: bool
    role_id: int
    must_change_password: bool


class SessionUserRead(UserRead):
    role_name: str
    permissions: list[str]


class ContractCreate(RequestModel):
    kardex: str = Field(strict=True)

    @field_validator("kardex")
    @classmethod
    def valid_kardex(cls, value: str) -> str:
        if not value.strip() or "\x00" in value:
            raise ValueError("Kardex inválido")
        return value


class ContractRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    kardex: str


class HistoricalSourceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    ruta_original: str
    tipo: str
    sha256: str | None
    estado_revision: str
    kardex: str | None


class LocationCreate(ContractCreate):
    pass


class FieldLocationCreate(ContractCreate):
    idempotencia: UUID
    latitud: Decimal = Field(ge=-90, le=90, allow_inf_nan=False)
    longitud: Decimal = Field(ge=-180, le=180, allow_inf_nan=False)
    fotografia_base64: str = Field(min_length=1, max_length=12 * 1024 * 1024)


class LocationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    kardex: str
    revision_actual_id: int | None


class LocationRevisionCreate(RequestModel):
    url_gps: str | None = None
    latitud: Decimal | None = Field(default=None, ge=-90, le=90, allow_inf_nan=False)
    longitud: Decimal | None = Field(default=None, ge=-180, le=180, allow_inf_nan=False)
    fecha_evento: AwareDatetime | None = None

    @field_validator("url_gps")
    @classmethod
    def valid_url(cls, value: str | None) -> str | None:
        if value is not None:
            try:
                parts = urlsplit(value)
                valid = parts.scheme in {"http", "https"} and parts.hostname is not None
                _ = parts.port
            except ValueError as exc:
                raise ValueError("URL inválida") from exc
            if not valid or any(char.isspace() or ord(char) < 32 for char in value):
                raise ValueError("URL inválida")
        return value

    @model_validator(mode="after")
    def coordinates_and_content(self) -> Self:
        if (self.latitud is None) != (self.longitud is None):
            raise ValueError("Latitud y longitud deben indicarse juntas")
        if self.url_gps is None and self.latitud is None:
            raise ValueError("Se requiere una URL o coordenadas")
        return self


class LocationRevisionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    ubicacion_id: int
    url_gps: str | None
    latitud: Decimal | None
    longitud: Decimal | None
    fecha_evento: datetime | None
    registrado_en: datetime
    responsable_id: int | None
    cerrada: bool
