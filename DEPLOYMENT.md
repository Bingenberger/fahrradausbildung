# Betrieb der Fahrradprüfung

Diese Anleitung beschreibt den Betrieb auf einem Ubuntu-Server mit Docker Compose
hinter nginx. Sie richtet sich an die Person, die den Server betreut. Programmierkenntnisse
sind dafür nicht nötig.

```
Internet ──HTTPS──► nginx (Host, Port 443) ──HTTP──► app (127.0.0.1:8000) ──► db (PostgreSQL 16)
                                                      └── Docker Compose ──────────┘
```

## 1. Voraussetzungen

- Ubuntu 22.04 oder 24.04 mit einer festen Domain, z. B. `fahrrad.example.org`, deren
  DNS-Eintrag auf den Server zeigt.
- Docker Engine mit dem Compose-Plugin (`docker compose version` muss funktionieren),
  siehe <https://docs.docker.com/engine/install/ubuntu/>.
  Das alte `docker-compose` 1.x funktioniert mit aktuellen Docker-Versionen nicht
  zuverlässig (Fehler `KeyError: 'ContainerConfig'` beim Aktualisieren).
- nginx und certbot: `sudo apt install nginx certbot python3-certbot-nginx`.

**HTTPS ist Pflicht.** Ohne HTTPS funktioniert die Posten-App nicht offline: Browser
erlauben Service Worker und dauerhaften Speicher nur auf sicheren Seiten.

## 2. Installation

```bash
sudo mkdir -p /opt/fahrradpruefung && sudo chown $USER /opt/fahrradpruefung
# Code nach /opt/fahrradpruefung kopieren (git clone oder Archiv entpacken)
cd /opt/fahrradpruefung

cp .env.example .env
nano .env
```

In `.env` mindestens anpassen:

| Variable | Wert |
|---|---|
| `POSTGRES_PASSWORD` | langes Zufallspasswort, nur Buchstaben und Ziffern: `openssl rand -hex 24` |
| `FP_OEFFENTLICHE_URL` | `https://fahrrad.example.org` (ohne `/` am Ende) – steht in den QR-Codes |
| `FP_COOKIE_SECURE` | `true` |

`FP_DATABASE_URL` und `FP_VORLAGEN_VERZEICHNIS` setzt `docker-compose.yml` selbst.
Die Datei `.env` enthält das Datenbankpasswort: `chmod 600 .env`.

```bash
docker compose up -d --build
docker compose ps                        # app muss nach etwa 20 s "healthy" sein
docker compose exec app python -m app.kommandos systemadmin-anlegen admin@example.org
```

Beim Start bringt der Container die Datenbank automatisch auf den neuesten Stand
(`alembic upgrade head`).

### Besonderheit: Docker in einem LXC-Container (Proxmox)

Die Anwendung läuft in einem LXC-Container, aber Docker braucht dort Rechte, die ein
unprivilegierter Container nicht von sich aus hat. Auf dem Proxmox-Host gehört in
`/etc/pve/lxc/<ID>.conf`:

```
features: nesting=1,keyctl=1
```

Danach den Container neu starten. Zwei Fallen kosten sonst einen Abend Fehlersuche:

**1. Firewall-Dienste räumen Dockers Netzwerkregeln weg.** Debian aktiviert
`nftables.service` mitunter von sich aus. Dessen `/etc/nftables.conf` beginnt mit
`flush ruleset` – und weil `iptables` im `nft`-Modus arbeitet, löscht dieser Befehl
auch Dockers Ketten. Docker legt sie wenige Sekunden nach dem Systemstart an, der
Firewall-Dienst startet danach und wischt sie weg. Im Protokoll steht kein Fehler,
denn Docker hat korrekt gearbeitet; ihm wurde nur hinterher der Boden entzogen.

Das Fehlerbild wandert weit vom Verursacher weg: Der Build bricht in `apt-get update`
ab mit `Temporary failure resolving 'deb.debian.org'`, jeder Versuch nach genau 30
Sekunden. Image-Pulls funktionieren trotzdem, weil die der Docker-Dienst selbst
ausführt und dafür kein NAT braucht. Nur Container kommen nicht hinaus.

