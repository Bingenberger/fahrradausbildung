"""Mandantentrennung je Admin-Endpunkt (Spezifikation 4.1, Abnahmekriterium 4).

Die Liste der Endpunkte wird nicht von Hand gepflegt, sondern aus dem
OpenAPI-Schema der Anwendung gelesen. Ein neuer Endpunkt ist damit automatisch
abgedeckt – oder der Test schlägt fehl, weil er einen unbekannten
Pfadparameter nicht befüllen kann.

Für jeden Endpunkt mit ID im Pfad gilt:
  * Schuladmin A mit IDs der Schule B → 404, und die Datenbank ist unverändert.
  * Gegenprobe: Schuladmin A mit eigenen IDs → kein 404 (der Test prüft also
    wirklich die Mandantengrenze und nicht z. B. ein fehlendes CSRF-Token).
Für Endpunkte ohne ID: Die Antwort an A enthält keine Texte der Schule B.
"""

from __future__ import annotations

import pytest
from fastapi.openapi.utils import get_openapi
from sqlalchemy import select

from app.main import erstelle_app
from app.mandant import Sitzungsfabrik
from app.modelle import MANDANTENMODELLE
from tests.conftest import angemeldet, csrf_aus


def _endpunkte(praefix: str) -> list[tuple[str, str]]:
    schema = get_openapi(title="x", version="1", routes=erstelle_app(Sitzungsfabrik(None)).routes)
    return sorted(
        (methode.upper(), pfad)
        for pfad, ops in schema["paths"].items()
        if pfad.startswith(praefix)
        for methode in ops
    )


VERWALTUNG = _endpunkte("/verwaltung")
SYSTEM = _endpunkte("/system")
MIT_ID = [e for e in VERWALTUNG if "{" in e[1]]
OHNE_ID = [e for e in VERWALTUNG if "{" not in e[1]]

PARAMETER = {
    "strecke_id": "strecke",
    "posten_id": "posten",
    "item_id": "item",
    "gruppe_id": "gruppe",
    "kind_id": "kind",
    "lauf_id": "lauf",
    "ablauf_id": "ablauf",
    "schritt_id": "ablauf_schritt",
}

# Plausible Formulardaten, damit eine Anfrage mit eigenen IDs tatsächlich etwas tut.
FORMULAR = {
    "name": "Geändert",
    "beschreibung": "x",
    "schuljahr": "2027/28",
    "kurzbezeichnung": "Neu",
    "beobachtungstext": "x",
    "uebungstext": "x",
    "von": "55",
    "bis": "56",
    "anzahl": "3",
    "richtung": "runter",
    "alt": "x",
    "neu": "x",
    "neu2": "x",
    "datum": "2099-01-01",
}


def _pfad(vorlage: str, daten) -> str:
    pfad = vorlage
    for teil in vorlage.split("/"):
        if teil.startswith("{"):
            name = teil.strip("{}")
            assert name in PARAMETER, f"Unbekannter Pfadparameter {name} in {vorlage} – Test ergänzen"
            pfad = pfad.replace(teil, str(getattr(daten, PARAMETER[name])))
    return pfad


def _anfrage(client, methode: str, pfad: str, csrf: str):
    if methode == "GET":
        return client.get(pfad)
    return client.post(pfad, data={**FORMULAR, "csrf": csrf})


def _datenbestand(fabrik) -> dict[str, list]:
    """Vollständiger Abzug aller Schuldaten beider Schulen."""
    abzug = {}
    with fabrik.intern_kontext() as s:
        for modell in MANDANTENMODELLE:
            spalten = modell.__table__.columns
            zeilen = s.execute(select(*[getattr(modell, c.key) for c in spalten])).all()
            abzug[modell.__tablename__] = sorted(map(repr, zeilen))
    return abzug


# --------------------------------------------------------------------------- Schuladmin A gegen Schule B


