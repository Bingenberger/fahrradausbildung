# Standalone und Plattformvertrag

## Neue Installation

Python 3.12.12, FastAPI/WeasyPrint aus vorhandenem uv.lock, amd64. Basisimages
Python/uv/PostgreSQL sind mit Digest fixiert; lokale Entwicklungstags sind kein
freigegebenes Registry-Release. Debian-Systempakete werden aus den konfigurierten
Paketquellen installiert, noch ohne vollständigen Paket-Snapshot/SBOM.

~~~sh
python3 prepare_secrets.py
export FP_SECRETS_DIR="$PWD/.private"
export FP_OEFFENTLICHE_URL="https://fahrrad.example.org"
export FP_PROXY_IPS="EXAKTE_PROXY_IP_WIE_DER_CONTAINER_SIE_SIEHT"
docker compose build
docker compose up -d --wait db
docker compose run --rm --no-deps app python -m app.migrate
docker compose up -d --no-build
docker compose exec app python -m app.kommandos systemadmin-anlegen PERSOENLICHE_EMAIL
~~~

Ein vorhandener Proxy wird ausdrücklich konfiguriert, keine DNS-/Firewall-
Änderung durch Compose. Backend standardmäßig nur 127.0.0.1:8000; FP_BIND und
FP_PORT bleiben erhalten. Vor den Schulbetrieb gehört HTTPS; nur für lokales
synthetisches HTTP-Testen FP_COOKIE_SECURE=false setzen.

Der Schlüsselhelfer erzeugt ausschließlich neue private Dateien, verweigert
Überschreiben und gibt keine Werte aus. Elternverzeichnis 0700, einzeln in die
Container projizierte Credentialdateien 0444. Der Webcontainer bekommt nur
database-url, niemals das PostgreSQL-Administrationspasswort.
FP_DATABASE_URL_FILE ergänzt FP_DATABASE_URL; beide zugleich werden abgewiesen.
Die DB-Approlle fahrrad besitzt ausschließlich ihre eigene Datenbank und hat
weder Superuser-, CREATEDB- noch CREATEROLE-Recht.

Kein Standardkonto, keine Registrierung oder Seed beim Start. Das persönliche
Adminpasswort wird ausschließlich über das kontrollierende Terminal abgefragt;
ohne Terminal scheitert das Kommando. Fachrollen und Konten bleiben in dieser App.
Keine SSO-Pflicht vor der Posten-App.

## Migration und Übernahme

Version 0008 ergänzt ausschließlich betriebliche Limitdaten, Version 0009 die
optionale Spalte `schule.posten_pin` (PIN vor der Posten-App, standardmäßig leer);
bestehende Fach-IDs, Posten-Tokens und Ereignisse bleiben erhalten. Der explizite Job hält eine
PostgreSQL-Transaktionssperre. Gleichzeitige Migration wartet begrenzt, Fehler
rollen die Transaktion zurück. Unversionierte Bestandsdaten werden nicht automatisch
adoptiert; unbekannte Revisionen scheitern. Migration niemals beim Webstart.

Bestehende native Installation erst mit zugehörigen Dateien sichern, dann
kontrolliert in isolierte Datenbank übernehmen und explizit migrieren.
Das Compose-DB-Initialisierungsskript gilt nur für leeres pgdata; es ändert keine
vorhandenen Rollenpasswörter. Alte Volumes nicht ungeprüft an neue Compose-Dateien
hängen. Ein neuer Pilotzustandsordner ist kein Datenupgrade.

## Laufzeit, Grenzen und Diagnose

Zwei Uvicorn-Worker, gemeinsame PostgreSQL-Anmelde-/Postenlimits und ein gemeinsamer
PDF-Slot über Dateisperre im Container. Getrennte zusätzliche Appcontainer würden
eigene PDF-Slots besitzen; diese Composekonfiguration startet genau eine Appinstanz.
Alle vier PDF-Funktionen werden begrenzt. Überlast liefert 503/Retry-After.
Höchstens 200 Feedbackbögen, 100 Posten oder 2000 Startnummern pro Export.
Requestbody-Streaming wird auch ohne Content-Length auf 2,1 MB begrenzt;
Postenbatch weiterhin höchstens 1000 Ereignisse/2 MB. Keine unbeschränkte
Argon2-Eingabelänge. Kartenkachelantworten höchstens 2 MiB/4 Millionen Pixel.

