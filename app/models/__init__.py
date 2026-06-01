# ==============================================================================
# PULSETRACK ANALYTICS - AUTOMATISCHE DATENBANK-MODELL-INITIALISIERUNG
# ==============================================================================
# Datum: 01.06.2026 | Version: 1.1 | Status: Aktiv gepflegt
#
# BETRIEBSWIRTSCHAFTLICHER ZWECK DIESER DATEI:
# Diese Datei bündelt alle einzelnen Datenstrukturen (Kundenkonten, Verträge,
# Webseiten, Klicks und Schlüssel), damit sie von SQLAlchemy beim Serverstart
# in einem einzigen Schritt in der SQLite-Datenbank angelegt werden können.
#
# INFORMATION FÜR DEN IT-TECHNIKER:
# - Aggregiert alle ORM-Klassen für den einfachen Import in main.py.
# ==============================================================================

from app.models.hit import Hit
from app.models.user import DailyKey, User, UserAVVSignature
from app.models.website import Website

__all__ = ["User", "UserAVVSignature", "Website", "Hit", "DailyKey"]
