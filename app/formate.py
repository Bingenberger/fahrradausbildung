"""Deutsche Datums- und Zahlenformate – unabhängig von der Locale des Servers."""

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


def laenge_text(meter: float) -> str:
    """„480 m" / „2,35 km" – wie die Anzeige auf der Planungskarte."""
    if meter < 1:
        return "–"
    if meter < 1000:
        return f"{round(meter)} m"
    return f"{meter / 1000:.2f}".replace(".", ",") + " km"
