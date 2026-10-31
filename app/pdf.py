"""PDF-Erzeugung mit WeasyPrint (HTML → PDF).

Vorlagen und Stylesheets liegen in ``app/vorlagen/pdf/`` und können von einer
Schule ausgetauscht werden.
"""

from __future__ import annotations

import base64
import re
from collections.abc import Sequence
from datetime import date
from functools import lru_cache
from pathlib import Path

import segno
from jinja2 import Environment, FileSystemLoader, select_autoescape
from weasyprint import CSS, HTML

from app.config import einstellungen
from app.kartenbild import ZOOM_POSTEN, ausschnitt, kartenbild, laenge_meter
from app.formate import datum_kurz, datum_lang, laenge_text
from app.modelle import Gruppe, Kind, Lauf, Schule, Strecke
from app.token import token_url

PDF_VORLAGEN = Path(__file__).resolve().parent / "vorlagen" / "pdf"

LOGO_DATEIEN = ("logo.svg", "logo.png", "logo.jpg")


@lru_cache
def _umgebung(suchpfade: tuple[Path, ...]) -> Environment:
    env = Environment(loader=FileSystemLoader(suchpfade), autoescape=select_autoescape(["html"]))
    env.filters["datum"] = datum_kurz
    env.filters["datum_lang"] = datum_lang
    env.filters["laenge"] = laenge_text
    return env


_env = _umgebung((PDF_VORLAGEN,))


def ordnername(kurzname: str) -> str:
    """Verzeichnisname für die Vorlagen einer Schule: „GS Lindenweg" → „gs-lindenweg"."""
    text = kurzname.lower()
    for alt, neu in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        text = text.replace(alt, neu)
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")


def suchpfade(schule: Schule) -> tuple[Path, ...]:
    """Schulordner vor gemeinsamem Ordner vor eingebauten Vorlagen."""
    pfade: list[Path] = []
    if einstellungen().vorlagen_verzeichnis:
        basis = Path(einstellungen().vorlagen_verzeichnis)
        ordner = ordnername(schule.kurzname)
        if ordner:
            pfade.append(basis / ordner)
        pfade.append(basis)
    return (*(p for p in pfade if p.is_dir()), PDF_VORLAGEN)


def _erste_datei(pfade: Sequence[Path], namen: Sequence[str]) -> Path | None:
    for ordner in pfade:
        for name in namen:
            if (ordner / name).is_file():
                return ordner / name
    return None


def qr_svg(url: str) -> str:
    """QR-Code als data:-URI (SVG), Fehlerkorrektur M – robust gegen Knicke im Papier."""
    return segno.make(url, error="m").svg_data_uri(scale=10, border=2, dark="#000000")


def _rendern(vorlage: str, stylesheet: str, **kontext) -> bytes:
    html = _env.get_template(vorlage).render(**kontext)
    return HTML(string=html, base_url=str(PDF_VORLAGEN)).write_pdf(
        stylesheets=[CSS(filename=str(PDF_VORLAGEN / stylesheet))]
    )


def feedbackboegen_pdf(schule: Schule, lauf: Lauf, boegen: list[dict]) -> bytes:
    """Feedbackbögen, eine Seite je Eintrag in ``boegen`` ({"kind", "feedback"}).

    Vorlage, Stylesheet und Logo kommen aus dem Schulordner, dem gemeinsamen
    Ordner oder – falls dort nichts liegt – aus ``app/vorlagen/pdf/``.
    """
    pfade = suchpfade(schule)
    vorlage = _umgebung(pfade).get_template("feedbackbogen.html")
    css = _erste_datei(pfade, ["feedbackbogen.css"])
    logo = _erste_datei(pfade[:-1], LOGO_DATEIEN)
    html = vorlage.render(schule=schule, lauf=lauf, boegen=boegen, logo=logo.as_uri() if logo else "")
    basis = Path(vorlage.filename).parent if vorlage.filename else PDF_VORLAGEN
    return HTML(string=html, base_url=str(basis)).write_pdf(
        stylesheets=[CSS(filename=str(css))] if css else []
    )


def namensliste_pdf(schule: Schule, gruppe: Gruppe, kinder: Sequence[Kind]) -> bytes:
    """Startnummern der Gruppe mit leeren Zeilen – die Namen kommen von Hand dazu."""
    return _rendern("namensliste.html", "namensliste.css", schule=schule, gruppe=gruppe, kinder=kinder)


