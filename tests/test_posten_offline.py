"""Offline-Strecke der Posten-App mit echtem Browser (Abnahmekriterien 1, 3, 5).

Jeder Test benutzt ein persistentes Browserprofil: „App schließen und neu
öffnen" ist hier ein vollständiger Neustart des Browsers – Service Worker,
Cache und IndexedDB müssen das überstehen.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import select

from app.modelle import Ereignis, Gruppe, Item, Kind, Lauf, Posten, PostenToken, Strecke
from app.sicherheit import neues_token
from app.token import token_ablauf
from tests.test_posten_frontend import server_starten

playwright_api = pytest.importorskip("playwright.sync_api")
expect = playwright_api.expect

BROWSER = ["chromium", "webkit"]
GERAET = "iPad (gen 7)"
BEREIT = "✓ offline einsatzbereit"


# --------------------------------------------------------------------------- Fixtures


@pytest.fixture(scope="module")
def basis_url(engine):
    url, server, t = server_starten(engine)
    yield url
    server.should_exit = True
    t.join(5)


@pytest.fixture(scope="module")
def pw():
    with playwright_api.sync_playwright() as p:
        yield p


@pytest.fixture
def lauf(fabrik, schulen):
    """Lauf mit 12 Kindern und zwei Posten (je ein Token)."""
    a, _ = schulen
    with fabrik.intern_kontext() as s:
        strecke = Strecke(schule_id=a.schule, name="Offline-Runde")
        for nr, name in ((1, "Posten Nord"), (2, "Posten Süd")):
            p = Posten(name=name, position=nr)
            p.items = [Item(kurzbezeichnung=k, position=i) for i, k in enumerate(["Schulterblick", "Handzeichen", "Einordnen"], 1)]
            strecke.posten.append(p)
        gruppe = Gruppe(schule_id=a.schule, name="Offline-Gruppe", schuljahr="2026/27")
        for n in range(1, 13):
            gruppe.kinder.append(Kind(startnummer=n))
        s.add_all([strecke, gruppe])
        s.flush()
        lauf = Lauf(schule_id=a.schule, strecke_id=strecke.id, gruppe_id=gruppe.id, datum=date.today())
        s.add(lauf)
        s.flush()
        tokens = []
        for p in strecke.posten:
            t = PostenToken(lauf_id=lauf.id, posten_id=p.id, token=neues_token(), gueltig_bis=token_ablauf(lauf.datum))
            s.add(t)
            tokens.append(t.token)
        s.flush()
        return {"lauf_id": lauf.id, "tokens": tokens, "namen": ["Offline-Gruppe", "Grundschule A"]}


class Geraet:
    """Ein „iPad" mit persistentem Profil, das sich vollständig neu starten lässt."""

    def __init__(self, pw, browser_typ: str, profil, basis_url: str):
        self.typ = getattr(pw, browser_typ)
        self.optionen = {k: v for k, v in pw.devices[GERAET].items() if k != "default_browser_type"}
        self.profil = str(profil)
        self.basis_url = basis_url
        self.ctx = None
        self.seite = None
        self.antworten: list[str] = []

    def starten(self, pfad: str, offline: bool = False):
        self.ctx = self.typ.launch_persistent_context(self.profil, **self.optionen)
        if offline:
            self.ctx.set_offline(True)
        self.seite = self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()
        self.seite.on("response", self._antwort_merken)
        self.seite.goto(self.basis_url + pfad)
        return self.seite

    def _antwort_merken(self, antwort):
        if "/api/" in antwort.url:
            try:
                self.antworten.append(antwort.text())
            except Exception:  # noqa: BLE001 – abgebrochene Antworten haben keinen Körper
                pass

    def beenden(self):
        self.ctx.close()

    def offline(self, wert: bool):
        self.ctx.set_offline(wert)

    def indexeddb(self) -> dict:
        return self.seite.evaluate(
            """() => new Promise((ok, fehler) => {
                const r = indexedDB.open('fahrradpruefung');
                r.onerror = () => fehler(r.error);
                r.onsuccess = async () => {
                    const db = r.result, inhalt = {};
                    for (const name of db.objectStoreNames) {
                        inhalt[name] = await new Promise(res => {
                            const tx = db.transaction(name);
                            const alle = tx.objectStore(name).getAll();
                            const schluessel = tx.objectStore(name).getAllKeys();
                            tx.oncomplete = () => res({werte: alle.result, schluessel: schluessel.result});
                        });
                    }
                    db.close();
                    ok(inhalt);
                };
            })"""
        )


