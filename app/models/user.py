# SQLAlchemy Modell: User & UserAVVSignature
#
# Datum: 28.05.2026 | Version: 1.0 | Status: Aktiv gepflegt

from sqlalchemy import Column, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    stripe_customer_id = Column(String, nullable=True)
    stripe_subscription_id = Column(String, nullable=True)
    subscription_status = Column(String, nullable=False, default="trial")
    created_at = Column(String, nullable=False)

    # Beziehungen (Kaskadiertes Löschen: Löscht der User sein Konto, verschwinden alle seine Webseiten und Signaturen)
    websites = relationship("Website", back_populates="owner", cascade="all, delete-orphan")
    avv_signatures = relationship("UserAVVSignature", back_populates="user", cascade="all, delete-orphan")


class UserAVVSignature(Base):
    __tablename__ = "user_avv_signatures"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    avv_version = Column(String, nullable=False)
    signed_at = Column(String, nullable=False)
    signed_from_ip = Column(String, nullable=False)
    signature_hash = Column(String, nullable=False)

    # Rückbeziehung zum User
    user = relationship("User", back_populates="avv_signatures")


class DailyKey(Base):
    __tablename__ = "daily_keys"

    day = Column(String, primary_key=True)  # e.g., "2026-05-28"
    key_value = Column(String, nullable=False)  # Stored as hex representation of 32-byte key