def _bild_uri(png: bytes | None) -> str | None:
    return "data:image/png;base64," + base64.b64encode(png).decode() if png else None


def _verortet(strecke: Strecke) -> list[tuple[int, float, float]]:
    """(Nummer, lat, lng) aller Posten mit Standort – in Fahrreihenfolge nummeriert."""
    return [(i, p.lat, p.lng) for i, p in enumerate(strecke.posten, 1) if p.lat is not None]


def _standort_karte(lauf: Lauf, nummer: int) -> str | None:
    """Kartenausschnitt rund um Posten ``nummer`` als data:-URI – oder None."""
    posten = lauf.strecke.posten[nummer - 1]
    if posten.lat is None or posten.lng is None:
        return None
    linie = (lauf.strecke.verlauf or {}).get("linie", [])
    # 1200 × 282 Pixel entspricht dem Rahmen auf dem Blatt (170 × 40 mm).
    png = kartenbild((posten.lat, posten.lng), linie, _verortet(lauf.strecke),
                     hervorgehoben=nummer, breite=1200, hoehe=282)
    return _bild_uri(png)


def postenblaetter_pdf(lauf: Lauf, schule_name: str) -> bytes:
    """Eine Seite je Posten. Das Blatt geht an die Eltern."""
    tokens = {t.posten_id: t for t in lauf.tokens}
    blaetter = [
        {
            "posten": p,
            "nummer": i,
            "anzahl": len(lauf.strecke.posten),
            "url": token_url(tokens[p.id].token),
            "qr": qr_svg(token_url(tokens[p.id].token)),
            "karte": _standort_karte(lauf, i),
        }
        for i, p in enumerate(lauf.strecke.posten, 1)
        if p.id in tokens
    ]
    return _rendern(
        "postenblatt.html",
        "postenblatt.css",
        lauf=lauf,
        schule_name=schule_name,
        blaetter=blaetter,
    )


# --------------------------------------------------------------------------- Streckenplan

# Bildgrößen in Pixel; die Seitenverhältnisse entsprechen den Rahmen im
# Stylesheet (Übersicht 170 × 141,7 mm, Posten 170 × 121,8 mm) – gut 175 dpi.
UEBERSICHT_PX = (1200, 1000)
POSTEN_PX = (1200, 860)


def streckenplan_pdf(strecke: Strecke, schule_name: str) -> bytes:
    """Streckenplan: Übersichtskarte der Gesamtstrecke, dann eine Seite je Posten.

    Die Posten-Seiten zeigen denselben Ausschnitt sehr hoch gezoomt
    (``ZOOM_POSTEN``), damit auf dem Papier die Einmündung selbst erkennbar ist.
    Posten ohne Standort bekommen ihre Seite ohne Karte; fällt der Kachelserver
    aus, entsteht der Plan ohne Bilder statt gar nicht.
    """
    linie = (strecke.verlauf or {}).get("linie", [])
    verortet = _verortet(strecke)

    punkte = [*linie, *[(lat, lng) for _, lat, lng in verortet]]
    uebersicht = None
    if punkte:
        mitte, zoom = ausschnitt(punkte, *UEBERSICHT_PX)
        uebersicht = _bild_uri(kartenbild(mitte, linie, verortet, breite=UEBERSICHT_PX[0],
                                          hoehe=UEBERSICHT_PX[1], zoom=zoom))

    blaetter = [
        {
            "nummer": i,
            "posten": p,
            "karte": _bild_uri(
                kartenbild((p.lat, p.lng), linie, verortet, hervorgehoben=i,
                           breite=POSTEN_PX[0], hoehe=POSTEN_PX[1], zoom=ZOOM_POSTEN)
            )
            if p.lat is not None
            else None,
        }
        for i, p in enumerate(strecke.posten, 1)
    ]
    return _rendern(
        "streckenplan.html",
        "streckenplan.css",
        strecke=strecke,
        schule_name=schule_name,
        stand=date.today(),
        uebersicht=uebersicht,
        laenge_m=laenge_meter(linie),
        verortet=len(verortet),
        blaetter=blaetter,
        zoom_posten=ZOOM_POSTEN,
    )