def erfassen(seite, anzahl: int, mit_items_jede: int = 4):
    for i in range(anzahl):
        if i % mit_items_jede == 0:
            seite.locator(".item").nth(i % 3).click()
        seite.click("#weiter")
        seite.wait_for_timeout(720)  # Doppeltipp-Sperre


def server_ereignisse(fabrik, lauf_id) -> dict[str, Ereignis]:
    with fabrik.intern_kontext() as s:
        return {str(e.event_id): e for e in s.execute(select(Ereignis).where(Ereignis.lauf_id == lauf_id)).scalars()}


def einrichten(geraet: Geraet, token: str):
    seite = geraet.starten(f"/p/{token}")
    expect(seite.locator("#einrichtung-offline")).to_have_text(BEREIT, timeout=30_000)
    seite.click("#start")
    expect(seite.locator("#haupt")).to_be_visible()
    return seite


# --------------------------------------------------------------------------- Abnahmekriterium 1


@pytest.mark.parametrize("browser_typ", BROWSER)
def test_flugmodus_mit_neustart(pw, basis_url, fabrik, lauf, tmp_path, browser_typ):
    """Einrichten im WLAN, Flugmodus, 50 Erfassungen mit komplettem Neustart, Wiederverbindung."""
    geraet = Geraet(pw, browser_typ, tmp_path / "profil", basis_url)
    token = lauf["tokens"][0]
    seite = einrichten(geraet, token)

    geraet.offline(True)
    erfassen(seite, 25)
    expect(seite.locator("#status-zaehler")).to_contain_text("25 Erfassungen · nicht übertragen")
    expect(seite.locator("#status-netz")).to_have_text("offline")
    geraet.beenden()

    # App komplett schließen und offline wieder öffnen
    seite = geraet.starten(f"/p/{token}", offline=True)
    expect(seite.locator("#haupt")).to_be_visible(timeout=15_000)
    expect(seite.locator("#status-zaehler")).to_contain_text("25 Erfassungen · nicht übertragen")
    erfassen(seite, 25)
    expect(seite.locator("#status-zaehler")).to_contain_text("50 Erfassungen · nicht übertragen")
    assert server_ereignisse(fabrik, lauf["lauf_id"]) == {}  # nichts ging ins Netz

    lokal = geraet.indexeddb()["ereignisse"]["werte"]
    assert len(lokal) == 50

    # Wiederverbindung: automatischer Upload
    geraet.offline(False)
    expect(seite.locator("#status-zaehler")).to_have_text("0 · alles übertragen", timeout=30_000)

    server = server_ereignisse(fabrik, lauf["lauf_id"])
    assert set(server) == {e["event_id"] for e in lokal}
    for e in lokal:
        s = server[e["event_id"]]
        assert (s.startnummer, s.typ, s.nutzlast) == (e["startnummer"], e["typ"], e["nutzlast"])
    assert all(e["uebertragen"] == 1 for e in geraet.indexeddb()["ereignisse"]["werte"])
    geraet.beenden()


# --------------------------------------------------------------------------- Abnahmekriterium 3


def test_abgebrochener_upload(pw, basis_url, fabrik, lauf, tmp_path):
    """Der Server speichert, die Antwort geht verloren; der zweite Versuch doppelt nichts.

    Nur Chromium: Playwright kann in WebKit keine Anfragen abfangen, solange ein
    Service Worker die Seite kontrolliert. Der Upload-Code ist für beide Browser
    derselbe; die Idempotenz prüft zusätzlich tests/test_posten_api.py.
    """
    geraet = Geraet(pw, "chromium", tmp_path / "profil", basis_url)
    seite = einrichten(geraet, lauf["tokens"][0])
    geraet.offline(True)
    erfassen(seite, 10)

    versuche = []

    def abbrechen(route):
        versuche.append(1)
        if len(versuche) == 1:
            route.fetch()  # Server verarbeitet den Stapel …
            route.abort("connectionreset")  # … aber die Antwort kommt nie an
        else:
            route.continue_()

    geraet.ctx.route("**/api/p/*/events", abbrechen)
    geraet.offline(False)
    seite.wait_for_timeout(1500)
    assert len(versuche) >= 1
    # Server hat alles, das Gerät weiß es noch nicht
    assert len(server_ereignisse(fabrik, lauf["lauf_id"])) == 10
    expect(seite.locator("#status-zaehler")).to_contain_text("10 Erfassungen · nicht übertragen")

    seite.click("#uebertragen")
    expect(seite.locator("#status-zaehler")).to_have_text("0 · alles übertragen", timeout=15_000)
    assert len(versuche) == 2
    assert len(server_ereignisse(fabrik, lauf["lauf_id"])) == 10
    geraet.beenden()


