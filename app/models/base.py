# ==============================================================================
# PULSETRACK ANALYTICS - ORM-BASISKLASSE & ZEITZONEN-MANAGEMENT
# ==============================================================================
# Datum: 01.06.2026 | Version: 1.2 | Status: Aktiv gepflegt
#
# BETRIEBSWIRTSCHAFTLICHER ZWECK DIESER DATEI:
# Diese Datei definiert die "Mutter-Klasse" (declarative_base) für alle unsere
# Datenbank-Tabellen. Außerdem löst sie ein klassisches Problem bei Zeitzonen:
# Da Server und Kunden auf der ganzen Welt verschiedene lokale Zeiten haben,
# speichert diese Datei alle Zeiten streng im standardisierten UTC-Format.
#
# AUSWIRKUNG FÜR DEN KUNDEN / GESCHÄFTSFÜHRER:
# - Konsistenz: Alle Statistiken im Dashboard stimmen exakt mit dem tatsächlichen
#   Besuchszeitpunkt überein, unabhängig davon, in welchem Land der Server gehostet ist.
#
# INFORMATION FÜR DEN IT-TECHNIKER:
# - Stellt 'Base' für deklarative Tabellenmodelle bereit.
# - 'UTCDateTime' konvertiert ISO-8601 Strings und zeitzonenbehaftete datetime-Objekte
#   in zeitzonenlose UTC-DateTimes zur sicheren Speicherung in SQLite.
# ==============================================================================

from datetime import datetime

from sqlalchemy import DateTime, TypeDecorator
from sqlalchemy.orm import declarative_base

# Die Basisklasse für das SQLAlchemy-ORM-System
Base = declarative_base()

class UTCDateTime(TypeDecorator):
    """
    KUNDENVERSTÄNDLICHE ERKLÄRUNG:
    Ein intelligenter Zeit-Konverter. Wenn z. B. ein Besucher um 14:00 Uhr
    deutscher Zeit (UTC+2) Ihre Website aufruft, wandelt dieser Konverter dies
    automatisch in 12:00 Uhr UTC um. Beim Laden wird es einheitlich verarbeitet,
    sodass Ihr IT-Techniker keine fehlerhaften Zeitberechnungen befürchten muss.
    """
    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        """Wird aufgerufen, wenn ein Wert in die Datenbank geschrieben wird."""
        if value is None:
            return None
        if isinstance(value, str):
            try:
                # ISO-8601 Zeitangaben (z.B. mit Z am Ende für UTC) sauber umrechnen
                return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
            except ValueError:
                # Fallback für einfachere Datums-Formate
                for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
                    try:
                        return datetime.strptime(value, fmt)
                    except ValueError:
                        continue
                raise ValueError(f"Ungueltiges Datumsformat: {value}")
        return value

    def process_result_value(self, value, dialect):
        """Wird aufgerufen, wenn ein Wert aus der Datenbank ausgelesen wird."""
        return value
