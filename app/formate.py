"""Deutsche Datumsformate – unabhängig von der Locale des Servers."""

from datetime import date

WOCHENTAGE = ("Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag")
MONATE = (
    "Januar", "Februar", "März", "April", "Mai", "Juni",
    "Juli", "August", "September", "Oktober", "November", "Dezember",
)


def datum_kurz(d: date | None) -> str:
    return d.strftime("%d.%m.%Y") if d else ""


def datum_lang(d: date | None) -> str:
    """„Dienstag, 20. Oktober 2026\""""
    if not d:
        return ""
    return f"{WOCHENTAGE[d.weekday()]}, {d.day}. {MONATE[d.month - 1]} {d.year}"
