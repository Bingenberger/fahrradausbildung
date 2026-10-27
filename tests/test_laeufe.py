"""Läufe, Tokens und Posten-Blätter (Spezifikation 5.3, 5.4, 5.7, 9)."""

from __future__ import annotations

import io
import re
from datetime import UTC, date, datetime, timedelta

import pytest
from pypdf import PdfReader

from app.modelle import Item, Kind, Lauf, Posten, PostenToken, Strecke
from app.token import token_ablauf, token_gueltig, token_url
from tests.conftest import angemeldet

ZUKUNFT = (date.today() + timedelta(days=7)).isoformat()


def _lauf_anlegen(client, csrf, strecke, gruppe, datum=ZUKUNFT):
    return client.post(
        "/verwaltung/laeufe/neu", data={"strecke_id": strecke, "gruppe_id": gruppe, "datum": datum, "csrf": csrf}
    )


def _lauf_id(antwort) -> int:
    assert antwort.status_code == 303
    treffer = re.search(r"/laeufe/(\d+)$", antwort.headers["location"])
    assert treffer, f"kein Lauf angelegt: {antwort.headers['location']}"
    return int(treffer.group(1))


@pytest.fixture
def strecke_mit_drei_posten(fabrik, schulen):
    a, _ = schulen
    with fabrik.intern_kontext() as s:
        strecke = Strecke(schule_id=a.schule, name="Große Runde")
        for i in range(1, 4):
            p = Posten(name=f"Posten {i} – Kreuzung {i}", position=i)
            p.items = [
                Item(kurzbezeichnung="Schulterblick", beobachtungstext=f"Blick nach hinten an Kreuzung {i}", position=1),
                Item(kurzbezeichnung="Handzeichen", beobachtungstext="Arm deutlich raus", position=2),
            ]
            strecke.posten.append(p)
        s.add(strecke)
        s.flush()
        return strecke.id


# --------------------------------------------------------------------------- Tokens


def test_token_ablauf_24_stunden_nach_tagesende():
    # 20.10.2026 endet um 0:00 Uhr am 21.10. (MESZ = UTC+2), plus 24 h
    assert token_ablauf(date(2026, 10, 20)) == datetime(2026, 10, 21, 22, 0, tzinfo=UTC)
    # Winterzeit (MEZ = UTC+1)
    assert token_ablauf(date(2026, 12, 1)) == datetime(2026, 12, 2, 23, 0, tzinfo=UTC)


def test_lauf_anlegen_erzeugt_je_posten_ein_token(client, fabrik, schulen, strecke_mit_drei_posten):
    a, _ = schulen
    csrf = angemeldet(client, a.email)
    lauf_id = _lauf_id(_lauf_anlegen(client, csrf, strecke_mit_drei_posten, a.gruppe))
    with fabrik.intern_kontext() as s:
        lauf = s.get(Lauf, lauf_id)
        assert lauf.schule_id == a.schule and lauf.status == "vorbereitet"
        assert {t.posten_id for t in lauf.tokens} == {p.id for p in lauf.strecke.posten}
        tokens = [t.token for t in lauf.tokens]
        assert len(set(tokens)) == 3
        assert all(len(t) >= 43 and re.fullmatch(r"[A-Za-z0-9_-]+", t) for t in tokens)
        assert all(t.gueltig_bis == token_ablauf(lauf.datum) for t in lauf.tokens)
        assert all(token_gueltig(t, lauf) for t in lauf.tokens)


