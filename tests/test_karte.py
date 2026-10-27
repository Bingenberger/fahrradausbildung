"""Streckenplanung auf der Karte und Kartenausschnitt auf dem Posten-Blatt."""

from __future__ import annotations

import io
import json
import re

import pytest
from PIL import Image
from playwright import sync_api as playwright_api
from pypdf import PdfReader

from app import kartenbild as kb
from app.config import einstellungen
from app.modelle import Item, Lauf, Posten, Strecke
from app.verwaltung.karte import MAX_LINIENPUNKTE, Ungueltig, orte_pruefen, verlauf_pruefen
from app.web.header import CSP, KARTEN_CSP
from tests.conftest import angemeldet, csrf_aus
from tests.test_posten_frontend import server_starten

NIEDERKASSEL = (50.8140, 7.0400)

# --------------------------------------------------------------------------- Prüfung der Eingaben


def test_verlauf_wird_geprueft_und_gerundet():
    v = verlauf_pruefen(json.dumps({"modus": "route", "wegpunkte": [[50.1234567, 7.1]], "linie": [[50.1, 7.1], [50.2, 7.2]]}))
    assert v == {"modus": "route", "wegpunkte": [[50.123457, 7.1]], "linie": [[50.1, 7.1], [50.2, 7.2]]}
    assert verlauf_pruefen("") is None
    assert verlauf_pruefen("null") is None
    assert verlauf_pruefen(json.dumps({"linie": [[50.1, 7.1]]})) is None  # ein Punkt ist keine Strecke


@pytest.mark.parametrize(
    "roh",
    [
        "kein json",
        json.dumps([1, 2]),
        json.dumps({"linie": [[50, 7], [91, 7]]}),
        json.dumps({"linie": [[50, 7], [50, 181]]}),
        json.dumps({"linie": [[50, 7], [50, "7"]]}),
        json.dumps({"linie": [[50, 7], [50, True]]}),
        json.dumps({"linie": [[50, 7], [50]]}),
        '{"linie": [[50, 7], [NaN, 7]]}',
        json.dumps({"linie": [[50, 7]] * (MAX_LINIENPUNKTE + 1)}),
        json.dumps({"modus": "teleport", "linie": [[50, 7], [50, 8]]}),
        json.dumps({"linie": [[50, 7], [50, 8]], "fremd": 1}),
    ],
)
def test_verlauf_ungueltig(roh):
    with pytest.raises(Ungueltig):
        verlauf_pruefen(roh)


def test_orte_nur_fuer_eigene_posten():
    assert orte_pruefen(json.dumps({"3": [50.1, 7.1], "4": None}), {3, 4}) == {3: [50.1, 7.1], 4: None}
    with pytest.raises(Ungueltig):
        orte_pruefen(json.dumps({"5": [50, 7]}), {3, 4})
    with pytest.raises(Ungueltig):
        orte_pruefen(json.dumps({"x": [50, 7]}), {3})
    with pytest.raises(Ungueltig):
        orte_pruefen(json.dumps({"3": [99, 7]}), {3})


# --------------------------------------------------------------------------- Seiten


def test_kartenseite_eigene_csp_nur_dort(client, schulen):
    a, _ = schulen
    angemeldet(client, a.email)
    karte = client.get(f"/verwaltung/strecken/{a.strecke}/karte")
    assert karte.status_code == 200
    assert karte.headers["content-security-policy"] == KARTEN_CSP
    assert "unsafe-inline" not in KARTEN_CSP and "unsafe-eval" not in KARTEN_CSP
    assert "script-src 'self';" in KARTEN_CSP
    assert "https://*.tile.openstreetmap.de" in KARTEN_CSP
    assert karte.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    # Alle anderen Seiten bleiben streng
    andere = client.get(f"/verwaltung/strecken/{a.strecke}")
    assert andere.headers["content-security-policy"] == CSP
    assert andere.headers["referrer-policy"] == "no-referrer"
    # Nur ein Datenblock, kein ausführbares Inline-Skript
    skripte = re.findall(r"<script([^>]*)>", karte.text)
    assert all("src=" in s or 'type="application/json"' in s for s in skripte)


def test_kartendaten_sicher_eingebettet(client, fabrik, schulen):
    a, _ = schulen
    with fabrik.intern_kontext() as s:
        s.get(Strecke, a.strecke).name = "Runde </script><script>alert(1)</script>"
    angemeldet(client, a.email)
    html = client.get(f"/verwaltung/strecken/{a.strecke}/karte").text
    block = re.search(r'<script type="application/json" id="kartendaten">(.*?)</script>', html, re.S).group(1)
    daten = json.loads(block)
    assert daten["strecke"]["name"].startswith("Runde </script>")
    assert daten["posten"] == [{"id": a.posten, "nummer": 1, "name": "Einmündung Lindenweg", "ort": None}]
    assert set(daten["quellen"]) == {"kacheln", "routing", "ortssuche"}


