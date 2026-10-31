"""Laufübersicht und Auswertung (Spezifikation 5.5 und 8, Aggregation)."""

from __future__ import annotations

import random
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

import pytest

from app.auswertung import auswerten, juengste_ereignisse, laufstand
from app.modelle import Ereignis, Gruppe, Item, Kind, Lauf, Posten, PostenToken, Strecke
from app.sicherheit import neues_token
from app.token import token_ablauf
from tests.conftest import angemeldet

T0 = datetime(2026, 6, 10, 9, 0, tzinfo=UTC)


@dataclass
class E:
    posten_id: int
    startnummer: int
    typ: str
    nutzlast: dict
    erfasst_am: datetime
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))


def d(nr, posten, durchgang, fehlend=(), sek=0, storniert=False):
    nutzlast = {"durchgang_nr": durchgang, "fehlende_items": list(fehlend)}
    if storniert:
        nutzlast["storniert"] = True
    return E(posten, nr, "durchgang", nutzlast, T0 + timedelta(seconds=sek))


def s(nr, posten, stufe, bemerkung=None, sek=0):
    nutzlast = {"stufe": stufe}
    if bemerkung:
        nutzlast["bemerkung"] = bemerkung
    return E(posten, nr, "sicherheit", nutzlast, T0 + timedelta(seconds=sek))


ITEMS = {1: [11, 12], 2: [21]}


# --------------------------------------------------------------------------- Reine Logik


def test_quote_je_item_bezogen_auf_durchgaenge_des_postens():
    erg = auswerten(
        [d(1, 1, 1, [11]), d(1, 1, 2, [11, 12]), d(1, 1, 3), d(1, 2, 1, [21])],
        ITEMS,
        [1],
    )[1]
    assert erg.posten[1].durchgaenge == 3
    assert (erg.posten[1].items[11].vergessen, erg.posten[1].items[11].gesamt) == (2, 3)
    assert (erg.posten[1].items[12].vergessen, erg.posten[1].items[12].gesamt) == (1, 3)
    assert erg.posten[2].durchgaenge == 1
    assert erg.posten[2].items[21].quote == 1.0


def test_juengstes_ereignis_je_schluessel_gewinnt():
    # Korrektur: derselbe Durchgang später ohne vergessenes Item erfasst.
    erg = auswerten([d(1, 1, 1, [11], sek=0), d(1, 1, 1, [], sek=30)], ITEMS, [1])[1]
    assert erg.posten[1].durchgaenge == 1
    assert erg.posten[1].items[11].vergessen == 0


def test_reihenfolge_der_ereignisse_ist_egal():
    ereignisse = [d(1, 1, n, [11] if n % 2 else [], sek=n) for n in range(1, 7)]
    ereignisse += [d(1, 1, 3, [], sek=100), d(1, 1, 4, storniert=True, sek=101), s(1, 1, 2, sek=1), s(1, 1, 3, sek=2)]
    erwartet = auswerten(ereignisse, ITEMS, [1])[1]
    for _ in range(20):
        random.shuffle(ereignisse)
        assert auswerten(ereignisse, ITEMS, [1])[1] == erwartet
    assert erwartet.posten[1].durchgaenge == 5
    assert erwartet.posten[1].items[11].vergessen == 2  # 1 und 5; 3 wurde korrigiert
    assert erwartet.posten[1].stufe == 3


def test_gleicher_zeitstempel_entscheidet_eindeutig_nach_event_id():
    a = d(1, 1, 1, [11])
    b = d(1, 1, 1, [])
    a.event_id, b.event_id = "00000000-0000-4000-8000-000000000001", "ffffffff-0000-4000-8000-000000000001"
    for liste in ([a, b], [b, a]):
        durchgaenge, _ = juengste_ereignisse(liste)
        assert durchgaenge[(1, 1, 1)] is b


def test_storno_zaehlt_nicht_und_neuerfassung_zaehlt_wieder():
    erg = auswerten([d(1, 1, 1, [11]), d(1, 1, 2, [11], sek=5), d(1, 1, 2, storniert=True, sek=8)], ITEMS, [1])[1]
    assert erg.posten[1].durchgaenge == 1
    assert erg.posten[1].items[11].vergessen == 1

    erg = auswerten(
        [d(1, 1, 1, [11]), d(1, 1, 1, storniert=True, sek=5), d(1, 1, 1, [12], sek=40)], ITEMS, [1]
    )[1]
    assert erg.posten[1].durchgaenge == 1
    assert (erg.posten[1].items[11].vergessen, erg.posten[1].items[12].vergessen) == (0, 1)


def test_sicherheit_juengste_einschaetzung_mit_bemerkung():
    erg = auswerten([s(1, 1, 3, "zu schnell", sek=0), s(1, 1, 2, "schon besser", sek=60)], ITEMS, [1])[1]
    assert erg.posten[1].stufe == 2
    assert erg.bemerkungen == [(1, "schon besser")]


