"""Gemeinsame Fixtures.

Die Tests laufen gegen eine echte PostgreSQL-Datenbank (``FP_TEST_DATABASE_URL``),
deren Schema über die Alembic-Migrationen aufgebaut wird – damit sind auch die
Migrationen selbst getestet.
"""

from __future__ import annotations

import os
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, make_url, text
from sqlalchemy.orm import close_all_sessions

from app.mandant import Sitzungsfabrik
from app.modelle import (
    Ablauf,
    AblaufSchritt,
    Basis,
    Benutzer,
    Ereignis,
    Gruppe,
    Item,
    Kind,
    Lauf,
    Posten,
    PostenToken,
    Schule,
    Strecke,
)
from app.sicherheit import neues_token, passwort_hashen

# Testclient spricht HTTP, nicht HTTPS – sonst würde das Sitzungs-Cookie nicht gesendet.
os.environ["FP_COOKIE_SECURE"] = "false"
# Kein Netz in Tests: Kartenausschnitte nur, wo ein Test die Kacheln selbst liefert.
os.environ["FP_KARTEN_KACHELN"] = ""

PROJEKT = Path(__file__).resolve().parent.parent
PASSWORT = "geheim-geheim"
TEST_URL = os.environ.get(
    "FP_TEST_DATABASE_URL",
    "postgresql+psycopg://fahrrad:fahrrad@localhost:55432/fahrrad_test",
)


@pytest.fixture(scope="session")
def engine():
    url = make_url(TEST_URL)
    verwaltung = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with verwaltung.connect() as c:
        c.execute(text(f'DROP DATABASE IF EXISTS "{url.database}" WITH (FORCE)'))
        c.execute(text(f'CREATE DATABASE "{url.database}"'))
    verwaltung.dispose()

    cfg = Config(str(PROJEKT / "alembic.ini"))
    cfg.attributes["database_url"] = TEST_URL
    command.upgrade(cfg, "head")

    eng = create_engine(url)
    yield eng
    eng.dispose()


@pytest.fixture
def fabrik(engine):
    yield Sitzungsfabrik(engine)
    close_all_sessions()  # offene Transaktionen würden TRUNCATE blockieren
    tabellen = ", ".join(t.name for t in Basis.metadata.sorted_tables)
    with engine.begin() as c:
        c.execute(text(f"TRUNCATE {tabellen} RESTART IDENTITY CASCADE"))


@dataclass
class Schuldaten:
    """IDs aller Objekte einer Testschule, je Modell eine."""

    schule: int
    benutzer: int
    strecke: int
    posten: int
    item: int
    gruppe: int
    kind: int
    lauf: int
    posten_token: int
    ereignis: uuid.UUID
    ablauf: int = 0
    ablauf_schritt: int = 0
    email: str = ""
    kurz: str = ""

    @property
    def fremde_texte(self) -> tuple[str, ...]:
        """Texte, die in keiner Antwort an eine andere Schule auftauchen dürfen."""
        return (f"Ablauf {self.kurz}", f"Runde {self.kurz}", f"Klasse {self.kurz}", f"Grundschule {self.kurz}")

    def id_fuer(self, modell: type) -> object:
        return {
            Schule: self.schule,
            Benutzer: self.benutzer,
            Strecke: self.strecke,
            Posten: self.posten,
            Item: self.item,
            Gruppe: self.gruppe,
            Kind: self.kind,
            Lauf: self.lauf,
            PostenToken: self.posten_token,
            Ereignis: self.ereignis,
            Ablauf: self.ablauf,
            AblaufSchritt: self.ablauf_schritt,
        }[modell]


