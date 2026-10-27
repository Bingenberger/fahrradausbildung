"""Eigenes Passwort ändern – gemeinsam für Schul- und Systemadmins."""

from __future__ import annotations

from fastapi import Request

from app.web.abhaengigkeiten import fabrik, meldung
from app.web.sitzung import SitzungsInfo, alle_sitzungen_beenden, passwort_aendern


def eigenes_passwort_aendern(request: Request, info: SitzungsInfo, alt: str, neu: str, neu2: str) -> None:
    if neu != neu2:
        meldung(request, "Die beiden neuen Passwörter stimmen nicht überein.", "fehler")
        return
    fehler = passwort_aendern(fabrik(request), info.benutzer_id, alt, neu)
    if fehler:
        meldung(request, fehler, "fehler")
        return
    # Andere Geräte abmelden, die aktuelle Sitzung bleibt bestehen.
    alle_sitzungen_beenden(fabrik(request), info.benutzer_id, ausser=info.id_hash)
    meldung(request, "Passwort geändert. Andere Anmeldungen wurden beendet.")


def sitzungen_beenden(request: Request, benutzer_id: int) -> None:
    """Alle Sitzungen eines (anderen) Benutzers beenden, z. B. nach Passwort-Reset."""
    alle_sitzungen_beenden(fabrik(request), benutzer_id)
