"""Token-API der Posten-Geräte (Spezifikation 7).

Drei Endpunkte ohne Login, ausschließlich über das Token autorisiert:

    GET  /api/p/{token}/config
    POST /api/p/{token}/events
    GET  /api/p/{token}/status

Die Endpunkte arbeiten im Bereich INTERN, weil es keinen angemeldeten Benutzer
gibt. Jede Abfrage ist an ``lauf_id`` und ``posten_id`` des aufgelösten Tokens
gebunden. Antworten und Logs enthalten keine Namen; Logs auch keine Tokens und
Startnummern (Spezifikation 4.2, 9).
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from app.mandant import FPSession
from app.modelle import Ereignis, Gruppe, Item, Kind, Lauf, PostenToken
from app.token import token_gueltig

log = logging.getLogger("fahrradpruefung.posten")

router = APIRouter(prefix="/api/p")

MAX_EREIGNISSE = 1000
MAX_BYTES = 2_000_000
MAX_BEMERKUNG = 500
MAX_DURCHGANG = 1000
# Mehr Läufe an einem Posten zur Auswahl zu stellen hilft niemandem.
MAX_WEITERE_LAEUFE = 20


# --------------------------------------------------------------------------- Hilfen


def _antwort(daten: Any, status: int = 200) -> JSONResponse:
    return JSONResponse(daten, status_code=status, headers={"Cache-Control": "no-store"})


def _nicht_gefunden() -> JSONResponse:
    # Unbekannt, abgelaufen und entwertet sind bewusst nicht unterscheidbar.
    return _antwort({"fehler": "unbekannt"}, 404)


class Bremse:
    """Einfache Ratenbegrenzung je Token (gleitendes Fenster, prozesslokal)."""

    def __init__(self, maximum: int = 120, fenster_s: float = 60.0) -> None:
        self.maximum = maximum
        self.fenster_s = fenster_s
        self._zeiten: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def erlaubt(self, schluessel: str) -> bool:
        jetzt = time.monotonic()
        with self._lock:
            q = self._zeiten[schluessel]
            while q and q[0] < jetzt - self.fenster_s:
                q.popleft()
            if len(q) >= self.maximum:
                return False
            q.append(jetzt)
            return True


def _bremse(request: Request) -> Bremse:
    if not hasattr(request.app.state, "posten_bremse"):
        request.app.state.posten_bremse = Bremse()
    return request.app.state.posten_bremse


@dataclass
class Zugang:
    token: PostenToken
    lauf: Lauf


def _zugang(session: FPSession, token: str) -> Zugang | None:
    if not (20 <= len(token) <= 100):
        return None
    pt = session.execute(select(PostenToken).where(PostenToken.token == token)).scalar_one_or_none()
    if pt is None or not token_gueltig(pt, pt.lauf):
        return None
    return Zugang(pt, pt.lauf)


def _startnummern(session: FPSession, gruppe_id: int, nur_aktive: bool) -> list[int]:
    stmt = select(Kind.startnummer).where(Kind.gruppe_id == gruppe_id)
    if nur_aktive:
        stmt = stmt.where(Kind.aktiv)
    return sorted(session.execute(stmt).scalars())


def _weitere_laeufe(session: FPSession, zugang: Zugang) -> list[dict[str, Any]]:
    """Andere Läufe, die an genau diesem Posten noch anstehen.

    Damit wechselt die Person am Posten in der installierten App auf den
    nächsten Lauf, statt den QR-Code erneut zu scannen – das legte sonst ein
    zweites Symbol auf dem Home-Bildschirm an (Spezifikation 6). Je Token bleibt
    es bei genau einem Lauf; hier steht nur, welche weiteren es gibt.

    Die Klassenbezeichnung muss mit, sonst sind zwei Läufe am selben Tag nicht
    auseinanderzuhalten. Kindernamen kennt die Anwendung nicht, und Startnummern
    stehen hier bewusst nicht (Spezifikation 4.2).
    """
    stmt = (
        select(PostenToken.token, Lauf.datum, Gruppe.name)
        .join(Lauf, Lauf.id == PostenToken.lauf_id)
        .join(Gruppe, Gruppe.id == Lauf.gruppe_id)
        .where(
            PostenToken.posten_id == zugang.token.posten_id,
            PostenToken.lauf_id != zugang.lauf.id,
            PostenToken.gueltig_bis > datetime.now(UTC),
            Lauf.status.in_(("vorbereitet", "laufend")),
        )
        .order_by(Lauf.datum, Gruppe.name, Lauf.id)
        .limit(MAX_WEITERE_LAEUFE)
    )
    return [
        {"token": token, "datum": datum.isoformat(), "gruppe": gruppe}
        for token, datum, gruppe in session.execute(stmt)
    ]


def _vorab(request: Request, token: str):
    """Ratenbegrenzung prüfen und Token auflösen. Liefert (session, zugang) oder Antwort."""
    if not _bremse(request).erlaubt(token):
        return None, _antwort({"fehler": "zu viele Anfragen"}, 429)
    session = request.app.state.fabrik.intern()
    zugang = _zugang(session, token)
    if zugang is None:
        session.close()
        return None, _nicht_gefunden()
    return (session, zugang), None


# --------------------------------------------------------------------------- Konfiguration


@router.get("/{token}/config")
def konfiguration(request: Request, token: str):
    vorab, fehler = _vorab(request, token)
    if fehler:
        return fehler
    session, z = vorab
    try:
        posten = z.token.posten
        antwort = {
            "lauf_id": z.lauf.id,
            "datum": z.lauf.datum.isoformat(),
            "posten": {"id": posten.id, "name": posten.name},
            "items": [
                {"id": i.id, "kurzbezeichnung": i.kurzbezeichnung, "position": i.position}
                for i in posten.items
            ],
            # Ausschließlich Startnummern – keine Namen (Spezifikation 4.2).
            "startnummern": _startnummern(session, z.lauf.gruppe_id, nur_aktive=True),
            # Für den Wechsel auf den nächsten Lauf ohne erneutes Scannen. Die App
            # legt die Liste lokal ab: Nach dem Abschließen des Laufs ist dieses
            # Token entwertet, und der Endpunkt antwortet dann mit 404.
            "weitere_laeufe": _weitere_laeufe(session, z),
        }
        z.token.letzter_abruf = datetime.now(UTC)
        session.commit()
        log.info("Konfiguration abgerufen lauf=%s posten=%s", z.lauf.id, posten.id)
        return _antwort(antwort)
    finally:
        session.close()


# --------------------------------------------------------------------------- Ereignisse


def _pruefe_ereignis(
    roh: Any, startnummern: set[int], item_ids: set[int]
) -> tuple[dict[str, Any] | None, str | None, str | None]:
    """Liefert (Ereignis, None, event_id) oder (None, Grund, event_id)."""
    if not isinstance(roh, dict):
        return None, "kein Objekt", None
    eid_roh = roh.get("event_id")
    eid_text = eid_roh if isinstance(eid_roh, str) else None
    try:
        eid = uuid.UUID(eid_roh)
    except (TypeError, ValueError, AttributeError):
        return None, "event_id ist keine UUID", eid_text
    if eid.version != 4:
        return None, "event_id ist keine UUIDv4", eid_text

    erwartet = {"event_id", "typ", "startnummer", "nutzlast", "erfasst_am"}
    if set(roh) - erwartet - {"uebertragen"}:
        return None, "unbekannte Felder", eid_text

    startnummer = roh.get("startnummer")
    if not isinstance(startnummer, int) or isinstance(startnummer, bool):
        return None, "startnummer fehlt", eid_text
    if startnummer not in startnummern:
        return None, "startnummer gehört nicht zum Lauf", eid_text

    try:
        erfasst_am = datetime.fromisoformat(str(roh.get("erfasst_am")).replace("Z", "+00:00"))
    except ValueError:
        return None, "erfasst_am ungültig", eid_text
    if erfasst_am.tzinfo is None:
        return None, "erfasst_am ohne Zeitzone", eid_text

    typ, nutzlast = roh.get("typ"), roh.get("nutzlast")
    if not isinstance(nutzlast, dict):
        return None, "nutzlast fehlt", eid_text

    if typ == "durchgang":
        if set(nutzlast) - {"durchgang_nr", "fehlende_items", "storniert"}:
            return None, "unbekannte Felder in nutzlast", eid_text
        nr, fehlend = nutzlast.get("durchgang_nr"), nutzlast.get("fehlende_items")
        if not isinstance(nr, int) or isinstance(nr, bool) or not 1 <= nr <= MAX_DURCHGANG:
            return None, "durchgang_nr ungültig", eid_text
        if not isinstance(fehlend, list) or not all(isinstance(i, int) and not isinstance(i, bool) for i in fehlend):
            return None, "fehlende_items ungültig", eid_text
        if len(set(fehlend)) != len(fehlend) or not set(fehlend) <= item_ids:
            return None, "fehlende_items gehören nicht zum Posten", eid_text
        storniert = nutzlast.get("storniert", False)
        if not isinstance(storniert, bool):
            return None, "storniert ungültig", eid_text
        sauber = {"durchgang_nr": nr, "fehlende_items": fehlend}
        if storniert:
            sauber["storniert"] = True
    elif typ == "sicherheit":
        if set(nutzlast) - {"stufe", "bemerkung"}:
            return None, "unbekannte Felder in nutzlast", eid_text
        stufe, bemerkung = nutzlast.get("stufe"), nutzlast.get("bemerkung")
        if stufe not in (1, 2, 3) or isinstance(stufe, bool):
            return None, "stufe ungültig", eid_text
        sauber = {"stufe": stufe}
        if bemerkung is not None:
            if not isinstance(bemerkung, str) or len(bemerkung) > MAX_BEMERKUNG:
                return None, "bemerkung ungültig", eid_text
            if bemerkung.strip():
                sauber["bemerkung"] = bemerkung.strip()
    else:
        return None, "typ ungültig", eid_text

    return (
        {
            "event_id": eid,
            "typ": typ,
            "startnummer": startnummer,
            "nutzlast": sauber,
            "erfasst_am": erfasst_am,
        },
        None,
        str(eid),
    )


@router.post("/{token}/events")
async def ereignisse(request: Request, token: str):
    laenge = request.headers.get("content-length")
    if laenge and laenge.isdigit() and int(laenge) > MAX_BYTES:
        return _antwort({"fehler": "Anfrage zu groß"}, 413)
    try:
        koerper = await request.json()
    except ValueError:
        return _antwort({"fehler": "kein gültiges JSON"}, 422)
    if not isinstance(koerper, dict) or not isinstance(koerper.get("events"), list):
        return _antwort({"fehler": "erwartet: {events: [...]}"}, 422)
    roh_liste = koerper["events"]
    if len(roh_liste) > MAX_EREIGNISSE:
        return _antwort({"fehler": f"höchstens {MAX_EREIGNISSE} Ereignisse je Anfrage"}, 413)

    vorab, fehler = _vorab(request, token)
    if fehler:
        return fehler
    session, z = vorab
    try:
        return _ereignisse_speichern(session, z, roh_liste)
    finally:
        session.close()


def _ereignisse_speichern(session: FPSession, z: Zugang, roh_liste: list[Any]) -> JSONResponse:
    lauf_id, posten_id = z.lauf.id, z.token.posten_id
    # Auch inaktive Kinder: Ein Kind kann nach dem Laden der Konfiguration
    # deaktiviert worden sein – seine Erfassungen sind trotzdem echt.
    startnummern = set(_startnummern(session, z.lauf.gruppe_id, nur_aktive=False))
    item_ids = set(session.execute(select(Item.id).where(Item.posten_id == posten_id)).scalars())

    gueltig: dict[uuid.UUID, dict[str, Any]] = {}
    abgewiesen: list[dict[str, Any]] = []
    for roh in roh_liste:
        ereignis, grund, eid = _pruefe_ereignis(roh, startnummern, item_ids)
        if ereignis is None:
            abgewiesen.append({"event_id": eid, "grund": grund})
        else:
            gueltig[ereignis["event_id"]] = ereignis

    jetzt = datetime.now(UTC)
    if gueltig:
        # Idempotent: Doppelte event_ids (auch aus früheren Anfragen) werden ignoriert.
        session.execute(
            insert(Ereignis)
            .values([{**e, "lauf_id": lauf_id, "posten_id": posten_id} for e in gueltig.values()])
            .on_conflict_do_nothing(index_elements=["event_id"])
        )
        # Bestätigt wird, was jetzt für genau diesen Lauf und Posten in der Datenbank steht –
        # ob gerade eingefügt oder schon bei einem früheren Versuch.
        vorhanden = set(
            session.execute(
                select(Ereignis.event_id).where(
                    Ereignis.event_id.in_(list(gueltig)),
                    Ereignis.lauf_id == lauf_id,
                    Ereignis.posten_id == posten_id,
                )
            ).scalars()
        )
        for eid in set(gueltig) - vorhanden:
            abgewiesen.append({"event_id": str(eid), "grund": "event_id bereits anderweitig vergeben"})
    else:
        vorhanden = set()

    z.token.letzter_upload = jetzt
    if vorhanden and z.lauf.status == "vorbereitet":
        z.lauf.status = "laufend"
    session.commit()

    log.info(
        "Upload lauf=%s posten=%s angenommen=%d abgewiesen=%d",
        lauf_id, posten_id, len(vorhanden), len(abgewiesen),
    )
    return _antwort({"akzeptiert": sorted(str(e) for e in vorhanden), "abgewiesen": abgewiesen})


# --------------------------------------------------------------------------- Status


@router.get("/{token}/status")
def status(request: Request, token: str):
    """``offen``: Startnummern, von denen dieser Posten noch keine Erfassung hat."""
    vorab, fehler = _vorab(request, token)
    if fehler:
        return fehler
    session, z = vorab
    try:
        erfasst = set(
            session.execute(
                select(Ereignis.startnummer).where(
                    Ereignis.lauf_id == z.lauf.id, Ereignis.posten_id == z.token.posten_id
                ).distinct()
            ).scalars()
        )
        aktive = _startnummern(session, z.lauf.gruppe_id, nur_aktive=True)
        zuletzt = session.execute(
            select(func.max(Ereignis.empfangen_am)).where(
                Ereignis.lauf_id == z.lauf.id, Ereignis.posten_id == z.token.posten_id
            )
        ).scalar_one()
        return _antwort(
            {
                "offen": len([n for n in aktive if n not in erfasst]),
                "zuletzt_empfangen": zuletzt.isoformat() if zuletzt else None,
            }
        )
    finally:
        session.close()
