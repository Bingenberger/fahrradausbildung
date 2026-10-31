"""Bedientests des Posten-Prototyps (Schritt 2) mit Playwright.

Läuft in WebKit (die Engine von Safari auf dem iPad) mit iPad-Emulation,
im Übungsmodus /p/demo (Beispieldaten, ohne Server-Daten).
Geprüft werden die Abnahmekriterien 6 (Bedienzeit in Taps) und 7 (Lesbarkeit)
sowie die Erfassungsregeln aus Spezifikation 6.

Hinweis: Die strenge CSP (kein 'unsafe-eval') gilt auch für Playwright selbst.
Statt page.wait_for_function("…") deshalb expect(locator)… verwenden.
"""

from __future__ import annotations

import re
import socket
import threading
import time

import pytest
import uvicorn

playwright_api = pytest.importorskip("playwright.sync_api")
expect = playwright_api.expect

GERAETE = ["iPad (gen 7)", "iPad (gen 7) landscape"]


# --------------------------------------------------------------------------- Fixtures


def server_starten(engine):
    """Startet die echte Anwendung in einem Hintergrund-Thread. Liefert (url, server, thread)."""
    from app.main import erstelle_app
    from app.mandant import Sitzungsfabrik

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(erstelle_app(Sitzungsfabrik(engine)), host="127.0.0.1", port=port, log_level="warning")
    )
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    return f"http://127.0.0.1:{port}", server, t


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


@pytest.fixture(scope="module")
def browser(pw):
    b = pw.webkit.launch()
    yield b
    b.close()


@pytest.fixture(scope="module")
def geraete(pw):
    return pw.devices


@pytest.fixture
def seite(browser, geraete, basis_url):
    ctx = browser.new_context(**geraete[GERAETE[0]])
    page = ctx.new_page()
    page.fp_fehler = []
    page.on("pageerror", lambda e: page.fp_fehler.append(str(e)))
    page.add_init_script(
        "document.addEventListener('securitypolicyviolation',"
        " e => console.error('CSP', e.violatedDirective))"
    )
    page.on(
        "console",
        lambda m: m.type == "error" and m.text.startswith("CSP") and page.fp_fehler.append(m.text),
    )
    page.goto(f"{basis_url}/p/demo?zuruecksetzen")
    page.wait_for_selector("#einrichtung:not([hidden])")
    page.click("#start")
    page.wait_for_selector("#haupt:not([hidden])")
    yield page
    assert page.fp_fehler == []
    ctx.close()


def ereignisse(page) -> list[dict]:
    return page.evaluate(
        """() => new Promise((ok, fehler) => {
            const r = indexedDB.open('fahrradpruefung');
            r.onerror = () => fehler(r.error);
            r.onsuccess = () => {
                const q = r.result.transaction('ereignisse').objectStore('ereignisse').getAll();
                q.onsuccess = () => { r.result.close(); ok(q.result); };
            };
        })"""
    )


def gueltige_durchgaenge(page) -> list[dict]:
    """Jüngstes Ereignis je (startnummer, durchgang_nr), ohne Stornos."""
    neueste: dict[tuple, dict] = {}
    for e in ereignisse(page):
        if e["typ"] != "durchgang":
            continue
        k = (e["startnummer"], e["nutzlast"]["durchgang_nr"])
        if k not in neueste or (e["erfasst_am"], e["event_id"]) > (
            neueste[k]["erfasst_am"],
            neueste[k]["event_id"],
        ):
            neueste[k] = e
    return [e for e in neueste.values() if not e["nutzlast"].get("storniert")]


def nummer(page) -> int:
    return int(page.text_content("#nummer"))


def weiter(page):
    page.click("#weiter")
    page.wait_for_timeout(750)  # Doppeltipp-Sperre abwarten


def item(page, name):
    return page.locator(".item", has_text=name)


# --------------------------------------------------------------------------- Bedienzeit (11.6)


def test_standarderfassung_ist_ein_tap(seite):
    assert nummer(seite) == 1
    seite.click("#weiter")  # der einzige Tap
    expect(seite.locator("#nummer")).to_have_text("2")
    [e] = ereignisse(seite)
    assert e["typ"] == "durchgang"
    assert e["startnummer"] == 1
    assert e["nutzlast"] == {"durchgang_nr": 1, "fehlende_items": []}
    assert e["uebertragen"] == 0


