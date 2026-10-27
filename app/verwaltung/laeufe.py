"""Läufe, Posten-Tokens und Posten-Blätter (Spezifikation 5.3, 5.4, 5.7).

Ein Lauf verbindet Gruppe, Strecke und Datum. Beim Anlegen entsteht je Posten
ein Token; das Posten-Blatt (PDF) trägt es als QR-Code an den Posten.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import Response
from sqlalchemy import func, select

from app.auswertung import laufstand
from app.mandant import SchulRepository
from app.modelle import Ereignis, Gruppe, Kind, Lauf, Posten, Schule, Strecke
from app.pdf import postenblaetter_pdf
from app.token import (
    token_ablauf,
    token_erneuern,
    token_url,
    tokens_entwerten,
    tokens_erzeugen,
    tokens_wiederherstellen,
)
from app.web.abhaengigkeiten import SCHULADMIN_ROUTER, SchulRepo, meldung
from app.web.vorlagen import seite, weiter_zu

router = APIRouter(dependencies=SCHULADMIN_ROUTER)

Text = Annotated[str, Form()]

STATUS_TEXT = {
    "vorbereitet": "vorbereitet",
    "laufend": "läuft",
    "abgeschlossen": "abgeschlossen",
    "archiviert": "archiviert",
}


def _ganzzahl(roh: str) -> int | None:
    try:
        return int(roh)
    except (TypeError, ValueError):
        return None


def _anzahl_ereignisse(repo: SchulRepository, lauf_id: int) -> int:
    return repo.abfrage(select(func.count()).select_from(Ereignis).where(Ereignis.lauf_id == lauf_id)).scalar_one()


def ereignisse_des_laufs(repo: SchulRepository, lauf_id: int) -> list[Ereignis]:
    return list(repo.abfrage(select(Ereignis).where(Ereignis.lauf_id == lauf_id)).scalars())


def kinder_des_laufs(repo: SchulRepository, lauf: Lauf) -> list[Kind]:
    return repo.liste(Kind, Kind.gruppe_id == lauf.gruppe_id, sortierung=[Kind.startnummer])


def _uebersicht(repo: SchulRepository, lauf: Lauf) -> dict:
    """Stand je Posten und auffällige Startnummern (Spezifikation 5.5).

    Fehlende Startnummern zählen nur bei Posten, die schon Daten geliefert
    haben – sonst wäre vor dem ersten Upload alles rot.
    """
    posten = lauf.strecke.posten
    ereignisse = ereignisse_des_laufs(repo, lauf.id)
    stand = laufstand(ereignisse, [p.id for p in posten])
    kinder = kinder_des_laufs(repo, lauf)
    aktiv = [k.startnummer for k in kinder if k.aktiv]
    mit_daten = {nr for s in stand.values() for nr in s.mit_daten}
    # Aktive Kinder plus inaktive, von denen trotzdem Erfassungen vorliegen.
    zeilen = [k for k in kinder if k.aktiv or k.startnummer in mit_daten]
    gemeldet = [p for p in posten if stand[p.id].ereignisse]

    fehlt_ueberall, fehlt_teilweise = [], []
    if gemeldet:
        for k in zeilen:
            if not k.aktiv:
                continue
            fehlt = [p for p in gemeldet if not stand[p.id].durchgaenge.get(k.startnummer)]
            if len(fehlt) == len(gemeldet):
                fehlt_ueberall.append(k)
            elif fehlt:
                fehlt_teilweise.append((k, fehlt))

    return {
        "stand": stand,
        "aktiv": aktiv,
        "zeilen": zeilen,
        "gemeldet": {p.id for p in gemeldet},
        "fehlt_ueberall": fehlt_ueberall,
        "fehlt_teilweise": fehlt_teilweise,
        "inaktiv_mit_daten": [k for k in zeilen if not k.aktiv],
        "anzahl_ereignisse": len(ereignisse),
    }


def _aktive_kinder(repo: SchulRepository, gruppe_id: int) -> int:
    return repo.abfrage(
        select(func.count(Kind.id)).where(Kind.gruppe_id == gruppe_id, Kind.aktiv)
    ).scalar_one()


def _pruefen(repo: SchulRepository, strecke: Strecke, gruppe: Gruppe, datum: date) -> str | None:
    if strecke.archiviert:
        return "Die Strecke ist archiviert."
    if gruppe.archiviert:
        return "Die Gruppe ist archiviert."
    if not strecke.posten:
        return "Die Strecke hat noch keine Posten."
    ohne_items = [p.name for p in strecke.posten if not p.items]
    if ohne_items:
        return f"Diese Posten haben noch keine Items: {', '.join(ohne_items)}."
    if not _aktive_kinder(repo, gruppe.id):
        return "Die Gruppe hat keine aktiven Kinder."
    if token_ablauf(datum) <= datetime.now(UTC):
        return "Das Datum liegt in der Vergangenheit."
    # OFFEN: Mehrere Gruppen gleichzeitig auf einer Strecke – Annahme: nein
    # (siehe Index uq_lauf_strecke_datum_aktiv).
    belegt = repo.liste(
        Lauf,
        Lauf.strecke_id == strecke.id,
        Lauf.datum == datum,
        Lauf.status.in_(("vorbereitet", "laufend")),
    )
    if belegt:
        return "Auf dieser Strecke gibt es an diesem Tag schon einen Lauf."
    return None


# --------------------------------------------------------------------------- Liste und Anlegen


@router.get("/laeufe")
def laeufe(request: Request, repo: SchulRepo):
    alle = repo.liste(Lauf, sortierung=[Lauf.datum.desc(), Lauf.id.desc()])
    return seite(
        request,
        "verwaltung/laeufe.html",
        laeufe=alle,
        strecken=repo.liste(Strecke, Strecke.archiviert.is_(False), sortierung=[Strecke.name]),
        gruppen=repo.liste(Gruppe, Gruppe.archiviert.is_(False), sortierung=[Gruppe.name]),
        status_text=STATUS_TEXT,
        heute=date.today().isoformat(),
    )


@router.post("/laeufe/neu")
def lauf_anlegen(
    request: Request, repo: SchulRepo, strecke_id: Text = "", gruppe_id: Text = "", datum: Text = ""
):
    sid, gid = _ganzzahl(strecke_id), _ganzzahl(gruppe_id)
    try:
        tag = date.fromisoformat(datum)
    except ValueError:
        tag = None
    if sid is None or gid is None or tag is None:
        meldung(request, "Bitte Strecke, Gruppe und Datum wählen.", "fehler")
        return weiter_zu("/verwaltung/laeufe")

    strecke = repo.holen(Strecke, sid)
    gruppe = repo.holen(Gruppe, gid)
    fehler = _pruefen(repo, strecke, gruppe, tag)
    if fehler:
        meldung(request, fehler, "fehler")
        return weiter_zu("/verwaltung/laeufe")

    lauf = Lauf(strecke=strecke, gruppe=gruppe, datum=tag, status="vorbereitet")
    repo.hinzufuegen(lauf)
    tokens_erzeugen(lauf)
    repo.commit()
    meldung(request, "Lauf angelegt. Drucke jetzt die Posten-Blätter.")
    return weiter_zu(f"/verwaltung/laeufe/{lauf.id}")


# --------------------------------------------------------------------------- Einzelner Lauf


@router.get("/laeufe/{lauf_id}")
def lauf_ansehen(request: Request, repo: SchulRepo, lauf_id: int):
    lauf = repo.holen(Lauf, lauf_id)
    tokens = {t.posten_id: t for t in lauf.tokens}
    posten = [
        {"posten": p, "token": tokens.get(p.id), "url": token_url(tokens[p.id].token) if p.id in tokens else None}
        for p in lauf.strecke.posten
    ]
    uebersicht = _uebersicht(repo, lauf)
    return seite(
        request,
        "verwaltung/lauf.html",
        lauf=lauf,
        posten=posten,
        status_text=STATUS_TEXT,
        aktive_kinder=len(uebersicht["aktiv"]),
        anzahl_ereignisse=uebersicht["anzahl_ereignisse"],
        u=uebersicht,
        ohne_upload=[e["posten"].name for e in posten if e["token"] and not e["token"].letzter_upload],
        wieder_oeffnenbar=lauf.status == "abgeschlossen" and token_ablauf(lauf.datum) > datetime.now(UTC),
    )


@router.get("/laeufe/{lauf_id}/postenblaetter.pdf")
def postenblaetter(repo: SchulRepo, lauf_id: int):
    lauf = repo.holen(Lauf, lauf_id)
    schule = repo.holen(Schule, repo.schule_id)
    pdf = postenblaetter_pdf(lauf, schule.name)
    return Response(
        pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="postenblaetter-{lauf.datum.isoformat()}.pdf"'},
    )


@router.post("/laeufe/{lauf_id}/tokens/{posten_id}/erneuern")
def token_neu(request: Request, repo: SchulRepo, lauf_id: int, posten_id: int):
    lauf = repo.holen(Lauf, lauf_id)
    posten = repo.holen(Posten, posten_id)
    token = next((t for t in lauf.tokens if t.posten_id == posten.id), None)
    if token is None:
        meldung(request, "Dieser Posten gehört nicht zum Lauf.", "fehler")
    elif lauf.status != "vorbereitet":
        meldung(
            request,
            "Der Zugang lässt sich nur vor Beginn des Laufs erneuern – ein bereits "
            "eingerichtetes iPad könnte sonst seine Daten nicht mehr übertragen.",
            "fehler",
        )
    else:
        token_erneuern(token, lauf)
        repo.commit()
        meldung(request, f"Neuer Zugang für „{posten.name}“. Drucke das Posten-Blatt neu; das alte gilt nicht mehr.")
    return weiter_zu(f"/verwaltung/laeufe/{lauf.id}")


@router.post("/laeufe/{lauf_id}/abschliessen")
def lauf_abschliessen(request: Request, repo: SchulRepo, lauf_id: int):
    lauf = repo.holen(Lauf, lauf_id)
    if lauf.status not in ("vorbereitet", "laufend"):
        meldung(request, "Der Lauf ist bereits abgeschlossen.", "fehler")
    else:
        lauf.status = "abgeschlossen"
        tokens_entwerten(lauf)
        repo.commit()
        meldung(request, "Lauf abgeschlossen. Die Zugänge der Posten sind entwertet.")
    return weiter_zu(f"/verwaltung/laeufe/{lauf.id}")


@router.post("/laeufe/{lauf_id}/wieder-oeffnen")
def lauf_wieder_oeffnen(request: Request, repo: SchulRepo, lauf_id: int):
    lauf = repo.holen(Lauf, lauf_id)
    if lauf.status != "abgeschlossen" or token_ablauf(lauf.datum) <= datetime.now(UTC):
        meldung(request, "Dieser Lauf lässt sich nicht mehr öffnen.", "fehler")
    else:
        lauf.status = "laufend"
        tokens_wiederherstellen(lauf)
        repo.commit()
        meldung(request, "Lauf wieder geöffnet. Die iPads können ihre Daten jetzt übertragen.")
    return weiter_zu(f"/verwaltung/laeufe/{lauf.id}")


@router.post("/laeufe/{lauf_id}/archivieren")
def lauf_archivieren(request: Request, repo: SchulRepo, lauf_id: int):
    lauf = repo.holen(Lauf, lauf_id)
    if lauf.status != "abgeschlossen":
        meldung(request, "Nur abgeschlossene Läufe lassen sich archivieren.", "fehler")
    else:
        lauf.status = "archiviert"
        repo.commit()
        meldung(request, "Lauf archiviert.")
    return weiter_zu(f"/verwaltung/laeufe/{lauf.id}")


@router.post("/laeufe/{lauf_id}/loeschen")
def lauf_loeschen(request: Request, repo: SchulRepo, lauf_id: int):
    lauf = repo.holen(Lauf, lauf_id)
    if lauf.status != "vorbereitet" or _anzahl_ereignisse(repo, lauf.id):
        meldung(request, "Nur ein vorbereiteter Lauf ohne Erfassungen lässt sich löschen.", "fehler")
        return weiter_zu(f"/verwaltung/laeufe/{lauf.id}")
    repo.loeschen(lauf)
    repo.commit()
    meldung(request, "Lauf gelöscht.")
    return weiter_zu("/verwaltung/laeufe")

