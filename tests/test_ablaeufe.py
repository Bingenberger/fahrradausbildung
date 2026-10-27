"""Wiederkehrende Handlungsabläufe als Vorlage für Posten."""

from __future__ import annotations

import re

import pytest
from sqlalchemy import select

from app.beispielablaeufe import BEISPIELE
from app.modelle import Ablauf, AblaufSchritt, Item, Posten, Strecke
from tests.conftest import angemeldet


def _ablaeufe(fabrik, schule_id) -> dict[str, list[str]]:
    with fabrik.intern_kontext() as s:
        return {
            a.name: [x.kurzbezeichnung for x in a.schritte]
            for a in s.scalars(select(Ablauf).where(Ablauf.schule_id == schule_id).order_by(Ablauf.name))
        }


def _items(fabrik, posten_id) -> list[tuple[str, str, str, int]]:
    with fabrik.intern_kontext() as s:
        return [(i.kurzbezeichnung, i.beobachtungstext, i.uebungstext, i.position) for i in s.get(Posten, posten_id).items]


@pytest.fixture
def freier_posten(fabrik, schulen) -> int:
    """Posten auf einer Strecke ohne Lauf, mit einem Item „Handzeichen links“."""
    a, _ = schulen
    with fabrik.intern_kontext() as s:
        strecke = Strecke(schule_id=a.schule, name="Neue Runde")
        posten = Posten(name="Kreuzung", position=1)
        posten.items = [Item(kurzbezeichnung="Handzeichen links", beobachtungstext="eigener Text", position=1)]
        strecke.posten.append(posten)
        s.add(strecke)
        s.flush()
        return posten.id


# --------------------------------------------------------------------------- Beispiele


def test_beispiele_passen_auf_die_knoepfe():
    namen = [b[0] for b in BEISPIELE]
    assert {"Linksabbiegen", "Rechtsabbiegen"} <= set(namen)
    for _, _, schritte in BEISPIELE:
        kurz = [k.casefold() for k, _, _ in schritte]
        assert len(kurz) == len(set(kurz))
        for k, beobachtung, uebung in schritte:
            assert 0 < len(k) <= 40
            assert beobachtung.endswith("?") and uebung


def test_beispiele_uebernehmen_ohne_doppelte(client, fabrik, schulen):
    a, _ = schulen
    csrf = angemeldet(client, a.email)
    assert "Beispielabläufe übernehmen" in client.get("/verwaltung/ablaeufe").text
    client.post("/verwaltung/ablaeufe/beispiele", data={"csrf": csrf})
    client.post("/verwaltung/ablaeufe/beispiele", data={"csrf": csrf})
    ablaeufe = _ablaeufe(fabrik, a.schule)
    assert len(ablaeufe) == len(BEISPIELE) + 1  # plus „Ablauf A“ aus den Testdaten
    assert ablaeufe["Linksabbiegen"][0] == "Schulterblick links"
    html = client.get("/verwaltung/ablaeufe").text
    assert "Beispielabläufe übernehmen" not in html
    assert "Schulterblick links · Handzeichen links" in html


# --------------------------------------------------------------------------- Abläufe pflegen


def test_ablauf_anlegen_und_schritte_pflegen(client, fabrik, schulen):
    a, _ = schulen
    csrf = angemeldet(client, a.email)
    r = client.post("/verwaltung/ablaeufe/neu", data={"name": " Wenden ", "csrf": csrf})
    ablauf_id = int(re.search(r"/ablaeufe/(\d+)$", r.headers["location"]).group(1))
    for k in ("Anhalten", "Schulterblick", "Wenden"):
        client.post(f"/verwaltung/ablaeufe/{ablauf_id}/schritte", data={"kurzbezeichnung": k, "uebungstext": f"Übe {k}.", "csrf": csrf})
    client.post(f"/verwaltung/ablaeufe/{ablauf_id}/schritte", data={"kurzbezeichnung": "x" * 41, "csrf": csrf})
    client.post(f"/verwaltung/ablaeufe/{ablauf_id}/schritte", data={"kurzbezeichnung": " ", "csrf": csrf})
    assert _ablaeufe(fabrik, a.schule)["Wenden"] == ["Anhalten", "Schulterblick", "Wenden"]

    with fabrik.intern_kontext() as s:
        ids = [x.id for x in s.get(Ablauf, ablauf_id).schritte]
    client.post(f"/verwaltung/ablaufschritte/{ids[2]}/verschieben", data={"richtung": "hoch", "csrf": csrf})
    client.post(f"/verwaltung/ablaufschritte/{ids[0]}/bearbeiten",
                data={"kurzbezeichnung": "Rechts anhalten", "beobachtungstext": "Hält es rechts an?", "uebungstext": "", "csrf": csrf})
    client.post(f"/verwaltung/ablaufschritte/{ids[1]}/loeschen", data={"csrf": csrf})
    with fabrik.intern_kontext() as s:
        schritte = [(x.kurzbezeichnung, x.position) for x in s.get(Ablauf, ablauf_id).schritte]
    assert schritte == [("Rechts anhalten", 1), ("Wenden", 2)]

    client.post(f"/verwaltung/ablaeufe/{ablauf_id}/loeschen", data={"csrf": csrf})
    assert "Wenden" not in _ablaeufe(fabrik, a.schule)
    with fabrik.intern_kontext() as s:
        assert s.execute(select(AblaufSchritt).where(AblaufSchritt.ablauf_id == ablauf_id)).first() is None


# --------------------------------------------------------------------------- In Posten einfügen


