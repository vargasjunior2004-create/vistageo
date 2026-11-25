import os
from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


def database_url() -> str:
    load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False, interpolate=False)
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL es obligatorio")
    if not url.startswith("postgresql+psycopg://"):
        raise RuntimeError("DATABASE_URL debe usar postgresql+psycopg")
    return url


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def create_database_engine(url: str) -> Engine:
    connect_args: dict[str, object] = {"prepare_threshold": None}
    connect_timeout = _env_int("DB_CONNECT_TIMEOUT_SECONDS", 10)
    statement_timeout_ms = _env_int("DB_STATEMENT_TIMEOUT_MS", 30000)
    connect_args["connect_timeout"] = connect_timeout
    connect_args["options"] = f"-c statement_timeout={statement_timeout_ms}"
    sslmode = os.environ.get("DB_SSLMODE", "").strip()
    if sslmode:
        connect_args["sslmode"] = sslmode
    sslrootcert = os.environ.get("DB_SSLROOTCERT", "").strip()
    if sslrootcert:
        connect_args["sslrootcert"] = sslrootcert
    return create_engine(
        url,
        pool_pre_ping=True,
        hide_parameters=True,
        connect_args=connect_args,
    )


@lru_cache
def session_factory() -> sessionmaker[Session]:
    engine = create_database_engine(database_url())
    return sessionmaker(bind=engine, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    with session_factory()() as db:
        yield db
