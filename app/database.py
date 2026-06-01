# Datenbank-Setup (SQLAlchemy ORM & WAL)
#
# Datum: 31.05.2026 | Version: 2.2 | Status: Aktiv gepflegt

import logging

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.config import get_database_path
from app.models.base import Base
from app.services.retention import prune_database

logger = logging.getLogger("analytics_database")

__all__ = ["engine", "SessionLocal", "Base", "get_db", "prune_database"]

# Bestimmung der Verbindungs-URL (SQLite standardmäßig, erweiterbar auf PostgreSQL)
DATABASE_URL = f"sqlite:///{get_database_path()}"

# Engine konfigurieren, check_same_thread=False ist für asynchronen Betrieb erforderlich
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    pool_size=1,
    max_overflow=0,
    pool_timeout=30,
    pool_pre_ping=True
)

# SQLite WAL-Modus, Foreign Key und Performance-Pragmas per Event-Listener erzwingen
@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA foreign_keys=ON;")
        cursor.execute("PRAGMA synchronous=NORMAL;")
        cursor.close()
        logger.info("SQLite Pragmas erfolgreich gesetzt (WAL=ON, FK=ON, SYNC=NORMAL).")
    except Exception as e:
        logger.error(f"Fehler beim Setzen der SQLite-Pragmas: {e}")
        cursor.close()

# Session-Factory erstellen
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# FastAPI Dependency zur Bereitstellung der DB-Session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