def test_ablauf_einfuegen_kopiert_schritte(client, fabrik, schulen, freier_posten):
    a, _ = schulen
    csrf = angemeldet(client, a.email)
    client.post("/verwaltung/ablaeufe/beispiele", data={"csrf": csrf})
    with fabrik.intern_kontext() as s:
        links = s.scalars(select(Ablauf).where(Ablauf.schule_id == a.schule, Ablauf.name == "Linksabbiegen")).one()
        links_id, erwartet = links.id, [(x.kurzbezeichnung, x.beobachtungstext, x.uebungstext) for x in links.schritte]

    html = client.get(f"/verwaltung/posten/{freier_posten}").text
    assert "Linksabbiegen (6 Schritte)" in html
    r = client.post(f"/verwaltung/posten/{freier_posten}/ablauf-einfuegen", data={"ablauf_id": str(links_id), "csrf": csrf})
    assert r.status_code == 303
    meldung = client.get(r.headers["location"]).text
    assert "„Linksabbiegen“ eingefügt: 5 Items." in meldung
    assert "Schon vorhanden und übersprungen: Handzeichen links." in meldung

    items = _items(fabrik, freier_posten)
    # Das vorhandene Item bleibt mit seinem eigenen Text vorne; die übrigen kommen dahinter.
    assert items[0] == ("Handzeichen links", "eigener Text", "", 1)
    assert [i[:3] for i in items[1:]] == [e for e in erwartet if e[0] != "Handzeichen links"]
    assert [i[3] for i in items] == list(range(1, 7))

    # Kopie, keine Verknüpfung: Änderungen am Ablauf ändern den Posten nicht.
    with fabrik.intern_kontext() as s:
        s.get(Ablauf, links_id).schritte[0].kurzbezeichnung = "Geändert"
    client.post(f"/verwaltung/ablaeufe/{links_id}/loeschen", data={"csrf": csrf})
    assert _items(fabrik, freier_posten) == items


def test_ablauf_einfuegen_gesperrt_wenn_strecke_laeufe_hat(client, fabrik, schulen):
    a, _ = schulen  # Strecke A hat einen Lauf
    csrf = angemeldet(client, a.email)
    vorher = _items(fabrik, a.posten)
    r = client.post(f"/verwaltung/posten/{a.posten}/ablauf-einfuegen", data={"ablauf_id": str(a.ablauf), "csrf": csrf})
    assert "bereits Läufe" in client.get(r.headers["location"]).text
    assert _items(fabrik, a.posten) == vorher
    assert "Ablauf einfügen" not in client.get(f"/verwaltung/posten/{a.posten}").text


def test_fremder_ablauf_ergibt_404(client, fabrik, schulen, freier_posten):
    a, b = schulen
    csrf = angemeldet(client, a.email)
    vorher = _items(fabrik, freier_posten)
    r = client.post(f"/verwaltung/posten/{freier_posten}/ablauf-einfuegen", data={"ablauf_id": str(b.ablauf), "csrf": csrf})
    assert r.status_code == 404
    assert _items(fabrik, freier_posten) == vorher
    r = client.post(f"/verwaltung/posten/{freier_posten}/ablauf-einfuegen", data={"ablauf_id": "abc", "csrf": csrf})
    assert "Bitte einen Ablauf auswählen" in client.get(r.headers["location"]).text
    # Die Auswahl zeigt nur eigene Abläufe
    html = client.get(f"/verwaltung/posten/{freier_posten}").text
    assert "Ablauf A" in html and "Ablauf B" not in html


# --------------------------------------------------------------------------- Posten als Ablauf speichern


def test_posten_als_ablauf_speichern(client, fabrik, schulen):
    a, _ = schulen  # geht auch, wenn die Strecke schon Läufe hat – es wird nur gelesen
    csrf = angemeldet(client, a.email)
    r = client.post(f"/verwaltung/posten/{a.posten}/als-ablauf", data={"name": "Einmündung", "csrf": csrf})
    neu = int(re.search(r"/ablaeufe/(\d+)$", r.headers["location"]).group(1))
    with fabrik.intern_kontext() as s:
        ablauf = s.get(Ablauf, neu)
        assert ablauf.schule_id == a.schule
        assert [(x.kurzbezeichnung, x.beobachtungstext, x.uebungstext, x.position) for x in ablauf.schritte] == [
            ("Schulterblick", "Dreht das Kind den Kopf nach hinten links?", "Übe den Schulterblick, bevor du abbiegst.", 1)
        ]
    r = client.post(f"/verwaltung/posten/{a.posten}/als-ablauf", data={"name": " ", "csrf": csrf})
    assert "Bitte einen Namen" in client.get(r.headers["location"]).text


def test_posten_ohne_items_nicht_als_ablauf(client, fabrik, schulen):
    a, _ = schulen
    csrf = angemeldet(client, a.email)
    with fabrik.intern_kontext() as s:
        leer = Posten(strecke_id=a.strecke, name="Leer", position=9)
        s.add(leer)
        s.flush()
        leer_id = leer.id
    vorher = _ablaeufe(fabrik, a.schule)
    r = client.post(f"/verwaltung/posten/{leer_id}/als-ablauf", data={"name": "Nichts", "csrf": csrf})
    assert "noch keine Items" in client.get(r.headers["location"]).text
    assert _ablaeufe(fabrik, a.schule) == vorher


def test_navigation_zeigt_ablaeufe(client, schulen):
    a, _ = schulen
    angemeldet(client, a.email)
    assert 'href="/verwaltung/ablaeufe"' in client.get("/verwaltung/strecken").text