Prüfen – in dieser Reihenfolge, jeder Schritt schließt eine Ursache aus:

```bash
docker info | grep -A2 "Storage Driver"      # overlay2 erwartet; vfs wäre nur sehr langsam
sysctl net.ipv4.ip_forward                   # muss 1 sein
iptables -t nat -S POSTROUTING | grep -i masq   # MASQUERADE-Regel für 172.17.0.0/16?
iptables -t nat -S | grep -c DOCKER          # muss > 0 sein
docker run --rm busybox ping -c2 -W2 <IP des Gateways>
systemctl is-enabled nftables ufw
```

Fehlen die `DOCKER`-Ketten, scheitert auch `docker network create` mit
`Unable to enable SKIP DNAT rule: … No chain/target/match by that name` – und damit
jedes `docker compose up`, weil Compose ein eigenes Netz anlegt.

Behebung, wenn im Container keine Firewall gebraucht wird (hinter einem Router und der
Proxmox-Host-Firewall ist das der Normalfall; `ufw status` zeigt dann `inactive`):

```bash
systemctl disable --now nftables ufw
systemctl restart docker                     # erst danach, der Stop-Befehl flusht erneut
iptables -t nat -S | grep -c DOCKER          # jetzt > 0
```

Wird eine Firewall gebraucht, bleibt sie – dann muss Docker nach ihr starten:
`systemctl edit docker` mit `[Unit]` / `After=nftables.service ufw.service`.
Der eigentliche Test ist in beiden Fällen ein Neustart des Containers: danach müssen
die Ketten noch stehen.

**2. Dateirechte gehen beim Kopieren verloren.** Kommt der Quellbaum nicht per
`git clone`, sondern über eine Windows-Freigabe, `scp` oder ein neu gepacktes Archiv,
fehlt den Skripten das Ausführungsbit. Das `Dockerfile` setzt es für `docker/start.sh`
inzwischen selbst (`chmod 0755`), damit ein Image nicht davon abhängt. Zeigt ein
Container trotzdem `exec … permission denied`, ist `chmod +x` auf die betroffene Datei
und ein `docker compose build` die Lösung.

## 3. nginx und HTTPS

```bash
sudo cp deploy/nginx-fahrradpruefung.conf /etc/nginx/sites-available/fahrradpruefung
sudo nano /etc/nginx/sites-available/fahrradpruefung   # Domain eintragen
sudo ln -s /etc/nginx/sites-available/fahrradpruefung /etc/nginx/sites-enabled/
sudo mkdir -p /var/www/certbot
sudo certbot certonly --webroot -w /var/www/certbot -d fahrrad.example.org
sudo nginx -t && sudo systemctl reload nginx
```

Hinweis: Damit nginx den ersten `certbot`-Aufruf übersteht, den `server`-Block für
Port 443 vorher auskommentieren und danach wieder aktivieren. Alternativ
`sudo certbot --nginx -d fahrrad.example.org`.

Was die Beispielkonfiguration bewusst tut:

- **Kein Pfad im Zugriffsprotokoll.** Posten-Adressen enthalten das Zugangs-Token
  (`/p/…`, `/api/p/…`). Das eigene Logformat `fahrrad_ohne_pfad` protokolliert nur
  Methode, Status und Größe. Auch die Anwendung selbst schwärzt Tokens (`/p/***`).
- **`X-Forwarded-For $remote_addr`** – die Anwendung erfährt die echte IP und kann
  wiederholte Fehlanmeldungen bremsen; ein vom Client erfundener Header wird
  überschrieben.
- **Keine Sicherheits-Header in nginx.** CSP, HSTS, `X-Content-Type-Options` usw.
  setzt die Anwendung selbst; doppelte Header stören.

Test: `curl -sI https://fahrrad.example.org/anmelden` zeigt u. a.
`strict-transport-security` und `content-security-policy`.

### Proxy auf einem anderen Rechner

Standardmäßig veröffentlicht `docker-compose.yml` den Port nur auf `127.0.0.1` – das
setzt voraus, dass nginx auf demselben Host läuft. Terminiert HTTPS auf einem anderen
Rechner (etwa ein öffentlicher Server, der per VPN zum Heimserver tunnelt), müssen zwei
Werte in die `.env`:

