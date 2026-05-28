# SQLAlchemy Modell: Website
#
# Datum: 28.05.2026 | Version: 1.0 | Status: Aktiv gepflegt

from sqlalchemy import Column, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.database import Base


class Website(Base):
    __tablename__ = "websites"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    domain = Column(String, nullable=False)
    tracking_token = Column(String, unique=True, index=True, nullable=False)
    track_apex = Column(Integer, nullable=False, default=1)
    track_subdomains = Column(Integer, nullable=False, default=1)
    created_at = Column(String, nullable=False)

    # Rückbeziehung zum User
    owner = relationship("User", back_populates="websites")
    
    # Beziehung zu Hits (Kaskadiertes Löschen aller Hits bei Löschen einer Webseite)
    hits = relationship("Hit", back_populates="website", cascade="all, delete-orphan")
