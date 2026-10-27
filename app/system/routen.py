"""Schulen anlegen und deaktivieren, Schuladmins verwalten (Spezifikation 5)."""

from __future__ import annotations

import re
from typing import Annotated

from fastapi import APIRouter, Form, Request
from sqlalchemy import func

from app.mandant import NichtGefunden
from app.modelle import Benutzer, Schule
from app.sicherheit import passwort_hashen
from app.web.abhaengigkeiten import SYSTEMADMIN_ROUTER, Sitzung, SystemRepo, meldung
from app.web.konto import eigenes_passwort_aendern, sitzungen_beenden
from app.web.sitzung import zufallspasswort
from app.web.vorlagen import seite, weiter_zu

router = APIRouter(prefix="/system", dependencies=SYSTEMADMIN_ROUTER)

Text = Annotated[str, Form()]

EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _schuladmin(repo, benutzer_id: int) -> Benutzer:
    benutzer = repo.holen(Benutzer, benutzer_id)
    if benutzer.rolle != "schuladmin":
        raise NichtGefunden("Benutzer")
    return benutzer


@router.get("")
@router.get("/")
def schulen(request: Request, repo: SystemRepo):
    alle = repo.liste(Schule, sortierung=[Schule.aktiv.desc(), Schule.name])
    return seite(request, "system/schulen.html", schulen=alle)


@router.post("/schulen/neu")
def schule_anlegen(request: Request, repo: SystemRepo, name: Text = "", kurzname: Text = ""):
    name, kurzname = name.strip(), kurzname.strip()
    if not name or not kurzname:
        meldung(request, "Bitte Name und Kurzname angeben.", "fehler")
        return weiter_zu("/system")
    if repo.liste(Schule, func.lower(Schule.kurzname) == kurzname.lower()):
        meldung(request, "Dieser Kurzname ist schon vergeben.", "fehler")
        return weiter_zu("/system")
    schule = repo.hinzufuegen(Schule(name=name, kurzname=kurzname))
    repo.commit()
    meldung(request, "Schule angelegt. Lege jetzt einen Schuladmin an.")
    return weiter_zu(f"/system/schulen/{schule.id}")


@router.get("/schulen/{schule_id}")
def schule_ansehen(request: Request, repo: SystemRepo, schule_id: int):
    schule = repo.holen(Schule, schule_id)
    admins = repo.liste(Benutzer, Benutzer.schule_id == schule.id, sortierung=[Benutzer.email])
    return seite(request, "system/schule.html", schule=schule, admins=admins)


@router.post("/schulen/{schule_id}/bearbeiten")
def schule_bearbeiten(request: Request, repo: SystemRepo, schule_id: int, name: Text = ""):
    schule = repo.holen(Schule, schule_id)
    if not name.strip():
        meldung(request, "Der Name darf nicht leer sein.", "fehler")
    else:
        schule.name = name.strip()
        repo.commit()
        meldung(request, "Gespeichert.")
    return weiter_zu(f"/system/schulen/{schule.id}")


@router.post("/schulen/{schule_id}/deaktivieren")
def schule_deaktivieren(request: Request, repo: SystemRepo, schule_id: int):
    schule = repo.holen(Schule, schule_id)
    schule.aktiv = False
    repo.commit()
    meldung(request, "Schule deaktiviert. Ihre Schuladmins können sich nicht mehr anmelden.")
    return weiter_zu(f"/system/schulen/{schule.id}")


@router.post("/schulen/{schule_id}/aktivieren")
def schule_aktivieren(request: Request, repo: SystemRepo, schule_id: int):
    schule = repo.holen(Schule, schule_id)
    schule.aktiv = True
    repo.commit()
    meldung(request, "Schule wieder aktiviert.")
    return weiter_zu(f"/system/schulen/{schule.id}")


@router.post("/schulen/{schule_id}/admins")
def schuladmin_anlegen(request: Request, repo: SystemRepo, schule_id: int, email: Text = ""):
    schule = repo.holen(Schule, schule_id)
    email = email.strip()
    if not EMAIL.match(email):
        meldung(request, "Bitte eine gültige E-Mail-Adresse angeben.", "fehler")
        return weiter_zu(f"/system/schulen/{schule.id}")
    if repo.liste(Benutzer, func.lower(Benutzer.email) == email.lower()):
        meldung(request, "Diese E-Mail-Adresse ist schon vergeben.", "fehler")
        return weiter_zu(f"/system/schulen/{schule.id}")
    passwort = zufallspasswort()
    repo.hinzufuegen(
        Benutzer(
            schule_id=schule.id,
            email=email,
            passwort_hash=passwort_hashen(passwort),
            rolle="schuladmin",
        )
    )
    repo.commit()
    return _passwort_anzeigen(request, schule, email, passwort)


def _passwort_anzeigen(request: Request, schule: Schule, email: str, passwort: str):
    # Das Startpasswort wird genau einmal angezeigt und nirgends gespeichert.
    antwort = seite(request, "system/passwort.html", schule=schule, email=email, passwort=passwort)
    antwort.headers["Cache-Control"] = "no-store"
    return antwort


@router.post("/benutzer/{benutzer_id}/deaktivieren")
def benutzer_deaktivieren(request: Request, repo: SystemRepo, benutzer_id: int):
    benutzer = _schuladmin(repo, benutzer_id)
    benutzer.aktiv = False
    repo.commit()
    meldung(request, "Schuladmin deaktiviert.")
    return weiter_zu(f"/system/schulen/{benutzer.schule_id}")


@router.post("/benutzer/{benutzer_id}/aktivieren")
def benutzer_aktivieren(request: Request, repo: SystemRepo, benutzer_id: int):
    benutzer = _schuladmin(repo, benutzer_id)
    benutzer.aktiv = True
    repo.commit()
    meldung(request, "Schuladmin wieder aktiviert.")
    return weiter_zu(f"/system/schulen/{benutzer.schule_id}")


@router.post("/benutzer/{benutzer_id}/passwort")
def passwort_zuruecksetzen(request: Request, repo: SystemRepo, benutzer_id: int):
    benutzer = _schuladmin(repo, benutzer_id)
    passwort = zufallspasswort()
    benutzer.passwort_hash = passwort_hashen(passwort)
    repo.commit()
    # Wer mit dem alten Passwort angemeldet ist, wird abgemeldet.
    sitzungen_beenden(request, benutzer.id)
    return _passwort_anzeigen(request, repo.holen(Schule, benutzer.schule_id), benutzer.email, passwort)


@router.get("/konto")
def konto(request: Request, _: SystemRepo):
    return seite(request, "konto.html", basis="/system")


@router.post("/konto/passwort")
def passwort(request: Request, info: Sitzung, _: SystemRepo, alt: Text = "", neu: Text = "", neu2: Text = ""):
    eigenes_passwort_aendern(request, info, alt, neu, neu2)
    return weiter_zu("/system/konto")