# --------------------------------------------------------------------------- Abnahmekriterium 5


def test_keine_namen_auf_dem_geraet(pw, basis_url, fabrik, lauf, tmp_path):
    """IndexedDB, API-Antworten und Seiteninhalt enthalten weder Gruppe noch Schule (Kindernamen gibt es nicht)."""
    geraet = Geraet(pw, "chromium", tmp_path / "profil", basis_url)
    seite = einrichten(geraet, lauf["tokens"][0])
    erfassen(seite, 6)
    seite.click("#reiter-sicherheit")
    seite.locator("#sicherheit-raster .zelle").first.click()
    seite.fill("#bewertung-bemerkung", "bremst spät")
    seite.click("#bewertung-stufen .stufe-2")
    seite.click("#bewertung-fertig")
    seite.click("#uebertragen")
    expect(seite.locator("#status-zaehler")).to_have_text("0 · alles übertragen", timeout=15_000)

    inhalt = json.dumps(geraet.indexeddb(), ensure_ascii=False)
    assert '"startnummern"' in inhalt and "bremst spät" in inhalt  # Gegenprobe: Daten sind da
    texte = [inhalt, seite.content(), *geraet.antworten]
    assert any("akzeptiert" in t for t in geraet.antworten)
    for text in texte:
        for name in lauf["namen"]:
            assert name not in text
    geraet.beenden()


# --------------------------------------------------------------------------- Rücklauf und Abschluss


def test_nach_abschluss_werden_lokale_daten_geloescht(pw, basis_url, fabrik, lauf, tmp_path):
    geraet = Geraet(pw, "chromium", tmp_path / "profil", basis_url)
    seite = einrichten(geraet, lauf["tokens"][0])
    erfassen(seite, 3)
    seite.click("#uebertragen")
    expect(seite.locator("#status-zaehler")).to_have_text("0 · alles übertragen", timeout=15_000)
    assert len(geraet.indexeddb()["ereignisse"]["werte"]) == 3  # noch nicht löschen: Lauf läuft

    with fabrik.intern_kontext() as s:
        l = s.get(Lauf, lauf["lauf_id"])
        l.status = "abgeschlossen"
        for t in l.tokens:
            t.gueltig_bis = datetime.now(UTC)
    seite.click("#uebertragen")
    expect(seite.locator("#fertig")).to_be_visible(timeout=15_000)
    db = geraet.indexeddb()
    assert db["ereignisse"]["werte"] == [] and db["konfig"]["werte"] == []
    assert len(server_ereignisse(fabrik, lauf["lauf_id"])) == 3
    geraet.beenden()


def test_offene_daten_bleiben_wenn_lauf_zu_frueh_abgeschlossen(pw, basis_url, fabrik, lauf, tmp_path):
    geraet = Geraet(pw, "chromium", tmp_path / "profil", basis_url)
    seite = einrichten(geraet, lauf["tokens"][0])
    geraet.offline(True)
    erfassen(seite, 4)
    with fabrik.intern_kontext() as s:
        s.get(Lauf, lauf["lauf_id"]).status = "abgeschlossen"
    geraet.offline(False)
    seite.click("#uebertragen")
    expect(seite.locator("#status-zaehler")).to_contain_text("Zugang ungültig", timeout=15_000)
    assert len(geraet.indexeddb()["ereignisse"]["werte"]) == 4  # nichts verloren
    geraet.beenden()

    # Neustart mit geschlossenem Lauf: App startet trotzdem mit den Daten
    seite = geraet.starten(f"/p/{lauf['tokens'][0]}")
    expect(seite.locator("#haupt")).to_be_visible(timeout=15_000)
    expect(seite.locator("#status-zaehler")).to_contain_text("4 Erfassungen · nicht übertragen")

    # Lehrkraft öffnet den Lauf wieder → Daten kommen an
    with fabrik.intern_kontext() as s:
        s.get(Lauf, lauf["lauf_id"]).status = "laufend"
    seite.click("#uebertragen")
    expect(seite.locator("#status-zaehler")).to_have_text("0 · alles übertragen", timeout=15_000)
    assert len(server_ereignisse(fabrik, lauf["lauf_id"])) == 4
    geraet.beenden()


