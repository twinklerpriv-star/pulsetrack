# SQLAlchemy Modell: Hit (Analytics)
#
# Datum: 31.05.2026 | Version: 1.1 | Status: Aktiv gepflegt

from datetime import datetime

from sqlalchemy import Column, ForeignKey, Index, Integer, String
from sqlalchemy.orm import relationship

from app.models.base import Base, UTCDateTime


class Hit(Base):
    __tablename__ = "hits"

    id = Column(Integer, primary_key=True, index=True)
    website_id = Column(Integer, ForeignKey("websites.id", ondelete="CASCADE"), nullable=False)
    timestamp = Column(UTCDateTime, index=True, nullable=False, default=datetime.utcnow)
    url = Column(String, nullable=False)
    referrer = Column(String, nullable=True)
    user_agent = Column(String, nullable=True)
    ip_hash = Column(String, nullable=False)
    browser = Column(String, nullable=True)
    os = Column(String, nullable=True)

    __table_args__ = (
        Index('ix_hits_website_timestamp', 'website_id', 'timestamp'),
    )

    # Rückbeziehung zur Website
    website = relationship("Website", back_populates="hits")
