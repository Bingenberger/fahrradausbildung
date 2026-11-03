"""Management-Kommandos.

    uv run python -m app.kommandos systemadmin-anlegen admin@example.org
    uv run python -m app.kommandos sitzungen-aufraeumen
    uv run python -m app.kommandos aufbewahrung [--monate 12] [--trocken]
"""

from __future__ import annotations

import argparse
import getpass
import sys

from sqlalchemy import func, select

from app.aufbewahrung import erfassungen_loeschen
from app.config import einstellungen
from app.db import sitzungen
from app.modelle import Benutzer
from app.sicherheit import passwort_hashen
from app.web.sitzung import MIN_PASSWORTLAENGE, abgelaufene_sitzungen_loeschen


def systemadmin_anlegen(email: str) -> int:
    try:
        tty=open("/dev/tty","r+")
    except OSError:
        print("Lokales kontrollierendes Terminal erforderlich.",file=sys.stderr)
        return 1
    passwort = getpass.getpass("Passwort: ",stream=tty)
    if len(passwort) < MIN_PASSWORTLAENGE:
        print(f"Das Passwort muss mindestens {MIN_PASSWORTLAENGE} Zeichen lang sein.", file=sys.stderr)
        return 1
    if getpass.getpass("Passwort wiederholen: ",stream=tty) != passwort:
        print("Die Passwörter stimmen nicht überein.", file=sys.stderr)
        return 1
    with sitzungen().intern_kontext() as s:
        if s.execute(select(Benutzer.id).where(func.lower(Benutzer.email) == email.lower())).first():
            print("Diese E-Mail-Adresse ist schon vergeben.", file=sys.stderr)
            return 1
        s.add(Benutzer(email=email, passwort_hash=passwort_hashen(passwort), rolle="systemadmin"))
    print("Systemadmin angelegt.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.kommandos")
    unter = parser.add_subparsers(dest="kommando", required=True)
    sa = unter.add_parser("systemadmin-anlegen", help="Systemadmin anlegen (Passwort wird abgefragt)")
    sa.add_argument("email")
    unter.add_parser("sitzungen-aufraeumen", help="Abgelaufene Anmeldesitzungen löschen")
    au = unter.add_parser(
        "aufbewahrung", help="Erfassungen von Läufen löschen, die älter als die Aufbewahrungsfrist sind"
    )
    au.add_argument("--monate", type=int, default=None, help="Frist in Monaten (Standard: FP_AUFBEWAHRUNG_MONATE)")
    au.add_argument("--trocken", action="store_true", help="Nur anzeigen, nichts löschen")
    args = parser.parse_args(argv)

    if args.kommando == "systemadmin-anlegen":
        return systemadmin_anlegen(args.email.strip())
    if args.kommando == "sitzungen-aufraeumen":
        print(f"{abgelaufene_sitzungen_loeschen(sitzungen())} abgelaufene Sitzungen gelöscht.")
        return 0
    if args.kommando == "aufbewahrung":
        monate = args.monate if args.monate is not None else einstellungen().aufbewahrung_monate
        try:
            e = erfassungen_loeschen(sitzungen(), monate, trocken=args.trocken)
        except ValueError as fehler:
            print(fehler, file=sys.stderr)
            return 1
        verb = "würden gelöscht" if args.trocken else "gelöscht"
        print(
            f"Frist {monate} Monate, Stichtag {e.stichtag.isoformat()}: "
            f"{e.ereignisse} Erfassungen aus {e.laeufe} Läufen {verb}."
        )
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
