"""Betrieb: Healthcheck, Konfigurationsvorlage, Compose-Datei (Spezifikation 2)."""

from __future__ import annotations

import re

from app.config import Einstellungen
from tests.conftest import PROJEKT


def test_gesund(client):
    antwort = client.get("/gesund")
    assert antwort.status_code == 200
    assert antwort.json() == {"ok": True}


def test_env_example_nennt_alle_einstellungen():
    text = (PROJEKT / ".env.example").read_text(encoding="utf-8")
    vorhanden = set(re.findall(r"^(FP_[A-Z_]+)=", text, flags=re.M))
    erwartet = {f"FP_{name.upper()}" for name in Einstellungen.model_fields}
    assert erwartet <= vorhanden, f"fehlt in .env.example: {sorted(erwartet - vorhanden)}"
    assert "POSTGRES_PASSWORD=" in text


def test_compose_benannte_volumes_und_nur_lokaler_port():
    text = (PROJEKT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "pgdata:/var/lib/postgresql/data" in text
    assert re.search(r"^volumes:\n  pgdata:", text, flags=re.M)
    assert "postgres:16" in text
    # Ohne Zutun zeigt die veröffentlichte Adresse auf Loopback. FP_BIND öffnet den
    # Port bewusst für einen Proxy auf einem anderen Rechner (DEPLOYMENT.md).
    assert '"${FP_BIND:-127.0.0.1}:${FP_PORT:-8000}:8000"' in text
