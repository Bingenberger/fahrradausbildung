"""Auslieferung der Posten-App (Spezifikation 4.3, 6).

    /p/{token}                     App-Seite (für jedes Token dieselbe Hülle)
    /p/{token}/manifest.webmanifest  Manifest mit start_url genau dieses Postens
    /p/sw.js                       Service Worker, Geltungsbereich /p/
    /p/assets/…                    statische Dateien (JS, CSS, Symbole)

Die Version des Service Workers ist ein Hash über alle App-Dateien. Jede
Änderung an der App führt so automatisch zu einem neuen Cache.
"""

from __future__ import annotations

import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, JSONResponse, Response

POSTEN_APP = Path(__file__).resolve().parent.parent / "posten_app"
ASSET_PRAEFIX = "/p/assets/"
# Token-Zeichen (URL-sicheres Base64) bzw. „demo" für den Probebetrieb
TOKEN_MUSTER = re.compile(r"^[A-Za-z0-9_-]{4,100}$")

router = APIRouter()

KEIN_CACHE = {"Cache-Control": "no-cache"}


@lru_cache
def _assets() -> tuple[str, ...]:
    """Alle Dateien, die der Service Worker vorab speichert."""
    ausgenommen = {"index.html", "sw.js", "manifest.webmanifest"}
    return tuple(
        ASSET_PRAEFIX + p.relative_to(POSTEN_APP).as_posix()
        for p in sorted(POSTEN_APP.rglob("*"))
        if p.is_file() and p.name not in ausgenommen and not p.name.endswith(".LICENSE")
    )


@lru_cache
def _version() -> str:
    h = hashlib.sha256()
    for p in sorted(POSTEN_APP.rglob("*")):
        if p.is_file():
            h.update(p.relative_to(POSTEN_APP).as_posix().encode())
            h.update(p.read_bytes())
    return h.hexdigest()[:16]


@lru_cache
def _sw() -> str:
    quelle = (POSTEN_APP / "sw.js").read_text()
    return quelle.replace("__VERSION__", _version()).replace("__ASSETS__", json.dumps(list(_assets())))


def _gueltig(token: str) -> bool:
    return bool(TOKEN_MUSTER.match(token))


@router.get("/p/sw.js")
def service_worker():
    return Response(
        _sw(),
        media_type="text/javascript",
        headers={**KEIN_CACHE, "Service-Worker-Allowed": "/p/"},
    )


@router.get("/p/{token}")
def app_seite(token: str):
    # Das Token wird hier nicht geprüft: Die Seite ist für alle gleich, und
    # ob ein Token gilt, beantwortet allein die API. Keine Existenz-Auskunft.
    if not _gueltig(token):
        return Response(status_code=404)
    html = (POSTEN_APP / "index.html").read_text()
    html = html.replace("__MANIFEST__", f"/p/{token}/manifest.webmanifest")
    return HTMLResponse(html, headers=KEIN_CACHE)


@router.get("/p/{token}/manifest.webmanifest")
def manifest(token: str):
    if not _gueltig(token):
        return Response(status_code=404)
    return JSONResponse(
        {
            "name": "Fahrradprüfung – Posten",
            "short_name": "Posten",
            "lang": "de",
            "id": f"/p/{token}",
            "start_url": f"/p/{token}",
            "scope": "/p/",
            # Zwingend standalone: Bei minimal-ui greift Safaris 7-Tage-Löschung (Spezifikation 4.3).
            "display": "standalone",
            "orientation": "any",
            "background_color": "#ffffff",
            "theme_color": "#000000",
            "icons": [
                {"src": "/p/assets/icon-180.png", "sizes": "180x180", "type": "image/png"},
                {"src": "/p/assets/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"},
            ],
        },
        media_type="application/manifest+json",
        headers=KEIN_CACHE,
    )
