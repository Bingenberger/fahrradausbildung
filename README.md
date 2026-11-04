# Fahrradprüfung

Webanwendung zur Begleitung der Radfahrausbildung an Grundschulen.
Verbindliche Spezifikation: [`fahrradpruefung-app-spec.md`](fahrradpruefung-app-spec.md).

<!-- schulplattform:installation -->
## Installation

### Im Rahmen der Schulplattform

Empfohlen für den Schulserver: Die [Schulplattform](https://github.com/Bingenberger/schulplattform) installiert diese App zusammen mit den
anderen Schul-Apps auf einem leeren Ubuntu-24.04-Server, mit eigener Subdomain, TLS-Zertifikat, Mailversand,
Sicherung und Dashboard. Sie verwendet das signierte Release-Image `ghcr.io/bingenberger/fahrradausbildung`
und die unveränderte `docker-compose.yml` dieses Repositorys plus eine Override-Datei.

1. In der Plattformkonfiguration (`./install.sh configure` bzw. `/etc/schulplattform/platform.toml`)
   unter `[apps.fahrradausbildung]` `enabled = true` und den Hostnamen setzen, z. B. `rad.ihre-schule.de`,
   und beim DNS-Provider einen A-Eintrag auf den Server anlegen.
2. `./install.sh apply …` installiert die App. Migration, Proxy, Zertifikat und Sicherung übernimmt die Plattform.
3. `./install.sh app-setup fahrradausbildung` legt den persönlichen Systemadmin per E-Mail an (`python -m app.kommandos systemadmin-anlegen`, Passwort am Terminal).
4. Daten vom bisherigen Server übernehmen: `./install.sh import fahrradausbildung …` nach dem
   [Umzugs-Runbook](https://github.com/Bingenberger/schulplattform/blob/main/docs/betrieb/umzug.md).

### Standalone mit Docker Compose

Ohne Plattform, z. B. zum Ausprobieren oder für einen eigenen Server mit eigenem Proxy.
Benötigt Docker Engine mit Compose v2 (amd64). Die App lauscht danach nur auf `http://127.0.0.1:8000`.

```sh
python3 prepare_secrets.py
export FP_SECRETS_DIR="$PWD/.private"
export FP_OEFFENTLICHE_URL="https://fahrrad.example.org"
docker compose build
docker compose up -d --wait db
docker compose run --rm --no-deps app python -m app.migrate
docker compose up -d --no-build
docker compose exec app python -m app.kommandos systemadmin-anlegen PERSOENLICHE_EMAIL
```

Hinter einem eigenen Proxy `FP_PROXY_IPS` exakt setzen (siehe [PLATFORM.md](PLATFORM.md)).

Statt selbst zu bauen, kann das veröffentlichte Image verwendet werden (dann `docker compose build` weglassen):

```sh
docker pull ghcr.io/bingenberger/fahrradausbildung:0.1.0 && docker tag ghcr.io/bingenberger/fahrradausbildung:0.1.0 fahrradausbildung:0.1.0-dev
```
<!-- /schulplattform:installation -->

## Stand

- [x] Schritt 1 – Datenmodell, Migrationen, Mandanten-Schicht, Tests
- [x] Schritt 2 – Posten-Frontend als Prototyp
- [x] Schritt 3 – Verwaltungsbereich: Strecken, Gruppen (seit der Umstellung: nur Startnummern)
- [x] Schritt 4 – Läufe, Tokens, Posten-Blätter
- [x] Schritt 5 – Anbindung Posten-Frontend, Offline, Upload
- [x] Schritt 6 – Laufübersicht und Auswertung
- [x] Schritt 7 – Feedbackbogen
- [x] Schritt 8 – Docker Compose, Deployment

## Keine Kindernamen – nur Startnummern

**Abweichung von der Spezifikation (Abschnitt 3, 5.2, 8) auf Wunsch der Schule:**
Die Anwendung speichert keine Namen von Kindern – nirgends, auch nicht im
Verwaltungsbereich. Ein Kind ist eine Startnummer in einer Gruppe.

- Beim Anlegen einer Gruppe gibt man die Anzahl der Kinder an (Startnummern 1 bis n);
  weitere Nummern lassen sich als Bereich „von–bis" ergänzen.
- **Namensliste (PDF)** auf der Gruppenseite: alle aktiven Startnummern mit leeren
  Zeilen. Die Klassenleitung trägt die Namen von Hand ein, bewahrt die Liste auf und
  sorgt dafür, dass jedes Kind bei jedem Lauf dieselbe Nummer trägt.
- Laufübersicht, Auswertung, Feedbackbogen und Export zeigen nur Startnummern.
  Der Feedbackbogen trägt „Startnummer 7" und eine Zeile „Name:" zum Ausfüllen.
- Der CSV-Import mit Namen ist entfallen. Die Migration `0004` löscht vorhandene
  Namensspalten endgültig.
- Ein Test (`tests/test_modelle.py`) stellt sicher, dass keine Tabelle Namensspalten
  bekommt.

## Abläufe – wiederkehrende Handlungsschritte

Unter **Abläufe** (`/verwaltung/ablaeufe`) legt eine Schule häufige Handlungsabläufe
wie „Linksabbiegen“ oder „Rechtsabbiegen“ einmal an – mit denselben drei Texten je
Schritt wie bei Items (Kurzbezeichnung, Beobachtungstext, Übungstext).

- **Einfügen:** Auf der Postenseite „Ablauf einfügen“ wählen. Die Schritte werden als
  Items ans Ende **kopiert**; Schritte mit einer Kurzbezeichnung, die der Posten schon
  hat, werden übersprungen. Danach sind Posten und Ablauf unabhängig: Spätere
  Änderungen am Ablauf verändern keinen Posten, an dem vielleicht schon Erfassungen hängen.
  Wie alle Item-Änderungen geht das Einfügen nur, solange an der Strecke kein Lauf hängt.
- **Als Ablauf speichern:** Ein fertiger Posten lässt sich als neuer Ablauf übernehmen.
- **Beispielabläufe** (`app/beispielablaeufe.py`): Linksabbiegen, Rechtsabbiegen,
  Anfahren vom Fahrbahnrand, Rechts vor links, Vorbeifahren an einem Hindernis – als
  Vorschläge zum Übernehmen und Anpassen an die eigene Ausbildung.

## Streckenplanung auf der Karte

Auf der Streckenseite: **Auf der Karte planen** (`/verwaltung/strecken/{id}/karte`).
Grundlage ist der eigenständige Kartengenerator `fahrradpruefung-karten.html`.

- **Posten verorten:** Posten links wählen, auf die Karte klicken; danach springt die
  Auswahl zum nächsten Posten ohne Standort. Markierungen lassen sich verschieben.
- **Strecke zeichnen:** über Wegpunkte (die Linie folgt per Routing den Straßen,
  Fahrrad- und Fußprofile, zwei Anbieter mit Rückfallebene), frei von Hand oder per
  Import aus GPX, KML (Google My Maps) oder GeoJSON. Eine Linie je Strecke; Varianten
  entstehen über „Strecke duplizieren" und lassen sich zum Vergleich einblenden.
- **Bild exportieren:** SVG oder PNG des sichtbaren Ausschnitts, mit Postennummern,
  Legende und Maßstab – z. B. für einen Elternbrief.
- **Kartenstile und Zoom:** Die Obergrenze der Karte gilt für alle Stile gleich
  (`MAX_ZOOM` in `app/kartenquellen.py`); je Stil ist zusätzlich die höchste Stufe
  mit eigenen Kacheln hinterlegt (`maxNativeZoom`), darüber vergrößert Leaflet.
  Ob ein Dienst eine Stufe auch für den konkreten Ort gerendert hat, zeigt erst
  der Abruf – CyclOSM hat z. B. über Niederkassel ab Stufe 18 keine Bilder, über
  Nürnberg schon. Bleibt eine Stufe ganz leer, zieht sich die Kartenseite auf die
  Stufe darunter zurück und sagt es in der Statuszeile, statt grau zu bleiben.
  Der gewählte Stil wird im Browser gemerkt.
- **Posten-Blatt:** Hat ein Posten einen Standort, zeigt sein Blatt einen
  Kartenausschnitt mit Strecke und allen Posten; der eigene ist gelb hervorgehoben.
  Das Bild setzt der Server aus Kacheln zusammen (`app/kartenbild.py`,
  `FP_KARTEN_KACHELN`); ist der Kachelserver nicht erreichbar, fehlt nur die Karte.
- **Export (JSON)** auf der Streckenseite (`/verwaltung/strecken/{id}/export.json`):
  die Strecke mit allen Posten, deren Items und dem gezeichneten Verlauf in einer
  Datei – zum Sichern vor einem Umbau oder zum Weitergeben an eine andere Schule.
  Läufe, Zugänge und Erfassungen sind nicht enthalten, also nichts, was einem Kind
  zuzuordnen wäre. Dieselbe Form steckt im Schulexport (`app/verwaltung/export.py`,
  `streckendaten()`), damit beide nicht auseinanderlaufen.
- **Streckenplan (PDF)** auf der Streckenseite
  (`/verwaltung/strecken/{id}/streckenplan.pdf`): Seite 1 die Gesamtstrecke mit
  Übersichtskarte (die Zoomstufe ergibt sich aus der Ausdehnung der Strecke),
  Länge und Postenliste, danach je Posten eine Seite mit dem Standort in
  Zoomstufe 19 – nah genug, dass die Einmündung auf dem Papier erkennbar ist.
  Posten ohne Standort bekommen ihre Seite mit einem Hinweis statt der Karte.
- Standorte und Verlauf bleiben änderbar, auch wenn schon Läufe an der Strecke hängen.

**Externe Dienste und Sicherheit.** Nur die Kartenseite darf externe Server ansprechen,
und nur die in `app/kartenquellen.py` (Kacheln von OpenStreetMap-Servern, Routing von
routing.openstreetmap.de, Valhalla und OSRM, Ortssuche Nominatim). Daraus entsteht ihre
eigene Content-Security-Policy – weiterhin ohne `unsafe-inline`, Skripte nur vom eigenen
Server (Leaflet 1.9.4 liegt unter `app/static/vendor/leaflet/`). Alle anderen Seiten
behalten die strenge CSP. Dabei gehen IP-Adresse der Lehrkraft, Kartenausschnitt und
Wegpunkte an diese Dienste – keine Kinderdaten. Die Schule sollte die Dienste in ihrer
Datenschutzerklärung nennen.

**Abweichung von der Spezifikation:** Abschnitt 10 nennt „Keine Kartendarstellung"
als Nicht-Ziel. Auf Wunsch der Schule gibt es Karten zur Planung und auf dem
Posten-Blatt; Kinder werden weiterhin nicht verortet, und die Posten-App zeigt keine Karte.

## Betrieb

Eigenständiges Docker Compose mit PostgreSQL 16, privaten Credentialdateien
und expliziter Migration. Kein Standardkonto; persönliche lokale Administration.

Installation, Limits, Offline-/Domainwechsel und Sicherung:
[PLATFORM.md](PLATFORM.md), Proxyhinweise: [DEPLOYMENT.md](DEPLOYMENT.md).

## Projektaufbau

| Pfad | Inhalt |
|---|---|
| `app/modelle.py`, `app/mandant.py` | Datenmodell und Mandanten-Schicht (Repository, Lese-/Schreibfilter) |
| `app/verwaltung/` | Verwaltungsbereich der Schule (nur über `SchulRepo`) |
| `app/system/` | Oberfläche des Systemadmins (nur Schulen und Benutzer) |
| `app/posten/` | Token-API und Auslieferung der Posten-App |
| `app/posten_app/` | Posten-App: Vanilla-JS, IndexedDB (`idb`), Service Worker – kein Build-Schritt |
| `app/auswertung.py`, `app/feedback.py` | Rechenregeln für Auswertung und Feedbackbogen (ohne Datenbank testbar) |
| `app/vorlagen/` | Jinja2-Vorlagen; `_makros.html` enthält die Bausteine, `pdf/` Posten-Blatt, Streckenplan und Feedbackbogen |
| `app/static/`, `app/web/symbole.py` | Stylesheets und Phosphor-Symbole (lokal, als Inline-SVG) |
| `app/aufbewahrung.py`, `app/kommandos.py` | Löschfrist und Management-Kommandos |
| `migrations/` | Alembic-Migrationen |
| `tests/` | pytest; Playwright (Chromium, WebKit) für die Offline-Strecke |
| `Dockerfile`, `docker-compose.yml`, `docker/`, `deploy/` | Betrieb |

Offene fachliche Fragen der Spezifikation (Abschnitt 13) sind im Code mit `# OFFEN:`
markiert: `grep -rn "OFFEN:" app/`.

## Entwicklung

Voraussetzungen: Python 3.12, [uv](https://docs.astral.sh/uv/), Docker.

```bash
# PostgreSQL 16 für Entwicklung und Tests
docker run -d --name fahrrad_pg_dev -e POSTGRES_USER=fahrrad -e POSTGRES_PASSWORD=fahrrad \
  -e POSTGRES_DB=fahrrad -p 127.0.0.1:55432:5432 postgres:16-alpine

cp .env.example .env
uv sync
uv run alembic upgrade head
uv run playwright install chromium webkit   # für die Frontend-Tests
uv run pytest
```

## Verwaltungsbereich starten

```bash
uv run python -m app.kommandos systemadmin-anlegen admin@example.org   # fragt das Passwort ab
FP_COOKIE_SECURE=false uv run uvicorn app.main:app --reload            # lokal ohne HTTPS
```

Dann `http://localhost:8000/anmelden`. Der Systemadmin legt Schulen und deren
Schuladmins an (das Startpasswort wird einmal angezeigt); Schuladmins pflegen
Strecken, Posten, Items, Gruppen und Kinder.

Weitere Kommandos: `uv run python -m app.kommandos --help`.

## Oberfläche und Symbole

Ein einziges Stylesheet trägt den Verwaltungsbereich: `app/static/verwaltung.css`,
gegliedert in Token (Farben, Abstandsskala `--s1`…`--s7`, Radien) und Bausteine.
Kein Build-Schritt, keine Framework-Abhängigkeit.

Gestaltungsregeln, an denen sich neue Seiten ausrichten:

- **Seitenkopf** (`.seitenkopf`): Brotkrume, Titel, eine Zeile Beiwerk
  (`.seitenkopf-bei`) und rechts die Hauptaktionen – auf jeder Seite gleich.
- **Eine Hauptaktion je Abschnitt** (`.knopf-haupt`), alles Weitere ruhig daneben;
  gefährliche Aktionen nur mit Rückfrage (`mit_rueckfrage`, reines CSS).
- **Leerzustände** (`.leerzustand`) statt leerer Kästen: Symbol, ein erklärender
  Satz und der Knopf, der zum nächsten Schritt führt.
- **Mindestens 40 px Trefferfläche**, sichtbarer Fokusring, Sprungmarke zum
  Inhalt, `prefers-reduced-motion` und eigene Druckregeln.
- **PDFs öffnen in einem neuen Tab** (Makro `pdf_knopf`, `target="_blank"` mit
  unsichtbarem Hinweis für Screenreader): Die Blätter werden angesehen und
  gedruckt, die Verwaltungsseite dahinter bleibt stehen. JSON-Exporte dagegen
  werden heruntergeladen (`Content-Disposition: attachment`) und brauchen das
  nicht.

**Symbole** sind [Phosphor Icons](https://phosphoricons.com) 2.1.1 (MIT) und liegen
lokal unter `app/static/vendor/phosphor/regular/` – nur die tatsächlich benutzten
Dateien. `app/web/symbole.py` bettet sie beim Rendern als Inline-SVG ein
(`{{ symbol("trash") }}`, in den Makros `sym="trash"`): keine zusätzliche Anfrage,
keine Schriftdatei, die Symbole erben über `fill="currentColor"` die Textfarbe,
und die strenge CSP braucht keine Ausnahme. Ein unbekannter Name wirft einen
Fehler; `tests/test_gestaltung.py` prüft, dass jedes verwendete Symbol vorliegt
und keine ungenutzte Datei liegen bleibt.

Ein neues Symbol: Datei aus `assets/regular/` des Pakets `@phosphor-icons/core`
nach `app/static/vendor/phosphor/regular/` kopieren, Dateiname ohne `.svg` ist
der Name im Aufruf.

## Posten-App

Aufruf über den QR-Code des Posten-Blatts: `/p/{token}`. Zum Üben ohne Lauf
gibt es den **Übungsmodus** `/p/demo` (Beispieldaten, keine Übertragung;
`?zuruecksetzen` löscht die Übungsdaten).

**Wichtig:** Offline-Betrieb (Service Worker) funktioniert nur über **HTTPS**
(oder `localhost`). Ein Test auf dem iPad über `http://<rechner-ip>` lädt die
App, kann sie aber nicht offline speichern – die Einrichtungsseite zeigt das an.

Ablauf auf dem Gerät:

1. **Einrichten (im WLAN):** Konfiguration laden, in IndexedDB speichern,
   Service Worker installieren. Erst wenn alle Dateien und die Seite selbst im
   Cache liegen, steht dort „✓ offline einsatzbereit".
2. **Prüfung (offline):** Jede Erfassung geht zuerst in IndexedDB.
3. **Rücklauf:** Upload automatisch beim Start, beim Ereignis `online` und
   jede Minute, solange etwas offen ist; zusätzlich „Jetzt übertragen".
   Ein Ereignis gilt erst als übertragen, wenn der Server seine `event_id`
   bestätigt hat.
4. **Abschluss:** Ist alles übertragen und meldet der Server den Zugang als
   ungültig (Lauf abgeschlossen), löscht die App ihre lokalen Daten. Liegen
   noch offene Erfassungen vor, bleiben sie erhalten und die Statusleiste
   bittet, die Lehrkraft zu informieren (Lauf wieder öffnen).
5. **Gerätewechsel:** Wird ein iPad für einen anderen Posten geöffnet, lädt es
   offene Daten des alten Postens zuerst hoch. Gelingt das nicht, wird der
   Wechsel verweigert. Die alte Konfiguration wird erst ersetzt, wenn die neue
   geladen ist.

Der Service Worker (`app/posten_app/sw.js`) bekommt seine Version vom Server:
ein Hash über alle App-Dateien. Jede Änderung an der App ergibt automatisch
einen neuen Cache; offline gespeicherte Seiten werden dabei übernommen.

### Display anlassen (`app/posten_app/js/wachbleiben.js`)

Das iPad liegt zwischen zwei Kindern still auf dem Tisch. Mit der üblichen
automatischen Sperre müsste die Aufsicht vor jedem Kind erst entsperren – genau
dann, wenn sie auf den Verkehr schauen soll. Die App fordert deshalb beim
Wechsel in die Erfassungsansicht einen **Screen Wake Lock** an und erneuert ihn
bei `visibilitychange`, weil das System ihn beim Wegschalten von selbst
freigibt. Am Ende des Laufs wird er zurückgegeben.

Grenzen, die die Oberfläche benennt:

- Vor **iPadOS 16.4** gibt es die Schnittstelle nicht. Die Einrichtungsseite
  sagt dann, dass „Automatische Sperre" auf „Nie" gestellt werden muss.
- Im **Energiesparmodus** darf das Gerät die Anfrage ablehnen. Dann steht in der
  Statusleiste „Display sperrt sich“ – die Erfassung läuft normal weiter.
- Die **Helligkeit** lässt sich aus dem Browser nicht steuern; das automatische
  Abdunkeln vor der Sperre entfällt mit dem Lock mit.

Verlässlicher bleibt die Geräteeinstellung *Einstellungen → Anzeige & Helligkeit
→ Automatische Sperre → Nie*, am besten per MDM-Profil auf allen Prüfungs-iPads.
Der Wake Lock ist die Absicherung für Geräte, die nicht so eingerichtet wurden.
Der Geführte Zugriff hilft hier übrigens nicht – er verhindert nur das Verlassen
der App, nicht die Display-Sperre.

### Token-API (`app/posten/api.py`)

- `GET /api/p/{token}/config` – nur Startnummern aktiver Kinder, keine Namen.
- `POST /api/p/{token}/events` – idempotent (`ON CONFLICT DO NOTHING`), bis zu
  1000 Ereignisse; jedes wird einzeln geprüft (UUIDv4, Startnummer der Gruppe,
  Items des Postens, Nutzlast-Schema). Antwort:
  `{"akzeptiert": [...], "abgewiesen": [{"event_id", "grund"}]}`.
  Bestätigt wird jede event_id, die für diesen Lauf und Posten in der
  Datenbank steht – auch wenn sie schon bei einem früheren, abgebrochenen
  Versuch ankam. Der erste Upload setzt den Lauf auf „läuft".
- `GET /api/p/{token}/status` – `offen` = Anzahl aktiver Startnummern, von denen
  dieser Posten noch keine Erfassung hat; `zuletzt_empfangen`.
- Unbekannte, abgelaufene und entwertete Tokens ergeben einheitlich 404.
  Ratenbegrenzung: 120 Anfragen je Minute und Token.
- Im Zugriffsprotokoll werden Tokens geschwärzt (`/p/***`); eigene Logs
  enthalten nur Lauf- und Posten-ID.

## Schutzregeln im Verwaltungsbereich

- **Strecke mit Lauf:** Posten und Items lassen sich nicht mehr hinzufügen,
  löschen oder umsortieren (Erfassungen verweisen auf sie). Texte bleiben
  bearbeitbar. Für einen Umbau: Strecke duplizieren. Löschen ist nicht möglich,
  Archivieren schon.
- **Gruppe mit Lauf:** Startnummern sind fest; sie lassen sich nur
  deaktivieren, nicht löschen – sonst passte die Papierliste der Klassenleitung
  nicht mehr. Die Gruppe selbst lässt sich nur archivieren.
- **Anmeldung:** argon2id, serverseitige Sitzungen (in der Datenbank nur der
  Hash des Cookies), HttpOnly-Cookie, CSRF-Token je Sitzung, Abmeldung nach
  2 Stunden Leerlauf bzw. spätestens nach 12 Stunden, Sperre nach 10
  Fehlversuchen in 15 Minuten. Deaktivieren einer Schule oder eines Benutzers
  wirkt sofort.
- **Rollen:** Eine Seite der jeweils anderen Rolle antwortet mit 404, ebenso
  jede fremde ID.

## Läufe und Tokens

- Beim Anlegen eines Laufs entsteht je Posten ein Token (256 Bit, URL-sicher).
  Geprüft wird: Strecke und Gruppe nicht archiviert, jeder Posten hat Items,
  die Gruppe hat aktive Kinder, das Datum liegt nicht in der Vergangenheit,
  auf der Strecke gibt es an dem Tag keinen weiteren Lauf.
- **Ablauf:** 24 Stunden nach dem *Ende* des Laufdatums in Ortszeit
  (`FP_ZEITZONE`). Ein Lauf am 20.10. ist bis 22.10., 0:00 Uhr nutzbar.
- **Zugang erneuern** (neues Token für einen Posten) geht nur, solange der Lauf
  „vorbereitet" ist – ein schon eingerichtetes iPad könnte sonst nicht mehr
  übertragen.
- **Abschließen** entwertet alle Tokens. Die Seite warnt, wenn von einem Posten
  noch kein Upload vorliegt. Innerhalb der Token-Gültigkeit lässt sich ein
  abgeschlossener Lauf **wieder öffnen**, damit ein vergessenes iPad seine
  Daten noch übertragen kann.
- **Posten-Blätter** (`app/vorlagen/pdf/postenblatt.html` + `.css`, je Schule
  austauschbar): Postenname, QR-Code (Fehlerkorrektur M), Einrichtungs- und
  Bedienanleitung, Items mit Beobachtungstext, Datum, Hinweisfeld.
  Die QR-Adresse kommt aus `FP_OEFFENTLICHE_URL`.

## Laufübersicht und Auswertung

**Laufseite** (`/verwaltung/laeufe/{id}`): je Posten letzter Abruf, letzter Upload,
Anzahl empfangener Ereignisse und „Startnummern mit Daten" (x von n aktiven Kindern).
Fehlende Startnummern stehen in einem roten Kasten oben auf der Seite – getrennt nach
„an keinem Posten erfasst" (Kind fehlt?) und „fehlt an Posten …" (Leibchen vertauscht?).
Darunter eine Tabelle Kind × Posten mit der Zahl der Durchgänge.
Ein Posten ohne jeden Upload zählt dabei nicht als „fehlend" – sonst wäre vor dem
ersten Upload alles rot; er erscheint stattdessen als „noch keine".

**Auswertung** (`…/auswertung`, je Kind `…/kinder/{kind_id}`): pro Kind und Item
`vergessen / Durchgänge an diesem Posten`, die Fahrsicherheit aller Posten nebeneinander
mit Bemerkungen. Liegen „sicher" und „unsicher" für dasselbe Kind vor
(`STARKE_ABWEICHUNG = 2` in `app/auswertung.py`), wird die Zeile markiert.

Rechenregeln (`app/auswertung.py`, rein und ohne Datenbank getestet):

- Je Schlüssel (Startnummer, Posten, Durchgang) bzw. (Startnummer, Posten) für die
  Fahrsicherheit gilt das jüngste Ereignis nach `erfasst_am`, bei Gleichstand nach
  `event_id` – dieselbe Regel wie auf dem iPad.
- Ist das jüngste Ereignis ein Storno, zählt der Durchgang nicht.
- Inaktive Kinder erscheinen, wenn Erfassungen zu ihnen vorliegen.

## Feedbackbogen

Eine A4-Seite je Kind, für das Kind und seine Eltern. Erzeugt in der Auswertung:
„Alle Feedbackbögen (PDF)" (Kinder ohne jede Erfassung bekommen keinen Bogen und werden
dort genannt) oder je Kind „Bogen". Die Dateinamen enthalten nur Datum und Startnummer.

Inhalt (`app/feedback.py`):

- **Das klappt schon gut** – Items mit einer Fehlerquote unter 25 %.
- **Daran üben wir noch** – höchstens drei Items mit der höchsten Quote (ab 25 %),
  jeweils mit dem `uebungstext`. Gleichstand: Reihenfolge auf der Strecke.
- Kommt dieselbe Kurzbezeichnung an mehreren Posten vor (z. B. „Schulterblick"), ist
  sie für das Kind *ein* Punkt; es zählt der Posten mit der höchsten Quote. So steht
  nichts zugleich unter „gut" und „üben".
- **So sicher fährst du** – ein Satz: alle Posten „sicher" · keiner „unsicher" ·
  mindestens einer „unsicher" · alle „unsicher". Die Bemerkungen der Posten erscheinen
  bewusst **nicht** auf dem Bogen (Eltern formulieren am Straßenrand nicht für Kinderohren);
  die Lehrkraft sieht sie in der Auswertung und kann sie handschriftlich übernehmen.
- Keine Zahlen, Prozente oder Noten (automatisch getestet).

### Feedbackbogen anpassen

Die eingebaute Vorlage liegt in `app/vorlagen/pdf/feedbackbogen.html` und `.css`;
dort stehen auch alle Sätze. Eigene Vorlagen kommen in ein Verzeichnis außerhalb des
Codes, das `FP_VORLAGEN_VERZEICHNIS` angibt:

```
vorlagen/
├── feedbackbogen.css          ← gilt für alle Schulen (optional)
├── logo.png                   ← Logo für alle Schulen (optional)
└── gs-lindenweg/              ← Kurzname der Schule, klein, Umlaute als ae/oe/ue,
    ├── feedbackbogen.html        alles andere als „-" (Kurzname „GS Lindenweg")
    ├── feedbackbogen.css
    └── logo.svg               ← logo.svg, logo.png oder logo.jpg
```

Jede Datei wird zuerst im Schulordner, dann im gemeinsamen Ordner, dann in den
eingebauten Vorlagen gesucht – eine Schule kann also auch nur ihr Logo oder nur das
Stylesheet austauschen. Am einfachsten kopiert man die eingebaute Vorlage und ändert sie;
welche Werte zur Verfügung stehen, steht oben in der Datei.

## Datenschutz-Funktionen

- **Löschfrist:** `python -m app.kommandos aufbewahrung [--monate N] [--trocken]` löscht
  alle Erfassungen von Läufen, deren Datum älter als die Frist ist (Standard
  `FP_AUFBEWAHRUNG_MONATE=12`). Gelöscht wird immer ein ganzer Lauf, nie ein Teil; der
  Lauf wird archiviert und zeigt das Löschdatum. Aufruf per cron, siehe `DEPLOYMENT.md`.
- **Export:** Schuladmins laden unter *Konto → Datenexport* (`/verwaltung/export.json`)
  alle Daten ihrer Schule als JSON herunter – für Auskunftsersuchen. Ohne Passwort-Hashes,
  Tokens und Sitzungen; die Mandanten-Schicht garantiert, dass nichts Fremdes darin steht.
- **Protokolle:** keine Namen, Startnummern oder Tokens – weder in der Anwendung noch
  (mit der Beispielkonfiguration) in nginx.

## Entscheidungen zur Erfassung

- **`fehlende_items` enthält Item-IDs**, keine Bezeichnungen – Umbenennungen
  einer Kurzbezeichnung verfälschen so keine alten Erfassungen.
- **Durchgänge werden pro Kind gezählt.** Der Schlüssel (Startnummer, Posten,
  `durchgang_nr`) bleibt damit auch eindeutig, wenn Kinder sich überholen
  oder übersprungen werden.
- **Rückgängig** schreibt ein Storno-Ereignis mit demselben Schlüssel
  (`{"durchgang_nr": n, "fehlende_items": [], "storniert": true}`). Wird das
  Kind danach erneut erfasst, bekommt es wieder `durchgang_nr` n, und das
  jüngere Ereignis gewinnt.
- **Doppeltipp-Schutz:** 0,7 s nach „Weiter" werden weitere Taps ignoriert.
- Beim Wechsel über „andere Nummer" bleiben bereits rot markierte Items
  stehen – die Beobachtung gehört zum Kind, nur die Nummer war falsch.

## Mandantentrennung (`app/mandant.py`)

Jede Datenbanksitzung hat einen *Bereich*, ohne den sie nichts ausführen kann:

| Bereich | Wofür | Wirkung |
|---|---|---|
| `MANDANT` | Schuladmin | Jede Abfrage wird automatisch auf die `schule_id` eingeschränkt, auch in Joins und Unterabfragen. Beim Schreiben wird geprüft, dass Objekt und Eltern zur Schule gehören. Rohes SQL und Core-Zugriffe sind gesperrt. |
| `SYSTEMADMIN` | Systemadmin | Nur `Schule` und `Benutzer`. Jede Anweisung, die eine andere Tabelle berührt, wird abgewiesen. |
| `INTERN` | Token-API, Anmeldung, Management-Kommandos | Uneingeschränkt; in Route-Modulen des Verwaltungsbereichs statisch verboten. |

Route-Handler verwenden ausschließlich `SchulRepository` bzw. `SystemRepository`.
Fremde IDs ergeben `NichtGefunden` (→ HTTP 404) – nicht unterscheidbar von nicht existierenden.

Neue Modelle müssen von `Mandantenmodell` erben und `mandant_kriterium` sowie
`__mandant_eltern__` definieren; `tests/test_architektur.py` schlägt sonst fehl.

Ereignisse sind append-only: Die Mandanten-Schicht verbietet Schreiben im
Verwaltungsbereich, ein Datenbank-Trigger verbietet `UPDATE` grundsätzlich.
