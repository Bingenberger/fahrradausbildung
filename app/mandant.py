"""Mandanten-Schicht (Spezifikation 4.1).

Jede ORM-Sitzung dieser Anwendung trägt einen *Bereich*:

``MANDANT``
    Gebunden an genau eine ``schule_id``. Jede SELECT-, UPDATE- und DELETE-Anweisung
    wird automatisch auf diese Schule eingeschränkt (``with_loader_criteria`` für
    jedes Mandantenmodell). Beim Schreiben wird geprüft, dass neue oder geänderte
    Objekte samt ihrer Eltern zu dieser Schule gehören. Rohes SQL ist gesperrt.

``SYSTEMADMIN``
    Darf ausschließlich ``Schule`` und ``Benutzer`` sehen. Jede Anweisung, die ein
    anderes Modell berührt, wird abgewiesen – technisch, nicht nur in der Navigation.

``INTERN``
    Uneingeschränkt. Nur für Token-Auflösung, Anmeldung, Management-Kommandos und
    Tests. Route-Handler des Verwaltungsbereichs dürfen sie nicht verwenden (ein
    Test prüft das statisch).

Eine Sitzung ohne Bereich kann keine Anweisung ausführen. Damit ist die
Einschränkung keine Konvention, die jede Query selbst mitbringen muss: wer eine
Sitzung hat, hat automatisch den richtigen Filter.

Route-Handler greifen nicht auf die Sitzung zu, sondern auf ``SchulRepository``
bzw. ``SystemRepository``.
"""

from __future__ import annotations

import enum
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any, TypeVar

from sqlalchemy import event, false, inspect, select
from sqlalchemy.orm import ORMExecuteState, Session, sessionmaker, with_loader_criteria
from sqlalchemy.sql import Executable, visitors
from sqlalchemy.sql.schema import Column
from sqlalchemy.sql.selectable import TableClause
from sqlalchemy.sql.elements import ColumnElement

from app.modelle import (
    MANDANTENMODELLE,
    SYSTEMADMIN_MODELLE,
    Benutzer,
    Ereignis,
    Mandantenmodell,
    Schule,
)

M = TypeVar("M")


class Bereich(enum.Enum):
    MANDANT = "mandant"
    SYSTEMADMIN = "systemadmin"
    INTERN = "intern"


class NichtGefunden(Exception):
    """Objekt existiert nicht – oder gehört einer anderen Schule.

    Beide Fälle sind bewusst nicht unterscheidbar; die Web-Schicht antwortet mit 404.
    """


class Mandantenverletzung(Exception):
    """Ein Schreib- oder Lesezugriff hätte die Mandantengrenze überschritten."""


# --------------------------------------------------------------------------- Sitzungen

_KEY_BEREICH = "fp_bereich"
_KEY_SCHULE = "fp_schule_id"


class FPSession(Session):
    """Sitzungsklasse der Anwendung. Nur über die Fabriken unten zu erzeugen."""

    @property
    def bereich(self) -> Bereich | None:
        return self.info.get(_KEY_BEREICH)

    @property
    def schule_id(self) -> int | None:
        return self.info.get(_KEY_SCHULE)


class Sitzungsfabrik:
    """Erzeugt Sitzungen mit festgelegtem Bereich."""

    def __init__(self, engine) -> None:
        self._maker = sessionmaker(bind=engine, class_=FPSession, expire_on_commit=False)

    def _neu(self, bereich: Bereich, schule_id: int | None) -> FPSession:
        s = self._maker()
        s.info[_KEY_BEREICH] = bereich
        s.info[_KEY_SCHULE] = schule_id
        return s

    def mandant(self, schule_id: int) -> FPSession:
        if not isinstance(schule_id, int) or isinstance(schule_id, bool):
            raise TypeError("schule_id muss eine ganze Zahl sein")
        return self._neu(Bereich.MANDANT, schule_id)

    def systemadmin(self) -> FPSession:
        return self._neu(Bereich.SYSTEMADMIN, None)

    def intern(self) -> FPSession:
        return self._neu(Bereich.INTERN, None)

    @contextmanager
    def intern_kontext(self) -> Iterator[FPSession]:
        s = self.intern()
        try:
            yield s
            s.commit()
        except BaseException:
            s.rollback()
            raise
        finally:
            s.close()


