"""Statische Kartenausschnitte für Posten-Blatt und Streckenplan (PNG).

WeasyPrint führt kein JavaScript aus; deshalb setzt der Server das Bild selbst
aus Kartenkacheln zusammen und zeichnet Strecke und Posten darüber.

Die Kacheln kommen von ``FP_KARTEN_KACHELN`` (Standard: OpenStreetMap
Deutschland). Ist die Variable leer oder der Server nicht erreichbar, hat das
Blatt eben keine Karte – das Drucken scheitert daran nie.

Kachel-Nutzungsbedingungen: wenige Abrufe, eigener User-Agent, Zwischenspeicher
im Arbeitsspeicher. Benachbarte Posten teilen sich auf dem Posten-Blatt die
meisten Kacheln; im Streckenplan (ZOOM_POSTEN) hat jeder Posten eigene.

tile.openstreetmap.de antwortet auf hohen Zoomstufen gelegentlich mit 404,
obwohl dieselbe Kachel beim nächsten Versuch kommt. Darum wird wiederholt und
notfalls die gröbere Kachel darüber vergrößert – ein unscharfes Viertel ist
besser als ein beiges Loch mitten in der Kreuzung.
"""

from __future__ import annotations

import io
import logging
import math
import threading
import time
import urllib.error
import urllib.request
from collections import OrderedDict
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor

from PIL import Image, ImageDraw, ImageFont

from app.config import einstellungen

log = logging.getLogger(__name__)

KACHEL = 256
ZOOM = 17  # Posten-Blatt: Standort im Umfeld
ZOOM_POSTEN = 19  # Streckenplan: einzelner Posten, sehr hoch gezoomt
# Grenzen für ausschnitt(): näher als 19 wird die Darstellung nicht genauer,
# gröber als 3 ist kein Schulweg mehr zu erkennen.
ZOOM_MAX = 19
ZOOM_MIN = 3
ERDRADIUS = 6_371_000.0
LINIENFARBE = (198, 40, 40)
NENNUNG = "© OpenStreetMap-Mitwirkende"

# Vorübergehende Serverfehler: wiederholen. Alles andere (kein Netz, kaputtes
# Bild) scheitert sofort, damit ein abgeschalteter Server nicht bremst.
VERSUCHE = 3
WARTEN = 0.3
VORUEBERGEHEND = frozenset({404, 408, 429, 500, 502, 503, 504})

_cache: OrderedDict[str, Image.Image] = OrderedDict()
_cache_sperre = threading.Lock()
CACHE_GROESSE = 400


def _kachel_holen(url: str) -> bytes:
    """Lädt eine Kachel. In Tests ersetzt (kein Netz)."""
    anfrage = urllib.request.Request(
        url, headers={"User-Agent": f"Fahrradpruefung/1.0 (+{einstellungen().oeffentliche_url})"}
    )
    with urllib.request.urlopen(anfrage, timeout=6) as antwort:
        data=antwort.read(2*1024*1024+1)
        if len(data)>2*1024*1024:raise ValueError("Tile byte limit")
        return data


def _laden(url: str, z: int) -> Image.Image | None:
    """Kachel holen, bei vorübergehenden Serverfehlern erneut versuchen."""
    for versuch in range(1, VERSUCHE + 1):
        try:
            image=Image.open(io.BytesIO(_kachel_holen(url)))
            if image.width*image.height>4_000_000:raise ValueError("Tile pixel limit")
            return image.convert("RGB")
        except urllib.error.HTTPError as fehler:
            if fehler.code not in VORUEBERGEHEND or versuch == VERSUCHE:
                log.warning("Kartenkachel nicht geladen (z=%s): HTTP %s", z, fehler.code)
                return None
            time.sleep(WARTEN * versuch)
        except Exception as fehler:  # kein Netz, kaputtes Bild – Karte ist optional
            log.warning("Kartenkachel nicht geladen (z=%s): %s", z, type(fehler).__name__)
            return None
    return None  # pragma: no cover


def _ersatz(z: int, x: int, y: int) -> Image.Image | None:
    """Fehlende Kachel durch das vergrößerte Viertel der gröberen darüber ersetzen.

    Dasselbe, was der Browser über ``maxNativeZoom`` tut (app/static/karte.js).
    Nur eine Stufe – fehlt auch die, bleibt die Fläche leer.
    """
    if z <= ZOOM_MIN:
        return None
    gruppe = _kachel(z - 1, x // 2, y // 2, ersatz=False)
    if gruppe is None:
        return None
    h = KACHEL // 2
    links, oben = (x % 2) * h, (y % 2) * h
    return gruppe.crop((links, oben, links + h, oben + h)).resize((KACHEL, KACHEL), Image.BICUBIC)


def _kachel(z: int, x: int, y: int, ersatz: bool = True) -> Image.Image | None:
    vorlage = einstellungen().karten_kacheln
    url = vorlage.replace("{z}", str(z)).replace("{x}", str(x)).replace("{y}", str(y))
    with _cache_sperre:
        if url in _cache:
            _cache.move_to_end(url)
            return _cache[url]
    bild = _laden(url, z)
    if bild is None:
        # Nicht zwischenspeichern: beim nächsten Bild darf es wieder klappen.
        return _ersatz(z, x, y) if ersatz else None
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


def _unpixel(x: float, y: float, z: int) -> tuple[float, float]:
    """Weltpixel in Web-Mercator auf Zoomstufe z → WGS84."""
    n = KACHEL * 2**z
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    return lat, x / n * 360 - 180


def laenge_meter(linie: Sequence[Sequence[float]]) -> float:
    """Länge eines Linienzugs in Metern (Kugelnäherung – genau genug für Schulwege)."""
    summe = 0.0
    for (lat1, lng1), (lat2, lng2) in zip(linie, linie[1:]):
        p1, p2 = math.radians(lat1), math.radians(lat2)
        dp, dl = p2 - p1, math.radians(lng2 - lng1)
        h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
        summe += 2 * ERDRADIUS * math.asin(min(1.0, math.sqrt(h)))
    return summe


def ausschnitt(
    punkte: Sequence[Sequence[float]],
    breite: int,
    hoehe: int,
    rand: int = 48,
    hoechstens: int = ZOOM_MAX,
) -> tuple[tuple[float, float], int]:
    """Mitte und höchste Zoomstufe, auf der alle ``punkte`` in breite×hoehe passen.

    ``rand`` hält die äußersten Punkte von der Bildkante weg – dort sitzen die
    Postenkreise. Für einen einzelnen Punkt kommt ``hoechstens`` heraus.
    """
    if not punkte:
        raise ValueError("ausschnitt braucht mindestens einen Punkt")
    for z in range(hoechstens, ZOOM_MIN - 1, -1):
        px = [_pixel(p[0], p[1], z) for p in punkte]
        xs, ys = [q[0] for q in px], [q[1] for q in px]
        passt = max(xs) - min(xs) <= breite - 2 * rand and max(ys) - min(ys) <= hoehe - 2 * rand
        if passt or z == ZOOM_MIN:
            return _unpixel((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2, z), z
    raise AssertionError("unerreichbar")  # pragma: no cover


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
