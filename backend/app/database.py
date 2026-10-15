"""Shared SQLAlchemy metadata, engine and request-scoped sessions."""

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import MetaData, create_engine
from sqlalchemy.engine import Engine, URL, make_url
from sqlalchemy.orm import DeclarativeBase, Session


load_dotenv(Path(__file__).resolve().parents[1] / ".env")


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention={
        "ix": "ix_%(table_name)s_%(column_0_name)s",
        "uq": "uq_%(table_name)s_%(column_0_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    })


def get_database_url() -> URL:
    value = os.environ.get("DATABASE_URL")
    if not value:
        raise RuntimeError("DATABASE_URL must be set to a PostgreSQL connection URL")
    url = make_url(value)
    if url.drivername not in {"postgresql", "postgresql+psycopg", "postgres"}:
        raise ValueError("DATABASE_URL must use PostgreSQL with the psycopg driver")
    return url.set(drivername="postgresql+psycopg")


@lru_cache
def get_engine() -> Engine:
    return create_engine(get_database_url(), pool_pre_ping=True)


def get_db():
    """FastAPI dependency. Callers explicitly commit successful writes."""
    with Session(get_engine()) as session:
        yield session