def test_zwei_vergessene_items_sind_drei_taps(seite):
    item(seite, "Handzeichen").click()
    item(seite, "Bremsbereitschaft").click()
    assert item(seite, "Handzeichen").get_attribute("aria-pressed") == "true"
    seite.click("#weiter")
    expect(seite.locator("#nummer")).to_have_text("2")
    [e] = ereignisse(seite)
    assert e["nutzlast"]["fehlende_items"] == [12, 15]  # Item-IDs, in Positionsreihenfolge
    # Nach dem Speichern ist alles wieder auf „erfüllt"
    assert seite.locator('.item[aria-pressed="true"]').count() == 0


def test_event_id_ist_uuid4(seite):
    weiter(seite)
    [e] = ereignisse(seite)
    import uuid

    assert uuid.UUID(e["event_id"]).version == 4


# --------------------------------------------------------------------------- Reihenfolge und Durchgänge


def test_nach_der_letzten_nummer_beginnt_der_naechste_durchgang(seite):
    for _ in range(24):
        seite.click("#weiter")
        seite.wait_for_timeout(720)
    assert nummer(seite) == 1
    assert seite.text_content("#durchgang") == "Durchgang 2"
    assert len(gueltige_durchgaenge(seite)) == 24


def test_doppeltipp_erzeugt_nur_eine_erfassung(seite):
    seite.click("#weiter")
    seite.click("#weiter")
    seite.wait_for_timeout(300)
    assert len(ereignisse(seite)) == 1
    assert nummer(seite) == 2


def test_ueberspringen_erfasst_nichts(seite):
    seite.click("#ueberspringen")
    assert nummer(seite) == 2
    assert ereignisse(seite) == []


def test_andere_nummer_ueber_raster(seite):
    seite.click("#andere-nummer")
    raster = seite.locator("#nummernwahl-raster .zelle")
    assert raster.count() == 24
    seite.locator("#nummernwahl-raster .zelle", has_text="17").first.click()
    assert seite.is_hidden("#nummernwahl")
    assert nummer(seite) == 17
    weiter(seite)
    assert ereignisse(seite)[0]["startnummer"] == 17
    assert nummer(seite) == 18


def test_markierungen_bleiben_beim_nummernwechsel(seite):
    """Die Beobachtung gehört zum Kind – nur die Nummer war falsch."""
    item(seite, "Schulterblick").click()
    seite.click("#andere-nummer")
    seite.locator("#nummernwahl-raster .zelle", has_text="5").first.click()
    assert item(seite, "Schulterblick").get_attribute("aria-pressed") == "true"


def test_durchgang_wird_pro_kind_gezaehlt(seite):
    weiter(seite)  # Nr. 1, Durchgang 1
    seite.click("#andere-nummer")
    seite.locator("#nummernwahl-raster .zelle", has_text="1").first.click()
    assert seite.text_content("#durchgang") == "Durchgang 2"
    weiter(seite)
    schluessel = sorted(
        (e["startnummer"], e["nutzlast"]["durchgang_nr"]) for e in gueltige_durchgaenge(seite)
    )
    assert schluessel == [(1, 1), (1, 2)]


# --------------------------------------------------------------------------- Rückgängig


def test_rueckgaengig_ist_neues_ereignis_keine_loeschung(seite):
    item(seite, "Einordnen").click()
    weiter(seite)
    assert seite.is_visible("#rueckgaengig-knopf")
    seite.click("#rueckgaengig-knopf")
    expect(seite.locator("#nummer")).to_have_text("1")

    alle = ereignisse(seite)
    assert len(alle) == 2  # nichts gelöscht
    assert gueltige_durchgaenge(seite) == []  # aber storniert
    # Zustand vor der Erfassung ist wiederhergestellt
    assert item(seite, "Einordnen").get_attribute("aria-pressed") == "true"
    assert seite.is_hidden("#rueckgaengig-inhalt")

    # Korrigiert erneut erfassen: gleicher Schlüssel, jüngeres Ereignis gewinnt
    item(seite, "Einordnen").click()
    weiter(seite)
    [e] = gueltige_durchgaenge(seite)
    assert e["nutzlast"] == {"durchgang_nr": 1, "fehlende_items": []}


