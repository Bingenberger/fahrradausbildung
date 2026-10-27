"""Streckenplanung auf der Karte: Verlauf zeichnen, Posten verorten.

Die Seite lädt Kacheln und Routing direkt im Browser von den Diensten in
``app/kartenquellen.py``; der Server speichert nur das Ergebnis. Gespeichert
wird klassisch per Formular (mit CSRF-Feld): ``verlauf`` und ``orte`` sind
JSON-Texte, die das Skript vor dem Absenden füllt.

Standorte und Verlauf dürfen sich auch ändern, wenn schon Läufe an der Strecke
hängen – Erfassungen verweisen nur auf Posten und Items, nicht auf Koordinaten.
"""

from __future__ import annotations

import json
import math
from typing import Annotated, Any

from fastapi import APIRouter, Form, Request

from app.kartenquellen import fuer_browser
from app.modelle import Strecke
from app.web.abhaengigkeiten import SCHULADMIN_ROUTER, SchulRepo, meldung
from app.web.vorlagen import seite, weiter_zu

router = APIRouter(dependencies=SCHULADMIN_ROUTER)

Text = Annotated[str, Form()]

MODI = {"route", "trace", "import"}
MAX_WEGPUNKTE = 500
MAX_LINIENPUNKTE = 20_000
MAX_ZEICHEN = 1_500_000


class Ungueltig(ValueError):
    pass


def _punkt(roh: Any) -> list[float]:
    if (
        not isinstance(roh, list)
        or len(roh) != 2
        or not all(isinstance(z, int | float) and not isinstance(z, bool) for z in roh)
    ):
        raise Ungueltig("Koordinate ungültig")
    lat, lng = float(roh[0]), float(roh[1])
    if not (math.isfinite(lat) and math.isfinite(lng) and -90 <= lat <= 90 and -180 <= lng <= 180):
        raise Ungueltig("Koordinate außerhalb des gültigen Bereichs")
    # 6 Nachkommastellen ≈ 10 cm – genauer zeichnet niemand.
    return [round(lat, 6), round(lng, 6)]


def _punkte(roh: Any, hoechstens: int) -> list[list[float]]:
    if not isinstance(roh, list):
        raise Ungueltig("Punktliste erwartet")
    if len(roh) > hoechstens:
        raise Ungueltig(f"höchstens {hoechstens} Punkte")
    return [_punkt(p) for p in roh]


def verlauf_pruefen(roh: str) -> dict[str, Any] | None:
    """JSON aus dem Formular → gespeicherter Verlauf (oder None für „keiner")."""
    if len(roh) > MAX_ZEICHEN:
        raise Ungueltig("Strecke zu lang")
    if not roh.strip() or roh.strip() == "null":
        return None
    try:
        daten = json.loads(roh)
    except ValueError as fehler:
        raise Ungueltig("kein gültiges JSON") from fehler
    if not isinstance(daten, dict) or set(daten) - {"modus", "wegpunkte", "linie"}:
        raise Ungueltig("unbekannte Felder")
    modus = daten.get("modus", "route")
    if modus not in MODI:
        raise Ungueltig("Modus ungültig")
    linie = _punkte(daten.get("linie", []), MAX_LINIENPUNKTE)
    wegpunkte = _punkte(daten.get("wegpunkte", []), MAX_WEGPUNKTE)
    if len(linie) < 2:
        return None
    return {"modus": modus, "wegpunkte": wegpunkte, "linie": linie}


def orte_pruefen(roh: str, posten_ids: set[int]) -> dict[int, list[float] | None]:
    if len(roh) > 100_000:
        raise Ungueltig("zu viele Daten")
    try:
        daten = json.loads(roh or "{}")
    except ValueError as fehler:
        raise Ungueltig("kein gültiges JSON") from fehler
    if not isinstance(daten, dict):
        raise Ungueltig("Objekt erwartet")
    ergebnis: dict[int, list[float] | None] = {}
    for schluessel, wert in daten.items():
        try:
            pid = int(schluessel)
        except ValueError as fehler:
            raise Ungueltig("Posten unbekannt") from fehler
        if pid not in posten_ids:
            raise Ungueltig("Posten gehört nicht zu dieser Strecke")
        ergebnis[pid] = None if wert is None else _punkt(wert)
    return ergebnis


def _kartendaten(repo, strecke: Strecke) -> dict[str, Any]:
    andere = [
        {"id": s.id, "name": s.name, "linie": s.verlauf["linie"]}
        for s in repo.liste(Strecke, Strecke.archiviert.is_(False), Strecke.id != strecke.id, sortierung=[Strecke.name])
        if s.verlauf and s.verlauf.get("linie")
    ]
    return {
        "strecke": {"id": strecke.id, "name": strecke.name, "verlauf": strecke.verlauf},
        "posten": [
            {"id": p.id, "nummer": i, "name": p.name, "ort": [p.lat, p.lng] if p.lat is not None else None}
            for i, p in enumerate(strecke.posten, 1)
        ],
        "andere": andere,
        "quellen": fuer_browser(),
    }


@router.get("/strecken/{strecke_id}/karte")
def karte(request: Request, repo: SchulRepo, strecke_id: int):
    strecke = repo.holen(Strecke, strecke_id)
    request.state.csp = "karte"
    return seite(request, "verwaltung/karte.html", strecke=strecke, daten=_kartendaten(repo, strecke))


@router.post("/strecken/{strecke_id}/karte")
def karte_speichern(request: Request, repo: SchulRepo, strecke_id: int, verlauf: Text = "", orte: Text = ""):
    strecke = repo.holen(Strecke, strecke_id)
    posten = {p.id: p for p in strecke.posten}
    try:
        neuer_verlauf = verlauf_pruefen(verlauf)
        neue_orte = orte_pruefen(orte, set(posten))
    except Ungueltig as fehler:
        meldung(request, f"Nicht gespeichert: {fehler}.", "fehler")
        return weiter_zu(f"/verwaltung/strecken/{strecke.id}/karte")
    strecke.verlauf = neuer_verlauf
    for pid, ort in neue_orte.items():
        posten[pid].lat, posten[pid].lng = (ort[0], ort[1]) if ort else (None, None)
    repo.commit()
    ohne = [p.name for p in strecke.posten if p.lat is None]
    if ohne:
        meldung(request, f"Gespeichert. Noch ohne Standort: {', '.join(ohne)}.")
    else:
        meldung(request, "Gespeichert.")
    return weiter_zu(f"/verwaltung/strecken/{strecke.id}/karte")
