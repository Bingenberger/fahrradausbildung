"""Löschung der Erfassungsdaten nach Ablauf der Aufbewahrungsfrist (Spezifikation 9).

Bewusst kein Hintergrundprozess: Das Kommando ``python -m app.kommandos aufbewahrung``
wird von außen aufgerufen (z. B. per cron, siehe README) und meldet, was es tut.

Maßgeblich ist das Laufdatum: Ist es älter als die Frist, werden *alle* Ereignisse
dieses Laufs gelöscht – nie nur ein Teil, sonst wäre eine Auswertung unvollständig,
ohne dass es jemand merkt. Der Lauf selbst bleibt mit ``daten_geloescht_am`` stehen,
damit die Verwaltung erklären kann, warum keine Erfassungen mehr da sind.
"""

from __future__ import annotations

import calendar
import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy import delete, func, select, update

from app.mandant import Sitzungsfabrik
from app.modelle import Ereignis, Lauf

log = logging.getLogger(__name__)


def monate_zurueck(tag: date, monate: int) -> date:
    """Gleicher Kalendertag ``monate`` Monate früher; 31. → letzter Tag des Monats."""
    jahr, monat = divmod(tag.year * 12 + tag.month - 1 - monate, 12)
    monat += 1
    return date(jahr, monat, min(tag.day, calendar.monthrange(jahr, monat)[1]))


@dataclass
class Ergebnis:
    stichtag: date
    laeufe: int
    ereignisse: int


def erfassungen_loeschen(fabrik: Sitzungsfabrik, monate: int, heute: date | None = None, trocken: bool = False) -> Ergebnis:
    """Löscht die Ereignisse aller Läufe, deren Datum vor dem Stichtag liegt.

    Unabhängig vom Status: Auch ein vergessener, nie abgeschlossener Lauf darf
    seine Daten nicht länger behalten. Er wird dabei archiviert.
    """
    if monate < 1:
        raise ValueError("Die Aufbewahrungsfrist muss mindestens einen Monat betragen.")
    stichtag = monate_zurueck(heute or date.today(), monate)
    with fabrik.intern_kontext() as s:
        lauf_ids = list(
            s.scalars(
                select(Lauf.id).where(
                    Lauf.datum < stichtag,
                    Lauf.daten_geloescht_am.is_(None),
                )
            )
        )
        if not lauf_ids:
            return Ergebnis(stichtag, 0, 0)
        anzahl = s.execute(
            select(func.count()).select_from(Ereignis).where(Ereignis.lauf_id.in_(lauf_ids))
        ).scalar_one()
        if trocken:
            s.rollback()
            return Ergebnis(stichtag, len(lauf_ids), anzahl)
        s.execute(delete(Ereignis).where(Ereignis.lauf_id.in_(lauf_ids)))
        s.execute(
            update(Lauf)
            .where(Lauf.id.in_(lauf_ids))
            .values(daten_geloescht_am=datetime.now(UTC), status="archiviert")
        )
        for lauf_id in lauf_ids:
            log.info("Aufbewahrungsfrist: Erfassungen gelöscht lauf_id=%s", lauf_id)
    return Ergebnis(stichtag, len(lauf_ids), anzahl)
