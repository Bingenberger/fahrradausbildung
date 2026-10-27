"""FastAPI-Abhängigkeiten für den Verwaltungsbereich.

Route-Handler bekommen ihren Datenzugang ausschließlich hierüber:

    @router.get("/strecken")
    def liste(repo: SchulRepo): ...

``SchulRepo`` ist an die Schule des angemeldeten Schuladmins gebunden,
``SystemRepo`` an den Systemadmin-Bereich. Eine falsche Rolle ergibt 404 –
wie eine fremde ID, ohne Rückschluss auf die Existenz der Seite.
"""

from __future__ import annotations

import hmac
from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request

from app.mandant import NichtGefunden, SchulRepository, Sitzungsfabrik, SystemRepository
from app.web.sitzung import COOKIE_NAME, SitzungsInfo, meldung_merken, sitzung_laden


class NichtAngemeldet(Exception):
    """Führt zur Weiterleitung auf die Anmeldeseite."""


class CsrfFehler(Exception):
    """Schreibende Anfrage ohne gültiges CSRF-Token."""


def fabrik(request: Request) -> Sitzungsfabrik:
    return request.app.state.fabrik


def sitzung_optional(request: Request) -> SitzungsInfo | None:
    if not hasattr(request.state, "sitzung"):
        request.state.sitzung = sitzung_laden(fabrik(request), request.cookies.get(COOKIE_NAME))
    return request.state.sitzung


def sitzung(request: Request) -> SitzungsInfo:
    info = sitzung_optional(request)
    if info is None:
        raise NichtAngemeldet
    return info


async def csrf_pruefen(request: Request) -> None:
    """Prüft bei jeder nicht lesenden Anfrage das Formularfeld ``csrf``."""
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    info = sitzung(request)
    formular = await request.form()
    gesendet = formular.get("csrf")
    if not isinstance(gesendet, str) or not hmac.compare_digest(gesendet, info.csrf_token):
        raise CsrfFehler


def schuladmin(request: Request) -> SitzungsInfo:
    info = sitzung(request)
    if info.rolle != "schuladmin" or info.schule_id is None:
        raise NichtGefunden("Seite")
    return info


def systemadmin(request: Request) -> SitzungsInfo:
    info = sitzung(request)
    if info.rolle != "systemadmin":
        raise NichtGefunden("Seite")
    return info


def _schul_repo(request: Request) -> Iterator[SchulRepository]:
    info = schuladmin(request)
    session = fabrik(request).mandant(info.schule_id)
    try:
        yield SchulRepository(session)
    finally:
        session.close()


def _system_repo(request: Request) -> Iterator[SystemRepository]:
    systemadmin(request)
    session = fabrik(request).systemadmin()
    try:
        yield SystemRepository(session)
    finally:
        session.close()


SchulRepo = Annotated[SchulRepository, Depends(_schul_repo)]
SystemRepo = Annotated[SystemRepository, Depends(_system_repo)]
Sitzung = Annotated[SitzungsInfo, Depends(sitzung)]

# Für APIRouter(dependencies=...): Rolle prüfen, dann CSRF.
SCHULADMIN_ROUTER = [Depends(schuladmin), Depends(csrf_pruefen)]
SYSTEMADMIN_ROUTER = [Depends(systemadmin), Depends(csrf_pruefen)]


def meldung(request: Request, text: str, art: str = "ok") -> None:
    """Einmal-Meldung für die nächste angezeigte Seite."""
    info = sitzung(request)
    meldung_merken(fabrik(request), info.id_hash, art, text)
