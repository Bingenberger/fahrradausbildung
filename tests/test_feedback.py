"""Feedbackbogen (Spezifikation 8; Abnahmekriterium 8)."""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field

import pytest
from pypdf import PdfReader

from app.auswertung import auswerten
from app.config import einstellungen
from app.feedback import MAX_UEBUNGEN, feedback
from app.formate import datum_lang
from app.modelle import Item, Lauf, Posten
from app.pdf import ordnername
from tests.conftest import angemeldet
from tests.test_auswertung import d, lauf, s, speichern  # noqa: F401  (lauf ist eine Fixture)

# --------------------------------------------------------------------------- Reine Logik


@dataclass
class I:
    id: int
    kurzbezeichnung: str
    uebungstext: str = ""


@dataclass
class P:
    id: int
    items: list[I] = field(default_factory=list)


def _bogen(ereignisse, posten):
    items = {p.id: [i.id for i in p.items] for p in posten}
    return feedback(auswerten(ereignisse, items, [1])[1], posten)


def _durchgaenge(posten_id, anzahl, vergessen: dict[int, int]):
    """``anzahl`` Durchgänge; Item ``i`` wird in den ersten ``vergessen[i]`` vergessen."""
    return [
        d(1, posten_id, n, [i for i, k in vergessen.items() if n <= k], sek=n) for n in range(1, anzahl + 1)
    ]


def test_gut_unter_25_prozent_ueben_ab_25_prozent():
    posten = [P(1, [I(11, "Blick", "Übe Blick."), I(12, "Arm", "Übe Arm."), I(13, "Spur")])]
    # 4 Durchgänge: Blick 0×, Arm 1× (25 %), Spur 3×
    bogen = _bogen(_durchgaenge(1, 4, {12: 1, 13: 3}), posten)
    assert bogen.gut == ["Blick"]
    assert [u.kurzbezeichnung for u in bogen.ueben] == ["Spur", "Arm"]
    assert bogen.ueben[1].uebungstext == "Übe Arm."
    assert bogen.hat_daten


def test_hoechstens_drei_uebungen_mit_der_hoechsten_quote():
    posten = [
        P(1, [I(11, "A"), I(12, "B"), I(13, "C")]),
        P(2, [I(21, "D"), I(22, "E")]),
    ]
    ereignisse = _durchgaenge(1, 4, {11: 1, 12: 4, 13: 2}) + _durchgaenge(2, 2, {21: 2, 22: 1})
    bogen = _bogen(ereignisse, posten)
    assert len(bogen.ueben) == MAX_UEBUNGEN == 3
    # Quoten: A 25 %, B 100 %, C 50 %, D 100 %, E 50 % – Gleichstand nach Streckenreihenfolge.
    assert [u.kurzbezeichnung for u in bogen.ueben] == ["B", "D", "C"]
    assert bogen.gut == []


def test_gleiches_item_an_mehreren_posten_zaehlt_einmal_mit_der_hoechsten_quote():
    posten = [
        P(1, [I(11, "Schulterblick", "Text an Posten 1")]),
        P(2, [I(21, "schulterblick ", "Text an Posten 2"), I(22, "Arm")]),
        P(3, [I(31, "Arm")]),
    ]
    ereignisse = _durchgaenge(1, 4, {}) + _durchgaenge(2, 4, {21: 2}) + _durchgaenge(3, 4, {})
    bogen = _bogen(ereignisse, posten)
    assert [(u.kurzbezeichnung, u.uebungstext) for u in bogen.ueben] == [("schulterblick", "Text an Posten 2")]
    assert bogen.gut == ["Arm"]


def test_posten_ohne_durchgang_zaehlt_weder_gut_noch_ueben():
    posten = [P(1, [I(11, "Blick")]), P(2, [I(21, "Spur")])]
    bogen = _bogen(_durchgaenge(1, 2, {}), posten)
    assert bogen.gut == ["Blick"]
    assert bogen.ueben == []
    assert not _bogen([s(1, 1, 1)], posten).hat_daten


@pytest.mark.parametrize(
    "stufen,aussage",
    [
        ((1, 1, 1), "sicher"),
        ((1, 2), "ueberwiegend_sicher"),
        ((2, 2), "ueberwiegend_sicher"),
        ((1, 3), "teilweise_unsicher"),
        ((2, 3, 3), "teilweise_unsicher"),
        ((3, 3), "unsicher"),
        ((), None),
    ],
)
def test_fahrsicherheit_als_aussage(stufen, aussage):
    posten = [P(n, [I(n * 10, f"X{n}")]) for n in (1, 2, 3)]
    bogen = _bogen([s(1, n, st) for n, st in zip((1, 2, 3), stufen)], posten)
    assert bogen.sicherheit == aussage


# --------------------------------------------------------------------------- PDF


def _seiten(pdf: bytes) -> list[str]:
    return [p.extract_text() for p in PdfReader(io.BytesIO(pdf)).pages]