def _speichern(client, csrf, strecke_id, verlauf, orte):
    return client.post(
        f"/verwaltung/strecken/{strecke_id}/karte",
        data={"verlauf": json.dumps(verlauf), "orte": json.dumps(orte), "csrf": csrf},
    )


def test_speichern_und_wieder_entfernen(client, fabrik, schulen):
    a, _ = schulen
    csrf = angemeldet(client, a.email)
    linie = [[50.81, 7.04], [50.812, 7.041], [50.813, 7.045]]
    r = _speichern(client, csrf, a.strecke, {"modus": "route", "wegpunkte": [linie[0], linie[-1]], "linie": linie},
                   {str(a.posten): [50.812, 7.041]})
    assert r.status_code == 303
    with fabrik.intern_kontext() as s:
        st = s.get(Strecke, a.strecke)
        assert st.verlauf["linie"] == linie
        assert (st.posten[0].lat, st.posten[0].lng) == (50.812, 7.041)
    assert "Gespeichert." in client.get(r.headers["location"]).text

    _speichern(client, csrf, a.strecke, None, {str(a.posten): None})
    with fabrik.intern_kontext() as s:
        st = s.get(Strecke, a.strecke)
        assert st.verlauf is None
        assert st.posten[0].lat is None and st.posten[0].lng is None
    assert "Noch ohne Standort: Einmündung Lindenweg" in client.get(f"/verwaltung/strecken/{a.strecke}/karte").text


def test_speichern_mit_fremdem_posten_aendert_nichts(client, fabrik, schulen):
    a, b = schulen
    csrf = angemeldet(client, a.email)
    with fabrik.intern_kontext() as s:
        andere = Strecke(schule_id=a.schule, name="Andere")
        andere.posten.append(Posten(name="Fremd", position=1))
        s.add(andere)
        s.flush()
        fremd_eigene_schule = andere.posten[0].id
    for pid in (fremd_eigene_schule, b.posten):
        r = _speichern(client, csrf, a.strecke, None, {str(a.posten): [50, 7], str(pid): [50, 7]})
        assert r.status_code == 303
        assert "Nicht gespeichert" in client.get(r.headers["location"]).text
    with fabrik.intern_kontext() as s:
        assert s.get(Posten, a.posten).lat is None
        assert s.get(Posten, b.posten).lat is None
        assert s.get(Posten, fremd_eigene_schule).lat is None


def test_standort_auch_mit_lauf_aenderbar_und_streckenseite_zeigt_stand(client, fabrik, schulen):
    a, _ = schulen  # Strecke A hat einen Lauf
    csrf = angemeldet(client, a.email)
    _speichern(client, csrf, a.strecke, None, {str(a.posten): [50.8, 7.0]})
    with fabrik.intern_kontext() as s:
        assert s.get(Posten, a.posten).lat == 50.8
    html = client.get(f"/verwaltung/strecken/{a.strecke}").text
    assert "1 von 1 Posten verortet" in html
    assert f"/verwaltung/strecken/{a.strecke}/karte" in html


def test_duplizieren_und_export_uebernehmen_karte(client, fabrik, schulen):
    a, _ = schulen
    csrf = angemeldet(client, a.email)
    linie = [[50.81, 7.04], [50.82, 7.05]]
    _speichern(client, csrf, a.strecke, {"modus": "trace", "linie": linie}, {str(a.posten): [50.815, 7.045]})
    r = client.post(f"/verwaltung/strecken/{a.strecke}/duplizieren", data={"csrf": csrf})
    neu = int(re.search(r"/strecken/(\d+)", r.headers["location"]).group(1))
    with fabrik.intern_kontext() as s:
        kopie = s.get(Strecke, neu)
        assert kopie.verlauf["linie"] == linie
        assert (kopie.posten[0].lat, kopie.posten[0].lng) == (50.815, 7.045)
    export = client.get("/verwaltung/export.json").json()
    original = next(s for s in export["strecken"] if s["id"] == a.strecke)
    assert original["verlauf"]["linie"] == linie
    assert original["posten"][0]["lat"] == 50.815


def test_andere_strecken_zum_vergleich_nur_eigene_schule(client, fabrik, schulen):
    a, b = schulen
    with fabrik.intern_kontext() as s:
        s.get(Strecke, b.strecke).verlauf = {"modus": "trace", "wegpunkte": [], "linie": [[1, 1], [2, 2]]}
        eigene = Strecke(schule_id=a.schule, name="Vergleichsrunde",
                         verlauf={"modus": "trace", "wegpunkte": [], "linie": [[3, 3], [4, 4]]})
        s.add(eigene)
    angemeldet(client, a.email)
    html = client.get(f"/verwaltung/strecken/{a.strecke}/karte").text
    daten = json.loads(re.search(r'id="kartendaten">(.*?)</script>', html, re.S).group(1))
    assert [x["name"] for x in daten["andere"]] == ["Vergleichsrunde"]
    assert "Runde B" not in html


