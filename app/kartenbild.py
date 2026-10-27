"""Statischer Kartenausschnitt für das Posten-Blatt (PNG).

WeasyPrint führt kein JavaScript aus; deshalb setzt der Server das Bild selbst
aus Kartenkacheln zusammen und zeichnet Strecke und Posten darüber.

Die Kacheln kommen von ``FP_KARTEN_KACHELN`` (Standard: OpenStreetMap
Deutschland). Ist die Variable leer oder der Server nicht erreichbar, hat das
Posten-Blatt eben keine Karte – das Drucken scheitert daran nie.

Kachel-Nutzungsbedingungen: wenige Abrufe, eigener User-Agent, Zwischenspeicher
im Arbeitsspeicher. Benachbarte Posten teilen sich die meisten Kacheln.
"""

from __future__ import annotations

import io
import logging
import math
import threading
import urllib.request
from collections import OrderedDict
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor

from PIL import Image, ImageDraw, ImageFont

from app.config import einstellungen

log = logging.getLogger(__name__)

KACHEL = 256
ZOOM = 17
LINIENFARBE = (198, 40, 40)
NENNUNG = "© OpenStreetMap-Mitwirkende"

_cache: OrderedDict[str, Image.Image] = OrderedDict()
_cache_sperre = threading.Lock()
CACHE_GROESSE = 400


def _kachel_holen(url: str) -> bytes:
    """Lädt eine Kachel. In Tests ersetzt (kein Netz)."""
    anfrage = urllib.request.Request(
        url, headers={"User-Agent": f"Fahrradpruefung/1.0 (+{einstellungen().oeffentliche_url})"}
    )
    with urllib.request.urlopen(anfrage, timeout=6) as antwort:
        return antwort.read()


def _kachel(z: int, x: int, y: int) -> Image.Image | None:
    vorlage = einstellungen().karten_kacheln
    url = vorlage.replace("{z}", str(z)).replace("{x}", str(x)).replace("{y}", str(y))
    with _cache_sperre:
        if url in _cache:
            _cache.move_to_end(url)
            return _cache[url]
    try:
        bild = Image.open(io.BytesIO(_kachel_holen(url))).convert("RGB")
    except Exception as fehler:  # Netz, HTTP-Fehler, kaputtes Bild – Karte ist optional
        log.warning("Kartenkachel nicht geladen (z=%s): %s", z, type(fehler).__name__)
        return None
    with _cache_sperre:
        _cache[url] = bild
        while len(_cache) > CACHE_GROESSE:
            _cache.popitem(last=False)
    return bild


def _pixel(lat: float, lng: float, z: int) -> tuple[float, float]:
    """WGS84 → Weltpixel in Web-Mercator auf Zoomstufe z."""
    n = KACHEL * 2**z
    s = math.sin(math.radians(max(min(lat, 85.0511), -85.0511)))
    return (lng + 180) / 360 * n, (0.5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)) * n


def _schrift(groesse: int) -> ImageFont.ImageFont:
    for name in ("DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(name, groesse)
        except OSError:
            continue
    return ImageFont.load_default()


def kartenbild(
    mitte: tuple[float, float],
    linie: Sequence[Sequence[float]],
    posten: Sequence[tuple[int, float, float]],
    hervorgehoben: int | None = None,
    breite: int = 1100,
    hoehe: int = 480,
    zoom: int = ZOOM,
) -> bytes | None:
    """PNG mit Strecke und nummerierten Posten, zentriert auf ``mitte``.

    ``posten``: (Nummer, lat, lng); der Posten mit Nummer ``hervorgehoben`` wird
    groß und gelb gezeichnet. Liefert None, wenn keine Kachel geladen werden konnte.
    """
    if not einstellungen().karten_kacheln:
        return None
    mx, my = _pixel(mitte[0], mitte[1], zoom)
    x0, y0 = mx - breite / 2, my - hoehe / 2
    kacheln = [
        (tx, ty)
        for tx in range(math.floor(x0 / KACHEL), math.floor((x0 + breite) / KACHEL) + 1)
        for ty in range(math.floor(y0 / KACHEL), math.floor((y0 + hoehe) / KACHEL) + 1)
    ]
    with ThreadPoolExecutor(max_workers=6) as pool:
        bilder = list(pool.map(lambda t: _kachel(zoom, t[0], t[1]), kacheln))
    if not any(bilder):
        return None

    bild = Image.new("RGB", (breite, hoehe), (242, 239, 233))
    for (tx, ty), kachel in zip(kacheln, bilder):
        if kachel is not None:
            bild.paste(kachel, (round(tx * KACHEL - x0), round(ty * KACHEL - y0)))
    zeichnen = ImageDraw.Draw(bild)

    def lokal(lat: float, lng: float) -> tuple[float, float]:
        px, py = _pixel(lat, lng, zoom)
        return px - x0, py - y0

    if len(linie) >= 2:
        punkte = [lokal(p[0], p[1]) for p in linie]
        zeichnen.line(punkte, fill=(255, 255, 255), width=14, joint="curve")
        zeichnen.line(punkte, fill=LINIENFARBE, width=8, joint="curve")

    # Erst die anderen Posten, zuletzt der hervorgehobene (liegt oben)
    for nummer, lat, lng in sorted(posten, key=lambda p: p[0] == hervorgehoben):
        x, y = lokal(lat, lng)
        gross = nummer == hervorgehoben
        r = 26 if gross else 17
        fuellung = (245, 180, 0) if gross else (26, 26, 26)
        zeichnen.ellipse((x - r, y - r, x + r, y + r), fill=fuellung, outline=(255, 255, 255), width=4)
        zeichnen.text((x, y), str(nummer), fill=(0, 0, 0) if gross else (255, 255, 255),
                      font=_schrift(30 if gross else 20), anchor="mm")

    schrift = _schrift(16)
    rand = zeichnen.textbbox((0, 0), NENNUNG, font=schrift)
    b, h = rand[2] - rand[0], rand[3] - rand[1]
    zeichnen.rectangle((breite - b - 16, hoehe - h - 14, breite, hoehe), fill=(255, 255, 255))
    zeichnen.text((breite - b - 8, hoehe - h - 9), NENNUNG, fill=(40, 40, 40), font=schrift)

    ausgabe = io.BytesIO()
    bild.save(ausgabe, "PNG", optimize=True)
    return ausgabe.getvalue()
