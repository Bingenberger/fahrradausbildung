"""Datenmodell (Spezifikation Abschnitt 3).

Jedes schulbezogene Modell beschreibt mit ``mandant_kriterium`` selbst, wie es
einer Schule zugeordnet ist, und mit ``__mandant_eltern__``, über welche
Fremdschlüssel es an schulbezogenen Eltern hängt. Die Mandanten-Schicht
(``app.mandant``) wertet beides automatisch aus – Route-Handler müssen und
dürfen sich darum nicht selbst kümmern.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, ClassVar

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Double,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql.elements import ColumnElement

NAMENSKONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

ROLLEN = ("schuladmin", "systemadmin")
LAUF_STATUS = ("vorbereitet", "laufend", "abgeschlossen", "archiviert")
EREIGNIS_TYPEN = ("durchgang", "sicherheit")


class Basis(DeclarativeBase):
    pass


Basis.metadata.naming_convention = NAMENSKONVENTION


class Mandantenmodell:
    """Markiert ein Modell als schulbezogen.

    ``__mandant_eltern__`` bildet Fremdschlüsselspalte -> (Beziehungsname, Elternmodell)
    ab. Die Mandanten-Schicht prüft beim Schreiben, dass jeder dieser Eltern zur
    Schule der Sitzung gehört.
    """

    __mandant_eltern__: ClassVar[dict[str, tuple[str, type]]] = {}

    @classmethod
    def mandant_kriterium(cls, schule_id: int) -> ColumnElement[bool]:
        raise NotImplementedError


def _in_list(text_: str) -> str:
    return ", ".join(f"'{w}'" for w in text_)


# --------------------------------------------------------------------------- Schule


class Schule(Mandantenmodell, Basis):
    __tablename__ = "schule"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    kurzname: Mapped[str] = mapped_column(String(50), unique=True)
    aktiv: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    erstellt_am: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    @classmethod
    def mandant_kriterium(cls, schule_id: int) -> ColumnElement[bool]:
        return cls.id == schule_id


# --------------------------------------------------------------------------- Benutzer


class Benutzer(Mandantenmodell, Basis):
    __tablename__ = "benutzer"
    __table_args__ = (
        CheckConstraint(f"rolle IN ({_in_list(ROLLEN)})", name="rolle"),
        # Systemadmins gehören zu keiner Schule, Schuladmins immer zu genau einer.
        CheckConstraint(
            "(rolle = 'systemadmin' AND schule_id IS NULL)"
            " OR (rolle = 'schuladmin' AND schule_id IS NOT NULL)",
            name="rolle_schule",
        ),
        Index("uq_benutzer_email_lower", func.lower(text("email")), unique=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    schule_id: Mapped[int | None] = mapped_column(
        ForeignKey("schule.id", ondelete="RESTRICT"), index=True
    )
    email: Mapped[str] = mapped_column(String(254))
    passwort_hash: Mapped[str] = mapped_column(String(255))
    rolle: Mapped[str] = mapped_column(String(20))
    aktiv: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))

    schule: Mapped[Schule | None] = relationship()

    __mandant_eltern__ = {"schule_id": ("schule", Schule)}

    @classmethod
    def mandant_kriterium(cls, schule_id: int) -> ColumnElement[bool]:
        return cls.schule_id == schule_id


# --------------------------------------------------------------------------- Strecke


class Strecke(Mandantenmodell, Basis):
    __tablename__ = "strecke"

    id: Mapped[int] = mapped_column(primary_key=True)
    schule_id: Mapped[int] = mapped_column(
        ForeignKey("schule.id", ondelete="RESTRICT"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    beschreibung: Mapped[str] = mapped_column(Text, default="", server_default="")
    archiviert: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
    # Verlauf auf der Karte (app/verwaltung/karte.py), z. B.
    # {"modus": "route", "wegpunkte": [[lat, lng], …], "linie": [[lat, lng], …]}.
    # "linie" ist die gezeichnete Strecke, "wegpunkte" die geklickten Punkte, aus
    # denen sie berechnet wurde (nur zum Weiterbearbeiten). Leer: noch nicht geplant.
    verlauf: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    posten: Mapped[list[Posten]] = relationship(
        back_populates="strecke", order_by="Posten.position", cascade="all, delete-orphan"
    )

    __mandant_eltern__ = {"schule_id": ("schule", Schule)}

    @classmethod
    def mandant_kriterium(cls, schule_id: int) -> ColumnElement[bool]:
        return cls.schule_id == schule_id


class Posten(Mandantenmodell, Basis):
    __tablename__ = "posten"
    __table_args__ = (
        CheckConstraint(
            "(lat IS NULL) = (lng IS NULL) AND "
            "(lat IS NULL OR (lat BETWEEN -90 AND 90 AND lng BETWEEN -180 AND 180))",
            name="ort",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    strecke_id: Mapped[int] = mapped_column(
        ForeignKey("strecke.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    position: Mapped[int] = mapped_column(Integer)
    beschreibung: Mapped[str] = mapped_column(Text, default="", server_default="")
    # Standort auf der Karte (WGS84); beide leer, solange der Posten nicht verortet ist.
    lat: Mapped[float | None] = mapped_column(Double)
    lng: Mapped[float | None] = mapped_column(Double)

    strecke: Mapped[Strecke] = relationship(back_populates="posten")
    items: Mapped[list[Item]] = relationship(
        back_populates="posten", order_by="Item.position", cascade="all, delete-orphan"
    )

    __mandant_eltern__ = {"strecke_id": ("strecke", Strecke)}

    @classmethod
    def mandant_kriterium(cls, schule_id: int) -> ColumnElement[bool]:
        return cls.strecke_id.in_(select(Strecke.id).where(Strecke.schule_id == schule_id))


class Item(Mandantenmodell, Basis):
    __tablename__ = "item"

    id: Mapped[int] = mapped_column(primary_key=True)
    posten_id: Mapped[int] = mapped_column(
        ForeignKey("posten.id", ondelete="CASCADE"), index=True
    )
    # Erscheint auf dem Posten-Button („Schulterblick").
    kurzbezeichnung: Mapped[str] = mapped_column(String(60))
    # Worauf die Eltern am Posten achten sollen.
    beobachtungstext: Mapped[str] = mapped_column(Text, default="", server_default="")
    # Satz für den Feedbackbogen – redaktionell gepflegt, nie generiert.
    uebungstext: Mapped[str] = mapped_column(Text, default="", server_default="")
    position: Mapped[int] = mapped_column(Integer)

    posten: Mapped[Posten] = relationship(back_populates="items")

    __mandant_eltern__ = {"posten_id": ("posten", Posten)}

    @classmethod
    def mandant_kriterium(cls, schule_id: int) -> ColumnElement[bool]:
        return cls.posten_id.in_(
            select(Posten.id)
            .join(Strecke, Posten.strecke_id == Strecke.id)
            .where(Strecke.schule_id == schule_id)
        )


# --------------------------------------------------------------------------- Abläufe


class Ablauf(Mandantenmodell, Basis):
    """Wiederkehrender Handlungsablauf als Vorlage, z. B. „Linksabbiegen".

    Wird in einen Posten *kopiert*: Die Items gehören danach dem Posten. So ändern
    spätere Anpassungen am Ablauf nie bestehende Posten oder deren Auswertung.
    """

    __tablename__ = "ablauf"

    id: Mapped[int] = mapped_column(primary_key=True)
    schule_id: Mapped[int] = mapped_column(
        ForeignKey("schule.id", ondelete="RESTRICT"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    beschreibung: Mapped[str] = mapped_column(Text, default="", server_default="")

    schritte: Mapped[list[AblaufSchritt]] = relationship(
        back_populates="ablauf", order_by="AblaufSchritt.position", cascade="all, delete-orphan"
    )

    __mandant_eltern__ = {"schule_id": ("schule", Schule)}

    @classmethod
    def mandant_kriterium(cls, schule_id: int) -> ColumnElement[bool]:
        return cls.schule_id == schule_id


class AblaufSchritt(Mandantenmodell, Basis):
    """Ein Handlungsschritt eines Ablaufs – dieselben drei Texte wie ein Item."""

    __tablename__ = "ablauf_schritt"

    id: Mapped[int] = mapped_column(primary_key=True)
    ablauf_id: Mapped[int] = mapped_column(
        ForeignKey("ablauf.id", ondelete="CASCADE"), index=True
    )
    kurzbezeichnung: Mapped[str] = mapped_column(String(60))
    beobachtungstext: Mapped[str] = mapped_column(Text, default="", server_default="")
    uebungstext: Mapped[str] = mapped_column(Text, default="", server_default="")
    position: Mapped[int] = mapped_column(Integer)

    ablauf: Mapped[Ablauf] = relationship(back_populates="schritte")

    __mandant_eltern__ = {"ablauf_id": ("ablauf", Ablauf)}

    @classmethod
    def mandant_kriterium(cls, schule_id: int) -> ColumnElement[bool]:
        return cls.ablauf_id.in_(select(Ablauf.id).where(Ablauf.schule_id == schule_id))


# --------------------------------------------------------------------------- Gruppe


class Gruppe(Mandantenmodell, Basis):
    __tablename__ = "gruppe"

    id: Mapped[int] = mapped_column(primary_key=True)
    schule_id: Mapped[int] = mapped_column(
        ForeignKey("schule.id", ondelete="RESTRICT"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    schuljahr: Mapped[str] = mapped_column(String(20))
    archiviert: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )

    kinder: Mapped[list[Kind]] = relationship(
        back_populates="gruppe", order_by="Kind.startnummer", cascade="all, delete-orphan"
    )

    __mandant_eltern__ = {"schule_id": ("schule", Schule)}

    @classmethod
    def mandant_kriterium(cls, schule_id: int) -> ColumnElement[bool]:
        return cls.schule_id == schule_id


class Kind(Mandantenmodell, Basis):
    """Ein Kind ist für die Anwendung nur eine Startnummer in einer Gruppe.

    Namen speichert die Anwendung bewusst nicht: Die Klassenleitung führt eine
    ausgedruckte Liste (Startnummer → Name) und sorgt dafür, dass jedes Kind immer
    dieselbe Nummer trägt. Abweichung von Spezifikation 3 auf Wunsch der Schule.
    """

    __tablename__ = "kind"
    __table_args__ = (
        UniqueConstraint("gruppe_id", "startnummer", name="uq_kind_gruppe_startnummer"),
        CheckConstraint("startnummer > 0", name="startnummer_positiv"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    gruppe_id: Mapped[int] = mapped_column(
        ForeignKey("gruppe.id", ondelete="CASCADE"), index=True
    )
    # OFFEN: Kinder ohne eigenes Rad / mit Leihrad – Annahme: kein Sonderfall,
    # die Startnummer gilt dem Kind, nicht dem Rad.
    startnummer: Mapped[int] = mapped_column(Integer)
    aktiv: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))

    gruppe: Mapped[Gruppe] = relationship(back_populates="kinder")

    __mandant_eltern__ = {"gruppe_id": ("gruppe", Gruppe)}

    @classmethod
    def mandant_kriterium(cls, schule_id: int) -> ColumnElement[bool]:
        return cls.gruppe_id.in_(select(Gruppe.id).where(Gruppe.schule_id == schule_id))

    def __repr__(self) -> str:
        return f"<Kind id={self.id} gruppe_id={self.gruppe_id}>"


# --------------------------------------------------------------------------- Lauf


class Lauf(Mandantenmodell, Basis):
    # OFFEN: Zweiter Prüfungstermin für erkrankte Kinder – Annahme: ein neuer Lauf
    # mit einer verkleinerten Gruppe. Die Zusammenführung mehrerer Läufe für ein
    # Kind ist nicht vorgesehen.
    __tablename__ = "lauf"
    __table_args__ = (
        CheckConstraint(f"status IN ({_in_list(LAUF_STATUS)})", name="status"),
        # Mehrere Klassen fahren dieselbe Strecke am selben Tag nacheinander – an
        # einer fünfzügigen Schule sind das zwei Läufe täglich. Verhindert wird nur
        # noch derselbe Lauf doppelt: eine Klasse, eine Strecke, ein Tag.
        # Die Eindeutigkeit der Startnummern bleibt dabei gewahrt, weil ein Token
        # genau einen Lauf adressiert und das Gerät am Posten immer nur in einem
        # Lauf erfasst (app/posten/api.py, „weitere_laeufe").
        Index(
            "uq_lauf_strecke_gruppe_datum_aktiv",
            "strecke_id",
            "gruppe_id",
            "datum",
            unique=True,
            postgresql_where=text("status IN ('vorbereitet', 'laufend')"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    schule_id: Mapped[int] = mapped_column(
        ForeignKey("schule.id", ondelete="RESTRICT"), index=True
    )
    # RESTRICT: Strecken und Gruppen lassen sich nicht löschen, solange Läufe daran hängen.
    strecke_id: Mapped[int] = mapped_column(
        ForeignKey("strecke.id", ondelete="RESTRICT"), index=True
    )
    gruppe_id: Mapped[int] = mapped_column(
        ForeignKey("gruppe.id", ondelete="RESTRICT"), index=True
    )
    datum: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(
        String(20), default="vorbereitet", server_default="vorbereitet"
    )
    erstellt_am: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # Gesetzt, wenn die Erfassungen nach Ablauf der Aufbewahrungsfrist gelöscht wurden
    # (python -m app.kommandos aufbewahrung).
    daten_geloescht_am: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    strecke: Mapped[Strecke] = relationship()
    gruppe: Mapped[Gruppe] = relationship()
    tokens: Mapped[list[PostenToken]] = relationship(
        back_populates="lauf", cascade="all, delete-orphan"
    )

    __mandant_eltern__ = {
        "schule_id": ("schule", Schule),
        "strecke_id": ("strecke", Strecke),
        "gruppe_id": ("gruppe", Gruppe),
    }

    @classmethod
    def mandant_kriterium(cls, schule_id: int) -> ColumnElement[bool]:
        return cls.schule_id == schule_id


def _lauf_der_schule(schule_id: int):
    return select(Lauf.id).where(Lauf.schule_id == schule_id)


class PostenToken(Mandantenmodell, Basis):
    __tablename__ = "posten_token"
    __table_args__ = (
        UniqueConstraint("lauf_id", "posten_id", name="uq_posten_token_lauf_posten"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    lauf_id: Mapped[int] = mapped_column(ForeignKey("lauf.id", ondelete="CASCADE"))
    posten_id: Mapped[int] = mapped_column(
        ForeignKey("posten.id", ondelete="RESTRICT"), index=True
    )
    token: Mapped[str] = mapped_column(String(64), unique=True)
    gueltig_bis: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    letzter_abruf: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    letzter_upload: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    lauf: Mapped[Lauf] = relationship(back_populates="tokens")
    posten: Mapped[Posten] = relationship()

    __mandant_eltern__ = {"lauf_id": ("lauf", Lauf), "posten_id": ("posten", Posten)}

    @classmethod
    def mandant_kriterium(cls, schule_id: int) -> ColumnElement[bool]:
        return cls.lauf_id.in_(_lauf_der_schule(schule_id))

    def __repr__(self) -> str:
        # Tokens dürfen nicht in Logs landen (Spezifikation 9).
        return f"<PostenToken id={self.id} lauf_id={self.lauf_id} posten_id={self.posten_id}>"


class Ereignis(Mandantenmodell, Basis):
    """Unveränderliches, append-only erfasstes Ereignis eines Postens.

    Ein Datenbank-Trigger verhindert UPDATE (siehe Migration). Korrekturen sind
    neue Ereignisse mit jüngerem ``erfasst_am``.
    """

    __tablename__ = "ereignis"
    __table_args__ = (
        CheckConstraint(f"typ IN ({_in_list(EREIGNIS_TYPEN)})", name="typ"),
        CheckConstraint("startnummer > 0", name="startnummer_positiv"),
        Index("ix_ereignis_auswertung", "lauf_id", "posten_id", "startnummer", "typ"),
    )

    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    lauf_id: Mapped[int] = mapped_column(ForeignKey("lauf.id", ondelete="CASCADE"))
    posten_id: Mapped[int] = mapped_column(ForeignKey("posten.id", ondelete="RESTRICT"))
    startnummer: Mapped[int] = mapped_column(Integer)
    typ: Mapped[str] = mapped_column(String(20))
    nutzlast: Mapped[dict[str, Any]] = mapped_column(JSONB)
    # Zeitpunkt auf dem Gerät – maßgeblich für „jüngstes Ereignis gewinnt".
    erfasst_am: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    empfangen_am: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    __mandant_eltern__ = {"lauf_id": ("lauf", Lauf), "posten_id": ("posten", Posten)}

    @classmethod
    def mandant_kriterium(cls, schule_id: int) -> ColumnElement[bool]:
        return cls.lauf_id.in_(_lauf_der_schule(schule_id))


# --------------------------------------------------------------------------- Infrastruktur


class AdminSitzung(Basis):
    """Serverseitige Sitzung des Verwaltungsbereichs.

    Kein Mandantenmodell: wird ausschließlich im Bereich INTERN gelesen und
    geschrieben (``app.web.sitzung``). Im Mandanten- und Systemadmin-Bereich ist
    jeder Zugriff gesperrt.

    Gespeichert wird nur der SHA-256-Hash des Cookie-Werts – ein Datenbankabzug
    erlaubt also keine Übernahme laufender Sitzungen.
    """

    __tablename__ = "admin_sitzung"

    id_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    benutzer_id: Mapped[int] = mapped_column(
        ForeignKey("benutzer.id", ondelete="CASCADE"), index=True
    )
    csrf_token: Mapped[str] = mapped_column(String(64))
    erstellt_am: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    zuletzt_aktiv: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Einmal-Meldungen für die nächste Seite („Gespeichert.")
    meldungen: Mapped[list[Any]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )

    benutzer: Mapped[Benutzer] = relationship()

    def __repr__(self) -> str:
        return f"<AdminSitzung benutzer_id={self.benutzer_id}>"


class BetriebsLimit(Basis):
    __tablename__ = "betriebs_limit"
    schluessel: Mapped[str] = mapped_column(String(64), primary_key=True)
    anzahl: Mapped[int] = mapped_column(Integer)
    bis: Mapped[datetime] = mapped_column(DateTime(timezone=True))

INFRASTRUKTURMODELLE: tuple[type, ...] = (AdminSitzung, BetriebsLimit)


MANDANTENMODELLE: tuple[type[Mandantenmodell], ...] = (
    Schule,
    Benutzer,
    Strecke,
    Posten,
    Item,
    Ablauf,
    AblaufSchritt,
    Gruppe,
    Kind,
    Lauf,
    PostenToken,
    Ereignis,
)

# Was der Systemadmin sehen darf. Alles andere ist für ihn technisch gesperrt.
SYSTEMADMIN_MODELLE: frozenset[type] = frozenset({Schule, Benutzer})
