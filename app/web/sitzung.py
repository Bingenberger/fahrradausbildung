"""Serverseitige Sitzungen, Anmeldung und Einmal-Meldungen.

Arbeitet im Bereich INTERN – deshalb liegt dieses Modul bewusst außerhalb der
Route-Pakete ``app.verwaltung`` und ``app.system``.

Das Cookie enthält einen 256-Bit-Zufallswert; in der Datenbank steht nur dessen
SHA-256-Hash. Je Sitzung gibt es ein eigenes CSRF-Token (Synchronizer-Token).
"""

from __future__ import annotations

import hashlib
import secrets
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select

from app.config import einstellungen
from app.mandant import Sitzungsfabrik
from app.modelle import AdminSitzung, Benutzer, Schule
from app.sicherheit import passwort_braucht_rehash, passwort_hashen, passwort_pruefen

COOKIE_NAME = "fp_sitzung"
# Zum Ausgleich der Laufzeit, wenn es die E-Mail-Adresse nicht gibt.
_DUMMY_HASH = passwort_hashen(secrets.token_urlsafe(16))
# zuletzt_aktiv nicht bei jedem Seitenaufruf schreiben
_AKTIVITAET_SCHREIBEN_NACH = timedelta(seconds=60)


@dataclass(frozen=True)
class SitzungsInfo:
    id_hash: str
    benutzer_id: int
    email: str
    rolle: str
    schule_id: int | None
    schule_name: str | None
    csrf_token: str


def _hash(cookie_wert: str) -> str:
    return hashlib.sha256(cookie_wert.encode()).hexdigest()


def _jetzt() -> datetime:
    return datetime.now(UTC)


# --------------------------------------------------------------------------- Anmeldung


@dataclass(frozen=True)
class Anmeldeergebnis:
    benutzer_id: int
    rolle: str


def anmelden(fabrik: Sitzungsfabrik, email: str, passwort: str) -> Anmeldeergebnis | None:
    """Prüft die Zugangsdaten. ``None`` bei jedem Fehlschlag, ohne Begründung."""
    email = email.strip()
    with fabrik.intern_kontext() as s:
        benutzer = s.execute(
            select(Benutzer).where(func.lower(Benutzer.email) == email.lower())
        ).scalar_one_or_none()
        if benutzer is None:
            passwort_pruefen(_DUMMY_HASH, passwort)
            return None
        if not passwort_pruefen(benutzer.passwort_hash, passwort):
            return None
        if not benutzer.aktiv:
            return None
        if benutzer.schule_id is not None and not s.get(Schule, benutzer.schule_id).aktiv:
            return None
        if passwort_braucht_rehash(benutzer.passwort_hash):
            benutzer.passwort_hash = passwort_hashen(passwort)
        return Anmeldeergebnis(benutzer.id, benutzer.rolle)


class Fehlversuchsbremse:
    """Begrenzt fehlgeschlagene Anmeldungen je Schlüssel (E-Mail, IP) im Zeitfenster.

    Bewusst einfach und prozesslokal: Die Anwendung läuft als ein Prozess.
    """

    FENSTER_S = 15 * 60

    def __init__(self, maximum: int) -> None:
        self.maximum = maximum
        self._versuche: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _aufraeumen(self, schluessel: str, jetzt: float) -> deque[float]:
        q = self._versuche[schluessel]
        while q and q[0] < jetzt - self.FENSTER_S:
            q.popleft()
        return q

    def gesperrt(self, *schluessel: str) -> bool:
        jetzt = time.monotonic()
        with self._lock:
            return any(len(self._aufraeumen(k, jetzt)) >= self.maximum for k in schluessel)

    def fehlschlag(self, *schluessel: str) -> None:
        jetzt = time.monotonic()
        with self._lock:
            for k in schluessel:
                self._aufraeumen(k, jetzt).append(jetzt)

    def erfolg(self, *schluessel: str) -> None:
        with self._lock:
            for k in schluessel:
                self._versuche.pop(k, None)


# --------------------------------------------------------------------------- Sitzungen


def sitzung_anlegen(fabrik: Sitzungsfabrik, benutzer_id: int) -> str:
    """Legt eine neue Sitzung an und liefert den Cookie-Wert."""
    cookie_wert = secrets.token_urlsafe(32)
    jetzt = _jetzt()
    with fabrik.intern_kontext() as s:
        s.add(
            AdminSitzung(
                id_hash=_hash(cookie_wert),
                benutzer_id=benutzer_id,
                csrf_token=secrets.token_urlsafe(32),
                erstellt_am=jetzt,
                zuletzt_aktiv=jetzt,
                meldungen=[],
            )
        )
    return cookie_wert