def test_rueckgaengig_verschwindet_nach_zehn_sekunden(seite):
    seite.clock.install()
    weiter(seite)
    assert seite.is_visible("#rueckgaengig-knopf")
    seite.clock.run_for(10_500)
    assert seite.is_hidden("#rueckgaengig-inhalt")


# --------------------------------------------------------------------------- Fahrsicherheit


def test_fahrsicherheit_ist_jederzeit_ueberschreibbar(seite):
    seite.click("#reiter-sicherheit")
    zelle = seite.locator("#sicherheit-raster .zelle", has_text="3").first
    assert "offen" in zelle.text_content()
    zelle.click()
    seite.fill("#bewertung-bemerkung", "fährt sehr dicht am Bordstein")
    seite.click("#bewertung-stufen .stufe-3")
    seite.click("#bewertung-fertig")
    assert "unsicher" in seite.locator("#sicherheit-raster .zelle", has_text="3").first.text_content()

    seite.locator("#sicherheit-raster .zelle", has_text="3").first.click()
    assert seite.input_value("#bewertung-bemerkung") == "fährt sehr dicht am Bordstein"
    seite.click("#bewertung-stufen .stufe-1")
    seite.click("#bewertung-fertig")
    zelle = seite.locator("#sicherheit-raster .zelle", has_text="3").first
    assert "sicher" in zelle.text_content() and "unsicher" not in zelle.text_content()

    sicherheit = [e for e in ereignisse(seite) if e["typ"] == "sicherheit"]
    assert len(sicherheit) == 2
    assert {e["nutzlast"]["stufe"] for e in sicherheit} == {1, 3}
    assert all(e["nutzlast"]["bemerkung"] == "fährt sehr dicht am Bordstein" for e in sicherheit)


def test_bemerkung_ohne_stufe_wird_nicht_verworfen(seite):
    seite.click("#reiter-sicherheit")
    seite.locator("#sicherheit-raster .zelle", has_text="4").first.click()
    seite.fill("#bewertung-bemerkung", "bremst spät")
    seite.click("#bewertung-fertig")
    assert seite.is_visible("#bewertung")
    assert "zuerst" in seite.text_content("#bewertung-meldung")


# --------------------------------------------------------------------------- Neustart


def test_daten_und_position_ueberstehen_neustart(seite):
    weiter(seite)
    weiter(seite)
    seite.reload()
    seite.wait_for_selector("#haupt:not([hidden])")  # keine erneute Einrichtung
    assert nummer(seite) == 3
    assert len(ereignisse(seite)) == 2
    assert "2 Erfassungen" in seite.text_content("#status-zaehler")


# --------------------------------------------------------------------------- Lesbarkeit (11.7)

LESBARKEIT_JS = """() => {
  const rgba = (s) => { const m = s.match(/[\\d.]+/g).map(Number); return [m[0], m[1], m[2], m[3] ?? 1]; };
  const lum = ([r, g, b]) => {
    const f = (c) => { c /= 255; return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4; };
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
  };
  const kontrast = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };
  const sichtbar = (el) => {
    for (let e = el; e; e = e.parentElement) {
      const s = getComputedStyle(e);
      if (s.display === 'none' || s.visibility === 'hidden' || Number(s.opacity) === 0) return false;
    }
    return el.getClientRects().length > 0;
  };
  const hintergrund = (el) => {
    for (let e = el; e; e = e.parentElement) {
      const c = rgba(getComputedStyle(e).backgroundColor);
      if (c[3] > 0) return c;
    }
    return [255, 255, 255, 1];
  };
  const probleme = [];
  for (const el of document.querySelectorAll('body *')) {
    const text = [...el.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent.trim()).join('');
    if (!text || !sichtbar(el)) continue;
    const s = getComputedStyle(el);
    const groesse = parseFloat(s.fontSize);
    const k = kontrast(rgba(s.color), hintergrund(el));
    if (groesse < 16) probleme.push(`${text.slice(0, 30)}: ${groesse}px`);
    if (k < 7) probleme.push(`${text.slice(0, 30)}: Kontrast ${k.toFixed(2)}`);
  }
  return probleme;
}"""


def _lesbar(page):
    page.wait_for_timeout(700)  # Rückmeldungs-Blitz ausblenden lassen
    assert page.evaluate(LESBARKEIT_JS) == []


