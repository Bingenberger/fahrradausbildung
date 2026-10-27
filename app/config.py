"""Zentrale Konfiguration, ausschließlich aus Umgebungsvariablen."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Einstellungen(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="FP_", extra="ignore")

    database_url: str = "postgresql+psycopg://fahrrad:fahrrad@localhost:55432/fahrrad"
    # Gültigkeit der Posten-Tokens nach dem Laufdatum (Spezifikation 9: 24 Stunden).
    token_gueltigkeit_stunden: int = 24
    # Aufbewahrungsfrist der Ereignisdaten in Monaten (Spezifikation 9: Standard 12).
    aufbewahrung_monate: int = 12

    # Öffentliche Adresse der Anwendung – daraus entstehen die QR-Codes der Posten-Blätter.
    oeffentliche_url: str = "http://localhost:8000"
    # Zeitzone der Schulen: maßgeblich dafür, wann ein Laufdatum endet.
    zeitzone: str = "Europe/Berlin"

    # Kartenkacheln für den Kartenausschnitt auf dem Posten-Blatt ({z}/{x}/{y}).
    # Leer: Posten-Blätter ohne Karte. Der Server braucht dafür Zugang ins Internet.
    karten_kacheln: str = "https://tile.openstreetmap.de/{z}/{x}/{y}.png"

    # Optionales Verzeichnis mit eigenen PDF-Vorlagen (Feedbackbogen, Logo).
    # Aufbau: <verzeichnis>/feedbackbogen.html|.css|logo.* für alle Schulen,
    # <verzeichnis>/<kurzname>/… für eine einzelne Schule. Siehe README.
    vorlagen_verzeichnis: str = ""

    # Sitzungs-Cookie nur über HTTPS senden. Nur für lokale Entwicklung abschalten.
    cookie_secure: bool = True
    # Abmeldung nach so vielen Minuten ohne Aktivität …
    sitzung_leerlauf_minuten: int = 120
    # … und spätestens nach so vielen Stunden.
    sitzung_max_stunden: int = 12
    # Fehlversuche bei der Anmeldung je E-Mail-Adresse bzw. IP in 15 Minuten.
    anmeldung_max_fehlversuche: int = 10


@lru_cache
def einstellungen() -> Einstellungen:
    return Einstellungen()
