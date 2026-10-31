"""Wiederkehrende Handlungsabläufe als Vorlage für Posten.

Ein Ablauf (z. B. „Linksabbiegen") ist eine benannte Liste von Handlungsschritten
mit denselben drei Texten wie ein Item. Beim Einfügen in einen Posten werden die
Schritte als Items *kopiert*; danach sind Posten und Ablauf unabhängig. So
verändert eine spätere Anpassung des Ablaufs nie einen Posten, an dem schon
Erfassungen hängen.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Form, Request

from app.beispielablaeufe import BEISPIELE
from app.mandant import SchulRepository
from app.modelle import Ablauf, AblaufSchritt, Item, Posten
from app.verwaltung.strecken import _neu_nummerieren, _struktur_aenderbar, _verschieben, item_pruefen
from app.web.abhaengigkeiten import SCHULADMIN_ROUTER, SchulRepo, meldung
from app.web.vorlagen import seite, weiter_zu

router = APIRouter(dependencies=SCHULADMIN_ROUTER)

Text = Annotated[str, Form()]


def _schluessel(text: str) -> str:
    return text.strip().casefold()


# --------------------------------------------------------------------------- Abläufe


@router.get("/ablaeufe")
def ablaeufe(request: Request, repo: SchulRepo):
    alle = repo.liste(Ablauf, sortierung=[Ablauf.name])
    vorhanden = {_schluessel(a.name) for a in alle}
    return seite(
        request,
        "verwaltung/ablaeufe.html",
        ablaeufe=alle,
        fehlende_beispiele=[b[0] for b in BEISPIELE if _schluessel(b[0]) not in vorhanden],
    )


@router.post("/ablaeufe/neu")
def ablauf_anlegen(request: Request, repo: SchulRepo, name: Text = "", beschreibung: Text = ""):
    if not name.strip():
        meldung(request, "Bitte einen Namen angeben, z. B. „Linksabbiegen“.", "fehler")
        return weiter_zu("/verwaltung/ablaeufe")
    ablauf = repo.hinzufuegen(Ablauf(name=name.strip(), beschreibung=beschreibung.strip()))
    repo.commit()
    meldung(request, "Ablauf angelegt. Füge jetzt die Handlungsschritte hinzu.")
    return weiter_zu(f"/verwaltung/ablaeufe/{ablauf.id}")


@router.post("/ablaeufe/beispiele")
def beispiele_uebernehmen(request: Request, repo: SchulRepo):
    vorhanden = {_schluessel(a.name) for a in repo.liste(Ablauf)}
    neu = 0
    for name, beschreibung, schritte in BEISPIELE:
        if _schluessel(name) in vorhanden:
            continue
        ablauf = Ablauf(name=name, beschreibung=beschreibung)
        ablauf.schritte = [
            AblaufSchritt(kurzbezeichnung=k, beobachtungstext=b, uebungstext=u, position=i)
            for i, (k, b, u) in enumerate(schritte, 1)
        ]
        repo.hinzufuegen(ablauf)
        neu += 1
    repo.commit()
    if neu:
        meldung(request, f"{neu} Beispielabläufe übernommen. Passe sie an eure Ausbildung an.")
    else:
        meldung(request, "Alle Beispielabläufe sind schon vorhanden.")
    return weiter_zu("/verwaltung/ablaeufe")


@router.get("/ablaeufe/{ablauf_id}")
def ablauf_ansehen(request: Request, repo: SchulRepo, ablauf_id: int):
    return seite(request, "verwaltung/ablauf.html", ablauf=repo.holen(Ablauf, ablauf_id))


@router.post("/ablaeufe/{ablauf_id}/bearbeiten")
def ablauf_bearbeiten(request: Request, repo: SchulRepo, ablauf_id: int, name: Text = "", beschreibung: Text = ""):
    ablauf = repo.holen(Ablauf, ablauf_id)
    if not name.strip():
        meldung(request, "Der Name darf nicht leer sein.", "fehler")
    else:
        ablauf.name = name.strip()
        ablauf.beschreibung = beschreibung.strip()
        repo.commit()
        meldung(request, "Gespeichert.")
    return weiter_zu(f"/verwaltung/ablaeufe/{ablauf.id}")


@router.post("/ablaeufe/{ablauf_id}/loeschen")
def ablauf_loeschen(request: Request, repo: SchulRepo, ablauf_id: int):
    ablauf = repo.holen(Ablauf, ablauf_id)
    repo.loeschen(ablauf)
    repo.commit()
    meldung(request, "Ablauf gelöscht. Posten, in die er eingefügt wurde, behalten ihre Items.")
    return weiter_zu("/verwaltung/ablaeufe")


# --------------------------------------------------------------------------- Schritte


@router.post("/ablaeufe/{ablauf_id}/schritte")
def schritt_anlegen(
    request: Request,
    repo: SchulRepo,
    ablauf_id: int,
    kurzbezeichnung: Text = "",
    beobachtungstext: Text = "",
    uebungstext: Text = "",
):
    ablauf = repo.holen(Ablauf, ablauf_id)
    fehler = item_pruefen(kurzbezeichnung)
    if fehler:
        meldung(request, fehler, "fehler")
    else:
        ablauf.schritte.append(
            AblaufSchritt(
                kurzbezeichnung=kurzbezeichnung.strip(),
                beobachtungstext=beobachtungstext.strip(),
                uebungstext=uebungstext.strip(),
                position=max((s.position for s in ablauf.schritte), default=0) + 1,
            )
        )
        repo.commit()
        meldung(request, "Schritt hinzugefügt.")
    return weiter_zu(f"/verwaltung/ablaeufe/{ablauf.id}")


@router.post("/ablaufschritte/{schritt_id}/bearbeiten")
def schritt_bearbeiten(
    request: Request,
    repo: SchulRepo,
    schritt_id: int,
    kurzbezeichnung: Text = "",
    beobachtungstext: Text = "",
    uebungstext: Text = "",
):
    schritt = repo.holen(AblaufSchritt, schritt_id)
    fehler = item_pruefen(kurzbezeichnung)
    if fehler:
        meldung(request, fehler, "fehler")
    else:
        schritt.kurzbezeichnung = kurzbezeichnung.strip()
        schritt.beobachtungstext = beobachtungstext.strip()
        schritt.uebungstext = uebungstext.strip()
        repo.commit()
        meldung(request, "Gespeichert.")
    return weiter_zu(f"/verwaltung/ablaeufe/{schritt.ablauf_id}#schritt-{schritt.id}")


@router.post("/ablaufschritte/{schritt_id}/verschieben")
def schritt_verschieben(request: Request, repo: SchulRepo, schritt_id: int, richtung: Text = ""):
    schritt = repo.holen(AblaufSchritt, schritt_id)
    if richtung in ("hoch", "runter"):
        _verschieben(schritt.ablauf.schritte, schritt, richtung)
        repo.commit()
    return weiter_zu(f"/verwaltung/ablaeufe/{schritt.ablauf_id}")


@router.post("/ablaufschritte/{schritt_id}/loeschen")
def schritt_loeschen(request: Request, repo: SchulRepo, schritt_id: int):
    schritt = repo.holen(AblaufSchritt, schritt_id)
    ablauf = schritt.ablauf
    ablauf.schritte.remove(schritt)
    repo.flush()
    _neu_nummerieren(ablauf.schritte)
    repo.commit()
    meldung(request, "Schritt gelöscht.")
    return weiter_zu(f"/verwaltung/ablaeufe/{ablauf.id}")


# --------------------------------------------------------------------------- Posten ↔ Ablauf


def _ablauf_aus_formular(repo: SchulRepository, roh: str) -> Ablauf | None:
    try:
        ablauf_id = int(roh)
    except ValueError:
        return None
    # Fremde oder unbekannte ID: 404 wie überall (NichtGefunden aus repo.holen)
    return repo.holen(Ablauf, ablauf_id)


@router.post("/posten/{posten_id}/ablauf-einfuegen")
def ablauf_einfuegen(request: Request, repo: SchulRepo, posten_id: int, ablauf_id: Text = ""):
    """Kopiert die Schritte eines Ablaufs als Items ans Ende des Postens.

    Schritte, deren Kurzbezeichnung der Posten schon hat, werden übersprungen –
    zwei gleiche Knöpfe am iPad wären verwirrend.
    """
    posten = repo.holen(Posten, posten_id)
    ablauf = _ablauf_aus_formular(repo, ablauf_id)
    if ablauf is None:
        meldung(request, "Bitte einen Ablauf auswählen.", "fehler")
        return weiter_zu(f"/verwaltung/posten/{posten.id}")
    if not _struktur_aenderbar(request, repo, posten.strecke):
        return weiter_zu(f"/verwaltung/posten/{posten.id}")

    vorhanden = {_schluessel(i.kurzbezeichnung) for i in posten.items}
    position = max((i.position for i in posten.items), default=0)
    neu, uebersprungen = 0, []
    for s in ablauf.schritte:
        if _schluessel(s.kurzbezeichnung) in vorhanden:
            uebersprungen.append(s.kurzbezeichnung)
            continue
        position += 1
        posten.items.append(
            Item(
                kurzbezeichnung=s.kurzbezeichnung,
                beobachtungstext=s.beobachtungstext,
                uebungstext=s.uebungstext,
                position=position,
            )
        )
        vorhanden.add(_schluessel(s.kurzbezeichnung))
        neu += 1
    repo.commit()
    text = f"„{ablauf.name}“ eingefügt: {neu} Items."
    if uebersprungen:
        text += f" Schon vorhanden und übersprungen: {', '.join(uebersprungen)}."
    meldung(request, text)
    return weiter_zu(f"/verwaltung/posten/{posten.id}")


@router.post("/posten/{posten_id}/als-ablauf")
def als_ablauf_speichern(request: Request, repo: SchulRepo, posten_id: int, name: Text = ""):
    posten = repo.holen(Posten, posten_id)
    if not posten.items:
        meldung(request, "Der Posten hat noch keine Items.", "fehler")
        return weiter_zu(f"/verwaltung/posten/{posten.id}")
    if not name.strip():
        meldung(request, "Bitte einen Namen für den Ablauf angeben.", "fehler")
        return weiter_zu(f"/verwaltung/posten/{posten.id}")
    ablauf = Ablauf(name=name.strip())
    ablauf.schritte = [
        AblaufSchritt(
            kurzbezeichnung=i.kurzbezeichnung,
            beobachtungstext=i.beobachtungstext,
            uebungstext=i.uebungstext,
            position=n,
        )
        for n, i in enumerate(posten.items, 1)
    ]
    repo.hinzufuegen(ablauf)
    repo.commit()
    meldung(request, f"Ablauf „{ablauf.name}“ mit {len(ablauf.schritte)} Schritten gespeichert.")
    return weiter_zu(f"/verwaltung/ablaeufe/{ablauf.id}")

