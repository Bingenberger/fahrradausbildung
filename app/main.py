"""Anwendung: Verwaltungsbereich, Systemadmin-Oberfläche, Anmeldung.

Start (Entwicklung):  uv run uvicorn app.main:app --reload
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, text
from app.betrieb import BodyLimit
from sqlalchemy.exc import SQLAlchemyError

from app import protokoll, system, verwaltung
from app.mandant import Mandantenverletzung, NichtGefunden, Sitzungsfabrik
from app.modelle import Schule
from app.posten import api as posten_api
from app.posten import seiten as posten_seiten
from app.web import anmeldung
from app.web.abhaengigkeiten import CsrfFehler, NichtAngemeldet
from app.web.header import Sicherheitsheader
from app.web.vorlagen import seite

STATIC = Path(__file__).resolve().parent / "static"

log = logging.getLogger("fahrradpruefung")


def erstelle_app(fabrik: Sitzungsfabrik | None = None) -> FastAPI:
    app = FastAPI(
        title="Fahrradprüfung", docs_url=None, redoc_url=None, openapi_url=None
    )
    if fabrik is None:
        from app.db import sitzungen

        fabrik = sitzungen()
    app.state.fabrik = fabrik

    protokoll.einrichten()

    # Verwaltungsseiten enthalten Auswertungen: nie zwischenspeichern.
    # (Die Posten-App setzt eigene Cache-Header; Offline übernimmt der Service Worker.)
    app.add_middleware(BodyLimit)
    app.add_middleware(Sicherheitsheader, cache="no-store")
    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    app.mount("/p/assets", StaticFiles(directory=posten_seiten.POSTEN_APP), name="posten_assets")
    app.include_router(posten_seiten.router)
    app.include_router(posten_api.router)
    app.include_router(anmeldung.router)
    app.include_router(verwaltung.router)
    app.include_router(system.router)

    @app.get("/health/live", include_in_schema=False)
    def live():
        return {"ok": True}

    @app.get("/gesund", include_in_schema=False)
    @app.get("/health/ready", include_in_schema=False)
    def gesund():
        try:
            with fabrik.intern_kontext() as session:
                revision=session.execute(text("SELECT version_num FROM alembic_version")).scalars().all()
                if revision!=["0008"]:
                    return JSONResponse({"ok":False},status_code=503)
                session.execute(select(Schule.id).limit(1))
        except SQLAlchemyError:
            return JSONResponse({"ok":False},status_code=503)
        return {"ok":True}

    @app.exception_handler(SQLAlchemyError)
    async def unavailable(request,exc):
        log.error("Database operation unavailable")
        return JSONResponse({"fehler":"Dienst derzeit nicht verfügbar"},status_code=503)

    @app.exception_handler(NichtAngemeldet)
    async def _nicht_angemeldet(request: Request, exc: NichtAngemeldet):
        return RedirectResponse("/anmelden", status_code=303)

    @app.exception_handler(NichtGefunden)
    async def _nicht_gefunden(request: Request, exc: NichtGefunden):
        return seite(request, "fehler.html", status_code=404, titel="Nicht gefunden",
                     text="Diese Seite gibt es nicht.")

    @app.exception_handler(Mandantenverletzung)
    async def _mandantenverletzung(request: Request, exc: Mandantenverletzung):
        # Wie „nicht gefunden" beantworten – kein Rückschluss auf fremde Daten.
        log.warning("Mandantenverletzung abgewiesen: %s %s", request.method, request.url.path)
        return seite(request, "fehler.html", status_code=404, titel="Nicht gefunden",
                     text="Diese Seite gibt es nicht.")

    @app.exception_handler(CsrfFehler)
    async def _csrf(request: Request, exc: CsrfFehler):
        return seite(request, "fehler.html", status_code=403, titel="Formular abgelaufen",
                     text="Das Formular ist abgelaufen. Bitte lade die Seite neu und versuche es noch einmal.")

    @app.exception_handler(RequestValidationError)
    async def _ungueltig(request: Request, exc: RequestValidationError):
        if request.url.path.startswith("/api/"):
            # Eingaben bewusst nicht zurückspiegeln.
            return JSONResponse({"fehler": "ungültige Anfrage"}, status_code=422)
        # Z. B. /verwaltung/strecken/abc – wie eine unbekannte Seite behandeln.
        # Bewusst ohne exc im Log: Formularwerte könnten Namen enthalten.
        return seite(request, "fehler.html", status_code=404, titel="Nicht gefunden",
                     text="Diese Seite gibt es nicht.")

    return app


def __getattr__(name: str):
    # ``app.main:app`` für uvicorn – erst beim Zugriff erzeugen, damit Tests ohne
    # Datenbankverbindung importieren können.
    if name == "app":
        global app
        app = erstelle_app()
        return app
    raise AttributeError(name)