@pytest.mark.parametrize(
    "stufen,abweichend",
    [((1, 3), True), ((3, 1), True), ((1, 2), False), ((2, 3), False), ((1,), False), ((), False)],
)
def test_starke_abweichung(stufen, abweichend):
    ereignisse = [s(1, p, st) for p, st in zip((1, 2), stufen)]
    assert auswerten(ereignisse, ITEMS, [1])[1].stark_abweichend is abweichend


def test_kinder_ohne_daten_und_zusaetzliche_startnummern():
    erg = auswerten([d(9, 1, 1)], ITEMS, [1, 2])
    assert sorted(erg) == [1, 2, 9]
    assert erg[1].posten[1].durchgaenge == 0
    assert erg[1].posten[1].items[11].quote is None


def test_laufstand():
    ereignisse = [
        d(1, 1, 1),
        d(1, 1, 2, sek=5),
        d(2, 1, 1),
        d(2, 1, 1, storniert=True, sek=9),
        s(3, 1, 1),
        d(1, 2, 1),
    ]
    stand = laufstand(ereignisse, [1, 2])
    assert stand[1].ereignisse == 5
    assert stand[1].durchgaenge == {1: 2}
    assert stand[1].mit_daten == {1, 3}
    assert stand[1].fehlend([1, 2, 3]) == [2, 3]
    assert stand[1].ohne_sicherheit([1, 2, 3]) == [1, 2]
    assert stand[2].fehlend([1, 2, 3]) == [2, 3]


# --------------------------------------------------------------------------- Verwaltungsseiten


@pytest.fixture
def lauf(fabrik, schulen):
    """Lauf der Schule A: Posten „Ampel" (Blick, Arm) und „Kreisel" (Spur), Kinder 1–5, Nr. 5 inaktiv."""
    a, _ = schulen
    with fabrik.intern_kontext() as sess:
        strecke = Strecke(schule_id=a.schule, name="Auswertungsrunde")
        ampel = Posten(name="Ampel", position=1)
        ampel.items = [Item(kurzbezeichnung="Blick", position=1), Item(kurzbezeichnung="Arm", position=2)]
        kreisel = Posten(name="Kreisel", position=2)
        kreisel.items = [Item(kurzbezeichnung="Spur", position=1)]
        strecke.posten.extend([ampel, kreisel])
        gruppe = Gruppe(schule_id=a.schule, name="Auswertungsgruppe", schuljahr="2026/27")
        for n in range(1, 6):
            gruppe.kinder.append(Kind(startnummer=n, aktiv=n != 5))
        andere = Gruppe(schule_id=a.schule, name="Andere Gruppe", schuljahr="2026/27")
        andere.kinder.append(Kind(startnummer=1))
        sess.add_all([strecke, gruppe, andere])
        sess.flush()
        lauf = Lauf(schule_id=a.schule, strecke_id=strecke.id, gruppe_id=gruppe.id, datum=date.today(), status="laufend")
        sess.add(lauf)
        sess.flush()
        for p in (ampel, kreisel):
            sess.add(PostenToken(lauf_id=lauf.id, posten_id=p.id, token=neues_token(), gueltig_bis=token_ablauf(lauf.datum)))
        sess.flush()
        return {
            "id": lauf.id,
            "ampel": ampel.id,
            "kreisel": kreisel.id,
            "blick": ampel.items[0].id,
            "arm": ampel.items[1].id,
            "spur": kreisel.items[0].id,
            "kinder": {k.startnummer: k.id for k in gruppe.kinder},
            "fremdes_kind": andere.kinder[0].id,
        }


def speichern(fabrik, lauf_id, *ereignisse: E):
    with fabrik.intern_kontext() as sess:
        for e in ereignisse:
            sess.add(
                Ereignis(
                    event_id=uuid.UUID(e.event_id),
                    lauf_id=lauf_id,
                    posten_id=e.posten_id,
                    startnummer=e.startnummer,
                    typ=e.typ,
                    nutzlast=e.nutzlast,
                    erfasst_am=e.erfasst_am,
                )
            )


def test_laufseite_vor_dem_ersten_upload_ohne_warnung(client, schulen, lauf):
    a, _ = schulen
    angemeldet(client, a.email)
    html = client.get(f"/verwaltung/laeufe/{lauf['id']}").text
    assert "Fehlende Startnummern" not in html
    assert "noch keine" in html
    assert "Durchgänge je Kind und Posten" not in html


