# SQLAlchemy Modell: Hit (Analytics)
#
# Datum: 28.05.2026 | Version: 1.0 | Status: Aktiv gepflegt

from sqlalchemy import Column, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.database import Base


class Hit(Base):
    __tablename__ = "hits"

    id = Column(Integer, primary_key=True, index=True)
    website_id = Column(Integer, ForeignKey("websites.id", ondelete="CASCADE"), nullable=False)
    timestamp = Column(String, index=True, nullable=False)
    url = Column(String, nullable=False)
    referrer = Column(String, nullable=True)
    user_agent = Column(String, nullable=True)
    ip_hash = Column(String, nullable=False)
    browser = Column(String, nullable=True)
    os = Column(String, nullable=True)

    # Rückbeziehung zur Website
    website = relationship("Website", back_populates="hits")
