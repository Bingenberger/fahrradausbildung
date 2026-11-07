"""Explicit schema job; serialized with a database advisory transaction lock."""
from pathlib import Path
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect,text
from app.db import engine
LOCK=762431802
# Exakte Schemarevision, die diese Codeversion erwartet (/health/ready, /gesund).
SCHEMA_REVISION="0009"
def migrate():
    config=Config(str(Path(__file__).resolve().parents[1]/"alembic.ini"))
    with engine().begin() as connection:
        connection.execute(text("SET LOCAL lock_timeout = '5s'"))
        connection.execute(text("SELECT pg_advisory_xact_lock(:key)"),{"key":LOCK})
        tables=inspect(connection).get_table_names()
        if tables and "alembic_version" not in tables:
            raise RuntimeError("Unversioned existing database; explicit adoption required")
        config.attributes["connection"]=connection
        command.upgrade(config,"head")
if __name__=="__main__":
    try:migrate();print("Fahrrad schema verified; no accounts created.")
    except Exception:raise SystemExit("Fahrrad migration failed; database/schema/lock must be checked") from None
