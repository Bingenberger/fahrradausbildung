"""Funktionen des Verwaltungsbereichs, Anmeldung und Sicherheits-Header."""

from __future__ import annotations

import io
import re
from datetime import date
from pathlib import Path

import pytest
from pypdf import PdfReader
from sqlalchemy import select

from app.modelle import AdminSitzung, Gruppe, Item, Kind, Lauf, Posten, Schule, Strecke
from tests.conftest import PASSWORT, anmelden, angemeldet, csrf_aus

VORLAGEN = Path(__file__).resolve().parent.parent / "app" / "vorlagen"


def _neue_id(antwort, art: str) -> int:
    assert antwort.status_code == 303, antwort.text[:300]
    treffer = re.search(rf"/{art}/(\d+)", antwort.headers["location"])
    assert treffer, antwort.headers["location"]
    return int(treffer.group(1))


def _lauf_anlegen(fabrik, schule_id, strecke_id, gruppe_id):
    with fabrik.intern_kontext() as s:
        s.add(Lauf(schule_id=schule_id, strecke_id=strecke_id, gruppe_id=gruppe_id, datum=date(2030, 6, 1)))


# --------------------------------------------------------------------------- Strecken


def test_strecke_mit_posten_und_items_aufbauen(client, fabrik, schulen):
    a, _ = schulen
    csrf = angemeldet(client, a.email)
    sid = _neue_id(client.post("/verwaltung/strecken/neu", data={"name": "Große Runde", "csrf": csrf}), "strecken")
    p1 = _neue_id(client.post(f"/verwaltung/strecken/{sid}/posten", data={"name": "Kreisel", "csrf": csrf}), "posten")
    p2 = _neue_id(client.post(f"/verwaltung/strecken/{sid}/posten", data={"name": "Ampel", "csrf": csrf}), "posten")
    for k in ("Schulterblick", "Handzeichen"):
        client.post(
            f"/verwaltung/posten/{p1}/items",
            data={"kurzbezeichnung": k, "uebungstext": f"Übe {k}.", "csrf": csrf},
        )
    # Reihenfolge der Posten tauschen
    client.post(f"/verwaltung/posten/{p2}/verschieben", data={"richtung": "hoch", "csrf": csrf})

    with fabrik.intern_kontext() as s:
        strecke = s.get(Strecke, sid)
        assert [p.name for p in strecke.posten] == ["Ampel", "Kreisel"]
        assert [i.kurzbezeichnung for i in s.get(Posten, p1).items] == ["Schulterblick", "Handzeichen"]
        assert s.get(Posten, p1).items[0].uebungstext == "Übe Schulterblick."

    seite = client.get(f"/verwaltung/strecken/{sid}").text
    assert seite.index("Ampel") < seite.index("Kreisel")


def test_strecke_duplizieren_kopiert_alle_texte(client, fabrik, schulen):
    a, _ = schulen
    csrf = angemeldet(client, a.email)
    neu = _neue_id(client.post(f"/verwaltung/strecken/{a.strecke}/duplizieren", data={"csrf": csrf}), "strecken")
    assert neu != a.strecke
    with fabrik.intern_kontext() as s:
        alt, kopie = s.get(Strecke, a.strecke), s.get(Strecke, neu)
        assert kopie.schule_id == a.schule
        assert kopie.name.endswith("(Kopie)")
        texte = lambda st: [  # noqa: E731
            (p.name, [(i.kurzbezeichnung, i.beobachtungstext, i.uebungstext) for i in p.items]) for p in st.posten
        ]
        assert texte(kopie) == texte(alt)
        assert {p.id for p in kopie.posten}.isdisjoint({p.id for p in alt.posten})


def test_strecke_mit_lauf_nicht_loeschbar_aber_archivierbar(client, fabrik, schulen):
    a, _ = schulen
    csrf = angemeldet(client, a.email)  # Testschule A hat bereits einen Lauf
    client.post(f"/verwaltung/strecken/{a.strecke}/loeschen", data={"csrf": csrf})
    assert "nicht gelöscht" in client.get(f"/verwaltung/strecken/{a.strecke}").text
    client.post(f"/verwaltung/strecken/{a.strecke}/archivieren", data={"csrf": csrf})
    with fabrik.intern_kontext() as s:
        assert s.get(Strecke, a.strecke).archiviert


