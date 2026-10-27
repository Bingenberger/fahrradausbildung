"""Anmeldung und Abmeldung (Spezifikation 5: E-Mail + Passwort, argon2id).

Das Anmeldeformular hat noch keine Sitzung; es ist per Double-Submit-Cookie
gegen CSRF geschützt (Login-CSRF).
"""

from __future__ import annotations

import hmac
import secrets
from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from app.config import einstellungen
from app.web.abhaengigkeiten import CsrfFehler, csrf_pruefen, fabrik, sitzung_optional
from app.web.sitzung import (
    COOKIE_NAME,
    Fehlversuchsbremse,
    anmelden,
    sitzung_anlegen,
    sitzung_beenden,
)
from app.web.vorlagen import seite, weiter_zu

router = APIRouter()

ANMELDE_CSRF_COOKIE = "fp_anmelde_csrf"
STARTSEITE = {"schuladmin": "/verwaltung/", "systemadmin": "/system"}


def _bremse(request: Request) -> Fehlversuchsbremse:
    app = request.app
    if not hasattr(app.state, "bremse"):
        app.state.bremse = Fehlversuchsbremse(einstellungen().anmeldung_max_fehlversuche)
    return app.state.bremse


def _anmeldeseite(request: Request, fehler: str | None = None, status_code: int = 200):
    token = secrets.token_urlsafe(32)
    antwort = seite(request, "anmelden.html", anmelde_csrf=token, fehler=fehler, status_code=status_code)
    antwort.set_cookie(
        ANMELDE_CSRF_COOKIE,
        token,
        httponly=True,
        secure=einstellungen().cookie_secure,
        samesite="strict",
        path="/anmelden",
    )
    return antwort


@router.get("/")
def wurzel(request: Request):
    info = sitzung_optional(request)
    return weiter_zu(STARTSEITE[info.rolle] if info else "/anmelden")


@router.get("/anmelden")
def anmeldeformular(request: Request):
    info = sitzung_optional(request)
    if info:
        return weiter_zu(STARTSEITE[info.rolle])
    return _anmeldeseite(request)


@router.post("/anmelden")
def anmelden_absenden(
    request: Request,
    email: Annotated[str, Form()] = "",
    passwort: Annotated[str, Form()] = "",
    csrf: Annotated[str, Form()] = "",
):
    cookie = request.cookies.get(ANMELDE_CSRF_COOKIE, "")
    if not cookie or not hmac.compare_digest(cookie, csrf):
        raise CsrfFehler

    bremse = _bremse(request)
    schluessel = (f"email:{email.strip().lower()}", f"ip:{request.client.host if request.client else '-'}")
    if bremse.gesperrt(*schluessel):
        return _anmeldeseite(
            request,
            "Zu viele Fehlversuche. Bitte warte 15 Minuten und versuche es dann erneut.",
            status_code=429,
        )

    ergebnis = anmelden(fabrik(request), email, passwort)
    if ergebnis is None:
        bremse.fehlschlag(*schluessel)
        return _anmeldeseite(request, "E-Mail-Adresse oder Passwort stimmen nicht.", status_code=401)

    bremse.erfolg(*schluessel)
    # Vorherige Sitzung dieses Browsers verwerfen (keine Sitzungsfixierung).
    sitzung_beenden(fabrik(request), request.cookies.get(COOKIE_NAME))
    cookie_wert = sitzung_anlegen(fabrik(request), ergebnis.benutzer_id)
    antwort = RedirectResponse(STARTSEITE[ergebnis.rolle], status_code=303)
    antwort.set_cookie(
        COOKIE_NAME,
        cookie_wert,
        httponly=True,
        secure=einstellungen().cookie_secure,
        samesite="lax",
        path="/",
    )
    antwort.delete_cookie(ANMELDE_CSRF_COOKIE, path="/anmelden")
    return antwort


@router.post("/abmelden")
async def abmelden(request: Request):
    if sitzung_optional(request) is not None:
        await csrf_pruefen(request)
    sitzung_beenden(fabrik(request), request.cookies.get(COOKIE_NAME))
    antwort = RedirectResponse("/anmelden", status_code=303)
    antwort.delete_cookie(COOKIE_NAME, path="/")
    return antwort