@pytest.mark.parametrize("methode,vorlage", MIT_ID, ids=[f"{m} {p}" for m, p in MIT_ID])
def test_fremde_id_ergibt_404_und_aendert_nichts(client, fabrik, schulen, methode, vorlage):
    a, b = schulen
    csrf = angemeldet(client, a.email)
    vorher = _datenbestand(fabrik)

    antwort = _anfrage(client, methode, _pfad(vorlage, b), csrf)

    assert antwort.status_code == 404, antwort.text[:500]
    for text in b.fremde_texte:
        assert text not in antwort.text
    assert _datenbestand(fabrik) == vorher


@pytest.mark.parametrize("methode,vorlage", MIT_ID, ids=[f"{m} {p}" for m, p in MIT_ID])
def test_gegenprobe_eigene_id_funktioniert(client, schulen, methode, vorlage):
    a, _ = schulen
    csrf = angemeldet(client, a.email)
    antwort = _anfrage(client, methode, _pfad(vorlage, a), csrf)
    assert antwort.status_code in (200, 303), antwort.text[:500]


@pytest.mark.parametrize("methode,vorlage", OHNE_ID, ids=[f"{m} {p}" for m, p in OHNE_ID])
def test_seiten_ohne_id_zeigen_nichts_von_schule_b(client, schulen, methode, vorlage):
    a, b = schulen
    csrf = angemeldet(client, a.email)
    antwort = _anfrage(client, methode, vorlage, csrf)
    if antwort.status_code == 303:
        antwort = client.get(antwort.headers["location"])
    assert antwort.status_code < 400, antwort.text[:500]
    for text in b.fremde_texte:
        assert text not in antwort.text


def test_alle_listen_zeigen_eigene_daten(client, schulen):
    """Gegenprobe zu oben: die eigenen Daten erscheinen sehr wohl."""
    a, _ = schulen
    angemeldet(client, a.email)
    assert f"Runde {a.kurz}" in client.get("/verwaltung/strecken").text
    assert f"Klasse {a.kurz}" in client.get("/verwaltung/gruppen").text
    assert "nummer-gross\">7<" in client.get(f"/verwaltung/gruppen/{a.gruppe}").text


# --------------------------------------------------------------------------- Rollen


@pytest.mark.parametrize("methode,vorlage", SYSTEM, ids=[f"{m} {p}" for m, p in SYSTEM])
def test_schuladmin_hat_keinen_zugang_zur_systemverwaltung(client, fabrik, schulen, methode, vorlage):
    a, _ = schulen
    csrf = angemeldet(client, a.email)
    vorher = _datenbestand(fabrik)
    pfad = vorlage.replace("{schule_id}", str(a.schule)).replace("{benutzer_id}", str(a.benutzer))
    antwort = _anfrage(client, methode, pfad, csrf)
    assert antwort.status_code == 404
    assert _datenbestand(fabrik) == vorher


@pytest.mark.parametrize("methode,vorlage", VERWALTUNG, ids=[f"{m} {p}" for m, p in VERWALTUNG])
def test_systemadmin_hat_keinen_zugang_zu_schuldaten(client, fabrik, schulen, systemadmin, methode, vorlage):
    a, b = schulen
    csrf = angemeldet(client, systemadmin)
    vorher = _datenbestand(fabrik)
    antwort = _anfrage(client, methode, _pfad(vorlage, a), csrf)
    assert antwort.status_code == 404
    for text in a.fremde_texte + b.fremde_texte:
        assert text not in antwort.text
    assert _datenbestand(fabrik) == vorher


def test_systemadmin_seiten_enthalten_keine_kinderdaten(client, schulen, systemadmin):
    a, b = schulen
    angemeldet(client, systemadmin)
    seiten = ["/system", "/system/konto", f"/system/schulen/{a.schule}", f"/system/schulen/{b.schule}"]
    for pfad in seiten:
        antwort = client.get(pfad)
        assert antwort.status_code == 200
        for text in (f"Klasse {a.kurz}", f"Runde {a.kurz}", f"Klasse {b.kurz}", f"Runde {b.kurz}"):
            assert text not in antwort.text


