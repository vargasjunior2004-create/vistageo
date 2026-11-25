import hashlib
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import jwt

DEFAULT_ISSUER = "geo-vista"
DEFAULT_AUDIENCE = "geo-vista-api"
DEFAULT_ACCESS_MINUTES = 15
DEFAULT_REFRESH_DAYS = 7
DEFAULT_ABSOLUTE_HOURS = 168


class TokenError(ValueError):
    pass


@dataclass(frozen=True)
class AccessClaims:
    subject: int
    session_id: int
    jwt_id: str
    issued_at: datetime
    expires_at: datetime


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise TokenError(f"{name} debe ser un entero") from exc
    if value <= 0:
        raise TokenError(f"{name} debe ser mayor a cero")
    return value


def jwt_secret() -> str:
    secret = os.environ.get("JWT_SECRET", "")
    if len(secret) < 32:
        raise TokenError("JWT_SECRET es obligatorio y debe tener al menos 32 caracteres")
    return secret


def jwt_issuer() -> str:
    return os.environ.get("JWT_ISSUER", DEFAULT_ISSUER)


def jwt_audience() -> str:
    return os.environ.get("JWT_AUDIENCE", DEFAULT_AUDIENCE)


def access_token_ttl() -> timedelta:
    return timedelta(minutes=_env_int("ACCESS_TOKEN_MINUTES", DEFAULT_ACCESS_MINUTES))


def refresh_token_ttl() -> timedelta:
    return timedelta(days=_env_int("REFRESH_TOKEN_DAYS", DEFAULT_REFRESH_DAYS))


def absolute_session_ttl() -> timedelta:
    return timedelta(hours=_env_int("SESSION_ABSOLUTE_HOURS", DEFAULT_ABSOLUTE_HOURS))


def session_idle_ttl() -> timedelta:
    return timedelta(minutes=_env_int("SESSION_IDLE_MINUTES", 10))


def create_access_token(session_id: int, user_id: int, now: datetime | None = None) -> tuple[str, int]:
    issued_at = now or datetime.now(timezone.utc)
    expires_at = issued_at + access_token_ttl()
    payload = {
        "sub": str(user_id),
        "sid": session_id,
        "jti": uuid4().hex,
        "iat": int(issued_at.timestamp()),
        "exp": int(expires_at.timestamp()),
        "iss": jwt_issuer(),
        "aud": jwt_audience(),
        "typ": "access",
    }
    token = jwt.encode(payload, jwt_secret(), algorithm="HS256")
    return token, int(access_token_ttl().total_seconds())


def decode_access_token(token: str) -> AccessClaims:
    try:
        payload = jwt.decode(
            token,
            jwt_secret(),
            algorithms=["HS256"],
            audience=jwt_audience(),
            issuer=jwt_issuer(),
            options={"require": ["sub", "sid", "jti", "iat", "exp", "iss", "aud", "typ"]},
        )
    except jwt.InvalidTokenError as exc:
        raise TokenError("Token inválido") from exc
    if payload.get("typ") != "access":
        raise TokenError("Token inválido")
    try:
        subject = int(payload["sub"])
        session_id = int(payload["sid"])
        jwt_id = str(payload["jti"])
        issued_at = datetime.fromtimestamp(int(payload["iat"]), tz=timezone.utc)
        expires_at = datetime.fromtimestamp(int(payload["exp"]), tz=timezone.utc)
    except (KeyError, TypeError, ValueError) as exc:
        raise TokenError("Token inválido") from exc
    return AccessClaims(subject=subject, session_id=session_id, jwt_id=jwt_id, issued_at=issued_at, expires_at=expires_at)


def generate_refresh_token() -> str:
    return secrets.token_urlsafe(32)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def looks_like_jwt(token: str) -> bool:
    return token.count(".") == 2