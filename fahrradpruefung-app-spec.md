# Auftrag: Webapp „Fahrradprüfung" (mandantenfähig, offline-fähig)

Du baust eine Webanwendung zur Begleitung der Radfahrausbildung an Grundschulen.
Diese Datei ist die verbindliche Spezifikation. Wenn etwas unklar ist, frage nach,
statt zu raten. Abweichungen von den unter „Harte Anforderungen" genannten Punkten
sind nicht zulässig.

---

## 1. Fachlicher Kontext

Bei der Radfahrprüfung in Klasse 4 fahren Kinder eine festgelegte Strecke im
öffentlichen Straßenraum ab. An neuralgischen Punkten (Einmündungen, Abbiegestellen)
stehen Eltern als Streckenposten und beobachten, ob die Kinder die dort erforderlichen
Handlungsschritte ausführen – z. B. Schulterblick, Handzeichen, richtiges Einordnen.

Ablauf eines Prüfungstages:

- Eine Gruppe von 15–30 Kindern fährt die Strecke **90 Minuten lang wiederholt** ab,
  immer in derselben Reihenfolge.
- Jedes Kind kommt dadurch mehrfach an jedem Posten vorbei (typisch 4–8 Durchgänge).
- Jeder Posten beobachtet **seine eigenen** Handlungsschritte – die Itemlisten
  unterscheiden sich pro Posten.
- Zusätzlich gibt jeder Posten pro Kind **eine** Gesamteinschätzung zur Fahrsicherheit.
- Die Kinder tragen Startnummern-Leibchen. **Die Erfassung erfolgt ausschließlich über
  die Startnummer, niemals über Namen.**
- Am Ende werden die Daten aller Posten zusammengeführt. Pro Kind entsteht ein
  Feedbackbogen zum Ausdrucken, mit dem Kind und Eltern weiter üben können.

Die Posten-Geräte (iPads) sind während der gesamten 90 Minuten **ohne Netzverbindung**.

### Die kritische Randbedingung

Bei 25 Kindern und 90 Minuten erreicht ein Posten alle 20–30 Sekunden ein Kind.
Die Eltern bedienen das Gerät zum ersten Mal, im Stehen, bei Wind, und müssen
gleichzeitig auf den Verkehr achten.

**Eine Erfassung muss in unter 10 Sekunden und mit maximal zwei Taps erledigt sein.**
Jede Designentscheidung im Posten-Frontend ist diesem Ziel unterzuordnen. Im Zweifel
gilt: weniger Funktionen, größere Flächen.

---

## 2. Technischer Rahmen

Betrieb auf einem Ubuntu-Server hinter nginx, Deployment per Docker Compose.

| Bereich | Vorgabe |
|---|---|
| Backend | Python 3.12, FastAPI, SQLAlchemy 2.x, Alembic für Migrationen |
| Datenbank | PostgreSQL 16 |
| Admin-Oberfläche | Serverseitig gerendert (Jinja2), kein SPA-Framework |
| Posten-Frontend | Vanilla JS (ES-Module), **kein Build-Schritt**, IndexedDB über `idb` |
| PDF | WeasyPrint (HTML → PDF) |
| QR-Codes | `segno` |
| Tests | pytest, Playwright für die Offline-Strecke |

Begründung für „kein Build-Schritt": Die Anwendung muss in fünf Jahren noch von einer
Person wartbar sein, die nicht täglich mit JS-Toolchains arbeitet. Keine npm-Abhängigkeiten
im Frontend außer `idb`, das als einzelne Datei mitgeliefert wird.

Liefere ein lauffähiges `docker-compose.yml` (App, PostgreSQL, benannte Volumes) und
eine `.env.example` mit allen benötigten Variablen.

---

## 3. Datenmodell

