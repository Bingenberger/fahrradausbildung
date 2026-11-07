"""Token-API der Posten (Spezifikation 4.2, 4.4, 7, 9; Abnahmekriterien 2, 3, 5)."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.modelle import Ereignis, Gruppe, Item, Kind, Lauf, Posten, PostenToken, Schule, Strecke
from app.sicherheit import neues_token
from app.token import token_ablauf


@pytest.fixture
def lauf(fabrik, schulen):
    """Lauf der Schule A mit 10 Kindern (Nr. 1–10, Nr. 10 inaktiv) und einem Posten mit 3 Items."""
    a, _ = schulen
    with fabrik.intern_kontext() as s:
        strecke = Strecke(schule_id=a.schule, name="API-Runde")
        posten = Posten(name="Kreuzung", position=1)
        posten.items = [Item(kurzbezeichnung=k, position=i) for i, k in enumerate(["Blick", "Arm", "Spur"], 1)]
        strecke.posten.append(posten)
        gruppe = Gruppe(schule_id=a.schule, name="API-Gruppe", schuljahr="2026/27")
        for n in range(1, 11):
            gruppe.kinder.append(Kind(startnummer=n, aktiv=n != 10))
        s.add_all([strecke, gruppe])
        s.flush()
        lauf = Lauf(schule_id=a.schule, strecke_id=strecke.id, gruppe_id=gruppe.id, datum=date.today())
        s.add(lauf)
        s.flush()
        token = PostenToken(lauf_id=lauf.id, posten_id=posten.id, token=neues_token(), gueltig_bis=token_ablauf(lauf.datum))
        s.add(token)
        s.flush()
        return {
            "token": token.token,
            "lauf_id": lauf.id,
            "posten_id": posten.id,
            "item_ids": [i.id for i in posten.items],
            # Texte, die nichts auf dem Gerät verloren haben (Kindernamen gibt es nicht).
            "namen": ["API-Gruppe", "Grundschule A"],
            "schule_name": "Grundschule A",
        }


def ereignis(startnummer=1, typ="durchgang", nutzlast=None, **extra):
    return {
        "event_id": str(uuid.uuid4()),
        "typ": typ,
        "startnummer": startnummer,
        "nutzlast": nutzlast if nutzlast is not None else {"durchgang_nr": 1, "fehlende_items": []},
        "erfasst_am": datetime.now(UTC).isoformat(),
        **extra,
    }


def anzahl_ereignisse(fabrik, **filter_) -> int:
    with fabrik.intern_kontext() as s:
        stmt = select(func.count()).select_from(Ereignis)
        for k, v in filter_.items():
            stmt = stmt.where(getattr(Ereignis, k) == v)
        return s.execute(stmt).scalar_one()


def senden(client, token, events):
    return client.post(f"/api/p/{token}/events", json={"events": events})


# --------------------------------------------------------------------------- Konfiguration


def test_konfiguration(client, fabrik, lauf):
    r = client.get(f"/api/p/{lauf['token']}/config")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-store"
    k = r.json()
    assert set(k) == {"lauf_id", "datum", "posten", "items", "startnummern", "weitere_laeufe", "pin"}
    assert k["pin"] is None  # Standard: keine PIN-Abfrage
    assert k["lauf_id"] == lauf["lauf_id"]
    assert k["datum"] == date.today().isoformat()
    assert k["posten"] == {"id": lauf["posten_id"], "name": "Kreuzung"}
    assert [i["kurzbezeichnung"] for i in k["items"]] == ["Blick", "Arm", "Spur"]
    assert set(k["items"][0]) == {"id", "kurzbezeichnung", "position"}
    assert k["startnummern"] == list(range(1, 10))  # Nr. 10 ist inaktiv
    with fabrik.intern_kontext() as s:
        assert s.execute(select(PostenToken.letzter_abruf).where(PostenToken.token == lauf["token"])).scalar_one()


def test_konfiguration_enthaelt_keine_namen(client, fabrik, lauf):
    """Spezifikation 4.2: weder Gruppe noch Schule; Kindernamen gibt es in der Anwendung nicht.

    Einzige Ausnahme ist die Klassenbezeichnung *anderer* Läufe in
    ``weitere_laeufe`` – ohne sie kann die Person am Posten zwei Läufe desselben
    Tages nicht auseinanderhalten (siehe test_weitere_laeufe_nennen_tag_und_klasse).
    """
    text = client.get(f"/api/p/{lauf['token']}/config").text
    for name in lauf["namen"]:
        assert name not in text


def test_konfiguration_enthaelt_pin_der_schule(client, fabrik, schulen, lauf):
    a, b = schulen
    with fabrik.intern_kontext() as s:
        s.get(Schule, a.schule).posten_pin = "4711"
        s.get(Schule, b.schule).posten_pin = "0000"
    assert client.get(f"/api/p/{lauf['token']}/config").json()["pin"] == "4711"


# ----------------------------------------------------------- Wechsel auf den nächsten Lauf


def _zweiter_lauf(fabrik, schulen, lauf, *, datum=None, posten_id=None, status="vorbereitet"):
    """Weiterer Lauf einer anderen Klasse – standardmäßig am selben Posten und Tag."""
    a, _ = schulen
    with fabrik.intern_kontext() as s:
        gruppe = Gruppe(schule_id=a.schule, name="Klasse 4b", schuljahr="2026/27")
        gruppe.kinder.append(Kind(startnummer=1))
        s.add(gruppe)
        s.flush()
        strecke_id = s.execute(
            select(Posten.strecke_id).where(Posten.id == (posten_id or lauf["posten_id"]))
        ).scalar_one()
        zweiter = Lauf(
            schule_id=a.schule, strecke_id=strecke_id, gruppe_id=gruppe.id,
            datum=datum or date.today(), status=status,
        )
        s.add(zweiter)
        s.flush()
        token = PostenToken(
            lauf_id=zweiter.id, posten_id=posten_id or lauf["posten_id"],
            token=neues_token(), gueltig_bis=token_ablauf(zweiter.datum),
        )
        s.add(token)
        s.flush()
        return {"token": token.token, "lauf_id": zweiter.id}


def test_weitere_laeufe_nennen_tag_und_klasse(client, fabrik, schulen, lauf):
    """Zwei Läufe am selben Tag: Nur die Klasse unterscheidet sie."""
    zweiter = _zweiter_lauf(fabrik, schulen, lauf)
    k = client.get(f"/api/p/{lauf['token']}/config").json()
    assert k["weitere_laeufe"] == [
        {"token": zweiter["token"], "datum": date.today().isoformat(), "gruppe": "Klasse 4b"}
    ]
    # Startnummern fremder Läufe gehören nicht auf das Gerät.
    assert all(set(e) == {"token", "datum", "gruppe"} for e in k["weitere_laeufe"])


def test_weitere_laeufe_fuehren_nicht_den_eigenen_lauf(client, fabrik, lauf):
    k = client.get(f"/api/p/{lauf['token']}/config").json()
    assert k["weitere_laeufe"] == []


@pytest.mark.parametrize("fall", ["abgeschlossen", "archiviert", "anderer_posten", "token_abgelaufen"])
def test_weitere_laeufe_lassen_unerreichbares_weg(client, fabrik, schulen, lauf, fall):
    a, _ = schulen
    if fall == "anderer_posten":
        with fabrik.intern_kontext() as s:
            strecke = Strecke(schule_id=a.schule, name="Andere Runde")
            posten = Posten(name="Ampel", position=1)
            strecke.posten.append(posten)
            s.add(strecke)
            s.flush()
            fremder_posten = posten.id
        _zweiter_lauf(fabrik, schulen, lauf, posten_id=fremder_posten)
    elif fall == "token_abgelaufen":
        zweiter = _zweiter_lauf(fabrik, schulen, lauf)
        with fabrik.intern_kontext() as s:
            pt = s.execute(select(PostenToken).where(PostenToken.token == zweiter["token"])).scalar_one()
            pt.gueltig_bis = datetime.now(UTC) - timedelta(minutes=1)
    else:
        _zweiter_lauf(fabrik, schulen, lauf, status=fall)

    assert client.get(f"/api/p/{lauf['token']}/config").json()["weitere_laeufe"] == []


def test_angebotenes_token_traegt_wirklich_in_den_anderen_lauf(client, fabrik, schulen, lauf):
    """Der Wechsel muss funktionieren, sonst steht die Person am Posten ohne App da."""
    zweiter = _zweiter_lauf(fabrik, schulen, lauf)
    k = client.get(f"/api/p/{lauf['token']}/config").json()
    anderes = k["weitere_laeufe"][0]["token"]
    neu = client.get(f"/api/p/{anderes}/config").json()
    assert neu["lauf_id"] == zweiter["lauf_id"] != lauf["lauf_id"]
    assert neu["posten"]["id"] == lauf["posten_id"]  # derselbe Posten
    assert neu["startnummern"] == [1]  # Klasse 4b hat nur ein Kind


@pytest.mark.parametrize("fall", ["unbekannt", "abgelaufen", "abgeschlossen", "archiviert", "zu_kurz"])
def test_ungueltige_tokens_ergeben_einheitlich_404(client, fabrik, lauf, fall):
    token = lauf["token"]
    with fabrik.intern_kontext() as s:
        pt = s.execute(select(PostenToken).where(PostenToken.token == token)).scalar_one()
        if fall == "unbekannt":
            token = neues_token()
        elif fall == "abgelaufen":
            pt.gueltig_bis = datetime.now(UTC) - timedelta(seconds=1)
        elif fall in ("abgeschlossen", "archiviert"):
            pt.lauf.status = fall
        elif fall == "zu_kurz":
            token = "abc"
    for pfad in ("config", "status"):
        r = client.get(f"/api/p/{token}/{pfad}")
        assert r.status_code == 404
        assert r.json() == {"fehler": "unbekannt"}
    assert senden(client, token, [ereignis()]).status_code == 404
    assert anzahl_ereignisse(fabrik, lauf_id=lauf["lauf_id"]) == 0


# --------------------------------------------------------------------------- Ereignisse


def test_upload_wird_bestaetigt_und_gespeichert(client, fabrik, lauf):
    events = [
        ereignis(1),
        ereignis(2, nutzlast={"durchgang_nr": 1, "fehlende_items": lauf["item_ids"][:2]}),
        ereignis(3, typ="sicherheit", nutzlast={"stufe": 2, "bemerkung": " fährt dicht am Bordstein "}),
        ereignis(1, nutzlast={"durchgang_nr": 1, "fehlende_items": [], "storniert": True}),
    ]
    r = senden(client, lauf["token"], events)
    assert r.status_code == 200
    assert sorted(r.json()["akzeptiert"]) == sorted(e["event_id"] for e in events)
    assert r.json()["abgewiesen"] == []
    with fabrik.intern_kontext() as s:
        gespeichert = {str(e.event_id): e for e in s.execute(select(Ereignis)).scalars() if e.lauf_id == lauf["lauf_id"]}
        assert gespeichert[events[1]["event_id"]].nutzlast == {"durchgang_nr": 1, "fehlende_items": lauf["item_ids"][:2]}
        assert gespeichert[events[2]["event_id"]].nutzlast == {"stufe": 2, "bemerkung": "fährt dicht am Bordstein"}
        assert gespeichert[events[3]["event_id"]].nutzlast["storniert"] is True
        assert all(e.posten_id == lauf["posten_id"] for e in gespeichert.values())
        lauf_obj = s.get(Lauf, lauf["lauf_id"])
        assert lauf_obj.status == "laufend"  # erster Upload startet den Lauf
        assert lauf_obj.tokens[0].letzter_upload is not None


def test_doppel_upload_dreimal_derselbe_stapel(client, fabrik, lauf):
    """Abnahmekriterium 2."""
    events = [ereignis(n % 9 + 1, nutzlast={"durchgang_nr": n // 9 + 1, "fehlende_items": []}) for n in range(60)]
    for _ in range(3):
        r = senden(client, lauf["token"], events)
        assert r.status_code == 200
        assert sorted(r.json()["akzeptiert"]) == sorted(e["event_id"] for e in events)
    assert anzahl_ereignisse(fabrik, lauf_id=lauf["lauf_id"]) == 60


def test_abgebrochener_upload_wird_vollstaendig_nachgeholt(client, fabrik, lauf):
    """Abnahmekriterium 3 (Server-Seite): Der erste Teil kam an, die Antwort ging verloren."""
    events = [ereignis(n % 9 + 1, nutzlast={"durchgang_nr": n // 9 + 1, "fehlende_items": []}) for n in range(40)]
    senden(client, lauf["token"], events[:17])  # Antwort „verloren"
    r = senden(client, lauf["token"], events)  # Gerät sendet alles erneut
    assert sorted(r.json()["akzeptiert"]) == sorted(e["event_id"] for e in events)
    assert anzahl_ereignisse(fabrik, lauf_id=lauf["lauf_id"]) == 40


def test_doppelte_id_im_selben_stapel(client, fabrik, lauf):
    e = ereignis()
    r = senden(client, lauf["token"], [e, dict(e)])
    assert r.json()["akzeptiert"] == [e["event_id"]]
    assert anzahl_ereignisse(fabrik, lauf_id=lauf["lauf_id"]) == 1


def test_fremde_startnummer_wird_einzeln_abgewiesen(client, fabrik, lauf):
    gut, fremd = ereignis(4), ereignis(77)
    r = senden(client, lauf["token"], [gut, fremd])
    assert r.status_code == 200
    assert r.json()["akzeptiert"] == [gut["event_id"]]
    assert r.json()["abgewiesen"] == [{"event_id": fremd["event_id"], "grund": "startnummer gehört nicht zum Lauf"}]
    assert anzahl_ereignisse(fabrik, lauf_id=lauf["lauf_id"]) == 1


def test_inaktives_kind_wird_angenommen(client, lauf):
    """Nach dem Laden deaktiviert: die Erfassung ist trotzdem echt."""
    e = ereignis(10)
    assert senden(client, lauf["token"], [e]).json()["akzeptiert"] == [e["event_id"]]


@pytest.mark.parametrize(
    "aendern,grund",
    [
        (lambda e, l: e.update(event_id="keine-uuid"), "event_id ist keine UUID"),
        (lambda e, l: e.update(event_id=str(uuid.uuid1())), "event_id ist keine UUIDv4"),
        (lambda e, l: e.update(typ="sonstwas"), "typ ungültig"),
        (lambda e, l: e.update(startnummer=True), "startnummer fehlt"),
        (lambda e, l: e.update(startnummer="3"), "startnummer fehlt"),
        (lambda e, l: e.update(erfasst_am="gestern"), "erfasst_am ungültig"),
        (lambda e, l: e.update(erfasst_am="2026-10-20T10:00:00"), "erfasst_am ohne Zeitzone"),
        (lambda e, l: e.update(name="Max"), "unbekannte Felder"),
        (lambda e, l: e["nutzlast"].update(durchgang_nr=0), "durchgang_nr ungültig"),
        (lambda e, l: e["nutzlast"].update(fehlende_items=[999999]), "fehlende_items gehören nicht zum Posten"),
        (lambda e, l: e["nutzlast"].update(fehlende_items=[l["item_ids"][0]] * 2), "fehlende_items gehören nicht zum Posten"),
        (lambda e, l: e["nutzlast"].update(fehlende_items="Blick"), "fehlende_items ungültig"),
        (lambda e, l: e["nutzlast"].update(kommentar="x"), "unbekannte Felder in nutzlast"),
        (lambda e, l: e.update(typ="sicherheit", nutzlast={"stufe": 4}), "stufe ungültig"),
        (lambda e, l: e.update(typ="sicherheit", nutzlast={"stufe": True}), "stufe ungültig"),
        (lambda e, l: e.update(typ="sicherheit", nutzlast={"stufe": 1, "bemerkung": "x" * 501}), "bemerkung ungültig"),
    ],
)
def test_ungueltige_ereignisse_werden_einzeln_abgewiesen(client, fabrik, lauf, aendern, grund):
    gut, schlecht = ereignis(1), ereignis(2)
    aendern(schlecht, lauf)
    r = senden(client, lauf["token"], [gut, schlecht])
    assert r.status_code == 200
    assert r.json()["akzeptiert"] == [gut["event_id"]]
    [abgewiesen] = r.json()["abgewiesen"]
    assert abgewiesen["grund"] == grund
    assert anzahl_ereignisse(fabrik, lauf_id=lauf["lauf_id"]) == 1


def test_items_eines_anderen_postens_abgewiesen(client, fabrik, lauf, schulen):
    a, _ = schulen
    e = ereignis(1, nutzlast={"durchgang_nr": 1, "fehlende_items": [a.item]})
    assert senden(client, lauf["token"], [e]).json()["akzeptiert"] == []


def test_fremde_event_id_wird_nicht_ueberschrieben(client, fabrik, lauf, schulen):
    """Eine event_id, die schon einem anderen Lauf (hier: Schule B) gehört, wird abgewiesen."""
    _, b = schulen
    e = ereignis(1)
    e["event_id"] = str(b.ereignis)
    r = senden(client, lauf["token"], [e])
    assert r.json()["akzeptiert"] == []
    assert r.json()["abgewiesen"][0]["grund"] == "event_id bereits anderweitig vergeben"
    with fabrik.intern_kontext() as s:
        fremd = s.get(Ereignis, b.ereignis)
        assert fremd.lauf_id == b.lauf and fremd.startnummer == 7


def test_hoechstens_1000_ereignisse(client, fabrik, lauf):
    assert senden(client, lauf["token"], [ereignis() for _ in range(1001)]).status_code == 413
    assert senden(client, lauf["token"], [ereignis(n % 9 + 1, nutzlast={"durchgang_nr": n // 9 + 1, "fehlende_items": []}) for n in range(1000)]).status_code == 200
    assert anzahl_ereignisse(fabrik, lauf_id=lauf["lauf_id"]) == 1000


@pytest.mark.parametrize("koerper", [b"kein json", b"[]", b'{"events": 3}', b"{}"])
def test_kaputte_anfragen(client, lauf, koerper):
    r = client.post(f"/api/p/{lauf['token']}/events", content=koerper, headers={"Content-Type": "application/json"})
    assert r.status_code == 422


def test_antworten_enthalten_keine_namen(client, fabrik, lauf):
    """Abnahmekriterium 5 für die Ereignis-API."""
    antworten = [
        client.get(f"/api/p/{lauf['token']}/config").text,
        senden(client, lauf["token"], [ereignis(1), ereignis(77)]).text,
        client.get(f"/api/p/{lauf['token']}/status").text,
    ]
    for text in antworten:
        for name in lauf["namen"]:
            assert name not in text


# --------------------------------------------------------------------------- Status


def test_status(client, lauf):
    r = client.get(f"/api/p/{lauf['token']}/status").json()
    assert r == {"offen": 9, "zuletzt_empfangen": None}
    senden(client, lauf["token"], [ereignis(1), ereignis(2), ereignis(2, typ="sicherheit", nutzlast={"stufe": 1})])
    r = client.get(f"/api/p/{lauf['token']}/status").json()
    assert r["offen"] == 7
    assert datetime.fromisoformat(r["zuletzt_empfangen"]) <= datetime.now(UTC)


# --------------------------------------------------------------------------- Rahmen


def test_ratenbegrenzung_je_token(client, lauf, schulen):
    for _ in range(120):
        assert client.get(f"/api/p/{lauf['token']}/status").status_code == 200
    assert client.get(f"/api/p/{lauf['token']}/status").status_code == 429
    assert senden(client, lauf["token"], [ereignis()]).status_code == 429


def test_logs_ohne_token_namen_und_startnummern(client, lauf, caplog):
    caplog.set_level(logging.DEBUG)
    client.get(f"/api/p/{lauf['token']}/config")
    senden(client, lauf["token"], [ereignis(4), ereignis(77)])
    client.get(f"/api/p/{lauf['token']}/status")
    # Nur Server-Logs: „httpx" ist der Test-Client, also die Seite des Anfragenden.
    text = "\n".join(r.getMessage() for r in caplog.records if not r.name.startswith("httpx"))
    assert f"lauf={lauf['lauf_id']}" in text
    assert lauf["token"] not in text
    for name in lauf["namen"]:
        assert name not in text
    assert "77" not in text


def test_zugriffsprotokoll_schwaerzt_tokens():
    from app.protokoll import TokenFilter

    record = logging.LogRecord(
        "uvicorn.access", logging.INFO, __file__, 1,
        '%s - "%s %s HTTP/%s" %d', ("1.2.3.4:5", "POST", "/api/p/GeheimesToken_123/events", "1.1", 200), None,
    )
    TokenFilter().filter(record)
    assert "GeheimesToken_123" not in record.getMessage()
    assert "/api/p/***/events" in record.getMessage()


# --------------------------------------------------------------------------- Seiten


def test_app_seite_und_manifest(client, lauf):
    r = client.get(f"/p/{lauf['token']}")
    assert r.status_code == 200
    assert f'href="/p/{lauf["token"]}/manifest.webmanifest"' in r.text
    m = client.get(f"/p/{lauf['token']}/manifest.webmanifest").json()
    assert m["display"] == "standalone"
    assert m["start_url"] == f"/p/{lauf['token']}"
    assert client.get("/p/ung%C3%BCltig!").status_code == 404


def test_service_worker(client):
    r = client.get("/p/sw.js")
    assert r.status_code == 200
    assert "javascript" in r.headers["content-type"]
    assert "__VERSION__" not in r.text and "__ASSETS__" not in r.text
    assets = json.loads(r.text.split("const ASSETS = ", 1)[1].split(";", 1)[0])
    assert "/p/assets/js/main.js" in assets and "/p/assets/vendor/idb.js" in assets
    for a in assets:
        assert client.get(a).status_code == 200, a
    # API wird vom Service Worker nie aus dem Cache bedient
    assert 'startsWith("/api/")) return' in r.text


def test_app_seite_enthaelt_keine_namen(client, lauf):
    html = client.get(f"/p/{lauf['token']}").text
    for name in lauf["namen"]:
        assert name not in html
