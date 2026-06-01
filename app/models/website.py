# SQLAlchemy Modell: Website
#
# Datum: 31.05.2026 | Version: 1.1 | Status: Aktiv gepflegt

from datetime import datetime

from sqlalchemy import Boolean, Column, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.models.base import Base, UTCDateTime


class Website(Base):
    __tablename__ = "websites"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    domain = Column(String, nullable=False)
    tracking_token = Column(String, unique=True, index=True, nullable=False)
    track_apex = Column(Boolean, nullable=False, default=True)
    track_subdomains = Column(Boolean, nullable=False, default=True)
    created_at = Column(UTCDateTime, nullable=False, default=datetime.utcnow)

    # Rückbeziehung zum User
    owner = relationship("User", back_populates="websites")
    
    # Beziehung zu Hits (Kaskadiertes Löschen aller Hits bei Löschen einer Webseite)
    hits = relationship("Hit", back_populates="website", cascade="all, delete-orphan")
