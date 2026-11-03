#!/bin/sh
set -eu
export FP_INIT_PASSWORD="$(cat /run/secrets/db-app)"
psql --username "$POSTGRES_USER" --dbname postgres --set ON_ERROR_STOP=1 <<'SQL'
\getenv app_password FP_INIT_PASSWORD
CREATE ROLE fahrrad LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD :'app_password';
CREATE DATABASE fahrrad OWNER fahrrad;
REVOKE ALL ON DATABASE postgres FROM PUBLIC;
REVOKE ALL ON DATABASE template1 FROM PUBLIC;
SQL
