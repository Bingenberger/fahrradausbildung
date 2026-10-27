#!/bin/sh
# Container-Start: Datenbank auf den neuesten Stand bringen, dann die Anwendung starten.
set -eu

alembic upgrade head

# Ein Prozess: Die Bremsen gegen zu viele Anmeldeversuche und Uploads zählen im
# Arbeitsspeicher. Mehrere Worker würden sie unterlaufen. Für eine Schule mit
# einigen iPads reicht ein Prozess mit Thread-Pool bei Weitem.
#
# --proxy-headers: Die echte Client-IP kommt von nginx (X-Forwarded-For) – sonst
# sähe die Anmeldebremse für alle Anfragen dieselbe IP. FORWARDED_ALLOW_IPS legt
# fest, wessen Header geglaubt wird (siehe docker-compose.yml).
exec uvicorn app.main:app \
  --host 0.0.0.0 --port 8000 \
  --proxy-headers --forwarded-allow-ips "${FORWARDED_ALLOW_IPS:-127.0.0.1}" \
  --no-server-header