def test_geraetewechsel_uebertraegt_zuerst_alte_daten(pw, basis_url, fabrik, lauf, tmp_path):
    """Ein iPad wechselt den Posten: Offene Daten des alten Postens gehen nicht verloren."""
    geraet = Geraet(pw, "chromium", tmp_path / "profil", basis_url)
    seite = einrichten(geraet, lauf["tokens"][0])
    geraet.offline(True)
    erfassen(seite, 5)
    geraet.beenden()

    # Offline: Wechsel wird verweigert, Daten bleiben
    seite = geraet.starten(f"/p/{lauf['tokens'][1]}", offline=True)
    expect(seite.locator("#fehler")).to_be_visible(timeout=15_000)
    expect(seite.locator("#fehler-text")).to_contain_text("5 nicht übertragene Erfassungen")
    geraet.beenden()

    # Online: erst hochladen, dann wechseln
    seite = geraet.starten(f"/p/{lauf['tokens'][1]}")
    expect(seite.locator("#einrichtung-posten")).to_have_text("Posten Süd", timeout=15_000)
    with fabrik.intern_kontext() as s:
        posten = {p.id: p.name for p in s.get(Lauf, lauf["lauf_id"]).strecke.posten}
    server = server_ereignisse(fabrik, lauf["lauf_id"])
    assert len(server) == 5 and {posten[e.posten_id] for e in server.values()} == {"Posten Nord"}
    geraet.beenden()


def test_ungueltiger_zugang(pw, basis_url, tmp_path):
    geraet = Geraet(pw, "chromium", tmp_path / "profil", basis_url)
    seite = geraet.starten("/p/" + "x" * 43)
    expect(seite.locator("#fehler-text")).to_contain_text("ungültig oder abgelaufen", timeout=15_000)
    geraet.beenden()


def test_uebungsmodus_offline(pw, basis_url, tmp_path):
    """/p/demo funktioniert ebenfalls offline und überträgt nichts."""
    geraet = Geraet(pw, "chromium", tmp_path / "profil", basis_url)
    seite = einrichten(geraet, "demo")
    geraet.beenden()
    seite = geraet.starten("/p/demo", offline=True)
    expect(seite.locator("#haupt")).to_be_visible(timeout=15_000)
    assert seite.is_hidden("#uebertragen")
    erfassen(seite, 2)
    expect(seite.locator("#status-zaehler")).to_contain_text("Übungsmodus")
    geraet.beenden()


def test_versehentlicher_wechsel_offline_behaelt_alten_posten(pw, basis_url, fabrik, lauf, tmp_path):
    """Alles übertragen, dann offline die Adresse eines anderen Postens geöffnet: alter Posten bleibt nutzbar."""
    geraet = Geraet(pw, "chromium", tmp_path / "profil", basis_url)
    seite = einrichten(geraet, lauf["tokens"][0])
    erfassen(seite, 2)
    seite.click("#uebertragen")
    expect(seite.locator("#status-zaehler")).to_have_text("0 · alles übertragen", timeout=15_000)
    geraet.beenden()

    seite = geraet.starten(f"/p/{lauf['tokens'][1]}", offline=True)
    expect(seite.locator("#fehler-text")).to_contain_text("für „Posten Nord“ eingerichtet", timeout=15_000)
    geraet.beenden()

    seite = geraet.starten(f"/p/{lauf['tokens'][0]}", offline=True)
    expect(seite.locator("#haupt")).to_be_visible(timeout=15_000)
    expect(seite.locator("#status-posten")).to_have_text("Posten Nord")
    geraet.beenden()