| Variable | Wert |
|---|---|
| `FP_BIND` | Adresse, über die der Proxy die App erreicht, z. B. `192.168.178.103` |
| `FP_PROXY_IPS` | Adresse des Proxys, wie die App sie sieht – mehrere mit Komma, CIDR erlaubt |

`FP_PROXY_IPS` ist dabei nicht optional. Der Vorgabewert `*` heißt „jedem
`X-Forwarded-For`-Header glauben" und ist nur deshalb unbedenklich, weil an
`127.0.0.1` niemand von außen herankommt. Sobald der Port im Netz liegt, könnte jedes
Gerät dort die Anmeldebremse umgehen, indem es bei jedem Fehlversuch eine andere IP
behauptet – und in den Protokollen stünde die erfundene Adresse.

Welchen Wert die App tatsächlich sieht, verrät sie selbst: `FP_PROXY_IPS` vorübergehend
auf eine falsche Adresse setzen, `docker compose up -d`, die Seite über den Proxy
aufrufen und `docker compose logs app --tail=20` ansehen. Weil der Header dann nicht
geglaubt wird, protokolliert uvicorn die echte Gegenstelle.

Zu bedenken: Mit gesetztem `FP_BIND` ist die App für jedes Gerät im selben Netz
unverschlüsselt und am Proxy vorbei erreichbar. Soll das nicht sein, gehört ein
zweiter nginx auf den Host, der auf der Netzadresse lauscht und auf `127.0.0.1`
weiterleitet; dann bleibt `FP_BIND` leer und `FP_PROXY_IPS` auf `*`.

### Ausgehende Verbindungen

Für den Kartenausschnitt auf den Posten-Blättern lädt der Server Kartenkacheln von
`FP_KARTEN_KACHELN` (Standard: `tile.openstreetmap.de`, ausgehend HTTPS). Ohne
Internetzugang oder mit leerem Wert entstehen die Blätter ohne Karte. Die Kartenseite
der Streckenplanung lädt Karten und Routing direkt im Browser der Lehrkraft; dafür
braucht der Server nichts.

## 4. Regelmäßige Aufgaben (cron)

Die Anwendung hat bewusst keine versteckten Hintergrundprozesse. Diese Aufgaben
laufen per cron (`crontab -e` des Benutzers, der Docker bedienen darf):

```cron
# Erfassungen nach Ablauf der Aufbewahrungsfrist löschen (FP_AUFBEWAHRUNG_MONATE, Standard 12)
30 3 * * *  cd /opt/fahrradpruefung && docker compose exec -T app python -m app.kommandos aufbewahrung >> /var/log/fahrrad/aufbewahrung.log 2>&1
# Abgelaufene Anmeldesitzungen entfernen
45 3 * * *  cd /opt/fahrradpruefung && docker compose exec -T app python -m app.kommandos sitzungen-aufraeumen > /dev/null
# Nächtliche Sicherung, 14 Tage aufbewahrt (siehe Abschnitt 5)
0 2 * * *   cd /opt/fahrradpruefung && docker compose exec -T db pg_dump -U fahrrad -Fc fahrrad > /var/backups/fahrrad/fahrrad-$(date +\%F).dump && find /var/backups/fahrrad -name '*.dump' -mtime +14 -delete
```

(`sudo mkdir -p /var/log/fahrrad /var/backups/fahrrad` und dem cron-Benutzer geben.)

Das Aufbewahrungs-Kommando löscht alle Erfassungen eines Laufs, dessen Datum älter
als die Frist ist, archiviert den Lauf und vermerkt das Löschdatum; die Verwaltung
zeigt dann einen Hinweis statt leerer Tabellen. Vorher ansehen, was passieren würde:

```bash
docker compose exec app python -m app.kommandos aufbewahrung --trocken
```

Namen von Kindern speichert die Anwendung nicht; Gruppen bestehen nur aus Startnummern.
Die Zuordnung zu Namen steht auf der Papierliste der Klassenleitung.

## 5. Sicherung und Wiederherstellung

Sicherung von Hand:

