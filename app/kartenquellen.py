"""Externe Kartendienste für die Streckenplanung – an einer Stelle.

Aus dieser Liste entstehen sowohl die Auswahl im Browser (app/static/karte.js)
als auch die Content-Security-Policy der Kartenseite (app/web/header.py):
Nur hier eingetragene Server darf die Seite ansprechen.

Datenschutz: Beim Planen lädt der Browser der Lehrkraft Kartenkacheln von diesen
Servern und schickt die geklickten Wegpunkte an die Routing-Dienste. Kinderdaten
sind nicht beteiligt. Die Schule sollte die Dienste in ihrer Datenschutzerklärung nennen.
"""

from __future__ import annotations

ATTRIBUTION = "Kartendaten © OpenStreetMap-Mitwirkende (ODbL)"

# Höchste Zoomstufe der Karte im Browser – für alle Kartenstile gleich.
# Darüber hinaus liefert kein Dienst eigene Kacheln; Leaflet vergrößert dann die
# letzte vorhandene Stufe (maxNativeZoom), statt eine graue Fläche zu zeigen.
MAX_ZOOM = 20

# Schlüssel → Anzeigename, Kachel-URL (Leaflet-Schreibweise), Subdomains,
# höchste Zoomstufe mit eigenen Kacheln (maxNativeZoom, vom Dienst abhängig), Nennung
KACHELN: dict[str, dict] = {
    "cyclosm": {
        "label": "CyclOSM – Radwege hervorgehoben",
        "url": "https://{s}.tile-cyclosm.openstreetmap.fr/cyclosm/{z}/{x}/{y}.png",
        "subs": ["a", "b", "c"],
        "maxNativeZoom": 19,
        "attr": ATTRIBUTION + ", Darstellung CyclOSM",
    },
    "osmde": {
        "label": "OpenStreetMap deutsch",
        "url": "https://{s}.tile.openstreetmap.de/{z}/{x}/{y}.png",
        "subs": ["a", "b", "c"],
        "maxNativeZoom": 18,
        "attr": ATTRIBUTION,
    },
    "osmfr": {
        "label": "OpenStreetMap Frankreich",
        "url": "https://{s}.tile.openstreetmap.fr/osmfr/{z}/{x}/{y}.png",
        "subs": ["a", "b", "c"],
        "maxNativeZoom": 19,
        "attr": ATTRIBUTION + ", Darstellung OpenStreetMap France",
    },
    "hot": {
        "label": "Humanitarian – hell, klare Straßen",
        "url": "https://{s}.tile.openstreetmap.fr/hot/{z}/{x}/{y}.png",
        "subs": ["a", "b"],
        "maxNativeZoom": 19,
        "attr": ATTRIBUTION + ", Darstellung Humanitarian OSM Team",
    },
    "topo": {
        "label": "OpenTopoMap",
        "url": "https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png",
        "subs": ["a", "b", "c"],
        "maxNativeZoom": 17,
        "attr": ATTRIBUTION + ", Darstellung © OpenTopoMap (CC-BY-SA)",
    },
    "osm": {
        "label": "OpenStreetMap Standard",
        "url": "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        "subs": [],
        "maxNativeZoom": 19,
        "attr": ATTRIBUTION,
    },
}

ROUTING = {
    "osrm_bike": "https://routing.openstreetmap.de/routed-bike/route/v1/driving/",
    "osrm_foot": "https://routing.openstreetmap.de/routed-foot/route/v1/driving/",
    "osrm_car": "https://router.project-osrm.org/route/v1/driving/",
    "valhalla": "https://valhalla1.openstreetmap.de/route",
}
ORTSSUCHE = "https://nominatim.openstreetmap.org/search"


def _herkunft(url: str) -> str:
    """https://{s}.tile.x.org/… → https://*.tile.x.org"""
    host = url.split("/")[2].replace("{s}.", "*.")
    return f"https://{host}"


def bildquellen() -> list[str]:
    return sorted({_herkunft(k["url"]) for k in KACHELN.values()})


def verbindungsziele() -> list[str]:
    return sorted({_herkunft(u) for u in [*ROUTING.values(), ORTSSUCHE]})


def fuer_browser() -> dict:
    return {"kacheln": KACHELN, "maxZoom": MAX_ZOOM, "routing": ROUTING, "ortssuche": ORTSSUCHE}