def test_strecke_ohne_lauf_loeschbar(client, fabrik, schulen):
    a, _ = schulen
    csrf = angemeldet(client, a.email)
    sid = _neue_id(client.post("/verwaltung/strecken/neu", data={"name": "Weg", "csrf": csrf}), "strecken")
    client.post(f"/verwaltung/strecken/{sid}/posten", data={"name": "P", "csrf": csrf})
    assert client.post(f"/verwaltung/strecken/{sid}/loeschen", data={"csrf": csrf}).status_code == 303
    with fabrik.intern_kontext() as s:
        assert s.get(Strecke, sid) is None


def test_struktur_ist_mit_lauf_eingefroren_texte_nicht(client, fabrik, schulen):
    a, _ = schulen
    csrf = angemeldet(client, a.email)
    client.post(f"/verwaltung/strecken/{a.strecke}/posten", data={"name": "Neu", "csrf": csrf})
    client.post(f"/verwaltung/posten/{a.posten}/items", data={"kurzbezeichnung": "Neu", "csrf": csrf})
    client.post(f"/verwaltung/items/{a.item}/loeschen", data={"csrf": csrf})
    client.post(f"/verwaltung/posten/{a.posten}/loeschen", data={"csrf": csrf})
    client.post(
        f"/verwaltung/items/{a.item}/bearbeiten",
        data={"kurzbezeichnung": "Schulterblick links", "uebungstext": "Neuer Text.", "csrf": csrf},
    )
    with fabrik.intern_kontext() as s:
        strecke = s.get(Strecke, a.strecke)
        assert [p.id for p in strecke.posten] == [a.posten]
        assert [i.id for i in strecke.posten[0].items] == [a.item]
        assert s.get(Item, a.item).kurzbezeichnung == "Schulterblick links"
        assert s.get(Item, a.item).uebungstext == "Neuer Text."


def test_item_kurzbezeichnung_pflicht_und_laenge(client, fabrik, schulen):
    a, _ = schulen
    csrf = angemeldet(client, a.email)
    sid = _neue_id(client.post("/verwaltung/strecken/neu", data={"name": "W", "csrf": csrf}), "strecken")
    pid = _neue_id(client.post(f"/verwaltung/strecken/{sid}/posten", data={"name": "P", "csrf": csrf}), "posten")
    client.post(f"/verwaltung/posten/{pid}/items", data={"kurzbezeichnung": " ", "csrf": csrf})
    client.post(f"/verwaltung/posten/{pid}/items", data={"kurzbezeichnung": "x" * 41, "csrf": csrf})
    with fabrik.intern_kontext() as s:
        assert s.get(Posten, pid).items == []


# --------------------------------------------------------------------------- Gruppen und Kinder


def _nummern(fabrik, gruppe_id: int) -> list[tuple[int, bool]]:
    with fabrik.intern_kontext() as s:
        return [(k.startnummer, k.aktiv) for k in s.get(Gruppe, gruppe_id).kinder]


def test_gruppe_mit_anzahl_legt_startnummern_an(client, fabrik, schulen):
    a, _ = schulen
    csrf = angemeldet(client, a.email)
    gid = _neue_id(
        client.post("/verwaltung/gruppen/neu", data={"name": "4b", "schuljahr": "2026/27", "anzahl": "24", "csrf": csrf}),
        "gruppen",
    )
    assert _nummern(fabrik, gid) == [(n, True) for n in range(1, 25)]
    html = client.get(f"/verwaltung/gruppen/{gid}").text
    assert "Startnummern 1 bis 24" in html
    assert f"/verwaltung/gruppen/{gid}/namensliste.pdf" in html
    assert "Vorname" not in html and "Nachname" not in html


def test_startnummern_bereich_hinzufuegen(client, fabrik, schulen):
    a, _ = schulen
    csrf = angemeldet(client, a.email)
    gid = _neue_id(client.post("/verwaltung/gruppen/neu", data={"name": "4c", "schuljahr": "x", "csrf": csrf}), "gruppen")
    assert _nummern(fabrik, gid) == []
    client.post(f"/verwaltung/gruppen/{gid}/kinder", data={"von": "3", "bis": "5", "csrf": csrf})
    client.post(f"/verwaltung/gruppen/{gid}/kinder", data={"von": "1", "bis": "", "csrf": csrf})
    # Überschneidung: vorhandene werden übersprungen
    client.post(f"/verwaltung/gruppen/{gid}/kinder", data={"von": "4", "bis": "6", "csrf": csrf})
    assert "1 Startnummer hinzugefügt" in client.get(f"/verwaltung/gruppen/{gid}").text
    assert [n for n, _ in _nummern(fabrik, gid)] == [1, 3, 4, 5, 6]