```
Schule (id, name, kurzname, aktiv, erstellt_am)
 │
 ├── Benutzer (id, schule_id, email, passwort_hash, rolle, aktiv)
 │       rolle ∈ {schuladmin, systemadmin}
 │       systemadmin hat schule_id = NULL
 │
 ├── Strecke (id, schule_id, name, beschreibung, archiviert)
 │     └── Posten (id, strecke_id, name, position, beschreibung)
 │           └── Item (id, posten_id, kurzbezeichnung, beobachtungstext,
 │                     uebungstext, position)
 │
 ├── Gruppe (id, schule_id, name, schuljahr, archiviert)
 │     └── Kind (id, gruppe_id, startnummer, vorname, nachname, aktiv)
 │           UNIQUE(gruppe_id, startnummer)
 │
 └── Lauf (id, schule_id, strecke_id, gruppe_id, datum, status, erstellt_am)
       │     status ∈ {vorbereitet, laufend, abgeschlossen, archiviert}
       │
       ├── PostenToken (id, lauf_id, posten_id, token, gueltig_bis,
       │                letzter_abruf, letzter_upload)
       │                UNIQUE(lauf_id, posten_id), UNIQUE(token)
       │
       └── Ereignis (event_id PK, lauf_id, posten_id, startnummer, typ,
                     nutzlast JSONB, erfasst_am, empfangen_am)
             typ ∈ {durchgang, sicherheit}
```

### Begründungen, die du nicht wegoptimieren sollst

**Gruppen hängen an der Schule, nicht an der Strecke.** Eine Gruppe ist eine Menge
Kinder; sie kann verschiedene Strecken abfahren. Der `Lauf` stellt die Verbindung
Gruppe ↔ Strecke ↔ Datum her und ist die Einheit, an der alle Erfassungen hängen.

