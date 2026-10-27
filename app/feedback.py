"""Inhalt des Feedbackbogens (Spezifikation 8, Feedbackbogen).

Intern wird gerechnet, nach außen wird formuliert: Diese Funktion entscheidet nur,
*welche* Items in welche Liste kommen und welche Fahrsicherheits-Aussage passt.
Die Sätze selbst stehen in der austauschbaren Vorlage
``app/vorlagen/pdf/feedbackbogen.html`` – dort kann eine Schule sie umformulieren.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, Sequence

from app.auswertung import KindErgebnis

# Items mit einer Fehlerquote darunter „klappen schon gut".
GUT_UNTER = 0.25
# Nie mehr Übungspunkte – eine Liste mit acht Punkten übt niemand.
MAX_UEBUNGEN = 3


class ItemArtig(Protocol):
    id: int
    kurzbezeichnung: str
    uebungstext: str


class PostenArtig(Protocol):
    id: int
    items: Sequence[ItemArtig]


@dataclass
class Uebung:
    kurzbezeichnung: str
    uebungstext: str


@dataclass
class Feedback:
    gut: list[str] = field(default_factory=list)
    ueben: list[Uebung] = field(default_factory=list)
    # sicher | ueberwiegend_sicher | teilweise_unsicher | unsicher | None (keine Einschätzung)
    sicherheit: str | None = None
    hat_daten: bool = False


def _sicherheit(stufen: list[int]) -> str | None:
    if not stufen:
        return None
    if all(s == 1 for s in stufen):
        return "sicher"
    if all(s == 3 for s in stufen):
        return "unsicher"
    if 3 in stufen:
        return "teilweise_unsicher"
    return "ueberwiegend_sicher"


def feedback(ergebnis: KindErgebnis, posten: Sequence[PostenArtig]) -> Feedback:
    """Leitet den Bogen aus dem Ergebnis eines Kindes ab.

    Dasselbe Item (gleiche Kurzbezeichnung) kann an mehreren Posten vorkommen,
    etwa der Schulterblick. Für das Kind ist es *ein* Punkt; maßgeblich ist der
    Posten mit der höchsten Fehlerquote. So steht nichts zugleich unter „klappt
    gut" und „üben".
    """
    # Schlüssel -> (Quote, Reihenfolge auf der Strecke, Item)
    gruppen: dict[str, tuple[float, int, ItemArtig]] = {}
    reihenfolge = 0
    for p in posten:
        pe = ergebnis.posten.get(p.id)
        for item in p.items:
            reihenfolge += 1
            q = pe.items.get(item.id) if pe else None
            if q is None or q.quote is None:
                continue
            schluessel = item.kurzbezeichnung.strip().casefold()
            bisher = gruppen.get(schluessel)
            if bisher is None:
                gruppen[schluessel] = (q.quote, reihenfolge, item)
            elif q.quote > bisher[0]:
                gruppen[schluessel] = (q.quote, bisher[1], item)

    eintraege = sorted(gruppen.values(), key=lambda g: g[1])
    gut = [item.kurzbezeichnung.strip() for quote, _, item in eintraege if quote < GUT_UNTER]
    auffaellig = sorted((g for g in eintraege if g[0] >= GUT_UNTER), key=lambda g: (-g[0], g[1]))
    ueben = [
        Uebung(item.kurzbezeichnung.strip(), item.uebungstext.strip())
        for _, _, item in auffaellig[:MAX_UEBUNGEN]
    ]
    return Feedback(
        gut=gut,
        ueben=ueben,
        sicherheit=_sicherheit(ergebnis.stufen),
        hat_daten=bool(gruppen),
    )
