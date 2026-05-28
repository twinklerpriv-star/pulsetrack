# Datenbank-Setup (SQLAlchemy ORM & WAL)
#
# Datum: 28.05.2026 | Version: 2.0 | Status: Aktiv gepflegt

import logging

from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import get_database_path

logger = logging.getLogger("analytics_database")

# Bestimmung der Verbindungs-URL (SQLite standardmäßig, erweiterbar auf PostgreSQL)
DATABASE_URL = f"sqlite:///{get_database_path()}"

# Engine konfigurieren, check_same_thread=False ist für asynchronen Betrieb erforderlich
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False}
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

# Deklarative Basisklasse für ORM-Modelle
Base = declarative_base()

# FastAPI Dependency zur Bereitstellung der DB-Session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
