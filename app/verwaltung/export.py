"""Exporte als JSON: alle Daten der Schule (Spezifikation 9, Auskunftsersuchen)
und einzelne Strecken zum Sichern oder Weitergeben – dazu der Import einer
exportierten Strecke.

Export und Import stehen bewusst im selben Modul: ``streckendaten()`` legt die
Form der Datei fest, ``strecke_aus_daten()`` liest sie zurück. Lägen sie
auseinander, würde das Format beim nächsten neuen Feld stillschweigend
auseinanderlaufen.

Läuft vollständig über ``SchulRepo`` – die Mandanten-Schicht stellt sicher, dass nur
Daten der eigenen Schule im Export landen. Nicht enthalten sind Geheimnisse:
Passwort-Hashes, Posten-Tokens und Anmeldesitzungen.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from typing import Annotated, Any

from fastapi import APIRouter, File, Request, UploadFile
from fastapi.responses import Response

from app.mandant import SchulRepository
from app.modelle import Ablauf, Benutzer, Ereignis, Gruppe, Item, Lauf, Posten, Schule, Strecke
from app.pdf import ordnername
from app.verwaltung.karte import Ungueltig, ort_pruefen, verlauf_aus_daten
from app.verwaltung.strecken import item_pruefen
from app.web.abhaengigkeiten import SCHULADMIN_ROUTER, SchulRepo, meldung
from app.web.vorlagen import weiter_zu

router = APIRouter(dependencies=SCHULADMIN_ROUTER)

FORMAT_VERSION = 1

# Grenzen für den Import. Die Dateigröße fängt nginx davor noch einmal ab
# (``client_max_body_size`` in deploy/nginx-fahrradpruefung.conf).
MAX_BYTES = 2_000_000
MAX_POSTEN = 100
MAX_ITEMS = 100


def _wert(w: Any) -> Any:
    if isinstance(w, datetime | date):
        return w.isoformat()
    return w


def _felder(obj: Any, *namen: str) -> dict[str, Any]:
    return {n: _wert(getattr(obj, n)) for n in namen}


def streckendaten(strecke: Strecke) -> dict[str, Any]:
    """Eine Strecke mit allen Posten und deren Items.

    Gemeinsame Form für den Schulexport und den Export einer einzelnen Strecke –
    damit beide dasselbe bedeuten und nicht auseinanderlaufen.
    """
    return {
        **_felder(strecke, "id", "name", "beschreibung", "archiviert", "verlauf"),
        "posten": [
            {
                **_felder(p, "id", "name", "position", "beschreibung", "lat", "lng"),
                "items": [
                    _felder(i, "id", "kurzbezeichnung", "beobachtungstext", "uebungstext", "position")
                    for i in p.items
                ],
            }
            for p in strecke.posten
        ],
    }


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
        "strecken": [streckendaten(s) for s in repo.liste(Strecke, sortierung=[Strecke.id])],
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


@router.get("/strecken/{strecke_id}/export.json")
def strecke_export(repo: SchulRepo, strecke_id: int):
    """Eine einzelne Strecke mit allen Posten und Items.

    Zum Sichern vor einem Umbau und zum Weitergeben an eine andere Schule –
    anders als der Schulexport enthält die Datei keine Läufe und keine
    Erfassungen, also auch nichts, was einem Kind zuzuordnen wäre.
    """
    strecke = repo.holen(Strecke, strecke_id)
    schule = repo.holen(Schule, repo.schule_id)
    daten = {
        "format": "fahrradpruefung-strecke",
        "version": FORMAT_VERSION,
        "erstellt_am": datetime.now(UTC).isoformat(),
        "schule": _felder(schule, "name", "kurzname"),
        "strecke": streckendaten(strecke),
    }
    name = ordnername(strecke.name) or str(strecke.id)
    return Response(
        json.dumps(daten, ensure_ascii=False, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="strecke-{name}.json"'},
    )


# --------------------------------------------------------------------------- Import


def _text(roh: Any, feld: str, hoechstens: int = 0) -> str:
    if roh is None:
        return ""
    if not isinstance(roh, str):
        raise Ungueltig(f"{feld}: Text erwartet")
    wert = roh.strip()
    if hoechstens and len(wert) > hoechstens:
        raise Ungueltig(f"{feld} ist zu lang (höchstens {hoechstens} Zeichen)")
    return wert


def _geordnet(roh: Any, feld: str, hoechstens: int) -> list[dict[str, Any]]:
    """Liste aus der Datei, nach ``position`` sortiert.

    Fehlt oder taugt ``position`` nicht, bleibt die Reihenfolge der Datei – eine
    Strecke soll auch aus einer handgeschriebenen Datei entstehen können.
    """
    if not isinstance(roh, list):
        raise Ungueltig(f"{feld}: Liste erwartet")
    if len(roh) > hoechstens:
        raise Ungueltig(f"höchstens {hoechstens} {feld} je Strecke")
    if not all(isinstance(e, dict) for e in roh):
        raise Ungueltig(f"{feld}: Objekte erwartet")

    def schluessel(paar: tuple[int, dict[str, Any]]) -> tuple[int, int]:
        i, eintrag = paar
        pos = eintrag.get("position")
        return (pos if isinstance(pos, int) and not isinstance(pos, bool) else i, i)

    return [e for _, e in sorted(enumerate(roh), key=schluessel)]


def strecke_aus_daten(roh: Any) -> Strecke:
    """Gelesene Exportdatei → noch nicht gespeicherte Strecke mit Posten und Items.

    Gegenstück zu :func:`streckendaten`. Zwei Felder der Datei werden bewusst
    verworfen: die ``id``-Werte (es entsteht eine neue Strecke, fremde IDs wären
    sinnlos oder gefährlich) und ``archiviert`` (eine frisch importierte Strecke
    soll sichtbar sein und nicht im Archiv liegen).
    """
    if not isinstance(roh, dict):
        raise Ungueltig("Objekt erwartet")
    if roh.get("format") != "fahrradpruefung-strecke":
        raise Ungueltig("das ist keine Datei aus „Strecke exportieren“")
    version = roh.get("version")
    if not isinstance(version, int) or isinstance(version, bool) or version > FORMAT_VERSION:
        raise Ungueltig(f"unbekannte Formatversion (diese App kennt Version {FORMAT_VERSION})")
    daten = roh.get("strecke")
    if not isinstance(daten, dict):
        raise Ungueltig("in der Datei steht keine Strecke")

    name = _text(daten.get("name"), "Streckenname", 200)
    if not name:
        raise Ungueltig("die Strecke in der Datei hat keinen Namen")
    strecke = Strecke(
        name=name,
        beschreibung=_text(daten.get("beschreibung"), "Streckenbeschreibung"),
        verlauf=verlauf_aus_daten(daten.get("verlauf")),
    )

    for nr, p in enumerate(_geordnet(daten.get("posten") or [], "Posten", MAX_POSTEN), 1):
        postenname = _text(p.get("name"), f"Name von Posten {nr}", 200)
        if not postenname:
            raise Ungueltig(f"Posten {nr} hat keinen Namen")
        ort = ort_pruefen(p.get("lat"), p.get("lng"))
        posten = Posten(
            name=postenname,
            position=nr,
            beschreibung=_text(p.get("beschreibung"), f"Beschreibung von „{postenname}“"),
            lat=ort[0] if ort else None,
            lng=ort[1] if ort else None,
        )
        for inr, i in enumerate(_geordnet(p.get("items") or [], "Items", MAX_ITEMS), 1):
            kurz = _text(i.get("kurzbezeichnung"), f"Kurzbezeichnung in „{postenname}“", 200)
            if fehler := item_pruefen(kurz):
                raise Ungueltig(f"„{postenname}“, Item {inr}: {fehler}")
            posten.items.append(
                Item(
                    kurzbezeichnung=kurz,
                    beobachtungstext=_text(i.get("beobachtungstext"), "Beobachtungstext"),
                    uebungstext=_text(i.get("uebungstext"), "Übungstext"),
                    position=inr,
                )
            )
        strecke.posten.append(posten)
    return strecke


def _freier_name(name: str, vorhanden: set[str]) -> str:
    """Name mit Zusatz, falls schon einer so heißt.

    Gleichnamige Strecken sind erlaubt, in der Liste aber nicht auseinanderzuhalten –
    und wer dieselbe Datei zweimal einliest, soll nicht zweimal „(Import)" sehen.
    Der Zuschnitt hält den Namen innerhalb der Spaltenbreite von 200 Zeichen.
    """
    if name not in vorhanden:
        return name
    for nr in range(1, 100):
        zusatz = " (Import)" if nr == 1 else f" (Import {nr})"
        kandidat = name[: 200 - len(zusatz)].rstrip() + zusatz
        if kandidat not in vorhanden:
            return kandidat
    return name[:200]


@router.post("/strecken/importieren")
async def strecke_importieren(
    request: Request, repo: SchulRepo, datei: Annotated[UploadFile | None, File()] = None
):
    """Eine exportierte Strecke als neue Strecke anlegen.

    Legt immer eine *neue* Strecke an; eine bestehende wird nie überschrieben.
    Die Datei darf aus einer anderen Schule stammen – sie enthält nur Strecke,
    Posten und Items, nichts, was einem Kind zuzuordnen wäre.
    """
    if datei is None or not datei.filename:
        meldung(request, "Bitte eine Datei auswählen.", "fehler")
        return weiter_zu("/verwaltung/strecken")

    inhalt = await datei.read(MAX_BYTES + 1)
    try:
        if len(inhalt) > MAX_BYTES:
            raise Ungueltig(f"Datei zu groß (höchstens {MAX_BYTES // 1_000_000} MB)")
        try:
            gelesen = json.loads(inhalt.decode())
        except (UnicodeDecodeError, ValueError) as fehler:
            raise Ungueltig("kein gültiges JSON") from fehler
        strecke = strecke_aus_daten(gelesen)
    except Ungueltig as fehler:
        meldung(request, f"Nicht importiert: {fehler}.", "fehler")
        return weiter_zu("/verwaltung/strecken")

    strecke.name = _freier_name(strecke.name, {s.name for s in repo.liste(Strecke)})
    repo.hinzufuegen(strecke)
    repo.commit()
    meldung(
        request,
        f"Strecke „{strecke.name}“ importiert, mit {len(strecke.posten)} Posten. "
        "Prüfe die Texte und zeichne den Verlauf auf der Karte nach.",
    )
    return weiter_zu(f"/verwaltung/strecken/{strecke.id}")