Anmeldeversuche reservieren den gemeinsamen Slot vor der Passwortprüfung.
Standard zehn erfolglose/in Bearbeitung befindliche Versuche je E-Mail/IP in
einem festen 15-Minuten-Fenster; eine erfolgreiche Prüfung gibt ihren eigenen Slot
zurück. Neustart setzt die Zähler nicht zurück. Kein gleitendes Fenster mehr.
Postenanfragen höchstens 120 je Token in festem 60-Sekunden-Fenster.
Gehasht gespeicherte Schlüssel, abgelaufene Einträge werden entfernt, maximal
10000 aktive Limitschlüssel. Bei voller Tabelle wird weiterer Zugang begrenzt.

UID/GID 10001, Read-only-Root, 128 MiB /tmp, 768 MiB RAM, eine CPU und 128 PIDs.
DB eigenes pgdata, 512 MiB/eine CPU. Das sind konfigurierte Grenzen, keine
Kapazitätsmessung. /health/live ist unabhängig von DB/Karten/SMTP;
 /health/ready und /gesund verlangen eigene DB und genau Revision 0009 (`app.migrate.SCHEMA_REVISION`).
DB-Healthcheck nutzt TCP und prüft dadurch nicht den temporären Socket-Initserver.
Keine Accesslogs mit Postentokens; SQL-Fehler liefern generische 503-Antwort.

## Daten, Karten, Offline und Domainwechsel

pgdata enthält sämtliche Schul-, Rollen-, Sitzungs-, Token-, Ereignis- und Limitdaten.
Das Volume vorlagen wird im Webcontainer nur unter /vorlagen:ro eingebunden.
Eigene Vorlagen nur bewusst und mit passender Lizenz unter UID/GID 10001 bereitstellen.
Die App verändert diese Dateien nicht. Keine Credentialdateien im Image.

FP_OEFFENTLICHE_URL ist die Laufzeit-Origin für vorhandene Postenlinks/QR-Codes;
Domainwechsel braucht Containerneustart und Proxyänderung, keinen Frontendbuild.
Host-/Forwarded-Header bestimmen die QR-Origin nicht. Bestehende Tokens bleiben
unverändert und funktionieren unter der neuen Origin.

IndexedDB, installierte PWA und Service Worker gehören zur Browser-Origin.
Sie wandern nicht durch Domainänderung oder Serverrestore mit. Vor Domainwechsel
alle Postengeräte online synchronisieren, lokalen Stand prüfen, erst dann umstellen
und Geräte neu einrichten. Nicht synchronisierte Browserdaten sind kein Serverbackup.
Offline-Sperren können erst beim Wiederverbinden wirken.

Serverseitige Kartenkacheln sind im Compose standardmäßig deaktiviert (in der Schulplattform:
`karten = true` unter `[apps.fahrradausbildung]` schaltet sie ein); bei Ausfall
bleiben PDF/Kernbetrieb verfügbar. Die interaktive Kartenseite kann weiterhin die
vorhandenen externen Karten-, Routing- und Suchanbieter ansprechen. Deren
Nutzungsbedingungen, Attribution und datenschutzrechtliche Freigabe bleiben
Betreiberaufgabe. Keine SMTP-Konfiguration, kein künstlicher Maildienst.

## Sicherung und Wiederherstellung

Appschreiber stoppen/drainieren, PostgreSQL mit pg_dump -Fc sichern, Vorlagen
generisch als Datei-/Verzeichnissnapshot und Credentials separat mit sichern.
Private Archive, vertrauenswürdig separat übergebene Prüfsummen, neues leeres
isoliertes Ziel, gleiche Rollen/UIDs. Danach Revision, Fremdschlüssel, Ereignis-
Trigger, Rollen/IDs und Zugriffssperren prüfen. Docker-exec-Transporte für
pg_restore brauchen -i, damit die Archivbytes tatsächlich ankommen.
Serverbackup enthält keine noch ungesendeten Geräteereignisse.

Image-Rollback setzt Daten nicht zurück. Daten-Rollback benötigt passenden
DB-/Datei-/Credentialstand und kann neuere Erfassungen verlieren. Restore von
Sitzungen und Tokens kann vorherige Zugänge reaktivieren; produktiv Widerruf und
Neuverteilung planen. Verschlüsseltes Offsitebackup, Rotation und Alarmierung
sind noch kein Bestandteil dieses Compose.

Tests: Testimage enthält Fach-/Vertragstests gegen eine eigene disposable
PostgreSQL-Instanz. Browser-Teststage enthält Chromium, WebKit und QR-Decoder.
Testdatenbank-Setup darf ausschließlich auf dieser isolierten Testinstanz laufen,
weil die vorhandene Suite ihre benannte Testdatenbank neu anlegt.
