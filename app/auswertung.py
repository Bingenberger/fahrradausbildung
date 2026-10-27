"""Laufübersicht und Auswertung (Spezifikation 5.5 und 8).

Die Rechenfunktionen hier sind rein: Sie bekommen Ereignisse, Posten und
Startnummern und liefern Ergebnisse – ohne Datenbank. Namen gibt es in der
ganzen Anwendung nicht; die Klassenleitung ordnet sie auf Papier zu.

Regeln (gleich wie im Posten-Frontend, app/posten_app/js/logik.js):

- Maßgeblich ist je Schlüssel das jüngste Ereignis, geordnet nach ``erfasst_am``
  und bei Gleichstand nach ``event_id`` – so ist das Ergebnis eindeutig.
  Schlüssel: (startnummer, posten, durchgang_nr) bzw. (startnummer, posten) für
  die Fahrsicherheit.
- Ist das jüngste Durchgangs-Ereignis ein Storno (``storniert: true``), zählt
  der Durchgang nicht.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable, Protocol

# Stufen 1 = sicher, 2 = teilweise sicher, 3 = unsicher.
STUFEN_TEXT = {1: "sicher", 2: "teilweise sicher", 3: "unsicher"}

# Ab diesem Abstand zwischen der besten und der schlechtesten Einschätzung
# gelten die Posten als „stark abweichend": sicher gegenüber unsicher.
STARKE_ABWEICHUNG = 2


class EreignisArtig(Protocol):
    event_id: Any
    posten_id: int
    startnummer: int
    typ: str
    nutzlast: dict[str, Any]
    erfasst_am: datetime


def _reihenfolge(e: EreignisArtig) -> tuple[datetime, str]:
    return e.erfasst_am, str(e.event_id)


def juengste_ereignisse(
    ereignisse: Iterable[EreignisArtig],
) -> tuple[dict[tuple[int, int, int], EreignisArtig], dict[tuple[int, int], EreignisArtig]]:
    """Jüngstes Ereignis je Schlüssel.

    Liefert (durchgaenge, sicherheit):
    durchgaenge[(startnummer, posten_id, durchgang_nr)] und
    sicherheit[(startnummer, posten_id)].
    """
    durchgaenge: dict[tuple[int, int, int], EreignisArtig] = {}
    sicherheit: dict[tuple[int, int], EreignisArtig] = {}
    for e in ereignisse:
        if e.typ == "durchgang":
            k3 = (e.startnummer, e.posten_id, e.nutzlast["durchgang_nr"])
            bisher = durchgaenge.get(k3)
            if bisher is None or _reihenfolge(e) > _reihenfolge(bisher):
                durchgaenge[k3] = e
        elif e.typ == "sicherheit":
            k2 = (e.startnummer, e.posten_id)
            bisher = sicherheit.get(k2)
            if bisher is None or _reihenfolge(e) > _reihenfolge(bisher):
                sicherheit[k2] = e
    return durchgaenge, sicherheit


# --------------------------------------------------------------------------- Ergebnis je Kind


@dataclass
class ItemQuote:
    item_id: int
    vergessen: int
    gesamt: int

    @property
    def quote(self) -> float | None:
        return self.vergessen / self.gesamt if self.gesamt else None


@dataclass
class PostenErgebnis:
    posten_id: int
    durchgaenge: int = 0
    items: dict[int, ItemQuote] = field(default_factory=dict)
    stufe: int | None = None
    bemerkung: str | None = None


@dataclass
class KindErgebnis:
    startnummer: int
    posten: dict[int, PostenErgebnis] = field(default_factory=dict)

    @property
    def stufen(self) -> list[int]:
        return [p.stufe for p in self.posten.values() if p.stufe is not None]

    @property
    def stark_abweichend(self) -> bool:
        s = self.stufen
        return len(s) >= 2 and max(s) - min(s) >= STARKE_ABWEICHUNG

    @property
    def bemerkungen(self) -> list[tuple[int, str]]:
        return [(p.posten_id, p.bemerkung) for p in self.posten.values() if p.bemerkung]

    def alle_items(self) -> list[ItemQuote]:
        return [q for p in self.posten.values() for q in p.items.values()]


def auswerten(
    ereignisse: Iterable[EreignisArtig],
    items_je_posten: dict[int, list[int]],
    startnummern: Iterable[int],
) -> dict[int, KindErgebnis]:
    """Pro Kind und Item: vergessen / Durchgänge des zugehörigen Postens.

    ``items_je_posten`` bestimmt Posten und Items in Streckenreihenfolge.
    Ereignisse zu Startnummern, die nicht in ``startnummern`` stehen, erscheinen
    trotzdem (z. B. ein später deaktiviertes Kind).
    """
    durchgaenge, sicherheit = juengste_ereignisse(ereignisse)
    nummern = set(startnummern) | {k[0] for k in durchgaenge} | {k[0] for k in sicherheit}

    ergebnis: dict[int, KindErgebnis] = {}
    for nr in sorted(nummern):
        kind = KindErgebnis(nr)
        for posten_id, item_ids in items_je_posten.items():
            kind.posten[posten_id] = PostenErgebnis(
                posten_id, items={i: ItemQuote(i, 0, 0) for i in item_ids}
            )
        ergebnis[nr] = kind

    for (nr, posten_id, _), e in durchgaenge.items():
        if e.nutzlast.get("storniert") or posten_id not in items_je_posten:
            continue
        p = ergebnis[nr].posten[posten_id]
        p.durchgaenge += 1
        fehlend = set(e.nutzlast.get("fehlende_items", []))
        for item_id, q in p.items.items():
            q.gesamt += 1
            if item_id in fehlend:
                q.vergessen += 1

    for (nr, posten_id), e in sicherheit.items():
        if posten_id not in items_je_posten:
            continue
        p = ergebnis[nr].posten[posten_id]
        p.stufe = e.nutzlast["stufe"]
        p.bemerkung = e.nutzlast.get("bemerkung")

    return ergebnis


# --------------------------------------------------------------------------- Laufübersicht


@dataclass
class PostenStand:
    posten_id: int
    ereignisse: int = 0
    # Startnummer -> Anzahl gültiger Durchgänge (nach Storno).
    durchgaenge: dict[int, int] = field(default_factory=dict)
    # Startnummern mit Fahrsicherheits-Einschätzung.
    sicherheit: set[int] = field(default_factory=set)

    @property
    def mit_daten(self) -> set[int]:
        return {nr for nr, n in self.durchgaenge.items() if n} | self.sicherheit

    def fehlend(self, startnummern: Iterable[int]) -> list[int]:
        """Startnummern ohne gültigen Durchgang an diesem Posten."""
        return sorted(nr for nr in startnummern if not self.durchgaenge.get(nr))

    def ohne_sicherheit(self, startnummern: Iterable[int]) -> list[int]:
        return sorted(nr for nr in startnummern if nr not in self.sicherheit)


def laufstand(ereignisse: Iterable[EreignisArtig], posten_ids: Iterable[int]) -> dict[int, PostenStand]:
    liste = list(ereignisse)
    stand = {pid: PostenStand(pid) for pid in posten_ids}
    for e in liste:
        if e.posten_id in stand:
            stand[e.posten_id].ereignisse += 1
    durchgaenge, sicherheit = juengste_ereignisse(liste)
    for (nr, pid, _), e in durchgaenge.items():
        if pid in stand and not e.nutzlast.get("storniert"):
            stand[pid].durchgaenge[nr] = stand[pid].durchgaenge.get(nr, 0) + 1
    for nr, pid in sicherheit:
        if pid in stand:
            stand[pid].sicherheit.add(nr)
    return stand
