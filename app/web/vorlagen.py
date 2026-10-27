"""Jinja2-Vorlagen des Verwaltungsbereichs."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.config import einstellungen
from app.formate import datum_kurz, datum_lang
from app.web.abhaengigkeiten import fabrik, sitzung_optional
from app.web.sitzung import meldungen_abholen

VORLAGEN = Path(__file__).resolve().parent.parent / "vorlagen"

templates = Jinja2Templates(directory=VORLAGEN)
templates.env.globals["STUFEN"] = {1: "sicher", 2: "teilweise sicher", 3: "unsicher"}


def _zeit(wert) -> str:
    if not wert:
        return "–"
    return wert.astimezone(ZoneInfo(einstellungen().zeitzone)).strftime("%d.%m.%Y, %H:%M Uhr")


templates.env.filters["datum"] = datum_kurz
templates.env.filters["datum_lang"] = datum_lang
templates.env.filters["zeit"] = _zeit


def seite(request: Request, name: str, status_code: int = 200, **kontext: Any) -> HTMLResponse:
    info = sitzung_optional(request)
    meldungen = meldungen_abholen(fabrik(request), info.id_hash) if info else []
    return templates.TemplateResponse(
        request,
        name,
        {"sitzung": info, "csrf": info.csrf_token if info else "", "meldungen": meldungen, **kontext},
        status_code=status_code,
    )


def weiter_zu(pfad: str) -> RedirectResponse:
    """Post/Redirect/Get: nach dem Speichern immer per 303 auf eine GET-Seite."""
    return RedirectResponse(pfad, status_code=303)
