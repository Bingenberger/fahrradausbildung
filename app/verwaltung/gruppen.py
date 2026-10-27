"""Gruppen und ihre Startnummern (Spezifikation 5.2, ohne Namen).

Die Anwendung kennt keine Kindernamen. Eine Gruppe besteht aus Startnummern;
die Klassenleitung druckt die Namensliste aus, trägt die Namen von Hand ein und
sorgt dafür, dass jedes Kind immer dieselbe Nummer bekommt.

Sobald an einer Gruppe ein Lauf hängt, sind die Startnummern fest: Sie lassen
sich dann nicht mehr löschen, nur deaktivieren – sonst passte die Papierliste
nicht mehr zu den Feedbackbögen.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import Response
from sqlalchemy import func, select

from app.mandant import SchulRepository
from app.modelle import Gruppe, Kind, Lauf, Schule
from app.pdf import namensliste_pdf
from app.web.abhaengigkeiten import SCHULADMIN_ROUTER, SchulRepo, meldung
from app.web.vorlagen import seite, weiter_zu

router = APIRouter(dependencies=SCHULADMIN_ROUTER)

Text = Annotated[str, Form()]

MAX_STARTNUMMER = 999


def _anzahl_laeufe(repo: SchulRepository, gruppe_id: int) -> int:
    return repo.abfrage(select(func.count(Lauf.id)).where(Lauf.gruppe_id == gruppe_id)).scalar_one()


def _startnummer(roh: str) -> int | None:
    try:
        nr = int(roh.strip())
    except ValueError:
        return None
    return nr if nr > 0 else None


def _gruppenseite(request: Request, repo: SchulRepository, gruppe: Gruppe, **extra):
    return seite(
        request,
        "verwaltung/gruppe.html",
        gruppe=gruppe,
        kinder=gruppe.kinder,
        startnummern_fest=bool(_anzahl_laeufe(repo, gruppe.id)),
        **extra,
    )


# --------------------------------------------------------------------------- Gruppen


@router.get("/gruppen")
def gruppen(request: Request, repo: SchulRepo):
    alle = repo.liste(Gruppe, sortierung=[Gruppe.archiviert, Gruppe.schuljahr.desc(), Gruppe.name])
    anzahl = dict(
        repo.abfrage(
            select(Kind.gruppe_id, func.count(Kind.id)).where(Kind.aktiv).group_by(Kind.gruppe_id)
        ).all()
    )
    return seite(request, "verwaltung/gruppen.html", gruppen=alle, anzahl=anzahl)


@router.post("/gruppen/neu")
def gruppe_anlegen(
    request: Request, repo: SchulRepo, name: Text = "", schuljahr: Text = "", anzahl: Text = ""
):
    n = _startnummer(anzahl) if anzahl.strip() else 0
    if not name.strip() or not schuljahr.strip():
        meldung(request, "Bitte Name und Schuljahr angeben.", "fehler")
        return weiter_zu("/verwaltung/gruppen")
    if n is None or n > MAX_STARTNUMMER:
        meldung(request, "Die Anzahl der Kinder muss eine positive ganze Zahl sein.", "fehler")
        return weiter_zu("/verwaltung/gruppen")
    gruppe = repo.hinzufuegen(Gruppe(name=name.strip(), schuljahr=schuljahr.strip()))
    if n:
        _nummern_anlegen(gruppe, 1, n)
    repo.commit()
    if n:
        meldung(request, f"Gruppe mit den Startnummern 1 bis {n} angelegt. Drucke jetzt die Namensliste.")
    else:
        meldung(request, "Gruppe angelegt. Lege jetzt die Startnummern an.")
    return weiter_zu(f"/verwaltung/gruppen/{gruppe.id}")


@router.get("/gruppen/{gruppe_id}")
def gruppe_ansehen(request: Request, repo: SchulRepo, gruppe_id: int):
    return _gruppenseite(request, repo, repo.holen(Gruppe, gruppe_id))


@router.post("/gruppen/{gruppe_id}/bearbeiten")
def gruppe_bearbeiten(
    request: Request, repo: SchulRepo, gruppe_id: int, name: Text = "", schuljahr: Text = ""
):
    gruppe = repo.holen(Gruppe, gruppe_id)
    if not name.strip() or not schuljahr.strip():
        meldung(request, "Name und Schuljahr dürfen nicht leer sein.", "fehler")
    else:
        gruppe.name = name.strip()
        gruppe.schuljahr = schuljahr.strip()
        repo.commit()
        meldung(request, "Gespeichert.")
    return weiter_zu(f"/verwaltung/gruppen/{gruppe.id}")


@router.post("/gruppen/{gruppe_id}/archivieren")
def gruppe_archivieren(request: Request, repo: SchulRepo, gruppe_id: int):
    gruppe = repo.holen(Gruppe, gruppe_id)
    gruppe.archiviert = True
    repo.commit()
    meldung(request, "Gruppe archiviert.")
    return weiter_zu(f"/verwaltung/gruppen/{gruppe.id}")


@router.post("/gruppen/{gruppe_id}/reaktivieren")
def gruppe_reaktivieren(request: Request, repo: SchulRepo, gruppe_id: int):
    gruppe = repo.holen(Gruppe, gruppe_id)
    gruppe.archiviert = False
    repo.commit()
    meldung(request, "Gruppe ist wieder aktiv.")
    return weiter_zu(f"/verwaltung/gruppen/{gruppe.id}")


@router.post("/gruppen/{gruppe_id}/loeschen")
def gruppe_loeschen(request: Request, repo: SchulRepo, gruppe_id: int):
    gruppe = repo.holen(Gruppe, gruppe_id)
    if _anzahl_laeufe(repo, gruppe.id):
        meldung(
            request,
            "Die Gruppe kann nicht gelöscht werden, weil Läufe daran hängen. "
            "Archiviere sie stattdessen.",
            "fehler",
        )
        return weiter_zu(f"/verwaltung/gruppen/{gruppe.id}")
    repo.loeschen(gruppe)
    repo.commit()
    meldung(request, "Gruppe mit allen Startnummern gelöscht.")
    return weiter_zu("/verwaltung/gruppen")


# --------------------------------------------------------------------------- Startnummern


def _nummern_anlegen(gruppe: Gruppe, von: int, bis: int) -> int:
    vorhanden = {k.startnummer for k in gruppe.kinder}
    neu = [nr for nr in range(von, bis + 1) if nr not in vorhanden]
    for nr in neu:
        gruppe.kinder.append(Kind(startnummer=nr))
    return len(neu)


@router.post("/gruppen/{gruppe_id}/kinder")
def nummern_anlegen(request: Request, repo: SchulRepo, gruppe_id: int, von: Text = "", bis: Text = ""):
    """Legt alle fehlenden Startnummern im Bereich von–bis an (bis leer: nur eine)."""
    gruppe = repo.holen(Gruppe, gruppe_id)
    a = _startnummer(von)
    b = _startnummer(bis) if bis.strip() else a
    if a is None or b is None or b > MAX_STARTNUMMER:
        meldung(request, f"Startnummern müssen ganze Zahlen von 1 bis {MAX_STARTNUMMER} sein.", "fehler")
    elif b < a:
        meldung(request, "„bis“ muss größer oder gleich „von“ sein.", "fehler")
    else:
        anzahl = _nummern_anlegen(gruppe, a, b)
        repo.commit()
        if anzahl:
            meldung(request, f"{anzahl} Startnummer{'n' if anzahl != 1 else ''} hinzugefügt.")
        else:
            meldung(request, "Diese Startnummern gibt es schon.", "fehler")
    return weiter_zu(f"/verwaltung/gruppen/{gruppe.id}#kinder")


@router.get("/gruppen/{gruppe_id}/namensliste.pdf")
def namensliste(repo: SchulRepo, gruppe_id: int):
    gruppe = repo.holen(Gruppe, gruppe_id)
    pdf = namensliste_pdf(repo.holen(Schule, repo.schule_id), gruppe, [k for k in gruppe.kinder if k.aktiv])
    return Response(
        pdf, media_type="application/pdf", headers={"Content-Disposition": 'inline; filename="namensliste.pdf"'}
    )


def _aktiv_setzen(request: Request, repo: SchulRepository, kind_id: int, aktiv: bool):
    kind = repo.holen(Kind, kind_id)
    kind.aktiv = aktiv
    repo.commit()
    meldung(request, f"Nr. {kind.startnummer} ist {'wieder aktiv' if aktiv else 'deaktiviert'}.")
    return weiter_zu(f"/verwaltung/gruppen/{kind.gruppe_id}#kinder")


@router.post("/kinder/{kind_id}/aktivieren")
def kind_aktivieren(request: Request, repo: SchulRepo, kind_id: int):
    return _aktiv_setzen(request, repo, kind_id, True)


@router.post("/kinder/{kind_id}/deaktivieren")
def kind_deaktivieren(request: Request, repo: SchulRepo, kind_id: int):
    return _aktiv_setzen(request, repo, kind_id, False)


@router.post("/kinder/{kind_id}/loeschen")
def kind_loeschen(request: Request, repo: SchulRepo, kind_id: int):
    kind = repo.holen(Kind, kind_id)
    gruppe = kind.gruppe
    if _anzahl_laeufe(repo, gruppe.id):
        meldung(
            request,
            "Startnummern einer Gruppe mit Lauf lassen sich nicht löschen, nur deaktivieren.",
            "fehler",
        )
    else:
        gruppe.kinder.remove(kind)
        repo.commit()
        meldung(request, f"Nr. {kind.startnummer} gelöscht.")
    return weiter_zu(f"/verwaltung/gruppen/{gruppe.id}#kinder")
