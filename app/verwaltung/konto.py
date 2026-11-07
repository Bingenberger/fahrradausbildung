"""Startseite und eigenes Konto des Schuladmins."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Form, Request
from sqlalchemy import func, select

from app.modelle import Gruppe, Kind, Lauf, Schule, Strecke
from app.web.abhaengigkeiten import SCHULADMIN_ROUTER, SchulRepo, Sitzung, meldung
from app.web.konto import eigenes_passwort_aendern
from app.web.vorlagen import seite, weiter_zu

router = APIRouter(dependencies=SCHULADMIN_ROUTER)

Text = Annotated[str, Form()]


@router.get("/")
def start(request: Request, repo: SchulRepo):
    strecken = repo.liste(Strecke, Strecke.archiviert.is_(False), sortierung=[Strecke.name])
    gruppen = repo.liste(Gruppe, Gruppe.archiviert.is_(False), sortierung=[Gruppe.name])
    anzahl = dict(
        repo.abfrage(
            select(Kind.gruppe_id, func.count(Kind.id)).where(Kind.aktiv).group_by(Kind.gruppe_id)
        ).all()
    )
    laeufe = repo.liste(Lauf, Lauf.status.in_(("vorbereitet", "laufend")), sortierung=[Lauf.datum])
    return seite(
        request, "verwaltung/start.html", strecken=strecken, gruppen=gruppen, anzahl=anzahl, laeufe=laeufe
    )


@router.get("/konto")
def konto(request: Request, repo: SchulRepo):
    schule = repo.holen(Schule, repo.schule_id)
    return seite(request, "konto.html", basis="/verwaltung", posten_pin=schule.posten_pin)


@router.post("/konto/posten-pin")
def posten_pin(request: Request, repo: SchulRepo, pin: Text = "", entfernen: Text = ""):
    """PIN vor der Posten-App setzen oder entfernen.

    Die iPads übernehmen die Änderung beim nächsten Öffnen der App im WLAN.
    """
    schule = repo.holen(Schule, repo.schule_id)
    if entfernen:
        schule.posten_pin = None
        meldung(request, "Die PIN-Abfrage ist ausgeschaltet.")
    else:
        pin = pin.strip()
        if len(pin) != 4 or not pin.isascii() or not pin.isdigit():
            meldung(request, "Die PIN muss aus genau vier Ziffern bestehen.", "fehler")
            return weiter_zu("/verwaltung/konto")
        schule.posten_pin = pin
        meldung(request, f"Die PIN für die Posten-App ist jetzt {pin}.")
    repo.commit()
    return weiter_zu("/verwaltung/konto")


@router.post("/konto/passwort")
def passwort(request: Request, info: Sitzung, _: SchulRepo, alt: Text = "", neu: Text = "", neu2: Text = ""):
    eigenes_passwort_aendern(request, info, alt, neu, neu2)
    return weiter_zu("/verwaltung/konto")
