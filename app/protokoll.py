"""Logging ohne Tokens, Namen und Startnummern (Spezifikation 9).

Das Zugriffsprotokoll von uvicorn enthält den Pfad jeder Anfrage – bei der
Posten-App also das Token (/p/<token>, /api/p/<token>/…). Dieser Filter
schwärzt es, bevor etwas geschrieben wird.
"""

from __future__ import annotations

import logging
import re

_TOKEN_IM_PFAD = re.compile(r"(/p/)(?!assets/|sw\.js)[A-Za-z0-9_-]+")


def schwaerzen(text: str) -> str:
    return _TOKEN_IM_PFAD.sub(r"\1***", text)


class TokenFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):
            record.args = tuple(schwaerzen(a) if isinstance(a, str) else a for a in record.args)
        elif isinstance(record.args, dict):
            record.args = {k: schwaerzen(v) if isinstance(v, str) else v for k, v in record.args.items()}
        if isinstance(record.msg, str):
            record.msg = schwaerzen(record.msg)
        return True


def einrichten() -> None:
    """Filter an alle Logger hängen, die Pfade schreiben. Mehrfacher Aufruf ist harmlos."""
    for name in ("uvicorn.access", "uvicorn.error", "uvicorn", "fahrradpruefung", ""):
        logger = logging.getLogger(name)
        if not any(isinstance(f, TokenFilter) for f in logger.filters):
            logger.addFilter(TokenFilter())
        for handler in logger.handlers:
            if not any(isinstance(f, TokenFilter) for f in handler.filters):
                handler.addFilter(TokenFilter())