@pytest.mark.parametrize("geraet", GERAETE)
def test_lesbarkeit_aller_ansichten(browser, geraete, basis_url, geraet):
    ctx = browser.new_context(**geraete[geraet])
    page = ctx.new_page()
    page.goto(f"{basis_url}/p/demo?zuruecksetzen")
    page.wait_for_selector("#einrichtung:not([hidden])")
    _lesbar(page)
    page.click("#start")
    item(page, "Handzeichen").click()
    _lesbar(page)  # inkl. rot markiertem Item
    page.click("#weiter")
    _lesbar(page)  # inkl. Rückgängig-Leiste
    page.click("#andere-nummer")
    _lesbar(page)
    page.click("#nummernwahl-abbrechen")
    page.click("#reiter-sicherheit")
    for stufe in (1, 2, 3):
        page.locator("#sicherheit-raster .zelle").nth(stufe).click()
        page.click(f"#bewertung-stufen .stufe-{stufe}")
        _lesbar(page)
        page.click("#bewertung-fertig")
    _lesbar(page)  # Raster mit allen drei Stufen
    page.click("#reiter-erfassung")
    page.evaluate("dispatchEvent(new Event('offline'))")
    _lesbar(page)
    ctx.close()


@pytest.mark.parametrize("geraet", GERAETE)
def test_groessen_der_bedienelemente(browser, geraete, basis_url, geraet):
    ctx = browser.new_context(**geraete[geraet])
    page = ctx.new_page()
    page.goto(f"{basis_url}/p/demo?zuruecksetzen")
    page.click("#start")
    groesse = page.evaluate("parseFloat(getComputedStyle(document.getElementById('nummer')).fontSize)")
    assert groesse >= 120
    for i in range(page.locator(".item").count()):
        box = page.locator(".item").nth(i).bounding_box()
        assert box["height"] >= 64
    # Alles Wesentliche ohne Scrollen sichtbar
    hoehe = page.viewport_size["height"]
    for sel in ("#nummer", "#weiter", "#andere-nummer", "#ueberspringen", ".item >> nth=-1"):
        box = page.locator(sel).bounding_box()
        assert box["y"] + box["height"] <= hoehe, sel
    ctx.close()


# --------------------------------------------------------------------------- Rahmen


def test_keine_links_nach_aussen(seite):
    assert seite.locator("a").count() == 0
    assert seite.locator("form").count() == 0


def test_manifest_standalone(seite, basis_url):
    import json
    import urllib.request

    with urllib.request.urlopen(f"{basis_url}/p/demo/manifest.webmanifest") as r:
        manifest = json.load(r)
    assert manifest["display"] == "standalone"  # nicht minimal-ui (Spezifikation 4.3)
    assert manifest["start_url"] == "/p/demo"
    assert seite.locator('link[rel="manifest"]').get_attribute("href") == "/p/demo/manifest.webmanifest"


def test_strenge_csp(basis_url):
    import urllib.request

    with urllib.request.urlopen(f"{basis_url}/p/demo") as r:
        csp = r.headers["Content-Security-Policy"]
    assert "unsafe-inline" not in csp and "unsafe-eval" not in csp
    assert "script-src 'self'" in csp


def test_lesbarkeitspruefung_erkennt_verstoesse(seite):
    """Gegenprobe: Die Prüfung oben würde schlechte Elemente tatsächlich finden."""
    seite.evaluate(
        """() => {
            const el = document.createElement('p');
            el.textContent = 'zu klein und zu blass';
            el.style.fontSize = '12px';
            el.style.color = '#999999';
            document.getElementById('ansicht-erfassung').append(el);
        }"""
    )
    probleme = seite.evaluate(LESBARKEIT_JS)
    assert any("12px" in p for p in probleme)
    assert any("Kontrast" in p for p in probleme)


# --------------------------------------------------------------------------- Display wachhalten


