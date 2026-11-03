# Betrieb der Fahrradprüfung

Die aktuelle Installation mit eigenen Credentialdateien, expliziter Migration,
zwei Webworkern und Sicherung ist in [PLATFORM.md](PLATFORM.md) beschrieben.
Die frühere automatische Migration beim Containerstart entfällt.

[deploy/nginx-fahrradpruefung.conf](deploy/nginx-fahrradpruefung.conf) bleibt
ein Beispiel für einen separat administrierten TLS-Proxy. FP_PROXY_IPS muss seine
exakte aus dem Container sichtbare Adresse enthalten. Bestehende nginx-, Docker-,
Firewall- und SSH-Konfiguration vor Änderungen prüfen und nicht blind ersetzen.

HTTPS ist für den realen Posten-PWA-/Offlinebetrieb erforderlich. Keine pauschale
Anmeldung vor /p/ und /api/p/: Dort autorisiert ausschließlich der Postenzugang.

Eigene Feedbackvorlagen und Logos liegen im benannten Volume vorlagen und sind
im Webcontainer nur lesbar. Vor Übernahme alter Bindmount-Dateien einen geprüften
Dateisnapshot anlegen und IDs, Dateirechte sowie die passende Schule kontrollieren.
Aufbewahrung und Sitzungsbereinigung bleiben explizite Managementkommandos;
bestehende Timer erst nach Prüfung ihrer Datenbank-/Credentialkonfiguration übernehmen.

Keine produktive Server-, DNS-, Zertifikats- oder Firewallkonfiguration wurde durch
die lokalen Plattformtests verändert.
