"""Strukturelle Absicherung der Mandanten-Schicht.

Diese Tests sorgen dafür, dass die Schutzmechanismen nicht still erodieren:
ein neues Modell ohne Mandantenbezug oder ein Route-Handler mit direktem
Sitzungszugriff fällt sofort auf.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.modelle import INFRASTRUKTURMODELLE, MANDANTENMODELLE, Basis, Mandantenmodell

APP = Path(__file__).resolve().parent.parent / "app"

# Pakete mit Route-Handlern des Verwaltungsbereichs (Schuladmin und Systemadmin).
# Sie dürfen ausschließlich über SchulRepository/SystemRepository zugreifen.
ROUTEN_PAKETE = ("verwaltung", "system")

VERBOTEN = {
    r"\.query\(": "session.query()",
    r"\bsession\.execute\(": "direkte session.execute()",
    r"\b(Session|FPSession|sessionmaker)\b": "direkte Sitzungsklasse",
    r"\.intern(_kontext)?\(": "uneingeschränkte interne Sitzung",
    r"__table__": "Core-Zugriff am ORM vorbei",
    r"\btext\(": "rohes SQL",
    r"\bfrom app\.db import\b": "direkter Zugriff auf Engine/Sitzungsfabrik",
}


def verstoesse(quelltext: str) -> list[str]:
    funde = []
    for nr, zeile in enumerate(quelltext.splitlines(), 1):
        if zeile.lstrip().startswith("#"):
            continue
        for muster, grund in VERBOTEN.items():
            if re.search(muster, zeile):
                funde.append(f"Zeile {nr}: {grund}: {zeile.strip()}")
    return funde


def _routenmodule() -> list[Path]:
    return [p for paket in ROUTEN_PAKETE for p in sorted((APP / paket).rglob("*.py"))]


@pytest.mark.parametrize("pfad", _routenmodule() or [None], ids=lambda p: p and p.name)
def test_routen_greifen_nur_ueber_repository_zu(pfad):
    if pfad is None:
        pytest.skip("Noch keine Route-Module vorhanden (folgen in Schritt 3)")
    funde = verstoesse(pfad.read_text())
    assert not funde, f"{pfad.relative_to(APP.parent)}:\n" + "\n".join(funde)


def test_pruefer_erkennt_verstoesse():
    schlecht = """
from app.db import sitzungen
def liste(session):
    return session.query(Kind).all()
def roh(s):
    s.execute(text("select 1"))
    return Kind.__table__
"""
    assert len(verstoesse(schlecht)) >= 4
    gut = "def liste(repo: SchulRepository):\n    return repo.liste(Kind)\n"
    assert verstoesse(gut) == []


def test_jedes_modell_ist_mandantenfaehig():
    """Wer ein Modell ergänzt, muss dessen Schulzuordnung definieren."""
    gemappt = {m.class_ for m in Basis.registry.mappers}
    assert gemappt == set(MANDANTENMODELLE) | set(INFRASTRUKTURMODELLE)
    for modell in MANDANTENMODELLE:
        assert issubclass(modell, Mandantenmodell)
        assert "mandant_kriterium" in vars(modell), modell.__name__


def test_jede_tabelle_hat_ein_modell():
    alle = MANDANTENMODELLE + INFRASTRUKTURMODELLE
    assert set(Basis.metadata.tables) == {m.__tablename__ for m in alle}


def test_mandanteneltern_sind_vollstaendig():
    """Jeder Fremdschlüssel auf eine schulbezogene Tabelle muss geprüft werden."""
    for modell in MANDANTENMODELLE:
        fks = {
            fk.parent.name
            for fk in modell.__table__.foreign_keys
        }
        assert fks == set(modell.__mandant_eltern__), modell.__name__
