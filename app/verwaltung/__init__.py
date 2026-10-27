"""Verwaltungsbereich des Schuladmins.

Route-Handler in diesem Paket greifen ausschließlich über ``SchulRepo`` auf
Daten zu (geprüft durch tests/test_architektur.py).
"""

from fastapi import APIRouter

from app.verwaltung import ablaeufe, auswertung, export, gruppen, karte, konto, laeufe, strecken

router = APIRouter(prefix="/verwaltung")
router.include_router(konto.router)
router.include_router(strecken.router)
router.include_router(gruppen.router)
router.include_router(laeufe.router)
router.include_router(auswertung.router)
router.include_router(export.router)
router.include_router(karte.router)
router.include_router(ablaeufe.router)