@pytest.mark.parametrize(
    "von,bis",
    [("0", ""), ("-1", "3"), ("x", ""), ("5", "2"), ("1", "1000"), ("", "")],
)
def test_startnummern_bereich_wird_geprueft(client, fabrik, schulen, von, bis):
    a, _ = schulen
    csrf = angemeldet(client, a.email)
    client.post(f"/verwaltung/gruppen/{a.gruppe}/kinder", data={"von": von, "bis": bis, "csrf": csrf})
    assert _nummern(fabrik, a.gruppe) == [(7, True)]


def test_doppelte_startnummer_abgewiesen(client, fabrik, schulen):
    a, _ = schulen
    csrf = angemeldet(client, a.email)
    client.post(f"/verwaltung/gruppen/{a.gruppe}/kinder", data={"von": "7", "csrf": csrf})
    assert "gibt es schon" in client.get(f"/verwaltung/gruppen/{a.gruppe}").text
    assert _nummern(fabrik, a.gruppe) == [(7, True)]


def test_startnummern_mit_lauf_fest_nur_deaktivierbar(client, fabrik, schulen):
    a, _ = schulen
    csrf = angemeldet(client, a.email)  # Gruppe von A hat einen Lauf
    client.post(f"/verwaltung/kinder/{a.kind}/loeschen", data={"csrf": csrf})
    assert _nummern(fabrik, a.gruppe) == [(7, True)]
    client.post(f"/verwaltung/kinder/{a.kind}/deaktivieren", data={"csrf": csrf})
    assert _nummern(fabrik, a.gruppe) == [(7, False)]
    client.post(f"/verwaltung/kinder/{a.kind}/aktivieren", data={"csrf": csrf})
    assert _nummern(fabrik, a.gruppe) == [(7, True)]


def test_startnummer_ohne_lauf_loeschbar(client, fabrik, schulen):
    a, _ = schulen
    csrf = angemeldet(client, a.email)
    gid = _neue_id(client.post("/verwaltung/gruppen/neu", data={"name": "x", "schuljahr": "y", "anzahl": "2", "csrf": csrf}), "gruppen")
    with fabrik.intern_kontext() as s:
        erste = s.get(Gruppe, gid).kinder[0].id
    client.post(f"/verwaltung/kinder/{erste}/loeschen", data={"csrf": csrf})
    assert _nummern(fabrik, gid) == [(2, True)]


def test_namensliste_pdf(client, fabrik, schulen):
    a, _ = schulen
    csrf = angemeldet(client, a.email)
    gid = _neue_id(client.post("/verwaltung/gruppen/neu", data={"name": "4d", "schuljahr": "2026/27", "anzahl": "30", "csrf": csrf}), "gruppen")
    with fabrik.intern_kontext() as s:
        neun = next(k.id for k in s.get(Gruppe, gid).kinder if k.startnummer == 9)
    client.post(f"/verwaltung/kinder/{neun}/deaktivieren", data={"csrf": csrf})

    antwort = client.get(f"/verwaltung/gruppen/{gid}/namensliste.pdf")
    assert antwort.status_code == 200
    assert antwort.headers["content-type"] == "application/pdf"
    seiten = PdfReader(io.BytesIO(antwort.content)).pages
    text = " ".join(" ".join(p.extract_text() for p in seiten).split())
    assert "Namensliste 4d" in text and "Grundschule A" in text and "2026/27" in text
    assert "dieselbe Startnummer" in text
    zahlen = [int(z) for z in re.findall(r"(?<![\d/])(\d{1,2})(?![\d/])", text.split("Notiz", 1)[1])]
    assert set(range(1, 31)) - {9} <= set(zahlen)
    assert 9 not in zahlen  # deaktiviert
    assert len(seiten) == 2  # 29 Zeilen à 10 mm passen nicht auf eine Seite
    assert "Seite 2 von 2" in text


def test_gruppe_ohne_lauf_loeschbar(client, fabrik, schulen):
    a, _ = schulen
    csrf = angemeldet(client, a.email)
    gid = _neue_id(client.post("/verwaltung/gruppen/neu", data={"name": "x", "schuljahr": "y", "anzahl": "3", "csrf": csrf}), "gruppen")
    client.post(f"/verwaltung/gruppen/{gid}/loeschen", data={"csrf": csrf})
    with fabrik.intern_kontext() as s:
        assert s.get(Gruppe, gid) is None
        assert s.execute(select(Kind).where(Kind.gruppe_id == gid)).first() is None


# --------------------------------------------------------------------------- Anmeldung und Sitzungen


