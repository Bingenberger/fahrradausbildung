"""Oberfläche: Symbole, Vorlagen, Bedienbarkeit.

Die Gestaltung trägt hier Bedeutung – ein fehlendes Symbol oder eine Vorlage,
die sich nicht mehr übersetzen lässt, fällt sonst erst im Browser auf.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from jinja2 import TemplateSyntaxError

from app.modelle import Benutzer, Schule
from app.sicherheit import passwort_hashen
from app.web.symbole import SYMBOLE, UnbekanntesSymbol, symbol
from app.web.vorlagen import VORLAGEN, templates
from tests.conftest import PASSWORT, angemeldet

# symbol("x") in der Vorlage, sym="x" als Argument der Makros in _makros.html
SYMBOLAUFRUF = re.compile(r'(?:symbol\(\s*|sym\s*=\s*)"([a-z0-9-]+)"')


def _verwendete_symbole() -> set[str]:
    namen: set[str] = set()
    for datei in VORLAGEN.rglob("*.html"):
        namen |= set(SYMBOLAUFRUF.findall(datei.read_text()))
    return namen


def _vorhandene_symbole() -> set[str]:
    return {p.stem for p in SYMBOLE.glob("*.svg")}


# --------------------------------------------------------------------------- Symbole


def test_jedes_verwendete_symbol_liegt_lokal_vor():
    """Phosphor-Symbole kommen aus dem Projekt, nicht aus dem Netz."""
    fehlend = _verwendete_symbole() - _vorhandene_symbole()
    assert not fehlend, f"Symboldateien fehlen: {sorted(fehlend)}"


def test_keine_unbenutzten_symboldateien():
    """Der Vendor-Ordner bleibt klein: nur, was die Vorlagen wirklich zeigen."""
    ueberfluessig = _vorhandene_symbole() - _verwendete_symbole()
    assert not ueberfluessig, f"Nicht mehr verwendet: {sorted(ueberfluessig)}"


def test_lizenz_liegt_bei():
    assert (SYMBOLE.parent / "LICENSE").is_file()
    assert "MIT" in (SYMBOLE.parent / "LICENSE").read_text()


def test_symbol_ist_inline_svg_und_erbt_textfarbe():
    s = str(symbol("bicycle"))
    assert s.startswith('<svg class="symbol"') and s.endswith("</svg>")
    assert 'fill="currentColor"' in s  # nimmt die Farbe des Knopfes an
    assert 'aria-hidden="true"' in s and 'focusable="false"' in s
    assert "width=" not in s and "height=" not in s  # Größe kommt aus dem CSS
    assert "<script" not in s
    assert 'class="symbol symbol-gross"' in str(symbol("bicycle", "symbol-gross"))


@pytest.mark.parametrize("name", ["gibtsnicht", "../../../etc/passwd", "Plus", "", "plus.svg"])
def test_unbekanntes_symbol_faellt_auf(name):
    """Lieber ein lauter Fehler als ein stilles Loch in der Oberfläche."""
    with pytest.raises(UnbekanntesSymbol):
        symbol(name)


# --------------------------------------------------------------------------- Vorlagen


@pytest.mark.parametrize(
    "pfad", sorted(VORLAGEN.rglob("*.html")), ids=lambda p: p.name
)
def test_jede_vorlage_laesst_sich_uebersetzen(pfad: Path):
    name = pfad.relative_to(VORLAGEN).as_posix()
    if name.startswith("pdf/"):
        pytest.skip("PDF-Vorlagen haben eine eigene Umgebung (app/pdf.py)")
    try:
        templates.env.get_template(name)
    except TemplateSyntaxError as fehler:
        pytest.fail(f"{name}:{fehler.lineno}: {fehler.message}")


def test_seiten_haben_sprungmarke_und_genau_eine_ueberschrift(client, schulen):
    """Tastaturbedienung und Struktur: ein H1 je Seite, Sprung über die Navigation."""
    a, _ = schulen
    angemeldet(client, a.email)
    for pfad in ("/verwaltung/", "/verwaltung/strecken", "/verwaltung/gruppen",
                 "/verwaltung/laeufe", "/verwaltung/ablaeufe", "/verwaltung/konto"):
        html = client.get(pfad).text
        assert 'href="#inhalt"' in html, pfad
        assert html.count("<h1") == 1, pfad
        assert 'id="inhalt"' in html, pfad


def test_oberflaeche_zeigt_symbole_und_keine_offenen_platzhalter(client, schulen):
    a, _ = schulen
    angemeldet(client, a.email)
    html = client.get("/verwaltung/").text
    assert html.count('class="symbol"') > 5  # Navigation, Karten, Knöpfe
    assert "{{" not in html and "{%" not in html
    assert "Undefined" not in html


def test_navigation_markiert_die_aktuelle_seite(client, schulen):
    a, _ = schulen
    angemeldet(client, a.email)
    for pfad, beschriftung in (
        ("/verwaltung/", "Übersicht"),
        ("/verwaltung/strecken", "Strecken"),
        ("/verwaltung/gruppen", "Gruppen"),
        ("/verwaltung/laeufe", "Läufe"),
    ):
        html = client.get(pfad).text
        aktuell = re.findall(r'<a[^>]*aria-current="page"[^>]*>(.*?)</a>', html, re.S)
        assert len(aktuell) == 1, pfad
        assert beschriftung in aktuell[0], pfad


def test_leere_bereiche_erklaeren_den_naechsten_schritt(client, fabrik):
    """Eine frische Schule sieht keine leeren Kästen, sondern den Weg dorthin."""
    with fabrik.intern_kontext() as s:
        schule = Schule(name="Frische Schule", kurzname="frisch")
        s.add(schule)
        s.flush()
        s.add(Benutzer(
            schule_id=schule.id,
            email="frisch@example.org",
            passwort_hash=passwort_hashen(PASSWORT),
            rolle="schuladmin",
        ))
    angemeldet(client, "frisch@example.org")
    html = client.get("/verwaltung/").text
    assert html.count("leerzustand") == 3  # Läufe, Strecken, Gruppen
    assert "Kein Lauf geplant" in html and "Noch keine Strecke angelegt" in html
    assert "Lauf anlegen" in html  # jeder leere Bereich nennt den nächsten Schritt


def test_pdfs_oeffnen_in_einem_neuen_tab(client, schulen):
    """Die Blätter werden gedruckt – die Seite dahinter soll stehen bleiben."""
    a, _ = schulen
    angemeldet(client, a.email)
    seiten = (
        f"/verwaltung/gruppen/{a.gruppe}",
        f"/verwaltung/strecken/{a.strecke}",
        f"/verwaltung/strecken/{a.strecke}/karte",
        f"/verwaltung/laeufe/{a.lauf}",
        f"/verwaltung/laeufe/{a.lauf}/auswertung",
        f"/verwaltung/laeufe/{a.lauf}/kinder/{a.kind}",
    )
    gefunden = 0
    for pfad in seiten:
        html = client.get(pfad).text
        assert ".pdf" in html, pfad
        for verweis in re.findall(r"<a\b[^>]*>", html):
            if ".pdf" not in verweis:
                continue
            gefunden += 1
            assert 'target="_blank"' in verweis, f"{pfad}: {verweis}"
            assert 'rel="noopener"' in verweis, f"{pfad}: {verweis}"
    assert gefunden >= len(seiten)


def test_json_export_wird_heruntergeladen_statt_geoeffnet(client, schulen):
    """Der Export ist eine Datei zum Aufheben, kein Blatt zum Ansehen."""
    a, _ = schulen
    angemeldet(client, a.email)
    kopf = client.get(f"/verwaltung/strecken/{a.strecke}/export.json").headers
    assert kopf["content-disposition"].startswith("attachment;")
    verweise = re.findall(r"<a\b[^>]*export\.json[^>]*>", client.get(f"/verwaltung/strecken/{a.strecke}").text)
    assert verweise and all("target=" not in v for v in verweise)
