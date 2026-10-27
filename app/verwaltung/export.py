"""Export aller Daten der eigenen Schule als JSON (Spezifikation 9, Auskunftsersuchen).

Läuft vollständig über ``SchulRepo`` – die Mandanten-Schicht stellt sicher, dass nur
Daten der eigenen Schule im Export landen. Nicht enthalten sind Geheimnisse:
Passwort-Hashes, Posten-Tokens und Anmeldesitzungen.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from typing import Any

from fastapi import APIRouter
from fastapi.responses import Response

from app.mandant import SchulRepository
from app.modelle import Ablauf, Benutzer, Ereignis, Gruppe, Lauf, Schule, Strecke
from app.pdf import ordnername
from app.web.abhaengigkeiten import SCHULADMIN_ROUTER, SchulRepo

router = APIRouter(dependencies=SCHULADMIN_ROUTER)

FORMAT_VERSION = 1


def _wert(w: Any) -> Any:
    if isinstance(w, datetime | date):
        return w.isoformat()
    return w


def _felder(obj: Any, *namen: str) -> dict[str, Any]:
    return {n: _wert(getattr(obj, n)) for n in namen}


def schuldaten(repo: SchulRepository) -> dict[str, Any]:
    schule = repo.holen(Schule, repo.schule_id)
    ereignisse: dict[int, list[Ereignis]] = {}
    for e in repo.liste(Ereignis, sortierung=[Ereignis.erfasst_am, Ereignis.event_id]):
        ereignisse.setdefault(e.lauf_id, []).append(e)

    return {
        "format": "fahrradpruefung-export",
        "version": FORMAT_VERSION,
        "erstellt_am": datetime.now(UTC).isoformat(),
        "schule": _felder(schule, "id", "name", "kurzname", "aktiv", "erstellt_am"),
        "benutzer": [
            _felder(b, "id", "email", "rolle", "aktiv") for b in repo.liste(Benutzer, sortierung=[Benutzer.id])
        ],
        "strecken": [
            {
                **_felder(s, "id", "name", "beschreibung", "archiviert", "verlauf"),
                "posten": [
                    {
                        **_felder(p, "id", "name", "position", "beschreibung", "lat", "lng"),
                        "items": [
                            _felder(i, "id", "kurzbezeichnung", "beobachtungstext", "uebungstext", "position")
                            for i in p.items
                        ],
                    }
                    for p in s.posten
                ],
            }
            for s in repo.liste(Strecke, sortierung=[Strecke.id])
        ],
        "ablaeufe": [
            {
                **_felder(a, "id", "name", "beschreibung"),
                "schritte": [
                    _felder(s, "id", "kurzbezeichnung", "beobachtungstext", "uebungstext", "position")
                    for s in a.schritte
                ],
            }
            for a in repo.liste(Ablauf, sortierung=[Ablauf.id])
        ],
        "gruppen": [
            {
                **_felder(g, "id", "name", "schuljahr", "archiviert"),
                "kinder": [_felder(k, "id", "startnummer", "aktiv") for k in g.kinder],
            }
            for g in repo.liste(Gruppe, sortierung=[Gruppe.id])
        ],
        "laeufe": [
            {
                **_felder(l, "id", "strecke_id", "gruppe_id", "datum", "status", "erstellt_am", "daten_geloescht_am"),
                "posten_zugaenge": [
                    _felder(t, "posten_id", "gueltig_bis", "letzter_abruf", "letzter_upload")
                    for t in sorted(l.tokens, key=lambda t: t.posten_id)
                ],
                "ereignisse": [
                    {
                        "event_id": str(e.event_id),
                        **_felder(e, "posten_id", "startnummer", "typ", "nutzlast", "erfasst_am", "empfangen_am"),
                    }
                    for e in ereignisse.get(l.id, [])
                ],
            }
            for l in repo.liste(Lauf, sortierung=[Lauf.datum, Lauf.id])
        ],
    }


@router.get("/export.json")
def export(repo: SchulRepo):
    daten = schuldaten(repo)
    name = ordnername(daten["schule"]["kurzname"]) or "schule"
    return Response(
        json.dumps(daten, ensure_ascii=False, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="export-{name}-{date.today().isoformat()}.json"'},
    )
