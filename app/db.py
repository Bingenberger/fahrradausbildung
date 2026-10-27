"""Datenbank-Engine und Sitzungsfabrik der Anwendung."""

from functools import lru_cache

from sqlalchemy import Engine, create_engine

from app.config import einstellungen
from app.mandant import Sitzungsfabrik


@lru_cache
def engine() -> Engine:
    return create_engine(einstellungen().database_url, pool_pre_ping=True)


@lru_cache
def sitzungen() -> Sitzungsfabrik:
    return Sitzungsfabrik(engine())