def _bereich(session: Session) -> Bereich:
    bereich = session.info.get(_KEY_BEREICH)
    if not isinstance(bereich, Bereich):
        raise Mandantenverletzung("Sitzung ohne Bereich – nur über Sitzungsfabrik erzeugen")
    return bereich


def _kriterien(schule_id: int) -> list[Any]:
    return [
        with_loader_criteria(modell, modell.mandant_kriterium(schule_id), include_aliases=True)
        for modell in MANDANTENMODELLE
    ]


_SYSTEMADMIN_SPERREN = [
    with_loader_criteria(modell, false(), include_aliases=True)
    for modell in MANDANTENMODELLE
    if modell not in SYSTEMADMIN_MODELLE
]


_SYSTEMADMIN_TABELLEN = frozenset(m.__tablename__ for m in SYSTEMADMIN_MODELLE)
_MANDANT_TABELLEN = frozenset(m.__tablename__ for m in MANDANTENMODELLE)


def _ist_orm(element: Any) -> bool:
    return "parententity" in getattr(element, "_annotations", {})


def _tabellen(stmt: Any) -> set[str]:
    """Namen aller Tabellen, die irgendwo in der Anweisung vorkommen.

    Wirft ``Mandantenverletzung``, wenn eine Tabelle nirgends über das ORM, sondern
    nur über die Core-Ebene (``Modell.__table__``) angesprochen wird – dort greift
    ``with_loader_criteria`` nicht. Rohe Spalten an einer ORM-Tabelle sind dagegen
    erlaubt: Solche Anweisungen erzeugt SQLAlchemy selbst für ``session.get()`` und
    das Nachladen von Beziehungen. Den Mischfall (ORM-Entität plus Core-Unterabfrage
    derselben Tabelle) schließt ``tests/test_architektur.py`` statisch aus.
    """
    alle: set[str] = set()
    orm: set[str] = set()
    for e in visitors.iterate(stmt):
        if isinstance(e, Column):
            if _ist_orm(e):
                orm.add(e.table.name)
        elif isinstance(e, TableClause):
            alle.add(e.name)
            if _ist_orm(e):
                orm.add(e.name)
    if alle - orm:
        raise Mandantenverletzung(f"Core-Zugriff auf {', '.join(sorted(alle - orm))} ist gesperrt")
    return alle


@event.listens_for(FPSession, "do_orm_execute")
def _lesefilter(state: ORMExecuteState) -> None:
    bereich = _bereich(state.session)
    if bereich is Bereich.INTERN:
        return

    tabellen = _tabellen(state.statement)
    if not tabellen:
        # Rohes SQL (text(), Core-Anweisungen ohne Modell) umgeht jeden Filter.
        raise Mandantenverletzung("Anweisung ohne Modellbezug ist in diesem Bereich gesperrt")

    if bereich is Bereich.SYSTEMADMIN:
        # Alle Tabellen der Anweisung, auch in Joins und Unterabfragen.
        verboten = tabellen - _SYSTEMADMIN_TABELLEN
        if verboten:
            raise Mandantenverletzung(
                f"Systemadmin hat keinen Zugriff auf: {', '.join(sorted(verboten))}"
            )
        if state.is_select or state.is_update or state.is_delete:
            # Zusätzlich jede indirekt mitgeladene Tabelle leeren.
            state.statement = state.statement.options(*_SYSTEMADMIN_SPERREN)
        return

    # Bereich.MANDANT
    fremd = tabellen - _MANDANT_TABELLEN
    if fremd:
        # Infrastruktur-Tabellen (Sitzungen) haben keinen Schulbezug.
        raise Mandantenverletzung(f"Kein Zugriff auf: {', '.join(sorted(fremd))}")
    if state.is_column_load:
        # Nachladen einer Spalte eines bereits (gefiltert) geladenen Objekts.
        return
    if state.is_insert:
        # INSERT-Anweisungen über die ORM (z. B. Bulk-Insert) prüfen wir nicht pauschal;
        # die Anwendung schreibt im Mandantenbereich nur über session.add() + Flush.
        raise Mandantenverletzung("Massen-INSERT im Mandantenbereich ist gesperrt")
    if state.is_select or state.is_update or state.is_delete:
        state.statement = state.statement.options(*_kriterien(state.session.info[_KEY_SCHULE]))


