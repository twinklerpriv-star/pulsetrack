# ==============================================================================
# PULSETRACK ANALYTICS - DATENBANK-MODELLE: USER, AVV-SIGNATUR & SCHLÜSSEL
# ==============================================================================
# Datum: 01.06.2026 | Version: 1.2 | Status: Aktiv gepflegt & DSGVO-konform
#
# BETRIEBSWIRTSCHAFTLICHER ZWECK DIESER DATEI:
# Diese Datei enthält drei fundamentale Modelle für unseren SaaS-Betrieb:
# 1. User: Speichert B2B-Kundenkonten (E-Mail, verschlüsseltes Passwort und Stripe-Abo).
# 2. UserAVVSignature: Dient der revisionssicheren Dokumentation, dass ein B2B-Kunde
#    den gesetzlich vorgeschriebenen Auftragsverarbeitungsvertrag (AVV) abgeschlossen hat.
# 3. DailyKey: Speichert die täglich neu generierten, geheimen Schlüssel für das
#    IP-Hashing zur Wahrung der DSGVO-Datenminimierung und Forward Secrecy.
# ==============================================================================

from datetime import datetime

from sqlalchemy import Column, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.models.base import Base, UTCDateTime


class User(Base):
    """
    Tabelle für registrierte B2B-Kunden (Webseiten-Betreiber).
    """
    __tablename__ = "users"

    # Eindeutige Kundennummer
    id = Column(Integer, primary_key=True, index=True)
    
    # E-Mail-Adresse des Kunden (wird für Login und Benachrichtigungen genutzt)
    email = Column(String, unique=True, index=True, nullable=False)
    
    # Sicher gehashtes Passwort ( Argon2id ) – niemals im Klartext!
    password_hash = Column(String, nullable=False)
    
    # Stripe-spezifische Kundennummer für Zahlungen
    stripe_customer_id = Column(String, nullable=True)
    
    # Aktive Stripe-Abonnementnummer
    stripe_subscription_id = Column(String, nullable=True)
    
    # Abo-Status (z. B. 'trial' für Testphase, 'active' für bezahlt oder 'canceled')
    subscription_status = Column(String, nullable=False, default="trial")
    
    # Registrierungsdatum des Kundenkontos
    created_at = Column(UTCDateTime, nullable=False, default=datetime.utcnow)

    # BEZIEHUNGEN (RECHT AUF LÖSCHUNG - ART. 17 DSGVO via Cascade-Delete):
    # KUNDENVERSTÄNDLICHE ERKLÄRUNG:
    # Wenn ein Kunde im Dashboard die Option "Konto unwiderruflich löschen" wählt,
    # sorgt das System dank 'cascade="all, delete-orphan"' dafür, dass alle seine
    # registrierten Webseiten, aufgezeichneten Hits und AVV-Verträge in Millisekunden
    # vollständig und rückstandslos aus der Datenbank entfernt werden.
    websites = relationship("Website", back_populates="owner", cascade="all, delete-orphan")
    avv_signatures = relationship("UserAVVSignature", back_populates="user", cascade="all, delete-orphan")


class UserAVVSignature(Base):
    """
    Tabelle zur revisionssicheren Speicherung digitaler DSGVO-Vertragsabschlüsse.
    """
    __tablename__ = "user_avv_signatures"

    id = Column(Integer, primary_key=True, index=True)
    
    # Verknüpfung zum Kundenkonto
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    
    # Version des unterzeichneten Vertrags
    avv_version = Column(String, nullable=False)
    
    # Genauer Abschlusszeitpunkt (UTC)
    signed_at = Column(UTCDateTime, nullable=False, default=datetime.utcnow)
    
    # Aus Datenschutzgründen nur maskiert gespeicherte IP-Adresse des Kunden (z.B. 192.168.1.0)
    signed_from_ip = Column(String, nullable=False)
    
    # Kryptografischer Signatur-Hash (garantiert, dass der Eintrag nachträglich nicht manipuliert werden kann)
    signature_hash = Column(String, nullable=False)

    # Rückbeziehung zum Kundenkonto
    user = relationship("User", back_populates="avv_signatures")


class DailyKey(Base):
    """
    Tabelle für täglich rotierende Verschlüsselungsschlüssel.
    
    KUNDENVERSTÄNDLICHE ERKLÄRUNG:
    Diese Tabelle speichert den für den jeweiligen Kalendertag generierten geheimen
    Schlüssel. Dieser wird genutzt, um die IP-Adresse eines Website-Besuchers in einen
    anonymen Zahlencode (Hash) umzuwandeln.
    Nach 24 Stunden wird dieser Schlüssel vom System gelöscht. Ab diesem Moment
    ist es mathematisch absolut unmöglich, den Besucher-Hash wieder in eine echte
    IP-Adresse zurückzuverwandeln! Das sorgt für 100%ige DSGVO-Konformität.
    """
    __tablename__ = "daily_keys"

    # Datum des Schlüssels (Format: YYYY-MM-DD)
    day = Column(String, primary_key=True)
    
    # Der sicher verschlüsselte 32-Byte-Schlüssel
    key_value = Column(String, nullable=False)