**Items tragen drei Texte.** `kurzbezeichnung` erscheint auf dem Posten-Button
(„Schulterblick"), `beobachtungstext` beschreibt für die Eltern, worauf zu achten ist,
`uebungstext` ist der Satz, der im Feedbackbogen für Kind und Eltern erscheint
(„Übe den Schulterblick, bevor du abbiegst."). Diese Texte werden von der Schule
**redaktionell gepflegt** und nicht aus den Daten generiert.

**Ereignisse sind unveränderlich und append-only.** Korrekturen erzeugen ein neues
Ereignis mit neuerem `erfasst_am`. Nichts wird überschrieben, nichts gelöscht.
Die Auswertung berücksichtigt pro Schlüssel jeweils das jüngste Ereignis.

`nutzlast` für `typ = durchgang`:
```json
{ "durchgang_nr": 4, "fehlende_items": ["schulterblick", "handzeichen"] }
```

`nutzlast` für `typ = sicherheit`:
```json
{ "stufe": 2, "bemerkung": "fährt sehr dicht am Bordstein" }
```
`stufe`: 1 = sicher, 2 = teilweise sicher, 3 = unsicher.

---

## 4. Harte Anforderungen

Diese Punkte sind nicht verhandelbar. Verletzt die Implementierung einen davon, gilt
sie als nicht abgenommen.

### 4.1 Mandantentrennung

Jede Abfrage auf schulbezogene Daten **muss** auf `schule_id` eingeschränkt sein.
Das darf nicht als Konvention umgesetzt werden, die jede Query einzeln mitbringt.

Implementiere eine Session-/Repository-Schicht, die die `schule_id` des angemeldeten
Benutzers hält und automatisch in jede Query einsetzt. Direkte `session.query(Modell)`-Aufrufe
in Route-Handlern sind nicht zulässig; der Zugriff läuft ausschließlich über diese Schicht.

Schreibe Tests, die für **jeden** Admin-Endpunkt nachweisen, dass ein Benutzer der
Schule A keine Daten der Schule B lesen, ändern oder löschen kann – auch nicht durch
direkte Angabe einer fremden ID in der URL. Erwartetes Verhalten: HTTP 404, nicht 403
(kein Rückschluss auf Existenz).

### 4.2 Keine Namen außerhalb des Verwaltungsbereichs

Namen von Kindern dürfen auftauchen in: Verwaltungsoberfläche, Feedback-PDF, Datenbank.
Sie dürfen **nicht** auftauchen in: Posten-Frontend, Konfigurations-Endpunkt, Ereignis-API,
IndexedDB auf dem Gerät, Logfiles.

Der Konfigurations-Endpunkt liefert ausschließlich Startnummern. Schreibe einen Test,
der die Antwort des Endpunkts gegen die Namensliste der Gruppe prüft.

### 4.3 Offline-Fähigkeit

Nach dem einmaligen Laden im WLAN muss das Posten-Frontend **ohne jede Netzwerkanfrage**
vollständig funktionieren – über die gesamten 90 Minuten und auch nach zwischenzeitlichem
Neustart des Browsers oder des Geräts.

- Service Worker cached die komplette App-Shell (Cache-First für Assets).
- Manifest mit `"display": "standalone"` — **zwingend**. Bei `minimal-ui` greift Safaris
  7-Tage-Löschung für Script-Storage; bei `standalone` ist die zum Home-Bildschirm
  hinzugefügte App davon ausgenommen.
- Beim ersten Start `navigator.storage.persist()` anfordern.
- Alle Erfassungen gehen in IndexedDB, bevor irgendeine UI-Rückmeldung erfolgt.

### 4.4 Idempotenter Upload

`event_id` wird **auf dem Gerät** als UUIDv4 erzeugt. Der Server schreibt per
`INSERT ... ON CONFLICT (event_id) DO NOTHING` und antwortet mit der Liste der
verarbeiteten IDs. Erst nach Erhalt dieser Bestätigung markiert das Gerät die
betroffenen Ereignisse lokal als übertragen.

Ein mehrfach gesendetes Ereignis darf unter keinen Umständen zu Doppelungen führen.

---

## 5. Verwaltungsbereich (Schuladmin)

Anmeldung per E-Mail und Passwort (argon2id), serverseitige Sessions, HttpOnly-Cookies,
CSRF-Schutz auf allen schreibenden Routen.

Funktionen:

1. **Strecken verwalten** – anlegen, Posten mit Reihenfolge hinzufügen, pro Posten die
   Itemliste pflegen (Kurzbezeichnung, Beobachtungstext, Übungstext). Strecken lassen
   sich duplizieren und archivieren, nicht löschen, solange Läufe daran hängen.
2. **Gruppen verwalten** – anlegen, Kinder einzeln erfassen oder per CSV importieren
   (`startnummer;vorname;nachname`). Startnummern innerhalb einer Gruppe eindeutig,
   Verstöße beim Import mit Zeilennummer melden.
3. **Lauf anlegen** – Gruppe + Strecke + Datum wählen. Erzeugt automatisch für jeden
   Posten ein Token.
4. **Posten-Blätter drucken** – eine PDF-Seite pro Posten mit: Postenname, QR-Code zur
   Token-URL, der Itemliste im Klartext, dem Datum und einem Hinweisfeld für die Eltern.
   Dieses Blatt geht mit dem iPad an den Posten.
5. **Laufübersicht während/nach der Durchführung** – pro Posten: letzter Abruf der
   Konfiguration, letzter Upload, Anzahl empfangener Ereignisse, Anzahl der
   Startnummern, von denen Daten vorliegen. Fehlende Startnummern werden **deutlich
   hervorgehoben** – sie bedeuten entweder ein fehlendes Kind oder ein vertauschtes
   Leibchen, und das muss am selben Tag auffallen.
6. **Feedbackbögen erzeugen** – einzeln oder als Sammel-PDF für die ganze Gruppe.
7. **Lauf abschließen** – setzt Status auf `abgeschlossen`, entwertet alle Tokens.

Der Systemadmin hat eine eigene, getrennte Oberfläche: Schulen anlegen, Schuladmins
anlegen, Schulen deaktivieren. **Er hat keinen Zugriff auf Kinder, Gruppen oder
Erfassungsdaten.** Setze das technisch durch, nicht nur in der Navigation.

---

## 6. Posten-Frontend (PWA)

Aufruf unter `/p/{token}`. Kein Login, keine Eingabe. Das Token identifiziert Lauf und
Posten.

### Einrichtung (im WLAN, am Vortag)

Beim Aufruf lädt die App ihre Konfiguration und schreibt sie in IndexedDB:
Postenname, Itemliste, Startnummern des Laufs, Lauf-ID, Datum.

Danach zeigt sie einen unmissverständlichen Status:

> **Posten 3 – Einmündung Lindenweg**
> 24 Startnummern geladen · offline einsatzbereit

Zusätzlich eine kurze, laienverständliche Anleitung auf dem Bildschirm: „Tippe auf
Teilen → Zum Home-Bildschirm. Dann ist die App auch ohne Internet nutzbar."
Erkenne per `display-mode: standalone`, ob die App bereits installiert ist, und blende
die Anleitung danach aus.

### Hauptansicht während der Prüfung

Aufbau von oben nach unten:

1. **Statusleiste** (dauerhaft sichtbar): Postenname, Zähler „38 Erfassungen · nicht
   übertragen", Offline-Indikator.
2. **Die aktuelle Startnummer, sehr groß** – mindestens 120px Schriftgröße, mittig.
   Daneben kleiner: „Durchgang 4".
3. **Die Items als große Schaltflächen.** Mindestens 64px hoch, volle Breite,
   deutlicher Abstand. Standardzustand: nicht angetippt = Handlungsschritt erfüllt.
   Angetippt = **vergessen**, deutlich rot markiert.
4. **Ein großer Abschluss-Button** („Weiter"), der die Erfassung speichert und zur
   nächsten Startnummer springt.
5. Darunter klein: „andere Nummer" und „überspringen".

Das Erfassungsprinzip ist bewusst invertiert: Im Normalfall – alles richtig gemacht –
genügt **ein einziger Tap** auf „Weiter".

### Weitere Anforderungen an die Hauptansicht

- Nach „Weiter" rückt die Startnummer automatisch zur nächsten in der Reihenfolge; nach
  der letzten beginnt sie wieder bei der ersten und erhöht den Durchgangszähler.
- „andere Nummer" öffnet ein **Raster** aller Startnummern (nicht eine Liste zum
  Scrollen), aus dem direkt gesprungen werden kann. Kinder überholen sich, Ketten
  springen ab, jemand macht Pause – das ist der Normalfall, nicht die Ausnahme.
- Nach dem Speichern eine kurze, eindeutige Rückmeldung (kurzes Aufleuchten,
  optional Vibration). Die Eltern müssen sehen, dass es gezählt hat, ohne hinzusehen.
- **Undo:** Die letzte Erfassung muss innerhalb von etwa 10 Sekunden korrigierbar sein.
  Umgesetzt als neues Ereignis, nicht als Löschung.
- Ein zweiter Reiter „Fahrsicherheit": Raster aller Startnummern, pro Nummer drei große
  Schaltflächen (sicher / teilweise sicher / unsicher) plus optionales Textfeld.
  Jederzeit überschreibbar. Bereits bewertete Nummern sind im Raster erkennbar.
- Kein Pull-to-Refresh, kein versehentliches Neuladen, keine Links nach außen.
  Ein Bildschirm, aus dem man nicht herausfällt.

### Rücklauf

Erkennt die App wieder eine Verbindung, lädt sie automatisch hoch und zeigt
„0 · alles übertragen". Zusätzlich ein manueller Button „Jetzt übertragen".

Nach bestätigtem Upload und abgeschlossenem Lauf löscht die App ihre lokalen Daten.
**Nicht vorher** – solange der Lauf läuft, sind die lokalen Daten die einzige Kopie.

---

## 7. API

Nur drei Endpunkte, alle ohne Login, ausschließlich über das Token autorisiert:

```
GET  /api/p/{token}/config
     → { lauf_id, datum, posten: {id, name},
         items: [{id, kurzbezeichnung, position}],
         startnummern: [1,2,3,...] }
     404 bei unbekanntem, abgelaufenem oder entwertetem Token.
     Enthält keine Namen.

POST /api/p/{token}/events
     Body: { events: [ {event_id, typ, startnummer, nutzlast, erfasst_am}, ... ] }
     → { akzeptiert: [event_id, ...] }
     Idempotent. Validiert, dass startnummer zum Lauf und die Items zum Posten gehören.
     Fremde Startnummern werden abgewiesen und einzeln im Ergebnis gemeldet,
     ohne den restlichen Batch scheitern zu lassen.

GET  /api/p/{token}/status
     → { offen: n, zuletzt_empfangen: timestamp }
```

Rate-Limiting pro Token. Maximal 1000 Ereignisse pro Request.

---

## 8. Auswertung und Feedbackbogen

### Aggregation

Pro Kind und Item über alle Durchgänge des zugehörigen Postens:
`vergessen_anzahl / durchgaenge_gesamt`. Maßgeblich ist je Schlüssel
(startnummer, posten, durchgang_nr) das jüngste Ereignis.

Fahrsicherheit: die Einschätzungen aller Posten nebeneinander, plus Bemerkungen.
Weichen sie stark voneinander ab, markiere das in der Verwaltungsansicht – das ist
für das Gespräch mit dem Kind die interessanteste Information.

### Feedbackbogen (eine A4-Seite pro Kind)

Adressaten sind ein Kind der Klasse 4 und seine Eltern. Nicht die Schulleitung.

Aufbau:

- Kopf: Name des Kindes, Datum, Schule. (Erst hier erfolgt die Auflösung der
  Startnummer.)
- Ein kurzer, freundlicher Einleitungssatz.
- **„Das klappt schon gut"** – die Items mit einer Fehlerquote unter 25 %, als
  Aufzählung im Klartext.
- **„Daran üben wir noch"** – maximal drei Items mit der höchsten Fehlerquote, jeweils
  mit dem hinterlegten `uebungstext`. Maximal drei, auch wenn mehr auffällig waren:
  Eine Liste mit acht Punkten übt niemand.
- Die Fahrsicherheits-Einschätzung in einem Satz, nicht als Zahl.
- Ein Platz für eine handschriftliche Ergänzung der Lehrkraft.

Keine Prozentzahlen, keine Punktwertungen, keine Noten im Bogen. Intern wird gerechnet,
nach außen wird formuliert.

Das Layout kommt aus einer Jinja2-Vorlage, die eine Schule anpassen können soll
(Logo, Fußzeile). Lege sie als austauschbare Datei an.

---

## 9. Datenschutz und Sicherheit

- Alle Tokens kryptografisch zufällig, mindestens 128 Bit, URL-sicher kodiert.
- Tokens laufen automatisch 24 Stunden nach dem Laufdatum ab.
- Passwörter mit argon2id.
- **Kein Logging von Startnummern, Namen oder Tokens.** Logge Lauf-ID und Posten-ID.
- Konfigurierbare automatische Löschung der Ereignisdaten nach einer einstellbaren
  Frist (Standard: 12 Monate). Umgesetzt als Management-Kommando, nicht als
  versteckter Hintergrundprozess.
- Pro Schule eine Export-Funktion über alle eigenen Daten (JSON), für Auskunftsersuchen.
- Security-Header: CSP ohne `unsafe-inline`, HSTS, `X-Content-Type-Options`.

---

## 10. Nicht-Ziele

Baue das ausdrücklich **nicht** mit ein:

- Keine native App, keine App-Store-Verteilung.
- Keine Live-Übertragung während des Laufs. Die Geräte sind offline, das ist Absicht.
- Keine Kartendarstellung, kein GPS-Tracking der Kinder.
- Keine Fotos, keine Videos.
- Keine Benotung, keine automatische Bestanden-/Nicht-bestanden-Entscheidung.
  Die Prüfungsentscheidung trifft die Lehrkraft, nicht die Software.
- Keine E-Mail-Versendung an Eltern. Die Bögen werden gedruckt.
- Keine Elternkonten.

---

## 11. Abnahmekriterien

Die Anwendung gilt als fertig, wenn alle folgenden Punkte nachweislich erfüllt sind:

1. **Flugmodus-Test:** iPad im WLAN einrichten, Flugmodus aktivieren, 50 Erfassungen
   über 90 Minuten vornehmen, zwischendurch die App komplett schließen und neu öffnen.
   Alle Erfassungen sind nach Wiederverbindung vollständig auf dem Server.
2. **Doppel-Upload-Test:** Derselbe Batch wird dreimal gesendet. In der Datenbank
   stehen die Ereignisse genau einmal.
3. **Abbruch-Test:** Upload wird mitten im Transfer unterbrochen. Nach erneutem
   Versuch sind alle Daten vollständig und nicht doppelt vorhanden.
4. **Mandantentest:** Für jeden Admin-Endpunkt existiert ein automatisierter Test,
   der den Zugriff über Schulgrenzen hinweg nachweislich verhindert.
5. **Anonymitätstest:** Automatisierter Test, dass weder Konfigurations-Endpunkt noch
   Ereignis-API noch IndexedDB einen Kindernamen enthalten.
6. **Bedienzeit:** Eine Standard-Erfassung ohne Auffälligkeit ist mit einem Tap
   abgeschlossen. Eine Erfassung mit zwei vergessenen Items mit drei Taps.
7. **Lesbarkeitstest:** Die Hauptansicht ist auf einem iPad bei direkter Sonne und
   aus 50 cm Entfernung lesbar. Keine Schrift unter 16px, Kontrastverhältnis
   mindestens 7:1.
8. **Feedbackbogen:** Ein erzeugter Bogen ist einem Zehnjährigen vorlesbar und
   enthält höchstens drei Übungspunkte.

---

## 12. Reihenfolge der Umsetzung

Liefere in dieser Reihenfolge, jeweils lauffähig, und hole nach jedem Schritt
Rückmeldung ein:

1. **Datenmodell, Migrationen, Mandanten-Schicht und die zugehörigen Tests.**
   Das Fundament, auf dem alles andere steht.
2. **Posten-Frontend als Prototyp** mit fest verdrahteten Beispieldaten, ohne Backend.
   Dieser Schritt dient dazu, die Bedienung mit echten Eltern zu testen, bevor
   Aufwand in die Serverseite fließt.
3. Verwaltungsbereich: Strecken, Posten, Items, Gruppen, Kinder, CSV-Import.
4. Läufe, Tokens, Posten-Blätter als PDF.
5. Anbindung des Posten-Frontends: Konfiguration, IndexedDB, Service Worker, Upload.
6. Laufübersicht und Auswertung.
7. Feedbackbogen als PDF.
8. Docker Compose, Deployment-Dokumentation, README.

---

## 13. Offene Punkte

Diese Fragen sind noch nicht entschieden. Setze die genannte Annahme um und markiere
die Stelle im Code mit `# OFFEN:`, damit sie später leicht zu finden ist.

- **Mehrere Gruppen gleichzeitig auf einer Strecke.** Annahme: nein, ein Lauf
  gleichzeitig pro Strecke. Falls doch nötig, müssen Startnummern über Gruppen hinweg
  eindeutig sein.
- **Kinder ohne eigenes Rad / mit Leihrad.** Annahme: kein Sonderfall, die Startnummer
  gilt dem Kind.
- **Zweiter Prüfungstermin für erkrankte Kinder.** Annahme: ein neuer Lauf mit einer
  verkleinerten Gruppe. Die Zusammenführung mehrerer Läufe für ein Kind ist nicht
  vorgesehen.