def test_laufseite_hebt_fehlende_startnummern_hervor(client, fabrik, schulen, lauf):
    a, _ = schulen
    ampel, kreisel = lauf["ampel"], lauf["kreisel"]
    speichern(
        fabrik,
        lauf["id"],
        # Nr. 1 an beiden Posten, Nr. 2 nur an der Ampel, Nr. 3 nur storniert, Nr. 4 gar nicht.
        d(1, ampel, 1), d(1, ampel, 2, sek=30), d(1, kreisel, 1),
        d(2, ampel, 1),
        d(3, ampel, 1), d(3, ampel, 1, storniert=True, sek=3),
        s(1, ampel, 1),
        # Nr. 5 ist inaktiv, wurde aber erfasst.
        d(5, kreisel, 1),
    )
    angemeldet(client, a.email)
    html = client.get(f"/verwaltung/laeufe/{lauf['id']}").text

    warnung = html[html.index('class="warnkasten"') : html.index("</section>", html.index('class="warnkasten"'))]
    assert "Nr. 3</strong> – an keinem Posten erfasst" in warnung
    assert "Nr. 4</strong> – an keinem Posten erfasst" in warnung
    assert "Nr. 2</strong> – fehlt an: Kreisel" in warnung
    assert "Nr. 1<" not in warnung
    assert "Nr. 5" not in warnung

    assert "Ohne Durchgang: Nr. 3, 4" in html  # Ampel
    assert "Ohne Durchgang: Nr. 2, 3, 4" in html  # Kreisel
    assert "Ohne Fahrsicherheits-Einschätzung: Nr. 2, 3, 4" in html
    assert '<span class="zahl-fehlt">2 von 4</span>' in html
    assert '<span class="zahl-fehlt">1 von 4</span>' in html
    assert "Erfassungen zu inaktiven Kindern: Nr. 5." in html
    assert html.count("zelle-fehlt") == 2 + 3 + 1  # Ampel: 3, 4; Kreisel: 2, 3, 4; Nr. 5 an der Ampel


def test_laufseite_ohne_luecken_ohne_warnung(client, fabrik, schulen, lauf):
    a, _ = schulen
    speichern(fabrik, lauf["id"], *[d(n, p, 1) for n in range(1, 5) for p in (lauf["ampel"], lauf["kreisel"])])
    angemeldet(client, a.email)
    html = client.get(f"/verwaltung/laeufe/{lauf['id']}").text
    assert "Fehlende Startnummern" not in html
    assert html.count('<span class="zahl-ok">4 von 4</span>') == 2


def test_auswertung_zeigt_quoten_abweichung_und_bemerkungen(client, fabrik, schulen, lauf):
    a, _ = schulen
    ampel, kreisel = lauf["ampel"], lauf["kreisel"]
    speichern(
        fabrik,
        lauf["id"],
        d(1, ampel, 1, [lauf["blick"]]), d(1, ampel, 2, [lauf["blick"], lauf["arm"]], sek=1), d(1, ampel, 3, sek=2),
        d(1, kreisel, 1),
        s(1, ampel, 1), s(1, kreisel, 3, "fährt Schlangenlinien"),
        d(2, ampel, 1), s(2, ampel, 1), s(2, kreisel, 2),
    )
    angemeldet(client, a.email)
    html = client.get(f"/verwaltung/laeufe/{lauf['id']}/auswertung").text
    assert "Blick 2/3" in html
    assert "Arm 1/3" in html
    assert "3 Durchgänge" in html
    assert "fährt Schlangenlinien" in html
    assert html.count("weicht stark ab") == 1
    assert 'href="#nr-1">Nr. 1</a>' in html
    assert "keine Daten" in html  # Nr. 2 am Kreisel, Nr. 3 und 4 überall
    assert 'id="nr-5"' not in html  # inaktiv und ohne Erfassungen
    assert html.count('<tr id="nr-') == 4


def test_auswertung_einzelnes_kind(client, fabrik, schulen, lauf):
    a, _ = schulen
    ampel = lauf["ampel"]
    speichern(fabrik, lauf["id"], d(2, ampel, 1, [lauf["arm"]]), d(2, ampel, 2, sek=1), s(2, ampel, 2, "bremst spät"))
    angemeldet(client, a.email)
    html = client.get(f"/verwaltung/laeufe/{lauf['id']}/kinder/{lauf['kinder'][2]}").text
    assert "<h1>Nr. 2" in html
    assert "1 von 2" in html
    assert "0 von 2" in html
    assert "bremst spät" in html
    assert "teilweise sicher" in html
    assert "Keine Durchgänge erfasst." in html  # Kreisel
    # Blätternavigation: seit der Überarbeitung tragen die Verweise Pfeilsymbole
    # statt der Zeichen ‹ und ›, deshalb wird der Inhalt des Verweises geprüft.
    def _verweis(kind_id: int) -> str:
        treffer = re.search(rf'/kinder/{kind_id}">(.*?)</a>', html, re.S)
        assert treffer, f"kein Verweis auf Kind {kind_id}"
        return " ".join(treffer.group(1).split())

    assert "Nr. 1" in _verweis(lauf["kinder"][1])
    assert "Nr. 3" in _verweis(lauf["kinder"][3])
    # Das vorherige Kind steht vor dem nächsten.
    assert html.index(f'/kinder/{lauf["kinder"][1]}"') < html.index(f'/kinder/{lauf["kinder"][3]}"')


def test_auswertung_kind_aus_anderer_gruppe_oder_inaktiv_ohne_daten_404(client, schulen, lauf):
    a, b = schulen
    angemeldet(client, a.email)
    basis = f"/verwaltung/laeufe/{lauf['id']}/kinder"
    assert client.get(f"{basis}/{lauf['fremdes_kind']}").status_code == 404
    assert client.get(f"{basis}/{lauf['kinder'][5]}").status_code == 404
    # Eigener Lauf, Kind einer anderen Schule.
    antwort = client.get(f"{basis}/{b.kind}")
    assert antwort.status_code == 404