@pytest.mark.parametrize(
    "vorlage", ["/system/benutzer/{benutzer_id}/passwort", "/system/benutzer/{benutzer_id}/deaktivieren"]
)
def test_systemadmin_kann_keine_systemadmins_aendern(client, fabrik, systemadmin, vorlage):
    from app.modelle import Benutzer

    csrf = angemeldet(client, systemadmin)
    with fabrik.intern_kontext() as s:
        eigene_id = s.execute(select(Benutzer.id).where(Benutzer.email == systemadmin)).scalar_one()
    antwort = client.post(vorlage.replace("{benutzer_id}", str(eigene_id)), data={"csrf": csrf})
    assert antwort.status_code == 404


# --------------------------------------------------------------------------- Ohne Anmeldung / ohne CSRF


ALLE_GESCHUETZTEN = VERWALTUNG + SYSTEM


@pytest.mark.parametrize("methode,vorlage", ALLE_GESCHUETZTEN, ids=[f"{m} {p}" for m, p in ALLE_GESCHUETZTEN])
def test_ohne_anmeldung_weiterleitung(client, fabrik, schulen, methode, vorlage):
    a, _ = schulen
    vorher = _datenbestand(fabrik)
    pfad = _pfad(vorlage.replace("{schule_id}", str(a.schule)).replace("{benutzer_id}", str(a.benutzer)), a)
    antwort = _anfrage(client, methode, pfad, "")
    assert antwort.status_code == 303
    assert antwort.headers["location"] == "/anmelden"
    assert _datenbestand(fabrik) == vorher


POSTS = [e for e in ALLE_GESCHUETZTEN if e[0] == "POST"]


@pytest.mark.parametrize("methode,vorlage", POSTS, ids=[f"{m} {p}" for m, p in POSTS])
def test_ohne_csrf_token_abgewiesen(client, fabrik, schulen, systemadmin, methode, vorlage):
    a, _ = schulen
    email = systemadmin if vorlage.startswith("/system") else a.email
    angemeldet(client, email)
    vorher = _datenbestand(fabrik)
    pfad = _pfad(vorlage.replace("{schule_id}", str(a.schule)).replace("{benutzer_id}", str(a.benutzer)), a)
    for falsch in ("", "gefaelscht"):
        antwort = _anfrage(client, methode, pfad, falsch)
        assert antwort.status_code == 403
    assert _datenbestand(fabrik) == vorher


def test_csrf_token_ist_an_die_sitzung_gebunden(client, fabrik, schulen):
    """Das Token einer Sitzung von B gilt nicht in einer Sitzung von A."""
    from fastapi.testclient import TestClient

    a, b = schulen
    with TestClient(erstelle_app(fabrik), follow_redirects=False) as anderer:
        csrf_b = angemeldet(anderer, b.email)
    angemeldet(client, a.email)
    antwort = client.post("/verwaltung/strecken/neu", data={"name": "x", "csrf": csrf_b})
    assert antwort.status_code == 403


def test_csrf_aus_html(client, schulen):
    a, _ = schulen
    angemeldet(client, a.email)
    assert csrf_aus(client.get("/verwaltung/strecken").text)


def test_eigener_lauf_mit_fremdem_posten(client, fabrik, schulen):
    """Gemischte IDs: eigener Lauf, Posten der anderen Schule."""
    a, b = schulen
    csrf = angemeldet(client, a.email)
    vorher = _datenbestand(fabrik)
    antwort = client.post(f"/verwaltung/laeufe/{a.lauf}/tokens/{b.posten}/erneuern", data={"csrf": csrf})
    assert antwort.status_code == 404
    assert _datenbestand(fabrik) == vorher


def test_lauf_mit_fremder_strecke_oder_gruppe_anlegen(client, fabrik, schulen):
    """IDs im Formular statt im Pfad werden genauso geprüft."""
    a, b = schulen
    csrf = angemeldet(client, a.email)
    vorher = _datenbestand(fabrik)
    for strecke, gruppe in ((b.strecke, a.gruppe), (a.strecke, b.gruppe)):
        antwort = client.post(
            "/verwaltung/laeufe/neu",
            data={"strecke_id": strecke, "gruppe_id": gruppe, "datum": "2099-01-01", "csrf": csrf},
        )
        assert antwort.status_code == 404
    assert _datenbestand(fabrik) == vorher