@pytest.mark.parametrize("fall", ["archiviert", "ohne_items", "ohne_kinder", "vergangenheit", "doppelt"])
def test_lauf_anlegen_wird_geprueft(client, fabrik, schulen, strecke_mit_drei_posten, fall):
    a, _ = schulen
    csrf = angemeldet(client, a.email)
    datum = ZUKUNFT
    strecke = strecke_mit_drei_posten
    with fabrik.intern_kontext() as s:
        if fall == "archiviert":
            s.get(Strecke, strecke).archiviert = True
        elif fall == "ohne_items":
            s.get(Strecke, strecke).posten[0].items = []
        elif fall == "ohne_kinder":
            s.get(Kind, a.kind).aktiv = False
        elif fall == "vergangenheit":
            datum = (date.today() - timedelta(days=3)).isoformat()
        elif fall == "doppelt":
            datum = date.today().isoformat()
            strecke = a.strecke  # hat heute schon einen Lauf (conftest)
    antwort = _lauf_anlegen(client, csrf, strecke, a.gruppe, datum)
    assert antwort.headers["location"] == "/verwaltung/laeufe"
    with fabrik.intern_kontext() as s:
        assert s.query(Lauf).count() == 2  # nur die beiden aus der conftest


def test_token_erneuern_nur_vor_beginn(client, fabrik, schulen):
    a, _ = schulen
    csrf = angemeldet(client, a.email)
    with fabrik.intern_kontext() as s:
        alt = s.get(PostenToken, a.posten_token).token
    client.post(f"/verwaltung/laeufe/{a.lauf}/tokens/{a.posten}/erneuern", data={"csrf": csrf})
    with fabrik.intern_kontext() as s:
        neu = s.get(PostenToken, a.posten_token).token
        assert neu != alt
        s.get(Lauf, a.lauf).status = "laufend"
    client.post(f"/verwaltung/laeufe/{a.lauf}/tokens/{a.posten}/erneuern", data={"csrf": csrf})
    with fabrik.intern_kontext() as s:
        assert s.get(PostenToken, a.posten_token).token == neu


# --------------------------------------------------------------------------- Status


def test_abschliessen_entwertet_tokens_und_wieder_oeffnen(client, fabrik, schulen):
    a, _ = schulen
    csrf = angemeldet(client, a.email)
    client.post(f"/verwaltung/laeufe/{a.lauf}/abschliessen", data={"csrf": csrf})
    with fabrik.intern_kontext() as s:
        lauf = s.get(Lauf, a.lauf)
        assert lauf.status == "abgeschlossen"
        assert all(not token_gueltig(t, lauf) for t in lauf.tokens)
        assert all(t.gueltig_bis <= datetime.now(UTC) for t in lauf.tokens)

    client.post(f"/verwaltung/laeufe/{a.lauf}/wieder-oeffnen", data={"csrf": csrf})
    with fabrik.intern_kontext() as s:
        lauf = s.get(Lauf, a.lauf)
        assert lauf.status == "laufend"
        assert all(token_gueltig(t, lauf) for t in lauf.tokens)


def test_wieder_oeffnen_nach_ablauf_nicht_moeglich(client, fabrik, schulen):
    a, _ = schulen
    csrf = angemeldet(client, a.email)
    with fabrik.intern_kontext() as s:
        lauf = s.get(Lauf, a.lauf)
        lauf.datum = date.today() - timedelta(days=5)
        lauf.status = "abgeschlossen"
    client.post(f"/verwaltung/laeufe/{a.lauf}/wieder-oeffnen", data={"csrf": csrf})
    with fabrik.intern_kontext() as s:
        assert s.get(Lauf, a.lauf).status == "abgeschlossen"


def test_archivieren_nur_nach_abschluss(client, fabrik, schulen):
    a, _ = schulen
    csrf = angemeldet(client, a.email)
    client.post(f"/verwaltung/laeufe/{a.lauf}/archivieren", data={"csrf": csrf})
    with fabrik.intern_kontext() as s:
        assert s.get(Lauf, a.lauf).status == "vorbereitet"
    client.post(f"/verwaltung/laeufe/{a.lauf}/abschliessen", data={"csrf": csrf})
    client.post(f"/verwaltung/laeufe/{a.lauf}/archivieren", data={"csrf": csrf})
    with fabrik.intern_kontext() as s:
        assert s.get(Lauf, a.lauf).status == "archiviert"