def _uebungstexte(fabrik, lauf):  # noqa: F811
    with fabrik.intern_kontext() as sess:
        for item_id, text in [
            (lauf["blick"], "Schau über die Schulter, bevor du losfährst."),
            (lauf["spur"], "Bleib im Kreisel rechts."),
        ]:
            sess.get(Item, item_id).uebungstext = text


@pytest.fixture
def mit_daten(fabrik, lauf):  # noqa: F811
    """Nr. 1: Blick oft vergessen, sonst gut, „sicher"/„unsicher". Nr. 2: alles gut. Nr. 3, 4: nichts."""
    _uebungstexte(fabrik, lauf)
    ampel, kreisel = lauf["ampel"], lauf["kreisel"]
    speichern(
        fabrik,
        lauf["id"],
        d(1, ampel, 1, [lauf["blick"]]), d(1, ampel, 2, [lauf["blick"]], sek=1), d(1, ampel, 3, sek=2),
        d(1, kreisel, 1, [lauf["spur"]]), d(1, kreisel, 2, sek=1),
        s(1, ampel, 1, "Bemerkung bleibt intern"), s(1, kreisel, 3),
        d(2, ampel, 1), d(2, kreisel, 1), s(2, ampel, 1),
    )
    return lauf


def test_sammel_pdf_ein_bogen_je_kind_mit_daten(client, schulen, mit_daten):
    a, _ = schulen
    angemeldet(client, a.email)
    antwort = client.get(f"/verwaltung/laeufe/{mit_daten['id']}/feedbackboegen.pdf")
    assert antwort.status_code == 200
    assert antwort.headers["content-type"] == "application/pdf"
    seiten = _seiten(antwort.content)
    assert len(seiten) == 2
    assert "Startnummer 1" in seiten[0] and "Name:" in seiten[0]
    assert "Startnummer 2" in seiten[1]

    eins = seiten[0]
    assert "Grundschule A" in eins
    assert "Das klappt schon gut" in eins and "Arm" in eins
    assert "Daran üben wir noch" in eins
    assert "Schau über die Schulter, bevor du losfährst." in eins
    assert "Bleib im Kreisel rechts." in eins
    assert "an manchen Stellen noch unsicher" in eins
    assert "Bemerkung bleibt intern" not in eins
    assert "Daran üben wir noch" not in seiten[1]
    assert "schon sicher Rad" in seiten[1]


def test_bogen_ohne_zahlen_prozente_oder_noten(client, fabrik, schulen, mit_daten):
    """Abnahmekriterium 8: keine Prozentzahlen, keine Punktwertungen.

    Erlaubte Ziffern: Datum, Startnummer, „Klasse 4" und die Aufzählung der
    Übungspunkte (1., 2., 3.).
    """
    a, _ = schulen
    angemeldet(client, a.email)
    pdf = client.get(f"/verwaltung/laeufe/{mit_daten['id']}/feedbackboegen.pdf").content
    with fabrik.intern_kontext() as sess:
        datum = datum_lang(sess.get(Lauf, mit_daten["id"]).datum)
    for seite in _seiten(pdf):
        rest = seite.replace(datum, "").replace("Klasse 4", "")
        rest = re.sub(r"Startnummer \d+", "", rest)
        rest = re.sub(r"^[123]\. ?$", "", rest, flags=re.M)
        assert not re.search(r"\d", rest), rest
        assert "%" not in seite
        for wort in ("Note", "Punkte", "bestanden"):
            assert wort not in seite


def test_hoechstens_drei_uebungspunkte_und_eine_seite_bei_vielen_items(client, fabrik, schulen):
    a, _ = schulen
    with fabrik.intern_kontext() as sess:
        posten = sess.get(Posten, a.posten)
        for n in range(2, 13):
            posten.items.append(
                Item(kurzbezeichnung=f"Punkt {chr(64 + n)}", uebungstext="Ein recht langer Übungssatz, " * 4, position=n)
            )
        sess.flush()
        ids = [i.id for i in posten.items]
    # Jedes zweite Item vergessen: 6 auffällig, 6 gut.
    speichern(fabrik, a.lauf, *[d(7, a.posten, n, ids[::2], sek=n) for n in range(2, 6)])
    angemeldet(client, a.email)
    seiten = _seiten(client.get(f"/verwaltung/laeufe/{a.lauf}/feedbackboegen.pdf").content)
    assert len(seiten) == 1
    uebungen = seiten[0].split("Daran üben wir noch")[1].split("So sicher")[0]
    assert len(re.findall(r"^(Punkt [A-L]|Schulterblick):", uebungen, flags=re.M)) == 3


