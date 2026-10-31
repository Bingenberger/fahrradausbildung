"""Phosphor-Symbole als Inline-SVG für die Vorlagen.

Die Dateien liegen unter ``app/static/vendor/phosphor/regular/`` (Phosphor
Icons 2.1.1, MIT – siehe LIESMICH.txt dort). Eingebettet statt verlinkt, weil
das drei Dinge auf einmal löst: keine zusätzliche Anfrage je Seite, die Symbole
erben über ``fill="currentColor"`` die Textfarbe (auch im Fokus- und
Gefahr-Zustand), und die strenge Content-Security-Policy braucht weder eine
Schriftquelle noch eine Ausnahme für externe ``<use>``-Verweise.

Aufruf in den Vorlagen: ``{{ symbol("trash") }}`` bzw. ``{{ symbol("plus",
"symbol-gross") }}``. Ein unbekannter Name ist ein Fehler, kein leeres Bild –
``tests/test_gestaltung.py`` prüft alle in den Vorlagen verwendeten Namen.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from markupsafe import Markup, escape

SYMBOLE = Path(__file__).resolve().parent.parent / "static" / "vendor" / "phosphor" / "regular"

NAME_MUSTER = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_RAHMEN = re.compile(r"^<svg[^>]*>|</svg>\s*$")


class UnbekanntesSymbol(KeyError):
    """Name ohne Datei – meist ein Tippfehler in der Vorlage."""


@lru_cache(maxsize=256)
def _pfade(name: str) -> str:
    """Inhalt des <svg>-Elements; den Rahmen setzt ``symbol()`` selbst."""
    if not NAME_MUSTER.match(name):
        raise UnbekanntesSymbol(name)
    datei = SYMBOLE / f"{name}.svg"
    if not datei.is_file():
        raise UnbekanntesSymbol(name)
    return _RAHMEN.sub("", datei.read_text().strip())


def symbol(name: str, klasse: str = "") -> Markup:
    """Symbol als Inline-SVG. Größe und Farbe kommen aus dem CSS (``.symbol``).

    Immer ``aria-hidden``: Symbole stehen hier ausnahmslos neben ihrer
    Beschriftung, eine zweite Vorlesung wäre nur Lärm. Reine Symbolknöpfe
    tragen stattdessen ein ``aria-label``.
    """
    klassen = f"symbol {escape(klasse)}".strip() if klasse else "symbol"
    return Markup(
        f'<svg class="{klassen}" viewBox="0 0 256 256" fill="currentColor" '
        f'aria-hidden="true" focusable="false">{_pfade(name)}</svg>'
    )