```bash
docker compose exec -T db pg_dump -U fahrrad -Fc fahrrad > fahrrad-$(date +%F).dump
```

Wiederherstellen (überschreibt die laufende Datenbank!):

```bash
docker compose stop app
docker compose exec -T db pg_restore -U fahrrad -d fahrrad --clean --if-exists < fahrrad-2026-10-15.dump
docker compose start app
```

**Datenschutz:** Sicherungen enthalten Erfassungen und die E-Mail-Adressen der Schuladmins. Bewahre sie nur so
lange auf, wie nötig (oben: 14 Tage) – sonst läuft die Löschfrist ins Leere. Sicherungen
gehören verschlüsselt auf ein anderes System.

Zusätzlich müssen gesichert werden: `.env` und der Ordner `vorlagen/`.

## 6. Aktualisieren

```bash
cd /opt/fahrradpruefung
# neuen Code holen (git pull o. Ä.)
docker compose up -d --build
```

Migrationen laufen beim Start automatisch. Vorher eine Sicherung ziehen.

**Nicht am Vortag oder Tag einer Prüfung aktualisieren.** Eingerichtete iPads behalten
zwar ihre Daten und laden die neue App-Version erst, wenn sie wieder online sind –
aber am Prüfungstag soll nichts Unerwartetes passieren.

## 7. Eigene Feedbackbögen

Der Ordner `vorlagen/` neben `docker-compose.yml` ist im Container als `/vorlagen`
eingebunden. Aufbau und Beispiele: README, Abschnitt „Feedbackbogen anpassen".
Änderungen wirken sofort, ohne Neustart.

## 8. Überwachung und Protokolle

- `https://fahrrad.example.org/gesund` antwortet mit `{"ok": true}`, wenn Anwendung und
  Datenbank laufen (sonst Status 503). Geeignet für externe Überwachung.
- `docker compose logs -f app` – Anwendungsprotokoll. Es enthält Lauf- und Posten-IDs,
  aber keine Namen, Startnummern oder Tokens.
- `docker compose ps` zeigt den Zustand des Healthchecks.

## 9. Häufige Probleme

| Beobachtung | Ursache / Lösung |
|---|---|
| QR-Codes führen auf `localhost` | `FP_OEFFENTLICHE_URL` in `.env` setzen, `docker compose up -d`, Posten-Blätter neu drucken |
| Einrichtungsseite am iPad meldet, die App sei nicht offline bereit | Seite nicht über HTTPS aufgerufen, oder privates Surfen aktiv |
| Anmeldung „zu viele Versuche" für alle gleichzeitig | nginx setzt `X-Forwarded-For` nicht – alle Anfragen haben dieselbe IP |
| Anmeldung klappt, aber man landet wieder auf der Anmeldeseite | Aufruf über `http://` mit `FP_COOKIE_SECURE=true` – über HTTPS aufrufen |
| `KeyError: 'ContainerConfig'` | altes `docker-compose` 1.x; das Compose-Plugin (`docker compose`) verwenden |
| Build bricht ab: `Temporary failure resolving 'deb.debian.org'` | Container kommen nicht ins Netz, meist in LXC – siehe „Docker in einem LXC-Container" |
| `docker network create` meldet `No chain/target/match by that name` | Dockers iptables-Ketten fehlen; gleiche Ursache wie oben |
| `exec /usr/local/bin/start.sh: permission denied` | Ausführungsbit beim Kopieren verloren: `chmod +x docker/start.sh`, dann `docker compose up -d --build` |
| Proxy auf einem anderen Rechner erreicht die App nicht | Port liegt nur auf `127.0.0.1`: `FP_BIND` setzen – siehe „Proxy auf einem anderen Rechner" |

## 10. Bewusste Grenzen

- **Ein Anwendungsprozess.** Die Bremsen gegen zu viele Anmeldeversuche und Uploads
  zählen im Arbeitsspeicher; mehrere Prozesse würden sie unterlaufen. Für eine Schule
  mit einigen iPads reicht ein Prozess bei Weitem. Bei einem Neustart beginnen die
  Zähler von vorn.
- **Keine E-Mails.** Startpasswörter zeigt die Systemverwaltung einmalig an; sie werden
  persönlich weitergegeben.
