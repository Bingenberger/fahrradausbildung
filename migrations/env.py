from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from app.config import einstellungen
from app.modelle import Basis

config = context.config
if config.config_file_name is not None:
    # Bestehende Logger der Anwendung nicht abschalten (Standard von fileConfig).
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Basis.metadata


def _url() -> str:
    return config.attributes.get("database_url") or einstellungen().database_url


def run_migrations_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    verbindung = config.attributes.get("connection")
    if verbindung is not None:
        context.configure(connection=verbindung, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
        return
    engine = create_engine(_url(), poolclass=pool.NullPool)
    with engine.connect() as verbindung:
        context.configure(connection=verbindung, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