# --------------------------------------------------------------------------- Schreibprüfung


def pk_attribut(modell: type) -> Any:
    """ORM-Attribut des Primärschlüssels (nicht die rohe Tabellenspalte)."""
    mapper = inspect(modell)
    return getattr(modell, mapper.get_property_by_column(mapper.primary_key[0]).key)


def _sichtbar(session: Session, modell: type, pk: Any) -> bool:
    """Ist das Objekt mit diesem Primärschlüssel in der (gefilterten) Sitzung sichtbar?"""
    pk_spalte = pk_attribut(modell)
    with session.no_autoflush:
        return session.execute(select(pk_spalte).where(pk_spalte == pk)).first() is not None


def _pruefe_eltern(session: Session, obj: Mandantenmodell, schule_id: int) -> None:
    for fk, (rel, eltern_modell) in type(obj).__mandant_eltern__.items():
        if eltern_modell is Schule:
            wert = getattr(obj, fk)
            if wert is None:
                setattr(obj, fk, schule_id)
            elif wert != schule_id:
                raise Mandantenverletzung(f"{type(obj).__name__}.{fk} gehört nicht zur Schule")
            continue

        wert = getattr(obj, fk)
        if wert is not None:
            # Fremdschlüssel gesetzt: maßgeblich ist der Wert, nicht eine evtl.
            # veraltete Beziehung im Speicher.
            if not _sichtbar(session, eltern_modell, wert):
                raise Mandantenverletzung(
                    f"{type(obj).__name__}.{fk} verweist auf fremdes oder fehlendes Objekt"
                )
            continue

        eltern = getattr(obj, rel, None) if rel in inspect(type(obj)).relationships else None
        if eltern is None:
            continue  # NOT NULL der Datenbank greift
        zustand = inspect(eltern)
        if zustand.pending:
            continue  # wird als neues Objekt selbst geprüft
        if not _sichtbar(session, eltern_modell, zustand.identity[0]):
            raise Mandantenverletzung(
                f"{type(obj).__name__}.{rel} verweist auf fremdes oder fehlendes Objekt"
            )


@event.listens_for(FPSession, "before_flush")
def _schreibpruefung(session: Session, flush_context, instances) -> None:
    bereich = _bereich(session)
    if bereich is Bereich.INTERN:
        return

    alle = list(session.new) + list(session.dirty) + list(session.deleted)

    if bereich is Bereich.SYSTEMADMIN:
        for obj in alle:
            if type(obj) not in SYSTEMADMIN_MODELLE:
                raise Mandantenverletzung(
                    f"Systemadmin darf {type(obj).__name__} nicht schreiben"
                )
        return

    schule_id: int = session.info[_KEY_SCHULE]

    for obj in alle:
        if not isinstance(obj, Mandantenmodell):
            raise Mandantenverletzung(f"Unbekanntes Modell {type(obj).__name__}")

        if isinstance(obj, Ereignis):
            # Ereignisse entstehen nur über die Token-API und sind unveränderlich.
            raise Mandantenverletzung("Ereignisse sind im Verwaltungsbereich nur lesbar")

        if isinstance(obj, Schule):
            if obj in session.new or obj in session.deleted or obj.id != schule_id:
                raise Mandantenverletzung("Schulen werden nur vom Systemadmin angelegt")
            continue

        if isinstance(obj, Benutzer) and obj.rolle != "schuladmin":
            raise Mandantenverletzung("Im Mandantenbereich gibt es nur Schuladmins")

        if obj not in session.new:
            # Bestehendes Objekt: muss vor der Änderung zur Schule gehört haben.
            ident = inspect(obj).identity
            if ident is None or not _sichtbar(session, type(obj), ident[0]):
                raise Mandantenverletzung(f"{type(obj).__name__} gehört nicht zur Schule")

        if obj not in session.deleted:
            _pruefe_eltern(session, obj, schule_id)