def schule_anlegen(fabrik: Sitzungsfabrik, kurz: str) -> Schuldaten:
    with fabrik.intern_kontext() as s:
        schule = Schule(name=f"Grundschule {kurz}", kurzname=kurz)
        s.add(schule)
        s.flush()
        admin = Benutzer(
            schule_id=schule.id,
            email=f"admin@{kurz.lower()}.example",
            passwort_hash=passwort_hashen(PASSWORT),
            rolle="schuladmin",
        )
        strecke = Strecke(schule_id=schule.id, name=f"Runde {kurz}")
        posten = Posten(strecke=strecke, name="Einmündung Lindenweg", position=1)
        item = Item(
            posten=posten,
            kurzbezeichnung="Schulterblick",
            beobachtungstext="Dreht das Kind den Kopf nach hinten links?",
            uebungstext="Übe den Schulterblick, bevor du abbiegst.",
            position=1,
        )
        gruppe = Gruppe(schule_id=schule.id, name=f"Klasse {kurz}", schuljahr="2026/27")
        kind = Kind(gruppe=gruppe, startnummer=7)
        s.add_all([admin, strecke, posten, item, gruppe, kind])
        s.flush()
        lauf = Lauf(
            schule_id=schule.id, strecke_id=strecke.id, gruppe_id=gruppe.id, datum=date.today()
        )
        s.add(lauf)
        s.flush()
        token = PostenToken(
            lauf_id=lauf.id,
            posten_id=posten.id,
            token=neues_token(),
            gueltig_bis=datetime.now(UTC) + timedelta(days=1),
        )
        ereignis = Ereignis(
            event_id=uuid.uuid4(),
            lauf_id=lauf.id,
            posten_id=posten.id,
            startnummer=7,
            typ="durchgang",
            nutzlast={"durchgang_nr": 1, "fehlende_items": [item.id]},
            erfasst_am=datetime.now(UTC),
        )
        ablauf = Ablauf(schule_id=schule.id, name=f"Ablauf {kurz}")
        ablauf.schritte.append(AblaufSchritt(kurzbezeichnung="Handzeichen", position=1))
        s.add_all([token, ereignis, ablauf])
        s.flush()
        return Schuldaten(
            schule=schule.id,
            benutzer=admin.id,
            strecke=strecke.id,
            posten=posten.id,
            item=item.id,
            gruppe=gruppe.id,
            kind=kind.id,
            lauf=lauf.id,
            posten_token=token.id,
            ereignis=ereignis.event_id,
            ablauf=ablauf.id,
            ablauf_schritt=ablauf.schritte[0].id,
            email=admin.email,
            kurz=kurz,
        )


@pytest.fixture
def schulen(fabrik) -> tuple[Schuldaten, Schuldaten]:
    return schule_anlegen(fabrik, "A"), schule_anlegen(fabrik, "B")


# --------------------------------------------------------------------------- Web


@pytest.fixture
def client(fabrik):
    from fastapi.testclient import TestClient

    from app.main import erstelle_app

    with TestClient(erstelle_app(fabrik), follow_redirects=False) as c:
        yield c


@pytest.fixture
def systemadmin(fabrik) -> str:
    email = "root@system.example"
    with fabrik.intern_kontext() as s:
        s.add(Benutzer(email=email, passwort_hash=passwort_hashen(PASSWORT), rolle="systemadmin"))
    return email


_CSRF = re.compile(r'name="csrf" value="([^"]+)"')


def csrf_aus(html: str) -> str:
    treffer = _CSRF.search(html)
    assert treffer, "Kein CSRF-Feld in der Seite"
    return treffer.group(1)


def anmelden(client, email: str, passwort: str = PASSWORT):
    seite = client.get("/anmelden")
    return client.post(
        "/anmelden", data={"email": email, "passwort": passwort, "csrf": csrf_aus(seite.text)}
    )


def angemeldet(client, email: str) -> str:
    """Meldet an und liefert das CSRF-Token der Sitzung."""
    r = anmelden(client, email)
    assert r.status_code == 303, r.text
    ziel = r.headers["location"]
    seite = client.get(ziel + ("konto" if ziel.endswith("/") else "/konto"))
    return csrf_aus(seite.text)
