"""Posten-Tokens: Erzeugung, Gültigkeit, URL (Spezifikation 4.4, 6, 9)."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.config import einstellungen
from app.modelle import Lauf, PostenToken
from app.sicherheit import neues_token


def token_ablauf(datum: date) -> datetime:
    """Tokens laufen 24 Stunden nach dem Laufdatum ab.

    Auslegung: 24 Stunden nach dem *Ende* des Prüfungstags in Ortszeit – ein Lauf
    am 20.10. ist also bis 22.10., 0:00 Uhr nutzbar. So bleibt der Folgetag für
    einen verspäteten Upload, falls ein Gerät erst dann wieder ins WLAN kommt.
    """
    cfg = einstellungen()
    tagesende = datetime.combine(datum + timedelta(days=1), time(0), tzinfo=ZoneInfo(cfg.zeitzone))
    return (tagesende + timedelta(hours=cfg.token_gueltigkeit_stunden)).astimezone(UTC)


def tokens_erzeugen(lauf: Lauf) -> None:
    """Je Posten der Strecke ein Token, sofern noch keines existiert."""
    vorhanden = {t.posten_id for t in lauf.tokens}
    for posten in lauf.strecke.posten:
        if posten.id not in vorhanden:
            lauf.tokens.append(
                PostenToken(posten_id=posten.id, token=neues_token(), gueltig_bis=token_ablauf(lauf.datum))
            )


def token_erneuern(token: PostenToken, lauf: Lauf) -> None:
    token.token = neues_token()
    token.gueltig_bis = token_ablauf(lauf.datum)
    token.letzter_abruf = None


def tokens_entwerten(lauf: Lauf, jetzt: datetime | None = None) -> None:
    jetzt = jetzt or datetime.now(UTC)
    for t in lauf.tokens:
        t.gueltig_bis = min(t.gueltig_bis, jetzt)


def tokens_wiederherstellen(lauf: Lauf) -> None:
    for t in lauf.tokens:
        t.gueltig_bis = token_ablauf(lauf.datum)


def token_gueltig(token: PostenToken, lauf: Lauf, jetzt: datetime | None = None) -> bool:
    jetzt = jetzt or datetime.now(UTC)
    return lauf.status in ("vorbereitet", "laufend") and token.gueltig_bis > jetzt


def token_url(token: str) -> str:
    return f"{einstellungen().oeffentliche_url.rstrip('/')}/p/{token}"
