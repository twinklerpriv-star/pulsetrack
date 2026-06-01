# ==============================================================================
# PULSETRACK ANALYTICS - DATENBANK-MODELL: WEBSITE
# ==============================================================================
# Datum: 01.06.2026 | Version: 1.2 | Status: Aktiv gepflegt
#
# BETRIEBSWIRTSCHAFTLICHER ZWECK DIESER DATEI:
# Dieses Modell repräsentiert eine Kundenwebsite, die getrackt werden soll (z. B.
# "https://www.elektro-pepi.at"). Jede Website erhält ein einzigartiges
# Sicherheits-Token, das im Tracking-Snippet eingebunden wird.
#
# AUSWIRKUNG FÜR DEN KUNDEN / GESCHÄFTSFÜHRER:
# - Einfache Verwaltung: Sie können beliebig viele Webseiten in Ihrem Dashboard
#   registrieren (je nach gewähltem Tarif).
# - Flexibilität: Sie können per Mausklick entscheiden, ob Sie auch Ihre Subdomains
#   (wie "shop.elektro-pepi.at") oder die Hauptdomain ohne "www" mit-tracken möchten.
# ==============================================================================

from datetime import datetime

from sqlalchemy import Boolean, Column, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.models.base import Base, UTCDateTime


class Website(Base):
    """
    Tabelle für die vom Kunden registrierten Webseiten.
    """
    __tablename__ = "websites"

    # Eindeutige ID der Website
    id = Column(Integer, primary_key=True, index=True)
    
    # Verknüpfung zum Kundenkonto (Fremdschlüssel mit Cascade-Delete: Wird das Kundenkonto
    # gelöscht, werden alle zugehörigen Webseiten automatisch mit-gelöscht)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Die Haupt-Domain der Website (z. B. https://www.elektro-pepi.at)
    domain = Column(String, nullable=False)
    
    # Eindeutiges Tracking-Token (z. B. pt_live_xxxx). Dieses Token wird im HTML-Snippet
    # genutzt, um ankommende Klicks genau dieser Website zuzuordnen.
    tracking_token = Column(String, unique=True, index=True, nullable=False)
    
    # Sollen Aufrufe ohne "www" erfasst werden? (Standard: Ja)
    track_apex = Column(Boolean, nullable=False, default=True)
    
    # Sollen Aufrufe von Unterdomains (z. B. shop.domain.at) erfasst werden? (Standard: Ja)
    track_subdomains = Column(Boolean, nullable=False, default=True)
    
    # Registrierungsdatum dieser Domain im PulseTrack-System
    created_at = Column(UTCDateTime, nullable=False, default=datetime.utcnow)

    # Rückbeziehung zum Kundenkonto (User)
    owner = relationship("User", back_populates="websites")
    
    # Kaskadierte Löschung aller aufgezeichneten Klicks dieser Website bei deren Löschung
    hits = relationship("Hit", back_populates="website", cascade="all, delete-orphan")