# --------------------------------------------------------------------------- Repositories


class SchulRepository:
    """Einziger Datenzugang der Route-Handler im Verwaltungsbereich.

    Die Einschränkung auf die Schule steckt in der Sitzung; das Repository bietet
    eine schmale, bequeme Oberfläche und wandelt „nicht sichtbar" in ``NichtGefunden``.
    """

    def __init__(self, session: FPSession) -> None:
        if session.bereich is not Bereich.MANDANT or session.schule_id is None:
            raise Mandantenverletzung("SchulRepository braucht eine Mandantensitzung")
        self._s = session

    @property
    def schule_id(self) -> int:
        assert self._s.schule_id is not None
        return self._s.schule_id

    def holen(self, modell: type[M], pk: Any) -> M:
        obj = self._s.execute(
            select(modell).where(pk_attribut(modell) == pk)
        ).scalar_one_or_none()
        if obj is None:
            raise NichtGefunden(modell.__name__)
        return obj

    def liste(
        self,
        modell: type[M],
        *bedingungen: ColumnElement[bool],
        sortierung: Sequence[Any] = (),
    ) -> list[M]:
        stmt = select(modell).where(*bedingungen).order_by(*sortierung)
        return list(self._s.execute(stmt).scalars())

    def abfrage(self, stmt: Executable) -> Any:
        """Beliebige ORM-Abfrage – sie läuft durch denselben Mandantenfilter."""
        return self._s.execute(stmt)

    def hinzufuegen(self, obj: Any) -> Any:
        self._s.add(obj)
        self._s.flush()
        return obj

    def loeschen(self, obj: Any) -> None:
        self._s.delete(obj)
        self._s.flush()

    def flush(self) -> None:
        self._s.flush()

    def commit(self) -> None:
        self._s.commit()

    def rollback(self) -> None:
        self._s.rollback()


class SystemRepository:
    """Datenzugang des Systemadmins: nur Schulen und Benutzer."""

    def __init__(self, session: FPSession) -> None:
        if session.bereich is not Bereich.SYSTEMADMIN:
            raise Mandantenverletzung("SystemRepository braucht eine Systemadmin-Sitzung")
        self._s = session

    def holen(self, modell: type[M], pk: Any) -> M:
        if modell not in SYSTEMADMIN_MODELLE:
            raise NichtGefunden(modell.__name__)
        obj = self._s.get(modell, pk)
        if obj is None:
            raise NichtGefunden(modell.__name__)
        return obj

    def liste(
        self,
        modell: type[M],
        *bedingungen: ColumnElement[bool],
        sortierung: Sequence[Any] = (),
    ) -> list[M]:
        stmt = select(modell).where(*bedingungen).order_by(*sortierung)
        return list(self._s.execute(stmt).scalars())

    def hinzufuegen(self, obj: Any) -> Any:
        self._s.add(obj)
        self._s.flush()
        return obj

    def flush(self) -> None:
        self._s.flush()

    def commit(self) -> None:
        self._s.commit()

    def rollback(self) -> None:
        self._s.rollback()