def test_einzelner_bogen(client, schulen, mit_daten):
    a, _ = schulen
    angemeldet(client, a.email)
    antwort = client.get(f"/verwaltung/laeufe/{mit_daten['id']}/kinder/{mit_daten['kinder'][2]}/feedbackbogen.pdf")
    assert antwort.status_code == 200
    assert re.fullmatch(r'inline; filename="feedbackbogen-\d{4}-\d\d-\d\d-nr-2\.pdf"', antwort.headers["content-disposition"])
    seiten = _seiten(antwort.content)
    assert len(seiten) == 1 and "Startnummer 2" in seiten[0]

    # Kind ohne Erfassungen: freundlicher Bogen statt Fehlermeldung.
    ohne = _seiten(client.get(f"/verwaltung/laeufe/{mit_daten['id']}/kinder/{mit_daten['kinder'][3]}/feedbackbogen.pdf").content)
    assert "nichts aufgeschrieben" in " ".join(ohne[0].split())
    assert "Daran üben" not in ohne[0]


def test_einzelner_bogen_fremdes_kind_404(client, schulen, mit_daten):
    a, b = schulen
    angemeldet(client, a.email)
    basis = f"/verwaltung/laeufe/{mit_daten['id']}/kinder"
    assert client.get(f"{basis}/{mit_daten['fremdes_kind']}/feedbackbogen.pdf").status_code == 404
    assert client.get(f"{basis}/{b.kind}/feedbackbogen.pdf").status_code == 404


def test_sammel_pdf_ohne_erfassungen_leitet_zurueck(client, schulen, lauf):  # noqa: F811
    a, _ = schulen
    angemeldet(client, a.email)
    antwort = client.get(f"/verwaltung/laeufe/{lauf['id']}/feedbackboegen.pdf")
    assert antwort.status_code == 303
    assert antwort.headers["location"].endswith("/auswertung")
    assert "Noch keine Erfassungen" in client.get(antwort.headers["location"]).text


def test_auswertung_verlinkt_boegen(client, schulen, mit_daten):
    a, _ = schulen
    angemeldet(client, a.email)
    html = " ".join(client.get(f"/verwaltung/laeufe/{mit_daten['id']}/auswertung").text.split())
    assert f"/laeufe/{mit_daten['id']}/feedbackboegen.pdf" in html
    assert f"/kinder/{mit_daten['kinder'][1]}/feedbackbogen.pdf" in html
    assert f"/kinder/{mit_daten['kinder'][3]}/feedbackbogen.pdf" not in html
    assert "Ohne Bogen, weil kein Posten das Kind erfasst hat: Nr. 3, Nr. 4." in html
    assert "noch nicht abgeschlossen" in html


# --------------------------------------------------------------------------- Eigene Vorlagen


def test_ordnername():
    assert ordnername("GS Lindenweg") == "gs-lindenweg"
    assert ordnername("Grundschule Süd/Ost") == "grundschule-sued-ost"
    assert ordnername("../..") == ""


def _png() -> bytes:
    from PIL import Image

    puffer = io.BytesIO()
    Image.new("RGB", (40, 20), "navy").save(puffer, "PNG")
    return puffer.getvalue()


@pytest.fixture
def eigene_vorlagen(tmp_path, monkeypatch):
    monkeypatch.setenv("FP_VORLAGEN_VERZEICHNIS", str(tmp_path))
    einstellungen.cache_clear()
    yield tmp_path
    monkeypatch.delenv("FP_VORLAGEN_VERZEICHNIS")
    einstellungen.cache_clear()


def test_schule_kann_vorlage_und_logo_austauschen(client, fabrik, schulen, eigene_vorlagen):
    a, b = schulen
    ordner_a = eigene_vorlagen / ordnername("A")
    ordner_a.mkdir()
    (ordner_a / "feedbackbogen.html").write_text(
        "{% for b in boegen %}<p>Eigene Vorlage A für Startnummer {{ b.kind.startnummer }}</p>"
        "{% if logo %}<img src=\"{{ logo }}\">{% endif %}{% endfor %}",
        encoding="utf-8",
    )
    (ordner_a / "logo.png").write_bytes(_png())
    # Gemeinsame Fußzeile für alle anderen Schulen: nur das Stylesheet austauschen.
    (eigene_vorlagen / "feedbackbogen.css").write_text(".fuss { color: red; }", encoding="utf-8")

    angemeldet(client, a.email)
    pdf = client.get(f"/verwaltung/laeufe/{a.lauf}/feedbackboegen.pdf").content
    seite = PdfReader(io.BytesIO(pdf)).pages[0]
    assert "Eigene Vorlage A für Startnummer 7" in seite.extract_text()
    assert len(seite.images) == 1

    client.post("/abmelden", data={"csrf": re.search(r'name="csrf" value="([^"]+)"', client.get("/verwaltung/").text).group(1)})
    angemeldet(client, b.email)
    text = _seiten(client.get(f"/verwaltung/laeufe/{b.lauf}/feedbackboegen.pdf").content)[0]
    assert "Eigene Vorlage" not in text
    assert "Deine Radfahrprüfung" in text
