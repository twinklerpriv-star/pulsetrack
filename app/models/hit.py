# ==============================================================================
# PULSETRACK ANALYTICS - DATENBANK-MODELL: HIT (BESUCHER-SEITENAUFRUF)
# ==============================================================================
# Datum: 01.06.2026 | Version: 1.2 | Status: Aktiv gepflegt & DSGVO-optimiert
#
# BETRIEBSWIRTSCHAFTLICHER ZWECK DIESER DATEI:
# Dieses Modell legt fest, welche Daten bei jedem einzelnen Klick/Seitenaufruf
# eines Website-Besuchers in der Datenbank gespeichert werden. 
# Wichtig: Es dient als Grundlage für die Dashboard-Diagramme (wie z.B.
# die beliebtesten Seiten oder Browser-Verteilungen).
#
# DSGVO- & DATENSCHUTZ-ERKLÄRUNG (MASSGEBLICHER VALUE PROPOSITION):
# - Keine IP-Adresse im Klartext: Es wird ausschließlich ein datenschutzkonformer
#   Hashwert der IP-Adresse (`ip_hash`) gespeichert. Dieser wird über die tägliche
#   Key-Rotation verschlüsselt und ist am Folgetag absolut unumkehrbar.
# - Keine Cookies: Die Identifikation geschieht rein server-seitig über den
#   kurzlebigen Hash. Ihr Kunde kann PulseTrack daher **ohne nervigen Cookie-Banner** betreiben!
# ==============================================================================

from datetime import datetime

from sqlalchemy import Column, ForeignKey, Index, Integer, String
from sqlalchemy.orm import relationship

from app.models.base import Base, UTCDateTime


class Hit(Base):
    """
    Diese Tabelle speichert alle erfassten Seitenaufrufe (Hits).
    """
    __tablename__ = "hits"

    # Fortlaufende, eindeutige Nummer des Eintrags
    id = Column(Integer, primary_key=True, index=True)
    
    # Zuordnung zur Kundenwebsite (Fremdschlüssel mit Cascade-Delete: Löscht der B2B-Kunde
    # seine Website im Dashboard, werden auch alle zugehörigen Hits sofort unwiderruflich gelöscht).
    website_id = Column(Integer, ForeignKey("websites.id", ondelete="CASCADE"), nullable=False)
    
    # Exakter Zeitpunkt des Seitenaufrufs (UTC)
    timestamp = Column(UTCDateTime, index=True, nullable=False, default=datetime.utcnow)
    
    # Die aufgerufene URL (z. B. https://www.elektro-pepi.at/kontakt)
    url = Column(String, nullable=False)
    
    # Herkunftsquelle des Besuchers (z. B. Google, Facebook oder Direct)
    referrer = Column(String, nullable=True)
    
    # Der rohe User-Agent-String des Browsers (wird zur statistischen Auswertung gefiltert)
    user_agent = Column(String, nullable=True)
    
    # Kryptografischer, datenschutzkonformer IP-Hash (siehe oben)
    ip_hash = Column(String, nullable=False)
    
    # Ermittelter Browser (z. B. Chrome, Firefox) zur Dashboard-Anzeige
    browser = Column(String, nullable=True)
    
    # Ermitteltes Betriebssystem (z. B. Windows, Android) zur Dashboard-Anzeige
    os = Column(String, nullable=True)

    # Datenbank-Index zur drastischen Beschleunigung der Dashboard-Abfragen (zeitliche Eingrenzung)
    __table_args__ = (
        Index('ix_hits_website_timestamp', 'website_id', 'timestamp'),
    )

    # Beziehung zur Website-Tabelle (ermöglicht einfachen Zugriff im Programmcode)
    website = relationship("Website", back_populates="hits")
