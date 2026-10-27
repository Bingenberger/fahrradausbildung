"""Auswertung eines Laufs in der Verwaltung (Spezifikation 8, Aggregation).

Die Anwendung kennt nur Startnummern; die Zuordnung zu Namen hat die
Klassenleitung auf ihrer Papierliste (Namensliste der Gruppe).
Die Zahlen sind für die Lehrkraft; der Feedbackbogen formuliert sie später
ohne Quoten.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import APIRouter, Request
from fastapi.responses import Response

from app.auswertung import STUFEN_TEXT, KindErgebnis, auswerten
from app.feedback import feedback
from app.mandant import NichtGefunden, SchulRepository
from app.modelle import Kind, Lauf, Posten, Schule
from app.pdf import feedbackboegen_pdf
from app.verwaltung.laeufe import STATUS_TEXT, ereignisse_des_laufs, kinder_des_laufs
from app.web.abhaengigkeiten import SCHULADMIN_ROUTER, SchulRepo, meldung
from app.web.vorlagen import seite, weiter_zu

router = APIRouter(dependencies=SCHULADMIN_ROUTER)


@dataclass
class Zeile:
    kind: Kind
    ergebnis: KindErgebnis


def lauf_auswerten(repo: SchulRepository, lauf: Lauf) -> tuple[list[Posten], list[Zeile]]:
    """Ergebnis je Kind in Startnummern-Reihenfolge.

    Aktive Kinder erscheinen immer, inaktive nur mit vorhandenen Erfassungen.
    """
    posten = lauf.strecke.posten
    kinder = {k.startnummer: k for k in kinder_des_laufs(repo, lauf)}
    ergebnisse = auswerten(
        ereignisse_des_laufs(repo, lauf.id),
        {p.id: [i.id for i in p.items] for p in posten},
        [nr for nr, k in kinder.items() if k.aktiv],
    )
    # Ereignisse gibt es nur zu Startnummern der Gruppe (die API prüft das).
    zeilen = [Zeile(kinder[nr], erg) for nr, erg in ergebnisse.items() if nr in kinder]
    return posten, zeilen


def _zeile_des_kindes(repo: SchulRepository, lauf: Lauf, kind_id: int) -> tuple[list[Posten], list[Zeile], int]:
    kind = repo.holen(Kind, kind_id)
    if kind.gruppe_id != lauf.gruppe_id:
        raise NichtGefunden(Kind, kind_id)
    posten, zeilen = lauf_auswerten(repo, lauf)
    for i, z in enumerate(zeilen):
        if z.kind.id == kind.id:
            return posten, zeilen, i
    raise NichtGefunden(Kind, kind_id)  # inaktiv und ohne Erfassungen


def _pdf(inhalt: bytes, dateiname: str) -> Response:
    return Response(
        inhalt, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{dateiname}"'}
    )


@router.get("/laeufe/{lauf_id}/auswertung")
def auswertung(request: Request, repo: SchulRepo, lauf_id: int):
    lauf = repo.holen(Lauf, lauf_id)
    posten, zeilen = lauf_auswerten(repo, lauf)
    ohne_bogen = [z.kind for z in zeilen if not feedback(z.ergebnis, posten).hat_daten]
    return seite(
        request,
        "verwaltung/auswertung.html",
        lauf=lauf,
        posten=posten,
        zeilen=zeilen,
        abweichend=[z for z in zeilen if z.ergebnis.stark_abweichend],
        ohne_bogen=ohne_bogen,
        status_text=STATUS_TEXT,
        stufen_text=STUFEN_TEXT,
    )


@router.get("/laeufe/{lauf_id}/kinder/{kind_id}")
def kind_auswertung(request: Request, repo: SchulRepo, lauf_id: int, kind_id: int):
    lauf = repo.holen(Lauf, lauf_id)
    posten, zeilen, i = _zeile_des_kindes(repo, lauf, kind_id)
    zeile = zeilen[i]
    return seite(
        request,
        "verwaltung/kind_auswertung.html",
        lauf=lauf,
        posten=posten,
        z=zeile,
        vorher=zeilen[i - 1].kind if i > 0 else None,
        nachher=zeilen[i + 1].kind if i + 1 < len(zeilen) else None,
        stufen_text=STUFEN_TEXT,
    )


@router.get("/laeufe/{lauf_id}/feedbackboegen.pdf")
def feedbackboegen(request: Request, repo: SchulRepo, lauf_id: int):
    """Sammel-PDF: ein Bogen je Kind, von dem Erfassungen vorliegen."""
    lauf = repo.holen(Lauf, lauf_id)
    posten, zeilen = lauf_auswerten(repo, lauf)
    boegen = [{"kind": z.kind, "feedback": feedback(z.ergebnis, posten)} for z in zeilen]
    boegen = [b for b in boegen if b["feedback"].hat_daten]
    if not boegen:
        meldung(request, "Noch keine Erfassungen – es gibt noch keine Feedbackbögen.", "fehler")
        return weiter_zu(f"/verwaltung/laeufe/{lauf.id}/auswertung")
    pdf = feedbackboegen_pdf(repo.holen(Schule, repo.schule_id), lauf, boegen)
    return _pdf(pdf, f"feedbackboegen-{lauf.datum.isoformat()}.pdf")


@router.get("/laeufe/{lauf_id}/kinder/{kind_id}/feedbackbogen.pdf")
def feedbackbogen(repo: SchulRepo, lauf_id: int, kind_id: int):
    lauf = repo.holen(Lauf, lauf_id)
    posten, zeilen, i = _zeile_des_kindes(repo, lauf, kind_id)
    z = zeilen[i]
    pdf = feedbackboegen_pdf(
        repo.holen(Schule, repo.schule_id), lauf, [{"kind": z.kind, "feedback": feedback(z.ergebnis, posten)}]
    )
    return _pdf(pdf, f"feedbackbogen-{lauf.datum.isoformat()}-nr-{z.kind.startnummer}.pdf")
