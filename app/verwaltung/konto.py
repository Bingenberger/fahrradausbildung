"""Startseite und eigenes Konto des Schuladmins."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Form, Request
from sqlalchemy import func, select

from app.modelle import Gruppe, Kind, Lauf, Strecke
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
def konto(request: Request, _: SchulRepo):
    return seite(request, "konto.html", basis="/verwaltung")


@router.post("/konto/passwort")
def passwort(request: Request, info: Sitzung, _: SchulRepo, alt: Text = "", neu: Text = "", neu2: Text = ""):
    eigenes_passwort_aendern(request, info, alt, neu, neu2)
    return weiter_zu("/verwaltung/konto")