def sitzung_laden(fabrik: Sitzungsfabrik, cookie_wert: str | None) -> SitzungsInfo | None:
    if not cookie_wert or len(cookie_wert) > 100:
        return None
    cfg = einstellungen()
    jetzt = _jetzt()
    with fabrik.intern_kontext() as s:
        sitzung = s.get(AdminSitzung, _hash(cookie_wert))
        if sitzung is None:
            return None
        abgelaufen = (
            jetzt - sitzung.zuletzt_aktiv > timedelta(minutes=cfg.sitzung_leerlauf_minuten)
            or jetzt - sitzung.erstellt_am > timedelta(hours=cfg.sitzung_max_stunden)
        )
        benutzer = sitzung.benutzer
        schule = s.get(Schule, benutzer.schule_id) if benutzer.schule_id else None
        # Deaktivierung von Benutzer oder Schule wirkt sofort, nicht erst beim nächsten Login.
        if abgelaufen or not benutzer.aktiv or (schule is not None and not schule.aktiv):
            s.delete(sitzung)
            return None
        if jetzt - sitzung.zuletzt_aktiv > _AKTIVITAET_SCHREIBEN_NACH:
            sitzung.zuletzt_aktiv = jetzt
        return SitzungsInfo(
            id_hash=sitzung.id_hash,
            benutzer_id=benutzer.id,
            email=benutzer.email,
            rolle=benutzer.rolle,
            schule_id=benutzer.schule_id,
            schule_name=schule.name if schule else None,
            csrf_token=sitzung.csrf_token,
        )


def sitzung_beenden(fabrik: Sitzungsfabrik, cookie_wert: str | None) -> None:
    if not cookie_wert:
        return
    with fabrik.intern_kontext() as s:
        s.execute(delete(AdminSitzung).where(AdminSitzung.id_hash == _hash(cookie_wert)))


def alle_sitzungen_beenden(fabrik: Sitzungsfabrik, benutzer_id: int, ausser: str | None = None):
    """Nach Passwortänderung: alle anderen Sitzungen des Benutzers beenden."""
    with fabrik.intern_kontext() as s:
        stmt = delete(AdminSitzung).where(AdminSitzung.benutzer_id == benutzer_id)
        if ausser:
            stmt = stmt.where(AdminSitzung.id_hash != ausser)
        s.execute(stmt)


def abgelaufene_sitzungen_loeschen(fabrik: Sitzungsfabrik) -> int:
    cfg = einstellungen()
    jetzt = _jetzt()
    with fabrik.intern_kontext() as s:
        ergebnis = s.execute(
            delete(AdminSitzung).where(
                (AdminSitzung.zuletzt_aktiv < jetzt - timedelta(minutes=cfg.sitzung_leerlauf_minuten))
                | (AdminSitzung.erstellt_am < jetzt - timedelta(hours=cfg.sitzung_max_stunden))
            )
        )
        return ergebnis.rowcount


# --------------------------------------------------------------------------- Meldungen


def meldung_merken(fabrik: Sitzungsfabrik, id_hash: str, art: str, text: str) -> None:
    with fabrik.intern_kontext() as s:
        sitzung = s.get(AdminSitzung, id_hash)
        if sitzung is not None:
            sitzung.meldungen = [*sitzung.meldungen, {"art": art, "text": text}]


def meldungen_abholen(fabrik: Sitzungsfabrik, id_hash: str) -> list[dict[str, str]]:
    with fabrik.intern_kontext() as s:
        sitzung = s.get(AdminSitzung, id_hash)
        if sitzung is None or not sitzung.meldungen:
            return []
        meldungen = list(sitzung.meldungen)
        sitzung.meldungen = []
        return meldungen


# --------------------------------------------------------------------------- Passwort


MIN_PASSWORTLAENGE = 10


def passwort_aendern(
    fabrik: Sitzungsfabrik, benutzer_id: int, altes: str, neues: str
) -> str | None:
    """Ändert das eigene Passwort. Liefert eine Fehlermeldung oder ``None``."""
    if len(neues) < MIN_PASSWORTLAENGE:
        return f"Das neue Passwort muss mindestens {MIN_PASSWORTLAENGE} Zeichen lang sein."
    with fabrik.intern_kontext() as s:
        benutzer = s.get(Benutzer, benutzer_id)
        if benutzer is None or not passwort_pruefen(benutzer.passwort_hash, altes):
            return "Das bisherige Passwort stimmt nicht."
        benutzer.passwort_hash = passwort_hashen(neues)
    return None


def zufallspasswort() -> str:
    """Gut abtippbares Startpasswort (ohne verwechselbare Zeichen)."""
    alphabet = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "-".join("".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(4))
