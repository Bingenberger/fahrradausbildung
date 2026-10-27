"""Strecken, Posten und Items (Spezifikation 5.1).

Sobald an einer Strecke ein Lauf hängt, ist ihre Struktur eingefroren: Posten
und Items lassen sich dann nicht mehr hinzufügen, löschen oder umsortieren,
weil Erfassungen und Feedbackbögen auf genau diese Posten und Items verweisen.
Die Texte bleiben redaktionell bearbeitbar. Für Umbauten wird die Strecke
dupliziert.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Form, Request
from sqlalchemy import func, select

from app.mandant import SchulRepository
from app.modelle import Ablauf, Item, Lauf, Posten, Strecke
from app.web.abhaengigkeiten import SCHULADMIN_ROUTER, SchulRepo, meldung
from app.web.vorlagen import seite, weiter_zu

router = APIRouter(dependencies=SCHULADMIN_ROUTER)

Text = Annotated[str, Form()]


def _anzahl_laeufe(repo: SchulRepository, strecke_id: int) -> int:
    return repo.abfrage(
        select(func.count(Lauf.id)).where(Lauf.strecke_id == strecke_id)
    ).scalar_one()


def _struktur_aenderbar(request: Request, repo: SchulRepository, strecke: Strecke) -> bool:
    if _anzahl_laeufe(repo, strecke.id):
        meldung(
            request,
            "An dieser Strecke hängen bereits Läufe. Posten und Items lassen sich nicht mehr "
            "hinzufügen, löschen oder umsortieren – dupliziere die Strecke für Änderungen.",
            "fehler",
        )
        return False
    return True


def _neu_nummerieren(eintraege) -> None:
    for i, e in enumerate(sorted(eintraege, key=lambda e: e.position), 1):
        e.position = i


def _verschieben(eintraege, eintrag, richtung: str) -> None:
    liste = sorted(eintraege, key=lambda e: e.position)
    i = liste.index(eintrag)
    j = i - 1 if richtung == "hoch" else i + 1
    if 0 <= j < len(liste):
        liste[i].position, liste[j].position = liste[j].position, liste[i].position


# --------------------------------------------------------------------------- Strecken


@router.get("/strecken")
def strecken(request: Request, repo: SchulRepo):
    alle = repo.liste(Strecke, sortierung=[Strecke.archiviert, Strecke.name])
    return seite(request, "verwaltung/strecken.html", strecken=alle)


@router.post("/strecken/neu")
def strecke_anlegen(request: Request, repo: SchulRepo, name: Text = "", beschreibung: Text = ""):
    if not name.strip():
        meldung(request, "Bitte einen Namen für die Strecke angeben.", "fehler")
        return weiter_zu("/verwaltung/strecken")
    strecke = repo.hinzufuegen(Strecke(name=name.strip(), beschreibung=beschreibung.strip()))
    repo.commit()
    meldung(request, "Strecke angelegt. Füge jetzt die Posten hinzu.")
    return weiter_zu(f"/verwaltung/strecken/{strecke.id}")


@router.get("/strecken/{strecke_id}")
def strecke_ansehen(request: Request, repo: SchulRepo, strecke_id: int):
    strecke = repo.holen(Strecke, strecke_id)
    return seite(
        request,
        "verwaltung/strecke.html",
        strecke=strecke,
        anzahl_laeufe=_anzahl_laeufe(repo, strecke.id),
    )


@router.post("/strecken/{strecke_id}/bearbeiten")
def strecke_bearbeiten(
    request: Request, repo: SchulRepo, strecke_id: int, name: Text = "", beschreibung: Text = ""
):
    strecke = repo.holen(Strecke, strecke_id)
    if not name.strip():
        meldung(request, "Der Name darf nicht leer sein.", "fehler")
    else:
        strecke.name = name.strip()
        strecke.beschreibung = beschreibung.strip()
        repo.commit()
        meldung(request, "Gespeichert.")
    return weiter_zu(f"/verwaltung/strecken/{strecke.id}")


@router.post("/strecken/{strecke_id}/duplizieren")
def strecke_duplizieren(request: Request, repo: SchulRepo, strecke_id: int):
    alt = repo.holen(Strecke, strecke_id)
    neu = Strecke(name=f"{alt.name} (Kopie)", beschreibung=alt.beschreibung, verlauf=alt.verlauf)
    for p in alt.posten:
        posten = Posten(name=p.name, position=p.position, beschreibung=p.beschreibung, lat=p.lat, lng=p.lng)
        posten.items = [
            Item(
                kurzbezeichnung=i.kurzbezeichnung,
                beobachtungstext=i.beobachtungstext,
                uebungstext=i.uebungstext,
                position=i.position,
            )
            for i in p.items
        ]
        neu.posten.append(posten)
    repo.hinzufuegen(neu)
    repo.commit()
    meldung(request, "Strecke dupliziert. Das ist die Kopie.")
    return weiter_zu(f"/verwaltung/strecken/{neu.id}")


@router.post("/strecken/{strecke_id}/archivieren")
def strecke_archivieren(request: Request, repo: SchulRepo, strecke_id: int):
    strecke = repo.holen(Strecke, strecke_id)
    strecke.archiviert = True
    repo.commit()
    meldung(request, "Strecke archiviert.")
    return weiter_zu(f"/verwaltung/strecken/{strecke.id}")


@router.post("/strecken/{strecke_id}/reaktivieren")
def strecke_reaktivieren(request: Request, repo: SchulRepo, strecke_id: int):
    strecke = repo.holen(Strecke, strecke_id)
    strecke.archiviert = False
    repo.commit()
    meldung(request, "Strecke ist wieder aktiv.")
    return weiter_zu(f"/verwaltung/strecken/{strecke.id}")


@router.post("/strecken/{strecke_id}/loeschen")
def strecke_loeschen(request: Request, repo: SchulRepo, strecke_id: int):
    strecke = repo.holen(Strecke, strecke_id)
    if _anzahl_laeufe(repo, strecke.id):
        meldung(
            request,
            "Die Strecke kann nicht gelöscht werden, weil Läufe daran hängen. "
            "Archiviere sie stattdessen.",
            "fehler",
        )
        return weiter_zu(f"/verwaltung/strecken/{strecke.id}")
    repo.loeschen(strecke)
    repo.commit()
    meldung(request, "Strecke gelöscht.")
    return weiter_zu("/verwaltung/strecken")


# --------------------------------------------------------------------------- Posten


@router.post("/strecken/{strecke_id}/posten")
def posten_anlegen(
    request: Request, repo: SchulRepo, strecke_id: int, name: Text = "", beschreibung: Text = ""
):
    strecke = repo.holen(Strecke, strecke_id)
    if not _struktur_aenderbar(request, repo, strecke):
        return weiter_zu(f"/verwaltung/strecken/{strecke.id}")
    if not name.strip():
        meldung(request, "Bitte einen Namen für den Posten angeben.", "fehler")
        return weiter_zu(f"/verwaltung/strecken/{strecke.id}")
    posten = Posten(
        name=name.strip(),
        beschreibung=beschreibung.strip(),
        position=max((p.position for p in strecke.posten), default=0) + 1,
    )
    strecke.posten.append(posten)
    repo.flush()
    repo.commit()
    meldung(request, "Posten angelegt. Füge jetzt die Handlungsschritte (Items) hinzu.")
    return weiter_zu(f"/verwaltung/posten/{posten.id}")


@router.get("/posten/{posten_id}")
def posten_ansehen(request: Request, repo: SchulRepo, posten_id: int):
    posten = repo.holen(Posten, posten_id)
    return seite(
        request,
        "verwaltung/posten.html",
        posten=posten,
        strecke=posten.strecke,
        struktur_fest=bool(_anzahl_laeufe(repo, posten.strecke_id)),
        ablaeufe=repo.liste(Ablauf, sortierung=[Ablauf.name]),
    )


@router.post("/posten/{posten_id}/bearbeiten")
def posten_bearbeiten(
    request: Request, repo: SchulRepo, posten_id: int, name: Text = "", beschreibung: Text = ""
):
    posten = repo.holen(Posten, posten_id)
    if not name.strip():
        meldung(request, "Der Name darf nicht leer sein.", "fehler")
    else:
        posten.name = name.strip()
        posten.beschreibung = beschreibung.strip()
        repo.commit()
        meldung(request, "Gespeichert.")
    return weiter_zu(f"/verwaltung/posten/{posten.id}")


@router.post("/posten/{posten_id}/verschieben")
def posten_verschieben(request: Request, repo: SchulRepo, posten_id: int, richtung: Text = ""):
    posten = repo.holen(Posten, posten_id)
    strecke = posten.strecke
    if _struktur_aenderbar(request, repo, strecke) and richtung in ("hoch", "runter"):
        _verschieben(strecke.posten, posten, richtung)
        repo.commit()
    return weiter_zu(f"/verwaltung/strecken/{strecke.id}")


@router.post("/posten/{posten_id}/loeschen")
def posten_loeschen(request: Request, repo: SchulRepo, posten_id: int):
    posten = repo.holen(Posten, posten_id)
    strecke = posten.strecke
    if _struktur_aenderbar(request, repo, strecke):
        strecke.posten.remove(posten)
        repo.flush()
        _neu_nummerieren(strecke.posten)
        repo.commit()
        meldung(request, "Posten gelöscht.")
    return weiter_zu(f"/verwaltung/strecken/{strecke.id}")


# --------------------------------------------------------------------------- Items


@router.post("/posten/{posten_id}/items")
def item_anlegen(
    request: Request,
    repo: SchulRepo,
    posten_id: int,
    kurzbezeichnung: Text = "",
    beobachtungstext: Text = "",
    uebungstext: Text = "",
):
    posten = repo.holen(Posten, posten_id)
    if not _struktur_aenderbar(request, repo, posten.strecke):
        return weiter_zu(f"/verwaltung/posten/{posten.id}")
    fehler = _item_pruefen(kurzbezeichnung)
    if fehler:
        meldung(request, fehler, "fehler")
        return weiter_zu(f"/verwaltung/posten/{posten.id}")
    posten.items.append(
        Item(
            kurzbezeichnung=kurzbezeichnung.strip(),
            beobachtungstext=beobachtungstext.strip(),
            uebungstext=uebungstext.strip(),
            position=max((i.position for i in posten.items), default=0) + 1,
        )
    )
    repo.commit()
    meldung(request, "Item hinzugefügt.")
    return weiter_zu(f"/verwaltung/posten/{posten.id}")


def _item_pruefen(kurzbezeichnung: str) -> str | None:
    k = kurzbezeichnung.strip()
    if not k:
        return "Bitte eine Kurzbezeichnung angeben – sie steht auf dem Knopf am Posten."
    if len(k) > 40:
        return "Die Kurzbezeichnung ist zu lang (höchstens 40 Zeichen, sie muss auf den Knopf passen)."
    return None


@router.post("/items/{item_id}/bearbeiten")
def item_bearbeiten(
    request: Request,
    repo: SchulRepo,
    item_id: int,
    kurzbezeichnung: Text = "",
    beobachtungstext: Text = "",
    uebungstext: Text = "",
):
    item = repo.holen(Item, item_id)
    fehler = _item_pruefen(kurzbezeichnung)
    if fehler:
        meldung(request, fehler, "fehler")
    else:
        item.kurzbezeichnung = kurzbezeichnung.strip()
        item.beobachtungstext = beobachtungstext.strip()
        item.uebungstext = uebungstext.strip()
        repo.commit()
        meldung(request, "Gespeichert.")
    return weiter_zu(f"/verwaltung/posten/{item.posten_id}#item-{item.id}")


@router.post("/items/{item_id}/verschieben")
def item_verschieben(request: Request, repo: SchulRepo, item_id: int, richtung: Text = ""):
    item = repo.holen(Item, item_id)
    posten = item.posten
    if _struktur_aenderbar(request, repo, posten.strecke) and richtung in ("hoch", "runter"):
        _verschieben(posten.items, item, richtung)
        repo.commit()
    return weiter_zu(f"/verwaltung/posten/{posten.id}")


@router.post("/items/{item_id}/loeschen")
def item_loeschen(request: Request, repo: SchulRepo, item_id: int):
    item = repo.holen(Item, item_id)
    posten = item.posten
    if _struktur_aenderbar(request, repo, posten.strecke):
        posten.items.remove(item)
        repo.flush()
        _neu_nummerieren(posten.items)
        repo.commit()
        meldung(request, "Item gelöscht.")
    return weiter_zu(f"/verwaltung/posten/{posten.id}")
