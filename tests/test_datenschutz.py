"""Aufbewahrungsfrist und Datenexport (Spezifikation 9)."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import func, select

from app import kommandos
from app.aufbewahrung import erfassungen_loeschen, monate_zurueck
from app.modelle import Ereignis, Lauf
from tests.conftest import angemeldet

# --------------------------------------------------------------------------- Aufbewahrung


@pytest.mark.parametrize(
    "tag,monate,erwartet",
    [
        (date(2026, 10, 15), 12, date(2025, 10, 15)),
        (date(2026, 3, 31), 1, date(2026, 2, 28)),
        (date(2028, 3, 31), 1, date(2028, 2, 29)),
        (date(2026, 1, 10), 1, date(2025, 12, 10)),
        (date(2026, 10, 15), 30, date(2024, 4, 15)),
    ],
)
def test_monate_zurueck(tag, monate, erwartet):
    assert monate_zurueck(tag, monate) == erwartet


def _lauf_mit_datum(fabrik, schule, datum: date, status: str = "abgeschlossen", ereignisse: int = 3) -> int:
    with fabrik.intern_kontext() as s:
        vorlage = s.get(Lauf, schule.lauf)
        lauf = Lauf(
            schule_id=schule.schule, strecke_id=vorlage.strecke_id, gruppe_id=vorlage.gruppe_id, datum=datum, status=status
        )
        s.add(lauf)
        s.flush()
        for n in range(ereignisse):
            s.add(
                Ereignis(
                    event_id=uuid.uuid4(),
                    lauf_id=lauf.id,
                    posten_id=schule.posten,
                    startnummer=7,
                    typ="durchgang",
                    nutzlast={"durchgang_nr": n + 1, "fehlende_items": []},
                    erfasst_am=datetime.now(UTC),
                )
            )
        return lauf.id


def _anzahl(fabrik, lauf_id: int) -> int:
    with fabrik.intern_kontext() as s:
        return s.execute(select(func.count()).select_from(Ereignis).where(Ereignis.lauf_id == lauf_id)).scalar_one()


HEUTE = date(2026, 10, 15)


def test_aufbewahrung_loescht_alte_erfassungen_aller_schulen(fabrik, schulen):
    a, b = schulen
    alt_a = _lauf_mit_datum(fabrik, a, date(2025, 10, 14))
    alt_b = _lauf_mit_datum(fabrik, b, date(2024, 5, 1), status="laufend")  # vergessen, nie abgeschlossen
    grenze = _lauf_mit_datum(fabrik, a, date(2025, 10, 15))  # genau 12 Monate: bleibt
    neu = _lauf_mit_datum(fabrik, b, date(2026, 6, 1))

    e = erfassungen_loeschen(fabrik, 12, heute=HEUTE)
    assert (e.stichtag, e.laeufe, e.ereignisse) == (date(2025, 10, 15), 2, 6)
    assert _anzahl(fabrik, alt_a) == _anzahl(fabrik, alt_b) == 0
    assert _anzahl(fabrik, grenze) == _anzahl(fabrik, neu) == 3
    with fabrik.intern_kontext() as s:
        for lauf_id in (alt_a, alt_b):
            lauf = s.get(Lauf, lauf_id)
            assert lauf.daten_geloescht_am is not None
            assert lauf.status == "archiviert"
        assert s.get(Lauf, grenze).daten_geloescht_am is None

    # Ein zweiter Lauf des Kommandos findet nichts mehr.
    assert erfassungen_loeschen(fabrik, 12, heute=HEUTE).laeufe == 0


def test_aufbewahrung_trocken_loescht_nichts(fabrik, schulen):
    a, _ = schulen
    alt = _lauf_mit_datum(fabrik, a, date(2020, 1, 1))
    e = erfassungen_loeschen(fabrik, 12, heute=HEUTE, trocken=True)
    assert (e.laeufe, e.ereignisse) == (1, 3)
    assert _anzahl(fabrik, alt) == 3
    with fabrik.intern_kontext() as s:
        assert s.get(Lauf, alt).daten_geloescht_am is None


def test_aufbewahrung_frist_mindestens_ein_monat(fabrik):
    with pytest.raises(ValueError):
        erfassungen_loeschen(fabrik, 0)


def test_aufbewahrung_kommando(fabrik, schulen, monkeypatch, capsys):
    a, _ = schulen
    alt = _lauf_mit_datum(fabrik, a, date(2020, 1, 1), ereignisse=2)
    monkeypatch.setattr(kommandos, "sitzungen", lambda: fabrik)
    monkeypatch.setenv("FP_AUFBEWAHRUNG_MONATE", "24")
    kommandos.einstellungen.cache_clear()
    try:
        assert kommandos.main(["aufbewahrung", "--trocken"]) == 0
        assert "Frist 24 Monate" in capsys.readouterr().out
        assert _anzahl(fabrik, alt) == 2
        assert kommandos.main(["aufbewahrung", "--monate", "6"]) == 0
        ausgabe = capsys.readouterr().out
        assert "2 Erfassungen aus 1 Läufen gelöscht" in ausgabe
        assert _anzahl(fabrik, alt) == 0
        assert kommandos.main(["aufbewahrung", "--monate", "0"]) == 1
    finally:
        kommandos.einstellungen.cache_clear()


def test_laufseite_erklaert_geloeschte_erfassungen(client, fabrik, schulen):
    a, _ = schulen
    alt = _lauf_mit_datum(fabrik, a, date(2020, 1, 1))
    erfassungen_loeschen(fabrik, 12)
    angemeldet(client, a.email)
    for pfad in (f"/verwaltung/laeufe/{alt}", f"/verwaltung/laeufe/{alt}/auswertung"):
        assert "nach Ablauf der Aufbewahrungsfrist gelöscht" in client.get(pfad).text


# --------------------------------------------------------------------------- Export


def test_export_enthaelt_alle_eigenen_daten_und_keine_fremden(client, fabrik, schulen):
    a, b = schulen
    angemeldet(client, a.email)
    antwort = client.get("/verwaltung/export.json")
    assert antwort.status_code == 200
    assert antwort.headers["content-type"].startswith("application/json")
    assert antwort.headers["content-disposition"].startswith('attachment; filename="export-a-')
    assert antwort.headers["cache-control"] == "no-store"

    daten = json.loads(antwort.content)
    assert daten["format"] == "fahrradpruefung-export"
    assert daten["schule"]["id"] == a.schule
    assert [b_["email"] for b_ in daten["benutzer"]] == [a.email]
    kinder = [k for g in daten["gruppen"] for k in g["kinder"]]
    assert kinder == [{"id": a.kind, "startnummer": 7, "aktiv": True}]
    assert [a_["name"] for a_ in daten["ablaeufe"]] == ["Ablauf A"]
    assert daten["ablaeufe"][0]["schritte"][0]["kurzbezeichnung"] == "Handzeichen"
    posten = daten["strecken"][0]["posten"][0]
    assert posten["items"][0]["uebungstext"] == "Übe den Schulterblick, bevor du abbiegst."
    (lauf,) = daten["laeufe"]
    assert lauf["id"] == a.lauf
    (ereignis,) = lauf["ereignisse"]
    assert ereignis["event_id"] == str(a.ereignis)
    assert ereignis["nutzlast"] == {"durchgang_nr": 1, "fehlende_items": [a.item]}

    text = antwort.text
    for fremd in b.fremde_texte:
        assert fremd not in text
    assert str(b.ereignis) not in text


def test_export_ohne_geheimnisse(client, fabrik, schulen):
    a, _ = schulen
    angemeldet(client, a.email)
    text = client.get("/verwaltung/export.json").text
    with fabrik.intern_kontext() as s:
        from app.modelle import Benutzer, PostenToken

        token = s.get(PostenToken, a.posten_token).token
        passwort_hash = s.get(Benutzer, a.benutzer).passwort_hash
    assert token not in text
    assert passwort_hash not in text
    assert "argon2" not in text
    assert "passwort" not in text


def test_export_auf_kontoseite_nur_fuer_schuladmin(client, schulen, systemadmin):
    a, _ = schulen
    angemeldet(client, a.email)
    assert "/verwaltung/export.json" in client.get("/verwaltung/konto").text
