"""Oberfläche des Systemadmins: Schulen und Schuladmins.

Der Systemadmin hat keinen Zugriff auf Kinder, Gruppen oder Erfassungsdaten.
Das erzwingt die Mandanten-Schicht (Bereich SYSTEMADMIN), nicht die Navigation.
"""

from app.system.routen import router

__all__ = ["router"]
