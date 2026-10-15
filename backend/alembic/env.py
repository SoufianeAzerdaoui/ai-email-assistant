"""Alembic uses the same DATABASE_URL and metadata as the application."""

from alembic import context

from app.database import Base, get_database_url, get_engine
from app import models  # noqa: F401 -- registers all model tables


def run_migrations_offline():
    context.configure(
        url=get_database_url(), target_metadata=Base.metadata,
        literal_binds=True, dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    with get_engine().connect() as connection:
        context.configure(
            connection=connection, target_metadata=Base.metadata, compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