# --------------------------------------------------------------------------- Kartenbild


def _kachelbild(farbe=(200, 220, 200)) -> bytes:
    puffer = io.BytesIO()
    Image.new("RGB", (256, 256), farbe).save(puffer, "PNG")
    return puffer.getvalue()


@pytest.fixture
def kacheln(monkeypatch):
    """Kartenkacheln ohne Netz: zählt die Abrufe und liefert einfarbige Bilder."""
    monkeypatch.setenv("FP_KARTEN_KACHELN", "https://kacheln.test/{z}/{x}/{y}.png")
    einstellungen.cache_clear()
    kb._cache.clear()
    abrufe = []

    def holen(url):
        abrufe.append(url)
        return _kachelbild()

    monkeypatch.setattr(kb, "_kachel_holen", holen)
    yield abrufe
    kb._cache.clear()
    monkeypatch.delenv("FP_KARTEN_KACHELN")
    einstellungen.cache_clear()


def test_kartenbild_zeichnet_strecke_und_posten(kacheln):
    a = NIEDERKASSEL
    b = (a[0] + 0.001, a[1] + 0.002)
    png = kb.kartenbild(a, [a, b], [(1, *a), (2, *b)], hervorgehoben=1, breite=600, hoehe=300)
    bild = Image.open(io.BytesIO(png)).convert("RGB")
    assert bild.size == (600, 300)
    assert bild.getpixel((300 - 22, 150)) == (245, 180, 0)  # hervorgehobener Posten in der Mitte, gelb
    assert any(bild.getpixel((x, y)) == kb.LINIENFARBE for x in range(300, 600) for y in range(0, 150))
    erste = len(kacheln)
    assert erste > 0 and all(u.startswith("https://kacheln.test/17/") for u in kacheln)
    kb.kartenbild(a, [], [(1, *a)], breite=600, hoehe=300)
    assert len(kacheln) == erste  # aus dem Zwischenspeicher


def test_kartenbild_ohne_kacheln_ergibt_none(kacheln, monkeypatch):
    def kaputt(url):
        raise OSError("kein Netz")

    monkeypatch.setattr(kb, "_kachel_holen", kaputt)
    assert kb.kartenbild(NIEDERKASSEL, [], [(1, *NIEDERKASSEL)]) is None


def test_kartenbild_abgeschaltet():
    assert einstellungen().karten_kacheln == ""
    assert kb.kartenbild(NIEDERKASSEL, [], [(1, *NIEDERKASSEL)]) is None


def _lauf_mit_vollen_posten(fabrik, schule, mit_ort=True, items=4) -> int:
    with fabrik.intern_kontext() as s:
        strecke = Strecke(schule_id=schule.schule, name="Kartenrunde",
                          verlauf={"modus": "trace", "wegpunkte": [], "linie": [[50.814, 7.04], [50.816, 7.045]]})
        for n in range(1, 4):
            p = Posten(name=f"Posten {n} – Kreuzung mit langem Namen {n}", position=n,
                       beschreibung="Steht auf dem Gehweg vor der Bäckerei, gut sichtbar für die Kinder.")
            if mit_ort:
                p.lat, p.lng = 50.814 + n * 0.0005, 7.04 + n * 0.001
            p.items = [
                Item(kurzbezeichnung=f"Punkt {k}", position=k,
                     beobachtungstext="Schaut das Kind deutlich über die linke Schulter nach hinten, bevor es losfährt?")
                for k in range(1, items + 1)
            ]
            strecke.posten.append(p)
        s.add(strecke)
        s.flush()
        lauf = Lauf(schule_id=schule.schule, strecke_id=strecke.id, gruppe_id=schule.gruppe, datum=s.get(Lauf, schule.lauf).datum.replace(year=2099))
        s.add(lauf)
        s.flush()
        from app.token import tokens_erzeugen

        tokens_erzeugen(lauf)
        return lauf.id


def _seiten(client, lauf_id) -> list:
    antwort = client.get(f"/verwaltung/laeufe/{lauf_id}/postenblaetter.pdf")
    assert antwort.status_code == 200
    return PdfReader(io.BytesIO(antwort.content)).pages


def test_postenblatt_mit_karte_bleibt_eine_seite(client, fabrik, schulen, kacheln):
    """Voller Posten (Beschreibung, vier Items mit zweizeiligem Text) plus Karte: eine Seite."""
    a, _ = schulen
    angemeldet(client, a.email)
    seiten = _seiten(client, _lauf_mit_vollen_posten(fabrik, a))
    assert len(seiten) == 3
    for seite in seiten:
        text = " ".join(seite.extract_text().split())
        assert "Dein Standort" in text
        assert "Punkt 4" in text and "Hinweise" in text
        assert len(seite.images) >= 1


