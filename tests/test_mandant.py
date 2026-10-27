"""Mandantentrennung auf Ebene der Sitzungs-/Repository-Schicht (Spezifikation 4.1).

Jeder Test läuft mit zwei vollständig befüllten Schulen A und B und prüft, dass
eine Sitzung der Schule A von B nichts lesen, ändern oder löschen kann.
Die endpunktbezogenen Tests (HTTP 404) folgen mit dem Verwaltungsbereich.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import delete, exists, func, inspect, select, text, update
from sqlalchemy.exc import DBAPIError

from app.mandant import (
    Bereich,
    FPSession,
    Mandantenverletzung,
    NichtGefunden,
    SchulRepository,
    SystemRepository,
    pk_attribut,
)
from app.modelle import (
    Ablauf,
    AblaufSchritt,
    MANDANTENMODELLE,
    Benutzer,
    Ereignis,
    Gruppe,
    Item,
    Kind,
    Lauf,
    Posten,
    PostenToken,
    Schule,
    Strecke,
)

MODELLE = pytest.mark.parametrize("modell", MANDANTENMODELLE, ids=lambda m: m.__name__)


def _pk(modell):
    return pk_attribut(modell)


def _repo(fabrik, schule_id: int) -> SchulRepository:
    return SchulRepository(fabrik.mandant(schule_id))


# --------------------------------------------------------------------------- Grundsätzliches


def test_sitzung_ohne_bereich_kann_nichts_ausfuehren(engine, schulen):
    with FPSession(bind=engine) as roh:
        with pytest.raises(Mandantenverletzung):
            roh.execute(select(Schule))


def test_repository_verlangt_passenden_bereich(fabrik):
    with pytest.raises(Mandantenverletzung):
        SchulRepository(fabrik.intern())
    with pytest.raises(Mandantenverletzung):
        SchulRepository(fabrik.systemadmin())
    with pytest.raises(Mandantenverletzung):
        SystemRepository(fabrik.mandant(1))
    with pytest.raises(TypeError):
        fabrik.mandant("1")  # type: ignore[arg-type]


def test_bereich_wird_gesetzt(fabrik):
    assert fabrik.mandant(3).bereich is Bereich.MANDANT
    assert fabrik.mandant(3).schule_id == 3
    assert fabrik.systemadmin().bereich is Bereich.SYSTEMADMIN


# --------------------------------------------------------------------------- Lesen


@MODELLE
def test_liste_zeigt_nur_eigene_schule(fabrik, schulen, modell):
    a, b = schulen
    for eigen, fremd in ((a, b), (b, a)):
        ids = {_ident(o) for o in _repo(fabrik, eigen.schule).liste(modell)}
        assert ids == {eigen.id_fuer(modell)}
        assert fremd.id_fuer(modell) not in ids


@MODELLE
def test_fremde_id_ist_nicht_gefunden(fabrik, schulen, modell):
    a, b = schulen
    repo = _repo(fabrik, a.schule)
    assert _ident(repo.holen(modell, a.id_fuer(modell))) == a.id_fuer(modell)
    with pytest.raises(NichtGefunden):
        repo.holen(modell, b.id_fuer(modell))


@MODELLE
def test_session_get_auf_fremde_id_liefert_nichts(fabrik, schulen, modell):
    a, b = schulen
    assert fabrik.mandant(a.schule).get(modell, b.id_fuer(modell)) is None


@MODELLE
def test_zaehlen_sieht_nur_eigene_schule(fabrik, schulen, modell):
    a, _ = schulen
    repo = _repo(fabrik, a.schule)
    assert repo.abfrage(select(func.count(_pk(modell)))).scalar_one() == 1
    assert repo.abfrage(select(func.count()).select_from(modell)).scalar_one() == 1


def test_unterabfrage_verraet_keine_fremden_daten(fabrik, schulen):
    a, b = schulen
    repo = _repo(fabrik, a.schule)
    # Existenz-Orakel über EXISTS
    stmt = select(Strecke.id).where(exists().where(Kind.id == b.kind))
    assert repo.abfrage(stmt).all() == []
    # Orakel über IN-Unterabfrage
    stmt = select(Schule.id).where(
        Schule.id.in_(select(Gruppe.schule_id).join(Kind).where(Kind.id == b.kind))
    )
    assert repo.abfrage(stmt).all() == []
    # Orakel über Join
    stmt = select(Lauf.id).join(Kind, Kind.gruppe_id == Lauf.gruppe_id).where(
        Kind.id == b.kind
    )
    assert repo.abfrage(stmt).all() == []


def test_spaltenabfrage_liefert_keine_fremden_zeilen(fabrik, schulen):
    a, b = schulen
    zeilen = _repo(fabrik, a.schule).abfrage(select(Kind.id, Kind.gruppe_id)).all()
    assert [tuple(z) for z in zeilen] == [(a.kind, a.gruppe)]


def test_beziehungen_laden_gefiltert(fabrik, schulen):
    a, _ = schulen
    repo = _repo(fabrik, a.schule)
    lauf = repo.holen(Lauf, a.lauf)
    assert lauf.strecke.id == a.strecke
    assert [k.id for k in lauf.gruppe.kinder] == [a.kind]
    assert [p.id for p in lauf.strecke.posten] == [a.posten]
    assert [t.id for t in lauf.tokens] == [a.posten_token]


def test_kein_cache_ueberlauf_zwischen_schulen(fabrik, schulen):
    """Gecachte Anweisungen dürfen die schule_id nicht mitschleppen."""
    a, b = schulen
    for _ in range(3):
        for daten in (a, b):
            kinder = _repo(fabrik, daten.schule).liste(Kind)
            assert [k.id for k in kinder] == [daten.kind]


def test_rohes_sql_ist_gesperrt(fabrik, schulen):
    a, _ = schulen
    s = fabrik.mandant(a.schule)
    with pytest.raises(Mandantenverletzung):
        s.execute(text("SELECT startnummer FROM kind"))
    with pytest.raises(Mandantenverletzung):
        s.execute(select(text("1")))


def test_core_zugriff_am_orm_vorbei_ist_gesperrt(fabrik, schulen):
    """Über ``Modell.__table__`` greift with_loader_criteria nicht – also gesperrt."""
    a, b = schulen
    s = fabrik.mandant(a.schule)
    kind = Kind.__table__
    umwege = [
        select(kind),
        select(kind.c.startnummer),
        select(func.count()).select_from(kind),
        select(Strecke).where(Strecke.id.in_(select(kind.c.gruppe_id))),
        select(Strecke).join(kind, kind.c.id == Strecke.id),
        update(kind).values(aktiv=False),
        delete(kind),
    ]
    for stmt in umwege:
        with pytest.raises(Mandantenverletzung):
            s.execute(stmt)
        s.rollback()
    _unveraendert(fabrik, Kind, b)


# --------------------------------------------------------------------------- Ändern / Löschen


@MODELLE
def test_massen_update_trifft_keine_fremden_zeilen(fabrik, schulen, modell):
    a, b = schulen
    s = fabrik.mandant(a.schule)
    pk = _pk(modell)
    spalte = _harmlose_spalte(modell)
    ergebnis = s.execute(
        update(modell).where(pk == b.id_fuer(modell)).values({spalte: _harmloser_wert(modell)}),
        execution_options={"synchronize_session": False},
    )
    assert ergebnis.rowcount == 0
    s.commit()
    _unveraendert(fabrik, modell, b)


@MODELLE
def test_massen_delete_trifft_keine_fremden_zeilen(fabrik, schulen, modell):
    a, b = schulen
    s = fabrik.mandant(a.schule)
    ergebnis = s.execute(
        delete(modell).where(_pk(modell) == b.id_fuer(modell)),
        execution_options={"synchronize_session": False},
    )
    assert ergebnis.rowcount == 0
    s.commit()
    _unveraendert(fabrik, modell, b)


def test_objekt_einer_fremden_schule_nicht_loeschbar(fabrik, schulen):
    """Selbst ein in die Sitzung geschmuggeltes fremdes Objekt lässt sich nicht löschen."""
    a, b = schulen
    with fabrik.intern_kontext() as intern:
        fremde_gruppe = intern.get(Gruppe, b.gruppe)
        intern.expunge(fremde_gruppe)
    s = fabrik.mandant(a.schule)
    s.add(fremde_gruppe)
    s.delete(fremde_gruppe)
    with pytest.raises(Mandantenverletzung):
        s.flush()
    s.rollback()
    _unveraendert(fabrik, Gruppe, b)


def test_objekt_einer_fremden_schule_nicht_aenderbar(fabrik, schulen):
    a, b = schulen
    with fabrik.intern_kontext() as intern:
        fremde_strecke = intern.get(Strecke, b.strecke)
        intern.expunge(fremde_strecke)
    s = fabrik.mandant(a.schule)
    fremde_strecke = s.merge(fremde_strecke, load=False)
    fremde_strecke.name = "gekapert"
    with pytest.raises(Mandantenverletzung):
        s.flush()
    s.rollback()
    _unveraendert(fabrik, Strecke, b)


# --------------------------------------------------------------------------- Anlegen


def _neu_mit_fremden_eltern(a, b):
    """Für jedes Kindmodell ein neues Objekt der Schule A, das auf B verweist."""
    jetzt = datetime.now(UTC)
    return {
        "Strecke.schule_id": Strecke(schule_id=b.schule, name="x"),
        "Gruppe.schule_id": Gruppe(schule_id=b.schule, name="x", schuljahr="x"),
        "Benutzer.schule_id": Benutzer(
            schule_id=b.schule, email="x@x.example", passwort_hash="x", rolle="schuladmin"
        ),
        "Posten.strecke_id": Posten(strecke_id=b.strecke, name="x", position=9),
        "Item.posten_id": Item(posten_id=b.posten, kurzbezeichnung="x", position=9),
        "Kind.gruppe_id": Kind(gruppe_id=b.gruppe, startnummer=99),
        "Ablauf.schule_id": Ablauf(schule_id=b.schule, name="x"),
        "AblaufSchritt.ablauf_id": AblaufSchritt(ablauf_id=b.ablauf, kurzbezeichnung="x", position=9),
        "Lauf.strecke_id": Lauf(
            strecke_id=b.strecke, gruppe_id=a.gruppe, datum=date(2030, 1, 1)
        ),
        "Lauf.gruppe_id": Lauf(
            strecke_id=a.strecke, gruppe_id=b.gruppe, datum=date(2030, 1, 2)
        ),
        "Lauf.schule_id": Lauf(
            schule_id=b.schule, strecke_id=a.strecke, gruppe_id=a.gruppe, datum=date(2030, 1, 3)
        ),
        "PostenToken.lauf_id": PostenToken(
            lauf_id=b.lauf, posten_id=a.posten, token="t1", gueltig_bis=jetzt
        ),
        "PostenToken.posten_id": PostenToken(
            lauf_id=a.lauf, posten_id=b.posten, token="t2", gueltig_bis=jetzt
        ),
    }


@pytest.mark.parametrize(
    "fall",
    [
        "Strecke.schule_id",
        "Gruppe.schule_id",
        "Benutzer.schule_id",
        "Posten.strecke_id",
        "Item.posten_id",
        "Kind.gruppe_id",
        "Lauf.strecke_id",
        "Lauf.gruppe_id",
        "Lauf.schule_id",
        "PostenToken.lauf_id",
        "PostenToken.posten_id",
    ],
)
def test_anlegen_mit_fremden_eltern_scheitert(fabrik, schulen, fall):
    a, b = schulen
    repo = _repo(fabrik, a.schule)
    with pytest.raises(Mandantenverletzung):
        repo.hinzufuegen(_neu_mit_fremden_eltern(a, b)[fall])
    repo.rollback()


def test_anlegen_ueber_beziehung_auf_fremdes_objekt_scheitert(fabrik, schulen):
    a, b = schulen
    with fabrik.intern_kontext() as intern:
        fremde_strecke = intern.get(Strecke, b.strecke)
        intern.expunge(fremde_strecke)
    repo = _repo(fabrik, a.schule)
    with pytest.raises(Mandantenverletzung):
        repo.hinzufuegen(Posten(strecke=fremde_strecke, name="x", position=9))
    repo.rollback()


def test_umhaengen_auf_fremde_eltern_scheitert(fabrik, schulen):
    a, b = schulen
    repo = _repo(fabrik, a.schule)
    posten = repo.holen(Posten, a.posten)
    posten.strecke_id = b.strecke
    with pytest.raises(Mandantenverletzung):
        repo.flush()
    repo.rollback()

    kind = repo.holen(Kind, a.kind)
    kind.gruppe_id = b.gruppe
    with pytest.raises(Mandantenverletzung):
        repo.flush()
    repo.rollback()

    strecke = repo.holen(Strecke, a.strecke)
    strecke.schule_id = b.schule
    with pytest.raises(Mandantenverletzung):
        repo.flush()
    repo.rollback()


def test_anlegen_in_eigener_schule_funktioniert(fabrik, schulen):
    a, _ = schulen
    repo = _repo(fabrik, a.schule)
    # schule_id wird automatisch gesetzt
    strecke = repo.hinzufuegen(Strecke(name="Neue Runde"))
    assert strecke.schule_id == a.schule
    posten = repo.hinzufuegen(Posten(strecke=strecke, name="Kreisel", position=1))
    repo.hinzufuegen(Item(posten_id=posten.id, kurzbezeichnung="Handzeichen", position=1))
    gruppe = repo.hinzufuegen(Gruppe(name="4b", schuljahr="2026/27"))
    repo.hinzufuegen(Kind(gruppe=gruppe, startnummer=1))
    repo.hinzufuegen(
        Lauf(strecke_id=strecke.id, gruppe_id=gruppe.id, datum=date(2030, 5, 5))
    )
    repo.commit()
    assert len(_repo(fabrik, a.schule).liste(Strecke)) == 2


def test_mandant_darf_keine_schule_anlegen_oder_fremde_aendern(fabrik, schulen):
    a, b = schulen
    repo = _repo(fabrik, a.schule)
    with pytest.raises(Mandantenverletzung):
        repo.hinzufuegen(Schule(name="x", kurzname="X"))
    repo.rollback()
    # die eigene Schule umbenennen ist erlaubt
    eigene = repo.holen(Schule, a.schule)
    eigene.name = "Grundschule am Park"
    repo.commit()


def test_mandant_darf_keinen_systemadmin_anlegen(fabrik, schulen):
    a, _ = schulen
    repo = _repo(fabrik, a.schule)
    with pytest.raises(Mandantenverletzung):
        repo.hinzufuegen(
            Benutzer(email="root@x.example", passwort_hash="x", rolle="systemadmin")
        )
    repo.rollback()


def test_massen_insert_im_mandantenbereich_gesperrt(fabrik, schulen):
    from sqlalchemy import insert

    a, b = schulen
    s = fabrik.mandant(a.schule)
    with pytest.raises(Mandantenverletzung):
        s.execute(insert(Strecke).values(schule_id=b.schule, name="x"))


# --------------------------------------------------------------------------- Ereignisse


def test_ereignisse_im_verwaltungsbereich_nur_lesbar(fabrik, schulen):
    a, _ = schulen
    repo = _repo(fabrik, a.schule)
    ereignis = repo.holen(Ereignis, a.ereignis)
    ereignis.startnummer = 8
    with pytest.raises(Mandantenverletzung):
        repo.flush()
    repo.rollback()

    with pytest.raises(Mandantenverletzung):
        repo.hinzufuegen(
            Ereignis(
                event_id=uuid.uuid4(),
                lauf_id=a.lauf,
                posten_id=a.posten,
                startnummer=7,
                typ="sicherheit",
                nutzlast={"stufe": 1},
                erfasst_am=datetime.now(UTC),
            )
        )
    repo.rollback()


def test_ereignisse_sind_in_der_datenbank_unveraenderlich(fabrik, schulen):
    a, _ = schulen
    s = fabrik.intern()
    with pytest.raises(DBAPIError, match="unveraenderlich"):
        s.execute(update(Ereignis).values(startnummer=8))
    s.rollback()
    s.close()


# --------------------------------------------------------------------------- Systemadmin


def test_systemadmin_sieht_schulen_und_benutzer(fabrik, schulen):
    repo = SystemRepository(fabrik.systemadmin())
    assert len(repo.liste(Schule)) == 2
    assert len(repo.liste(Benutzer)) == 2


@pytest.mark.parametrize(
    "modell",
    [m for m in MANDANTENMODELLE if m not in (Schule, Benutzer)],
    ids=lambda m: m.__name__,
)
def test_systemadmin_hat_keinen_zugriff_auf_schuldaten(fabrik, schulen, modell):
    s = fabrik.systemadmin()
    with pytest.raises(Mandantenverletzung):
        s.execute(select(modell))
    with pytest.raises(Mandantenverletzung):
        s.execute(select(func.count()).select_from(modell))
    with pytest.raises(Mandantenverletzung):
        s.get(modell, schulen[0].id_fuer(modell))
    with pytest.raises(NichtGefunden):
        SystemRepository(s).holen(modell, schulen[0].id_fuer(modell))


def test_systemadmin_kommt_auch_ueber_umwege_nicht_an_kinder(fabrik, schulen):
    a, _ = schulen
    s = fabrik.systemadmin()
    umwege = [
        select(Schule).join(Gruppe, Gruppe.schule_id == Schule.id),
        select(Schule).where(Schule.id.in_(select(Kind.gruppe_id))),
        select(Schule).where(exists().where(Kind.id == a.kind)),
        select(Schule).where(Schule.id.in_(select(Kind.__table__.c.gruppe_id))),
        select(Kind.startnummer),
    ]
    for stmt in umwege:
        with pytest.raises(Mandantenverletzung):
            s.execute(stmt)


def test_systemadmin_kann_keine_schuldaten_schreiben(fabrik, schulen):
    a, _ = schulen
    repo = SystemRepository(fabrik.systemadmin())
    with pytest.raises(Mandantenverletzung):
        repo.hinzufuegen(Gruppe(schule_id=a.schule, name="x", schuljahr="x"))
    repo.rollback()


def test_systemadmin_legt_schule_und_schuladmin_an(fabrik):
    repo = SystemRepository(fabrik.systemadmin())
    schule = repo.hinzufuegen(Schule(name="Grundschule C", kurzname="C"))
    repo.hinzufuegen(
        Benutzer(
            schule_id=schule.id, email="c@c.example", passwort_hash="x", rolle="schuladmin"
        )
    )
    schule.aktiv = False
    repo.commit()


# --------------------------------------------------------------------------- Hilfen


def _ident(obj):
    return inspect(obj).identity[0]


def _harmlose_spalte(modell) -> str:
    return {
        Schule: "name",
        Benutzer: "aktiv",
        Strecke: "name",
        Posten: "name",
        Item: "kurzbezeichnung",
        Ablauf: "name",
        AblaufSchritt: "kurzbezeichnung",
        Gruppe: "name",
        Kind: "aktiv",
        Lauf: "status",
        PostenToken: "gueltig_bis",
        Ereignis: "startnummer",
    }[modell]


def _harmloser_wert(modell):
    return {
        Benutzer: False,
        Kind: False,
        Lauf: "abgeschlossen",
        PostenToken: datetime.now(UTC) - timedelta(days=1),
        Ereignis: 99,
    }.get(modell, "gekapert")


def _unveraendert(fabrik, modell, daten) -> None:
    with fabrik.intern_kontext() as s:
        obj = s.get(modell, daten.id_fuer(modell))
        assert obj is not None, f"{modell.__name__} der fremden Schule wurde gelöscht"
        wert = getattr(obj, _harmlose_spalte(modell))
        assert wert != _harmloser_wert(modell) or isinstance(wert, datetime)
        if modell is PostenToken:
            assert obj.gueltig_bis > datetime.now(UTC)


def test_sitzungstabelle_ist_ausserhalb_von_intern_gesperrt(fabrik, schulen):
    from app.modelle import AdminSitzung

    a, _ = schulen
    for s in (fabrik.mandant(a.schule), fabrik.systemadmin()):
        with pytest.raises(Mandantenverletzung):
            s.execute(select(AdminSitzung))
        with pytest.raises(Mandantenverletzung):
            s.execute(select(Benutzer).join(AdminSitzung))
