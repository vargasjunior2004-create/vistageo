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


def create_database_engine(url: str) -> Engine:
    return create_engine(
        url, pool_pre_ping=True, hide_parameters=True,
        connect_args={"prepare_threshold": None},
    )


@lru_cache
def session_factory() -> sessionmaker[Session]:
    engine = create_database_engine(database_url())
    return sessionmaker(bind=engine, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    with session_factory()() as db:
        yield db