def test_anmeldung_falsches_passwort(client, schulen):
    a, _ = schulen
    r = anmelden(client, a.email, "falsch-falsch")
    assert r.status_code == 401
    assert "stimmen nicht" in r.text
    r = anmelden(client, "gibt-es-nicht@x.example", "falsch-falsch")
    assert r.status_code == 401


def test_email_gross_klein_egal(client, schulen):
    a, _ = schulen
    assert anmelden(client, a.email.upper()).status_code == 303


def test_sitzungscookie_flags(client, schulen):
    a, _ = schulen
    r = anmelden(client, a.email)
    cookie = next(c for c in r.headers.get_list("set-cookie") if c.startswith("fp_sitzung="))
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie or "samesite=lax" in cookie.lower()


def test_cookie_secure_in_produktion(monkeypatch, fabrik, schulen):
    from fastapi.testclient import TestClient

    from app.config import einstellungen
    from app.main import erstelle_app

    a, _ = schulen
    monkeypatch.setenv("FP_COOKIE_SECURE", "true")
    einstellungen.cache_clear()
    try:
        with TestClient(erstelle_app(fabrik), base_url="https://testserver", follow_redirects=False) as https:
            r = anmelden(https, a.email)
        cookie = next(c for c in r.headers.get_list("set-cookie") if c.startswith("fp_sitzung="))
        assert "Secure" in cookie
    finally:
        monkeypatch.setenv("FP_COOKIE_SECURE", "false")
        einstellungen.cache_clear()


def test_in_der_datenbank_steht_nur_der_hash(client, fabrik, schulen):
    a, _ = schulen
    anmelden(client, a.email)
    cookie = client.cookies["fp_sitzung"]
    with fabrik.intern_kontext() as s:
        ids = s.execute(select(AdminSitzung.id_hash)).scalars().all()
    assert cookie not in ids and len(ids) == 1


def test_anmeldeformular_braucht_csrf(client, schulen):
    a, _ = schulen
    client.get("/anmelden")
    r = client.post("/anmelden", data={"email": a.email, "passwort": PASSWORT, "csrf": "falsch"})
    assert r.status_code == 403


def test_fehlversuchsbremse(client, schulen):
    a, _ = schulen
    for _ in range(10):
        assert anmelden(client, a.email, "falsch-falsch").status_code == 401
    # Auch das richtige Passwort hilft jetzt nicht mehr.
    assert anmelden(client, a.email).status_code == 429


def test_abmelden(client, schulen):
    a, _ = schulen
    csrf = angemeldet(client, a.email)
    assert client.post("/abmelden", data={"csrf": csrf}).status_code == 303
    assert client.get("/verwaltung/").headers["location"] == "/anmelden"


def test_deaktivierte_schule_wirkt_sofort(client, fabrik, schulen):
    a, _ = schulen
    angemeldet(client, a.email)
    with fabrik.intern_kontext() as s:
        s.get(Schule, a.schule).aktiv = False
    assert client.get("/verwaltung/").status_code == 303
    assert anmelden(client, a.email).status_code == 401


def test_neue_anmeldung_ersetzt_alte_sitzung(client, fabrik, schulen):
    """Keine Sitzungsfixierung: Beim Anmelden wird eine mitgeschickte alte Sitzung verworfen."""
    import hashlib

    from fastapi.testclient import TestClient

    from app.main import erstelle_app

    a, _ = schulen
    anmelden(client, a.email)
    alt = client.cookies["fp_sitzung"]
    with TestClient(erstelle_app(fabrik), follow_redirects=False) as zweiter:
        formular = zweiter.get("/anmelden")
        zweiter.cookies.set("fp_sitzung", alt)
        r = zweiter.post("/anmelden", data={"email": a.email, "passwort": PASSWORT, "csrf": csrf_aus(formular.text)})
        assert r.status_code == 303
    with fabrik.intern_kontext() as s:
        ids = s.execute(select(AdminSitzung.id_hash)).scalars().all()
    assert len(ids) == 1
    assert hashlib.sha256(alt.encode()).hexdigest() not in ids


def test_passwort_aendern(client, schulen):
    a, _ = schulen
    csrf = angemeldet(client, a.email)
    client.post("/verwaltung/konto/passwort", data={"alt": PASSWORT, "neu": "kurz", "neu2": "kurz", "csrf": csrf})
    assert "mindestens 10" in client.get("/verwaltung/konto").text
    client.post("/verwaltung/konto/passwort",
                data={"alt": PASSWORT, "neu": "ganz-neues-pw", "neu2": "ganz-neues-pw", "csrf": csrf})
    client.post("/abmelden", data={"csrf": csrf})
    assert anmelden(client, a.email).status_code == 401
    assert anmelden(client, a.email, "ganz-neues-pw").status_code == 303