@pytest.mark.parametrize("items", [2, 5, 6])
def test_karte_macht_blatt_nie_laenger(client, fabrik, schulen, kacheln, items):
    a, _ = schulen
    angemeldet(client, a.email)
    ohne = len(_seiten(client, _lauf_mit_vollen_posten(fabrik, a, mit_ort=False, items=items)))
    mit = len(_seiten(client, _lauf_mit_vollen_posten(fabrik, a, mit_ort=True, items=items)))
    assert mit <= ohne


def test_postenblatt_ohne_karte_wenn_kachelserver_ausfaellt(client, fabrik, schulen, kacheln, monkeypatch):
    def kaputt(url):
        raise OSError("kein Netz")

    monkeypatch.setattr(kb, "_kachel_holen", kaputt)
    a, _ = schulen
    lauf_id = _lauf_mit_vollen_posten(fabrik, a)
    angemeldet(client, a.email)
    antwort = client.get(f"/verwaltung/laeufe/{lauf_id}/postenblaetter.pdf")
    assert antwort.status_code == 200
    text = PdfReader(io.BytesIO(antwort.content)).pages[0].extract_text()
    assert "Dein Standort" not in text


# --------------------------------------------------------------------------- Im Browser


PNG_KACHEL = _kachelbild((230, 230, 225))


@pytest.fixture(scope="module")
def basis_url(engine):
    url, server, t = server_starten(engine)
    yield url
    server.should_exit = True
    t.join(5)


def test_posten_verorten_und_strecke_zeichnen_im_browser(fabrik, schulen, basis_url):
    """Leaflet läuft unter der strengen CSP; externe Dienste sind durch Attrappen ersetzt."""
    a, _ = schulen
    with fabrik.intern_kontext() as s:
        st = s.get(Strecke, a.strecke)
        st.posten.append(Posten(name="Zweiter Posten", position=2))
        # Startansicht: vorhandener Standort von Posten 1
        st.posten[0].lat, st.posten[0].lng = NIEDERKASSEL

    with playwright_api.sync_playwright() as pw:
        browser = pw.chromium.launch()
        seite = browser.new_page(viewport={"width": 1300, "height": 900})
        fehler = []
        seite.on("pageerror", lambda e: fehler.append(str(e)))
        seite.on("console", lambda m: fehler.append(m.text) if m.type == "error" else None)
        # Kacheln und Routing ohne Netz
        seite.route(re.compile(r"https://.*\.png.*"), lambda r: r.fulfill(body=PNG_KACHEL, content_type="image/png"))
        seite.route(re.compile(r"https://routing\.openstreetmap\.de/.*"), lambda r: r.fulfill(json={
            "routes": [{"geometry": {"coordinates": [[7.04, 50.814], [7.041, 50.815], [7.043, 50.815]]}}]}))

        seite.goto(basis_url + "/anmelden")
        seite.fill("input[name=email]", a.email)
        seite.fill("input[name=passwort]", "geheim-geheim")
        seite.click("button[type=submit]")
        seite.goto(f"{basis_url}/verwaltung/strecken/{a.strecke}/karte")
        playwright_api.expect(seite.locator(".posten-marke")).to_have_count(1)

        # Posten 2 ist automatisch gewählt (noch ohne Standort): Klick setzt ihn
        box = seite.locator("#karte").bounding_box()
        seite.mouse.click(box["x"] + box["width"] / 2 + 120, box["y"] + box["height"] / 2 + 60)
        playwright_api.expect(seite.locator(".posten-marke")).to_have_count(2)

        # Strecke über zwei Wegpunkte – Antwort der Routing-Attrappe wird übernommen
        seite.check("input[name=modus][value=route]")
        seite.mouse.click(box["x"] + 200, box["y"] + 200)
        seite.mouse.click(box["x"] + 500, box["y"] + 300)
        playwright_api.expect(seite.locator("#laenge")).not_to_have_text("–")
        seite.click("#speichern")
        playwright_api.expect(seite.locator(".meldung")).to_have_text("Gespeichert.")
        browser.close()
    assert not fehler, fehler

    with fabrik.intern_kontext() as s:
        st = s.get(Strecke, a.strecke)
        assert st.verlauf["modus"] == "route"
        assert st.verlauf["linie"] == [[50.814, 7.04], [50.815, 7.041], [50.815, 7.043]]
        assert len(st.verlauf["wegpunkte"]) == 2
        assert st.posten[1].lat is not None
        assert (st.posten[0].lat, st.posten[0].lng) == NIEDERKASSEL