# Attrappe der Screen Wake Lock API: WebKit im Test hat sie nicht, und der
# Energiesparmodus eines echten iPads lässt sich hier ohnehin nicht herstellen.
WAKE_ATTRAPPE = """
window.__wake = { angefordert: 0, freigegeben: 0, ablehnen: false, letzte: null };
Object.defineProperty(navigator, "wakeLock", {
  configurable: true,
  value: {
    request: async (typ) => {
      window.__wake.angefordert++;
      if (window.__wake.ablehnen) throw new DOMException("Energiesparmodus", "NotAllowedError");
      const ziel = new EventTarget();
      const sperre = {
        type: typ,
        released: false,
        addEventListener: (...a) => ziel.addEventListener(...a),
        removeEventListener: (...a) => ziel.removeEventListener(...a),
        release: async () => {
          window.__wake.freigegeben++;
          sperre.released = true;
          ziel.dispatchEvent(new Event("release"));
        },
      };
      window.__wake.letzte = sperre;
      return sperre;
    },
  },
});
"""

OHNE_WAKE = """
Object.defineProperty(navigator, "wakeLock", { configurable: true, get: () => undefined });
"""


@pytest.fixture
def wach_seite(browser, geraete, basis_url):
    """Seite mit frei wählbarer Wake-Lock-Attrappe, noch vor „Prüfung starten“."""

    kontexte = []

    def oeffnen(skript: str):
        ctx = browser.new_context(**geraete[GERAETE[0]])
        kontexte.append(ctx)
        page = ctx.new_page()
        page.fp_fehler = []
        page.on("pageerror", lambda e: page.fp_fehler.append(str(e)))
        page.add_init_script(skript)
        page.goto(f"{basis_url}/p/demo?zuruecksetzen")
        page.wait_for_selector("#einrichtung:not([hidden])")
        return page

    yield oeffnen
    for ctx in kontexte:
        ctx.close()


def test_display_bleibt_waehrend_der_erfassung_an(wach_seite):
    """Ohne Wake Lock müsste die Aufsicht vor jedem Kind erst entsperren."""
    page = wach_seite(WAKE_ATTRAPPE)
    expect(page.locator("#einrichtung-wach")).to_have_text("Das Display bleibt während der Prüfung an.")
    assert page.evaluate("() => window.__wake.angefordert") == 0  # erst beim Erfassen

    page.click("#start")
    page.wait_for_selector("#haupt:not([hidden])")
    expect(page.locator("#status-zaehler")).not_to_contain_text("Display")
    assert page.evaluate("() => window.__wake.angefordert") == 1
    assert page.evaluate("() => window.__wake.letzte.type") == "screen"
    assert page.fp_fehler == []


def test_wake_lock_wird_nach_dem_wegschalten_neu_angefordert(wach_seite):
    """Das System gibt die Sperre beim Wegtippen frei – sonst wäre sie dann weg."""
    page = wach_seite(WAKE_ATTRAPPE)
    page.click("#start")
    page.wait_for_selector("#haupt:not([hidden])")

    # App war im Hintergrund: System gibt frei, beim Zurückkommen neu anfordern
    page.evaluate("() => window.__wake.letzte.release()")
    page.evaluate("() => document.dispatchEvent(new Event('visibilitychange'))")
    page.wait_for_timeout(200)
    assert page.evaluate("() => window.__wake.angefordert") == 2
    assert page.fp_fehler == []


def test_abgelehnte_sperre_wird_in_der_statuszeile_gesagt(wach_seite):
    """Energiesparmodus: Die Aufsicht soll es wissen, die Erfassung läuft weiter."""
    page = wach_seite(WAKE_ATTRAPPE + "window.__wake.ablehnen = true;")
    page.click("#start")
    page.wait_for_selector("#haupt:not([hidden])")
    expect(page.locator("#status-zaehler")).to_contain_text("Display sperrt sich")
    expect(page.locator("#status-zaehler")).to_have_class(re.compile("warnung"))
    # Erfassen geht trotzdem
    page.click("#weiter")
    page.wait_for_timeout(750)
    assert gueltige_durchgaenge(page)
    assert page.fp_fehler == []


def test_altes_geraet_ohne_wake_lock_bekommt_die_einstellung_gesagt(wach_seite):
    page = wach_seite(OHNE_WAKE)
    expect(page.locator("#einrichtung-wach")).to_contain_text("Automatische Sperre")
    page.click("#start")
    page.wait_for_selector("#haupt:not([hidden])")
    # Kein Hinweis in der Statuszeile: Dort wäre er bei jedem Kind im Weg,
    # und ändern lässt sich daran am Posten nichts mehr.
    expect(page.locator("#status-zaehler")).not_to_contain_text("Display")
    assert page.fp_fehler == []