# --------------------------------------------------------------------------- Systemadmin


def test_systemadmin_legt_schule_und_schuladmin_an(client, fabrik, systemadmin):
    csrf = angemeldet(client, systemadmin)
    sid = _neue_id(client.post("/system/schulen/neu", data={"name": "GS Nord", "kurzname": "nord", "csrf": csrf}), "schulen")
    r = client.post(f"/system/schulen/{sid}/admins", data={"email": "leitung@nord.example", "csrf": csrf})
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-store"
    passwort = re.search(r'<p class="passwort"><code>([^<]+)</code>', r.text).group(1)

    from fastapi.testclient import TestClient

    from app.main import erstelle_app

    with TestClient(erstelle_app(fabrik), follow_redirects=False) as neu:
        assert anmelden(neu, "leitung@nord.example", passwort).headers["location"] == "/verwaltung/"
        assert "GS Nord" in neu.get("/verwaltung/").text


def test_systemadmin_deaktiviert_schuladmin(client, fabrik, schulen, systemadmin):
    from fastapi.testclient import TestClient

    from app.main import erstelle_app

    a, _ = schulen
    with TestClient(erstelle_app(fabrik), follow_redirects=False) as schul_client:
        angemeldet(schul_client, a.email)
        csrf = angemeldet(client, systemadmin)
        client.post(f"/system/benutzer/{a.benutzer}/deaktivieren", data={"csrf": csrf})
        assert schul_client.get("/verwaltung/").status_code == 303  # sofort abgemeldet


def test_doppelter_kurzname_und_email_abgewiesen(client, schulen, systemadmin):
    a, _ = schulen
    csrf = angemeldet(client, systemadmin)
    client.post("/system/schulen/neu", data={"name": "X", "kurzname": "a", "csrf": csrf})
    assert "schon vergeben" in client.get("/system").text
    client.post(f"/system/schulen/{a.schule}/admins", data={"email": a.email.upper(), "csrf": csrf})
    assert "schon vergeben" in client.get(f"/system/schulen/{a.schule}").text


# --------------------------------------------------------------------------- Header und Vorlagen


def test_sicherheitsheader(client, schulen):
    a, _ = schulen
    angemeldet(client, a.email)
    for pfad in ("/anmelden", "/verwaltung/", "/static/verwaltung.css"):
        h = client.get(pfad).headers
        assert "unsafe-inline" not in h["content-security-policy"]
        assert "script-src 'self'" in h["content-security-policy"]
        assert h["strict-transport-security"].startswith("max-age=")
        assert h["x-content-type-options"] == "nosniff"
    assert client.get("/verwaltung/").headers["cache-control"] == "no-store"


def test_vorlagen_ohne_inline_skripte_und_styles():
    """CSP ohne 'unsafe-inline' verlangt: kein Inline-Skript, kein <style>, kein style=, kein on…=.

    Erlaubt sind nur Skriptdateien (``<script src=…></script>``) und reine
    Datenblöcke (``type="application/json"``), die der Browser nicht ausführt.
    """
    for datei in VORLAGEN.rglob("*.html"):
        text = datei.read_text()
        for attribute, inhalt in re.findall(r"<script([^>]*)>(.*?)</script>", text, re.S):
            datei_skript = re.search(r'\ssrc="/static/[^"]+"', attribute) and not inhalt.strip()
            datenblock = 'type="application/json"' in attribute
            assert datei_skript or datenblock, f"{datei.name}: Inline-Skript"
        assert text.count("<script") == len(re.findall(r"<script[^>]*>.*?</script>", text, re.S)), datei
        assert "<style" not in text, datei
        assert not re.search(r"\sstyle\s*=", text), datei
        assert not re.search(r"\son[a-z]+\s*=", text), datei


def test_jedes_post_formular_hat_csrf():
    for datei in VORLAGEN.rglob("*.html"):
        text = datei.read_text()
        for formular in re.findall(r"<form[^>]*method=\"post\"[^>]*>(.*?)</form>", text, re.S):
            assert "csrf" in formular, f"{datei.name}: Formular ohne CSRF-Feld"


def test_unbekannte_und_ungueltige_ids(client, schulen):
    a, _ = schulen
    angemeldet(client, a.email)
    assert client.get("/verwaltung/strecken/999999").status_code == 404
    assert client.get("/verwaltung/strecken/abc").status_code == 404
    assert csrf_aus(client.get("/verwaltung/strecken").text)