def test_loeschen_nur_ohne_erfassungen(client, fabrik, schulen, strecke_mit_drei_posten):
    a, _ = schulen
    csrf = angemeldet(client, a.email)
    # Der Lauf aus der conftest hat ein Ereignis
    client.post(f"/verwaltung/laeufe/{a.lauf}/loeschen", data={"csrf": csrf})
    with fabrik.intern_kontext() as s:
        assert s.get(Lauf, a.lauf) is not None
    neu = _lauf_id(_lauf_anlegen(client, csrf, strecke_mit_drei_posten, a.gruppe))
    client.post(f"/verwaltung/laeufe/{neu}/loeschen", data={"csrf": csrf})
    with fabrik.intern_kontext() as s:
        assert s.get(Lauf, neu) is None
        assert s.query(PostenToken).filter_by(lauf_id=neu).count() == 0


def test_abschliessen_warnt_vor_fehlenden_uploads(client, schulen):
    a, _ = schulen
    angemeldet(client, a.email)
    seite = client.get(f"/verwaltung/laeufe/{a.lauf}").text
    assert "noch kein Upload" in seite and "Einmündung Lindenweg" in seite


# --------------------------------------------------------------------------- Posten-Blätter


def test_postenblaetter_pdf(client, fabrik, schulen, strecke_mit_drei_posten):
    a, _ = schulen
    csrf = angemeldet(client, a.email)
    lauf_id = _lauf_id(_lauf_anlegen(client, csrf, strecke_mit_drei_posten, a.gruppe))
    antwort = client.get(f"/verwaltung/laeufe/{lauf_id}/postenblaetter.pdf")
    assert antwort.status_code == 200
    assert antwort.headers["content-type"] == "application/pdf"

    pdf = PdfReader(io.BytesIO(antwort.content))
    assert len(pdf.pages) == 3  # eine Seite je Posten
    with fabrik.intern_kontext() as s:
        lauf = s.get(Lauf, lauf_id)
        tokens = {t.posten_id: t.token for t in lauf.tokens}
        for seite, posten in zip(pdf.pages, lauf.strecke.posten, strict=True):
            text = " ".join(seite.extract_text().split())
            assert posten.name in text
            assert f"Posten {posten.position} von 3" in text
            for item in posten.items:
                assert item.kurzbezeichnung in text
                assert item.beobachtungstext in text
            # URL mit dem Token genau dieses Postens (umbrochen, daher ohne Leerraum vergleichen)
            assert token_url(tokens[posten.id]) in text.replace(" ", "")
            assert "Hinweise" in text
            assert "Grundschule A" in text
            # Keine Gruppe auf dem Blatt für die Eltern
            assert "Klasse A" not in text
        # Jede Seite trägt ein QR-Bild
        assert all(seite.images or "/XObject" in seite["/Resources"] for seite in pdf.pages)


def test_qr_codes_im_pdf_lassen_sich_scannen(client, fabrik, schulen, strecke_mit_drei_posten, tmp_path):
    """Rendert die PDF-Seiten als Bild und dekodiert jeden QR-Code wie eine Kamera."""
    import shutil
    import subprocess

    pyzbar = pytest.importorskip("pyzbar.pyzbar", reason="libzbar nicht installiert")
    if not shutil.which("pdftoppm"):
        pytest.skip("pdftoppm (poppler-utils) nicht installiert")
    from PIL import Image

    a, _ = schulen
    csrf = angemeldet(client, a.email)
    lauf_id = _lauf_id(_lauf_anlegen(client, csrf, strecke_mit_drei_posten, a.gruppe))
    (tmp_path / "b.pdf").write_bytes(client.get(f"/verwaltung/laeufe/{lauf_id}/postenblaetter.pdf").content)
    subprocess.run(["pdftoppm", "-r", "150", "-png", str(tmp_path / "b.pdf"), str(tmp_path / "s")], check=True)

    gelesen = []
    for bild in sorted(tmp_path.glob("s-*.png")):
        codes = pyzbar.decode(Image.open(bild))
        assert len(codes) == 1, bild.name
        gelesen.append(codes[0].data.decode())

    with fabrik.intern_kontext() as s:
        lauf = s.get(Lauf, lauf_id)
        tokens = {t.posten_id: t.token for t in lauf.tokens}
        assert gelesen == [token_url(tokens[p.id]) for p in lauf.strecke.posten]
