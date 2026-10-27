"""Datenmodell, Migrationen und Sicherheitsbausteine."""

from __future__ import annotations

import base64
from datetime import date

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.exc import IntegrityError

from app.modelle import Benutzer, Kind, Lauf, PostenToken
from app.sicherheit import neues_token, passwort_hashen, passwort_pruefen
from tests.conftest import PROJEKT, TEST_URL


def test_migrationen_entsprechen_den_modellen(engine):
    cfg = Config(str(PROJEKT / "alembic.ini"))
    cfg.attributes["database_url"] = TEST_URL
    command.check(cfg)  # wirft, wenn Modell und Migration auseinanderlaufen


def test_startnummer_in_gruppe_eindeutig(fabrik, schulen):
    a, _ = schulen
    with pytest.raises(IntegrityError):
        with fabrik.intern_kontext() as s:
            s.add(Kind(gruppe_id=a.gruppe, startnummer=7))


def test_gleiche_startnummer_in_anderer_gruppe_erlaubt(fabrik, schulen):
    a, b = schulen
    with fabrik.intern_kontext() as s:
        assert s.get(Kind, b.kind).startnummer == s.get(Kind, a.kind).startnummer


def test_rolle_und_schule_passen_zusammen(fabrik, schulen):
    a, _ = schulen
    for benutzer in (
        Benutzer(schule_id=a.schule, email="s@x.example", passwort_hash="x", rolle="systemadmin"),
        Benutzer(schule_id=None, email="t@x.example", passwort_hash="x", rolle="schuladmin"),
    ):
        with pytest.raises(IntegrityError):
            with fabrik.intern_kontext() as s:
                s.add(benutzer)


def test_email_eindeutig_ohne_gross_klein(fabrik, schulen):
    a, _ = schulen
    with pytest.raises(IntegrityError):
        with fabrik.intern_kontext() as s:
            s.add(
                Benutzer(
                    schule_id=a.schule,
                    email="ADMIN@A.example",
                    passwort_hash="x",
                    rolle="schuladmin",
                )
            )


def test_strecke_mit_lauf_nicht_loeschbar(fabrik, schulen):
    from app.modelle import Strecke

    a, _ = schulen
    with pytest.raises(IntegrityError):
        with fabrik.intern_kontext() as s:
            s.delete(s.get(Strecke, a.strecke))


def test_nur_ein_aktiver_lauf_pro_strecke_und_tag(fabrik, schulen):
    a, _ = schulen
    with pytest.raises(IntegrityError):
        with fabrik.intern_kontext() as s:
            s.add(
                Lauf(
                    schule_id=a.schule,
                    strecke_id=a.strecke,
                    gruppe_id=a.gruppe,
                    datum=date.today(),
                )
            )


def test_keine_namen_von_kindern_im_datenmodell():
    """Die Anwendung kennt Kinder nur als Startnummer – Namen stehen auf Papier."""
    assert {c.name for c in Kind.__table__.columns} == {"id", "gruppe_id", "startnummer", "aktiv"}
    verdaechtig = {"vorname", "nachname", "geburtsdatum", "kind_name"}
    for tabelle in Kind.metadata.tables.values():
        assert not verdaechtig & {c.name for c in tabelle.columns}, tabelle.name


def test_repr_enthaelt_keine_tokens(fabrik, schulen):
    a, _ = schulen
    with fabrik.intern_kontext() as s:
        token = s.get(PostenToken, a.posten_token)
        assert token.token not in repr(token)


def test_passwort_argon2id():
    h = passwort_hashen("Fahrrad!")
    assert h.startswith("$argon2id$")
    assert passwort_pruefen(h, "Fahrrad!")
    assert not passwort_pruefen(h, "falsch")
    assert not passwort_pruefen("kein-hash", "Fahrrad!")


def test_token_mindestens_128_bit_und_url_sicher():
    tokens = {neues_token() for _ in range(1000)}
    assert len(tokens) == 1000
    for t in list(tokens)[:50]:
        assert len(base64.urlsafe_b64decode(t + "=" * (-len(t) % 4))) * 8 >= 128
        assert all(c.isalnum() or c in "-_" for c in t)
