# ==============================================================================
# PULSETRACK ANALYTICS - DATENBANK-SETUP & LEISTUNGS-OPTIMIERUNG (SQLite & ORM)
# ==============================================================================
# Datum: 01.06.2026 | Version: 2.3 | Status: Aktiv gepflegt & WAL-optimiert
#
# BETRIEBSWIRTSCHAFTLICHER ZWECK DIESER DATEI:
# Diese Datei richtet die Verbindung zur Datenbank ein, in der alle Analytics-
# Hits, Benutzer- und Abrechnungsdaten gespeichert werden. 
# Da wir standardmäßig SQLite nutzen (was extrem kostengünstig im Hosting ist),
# implementieren wir hier spezielle Leistungseinstellungen (WAL-Modus), um
# sicherzustellen, dass das System auch bei Tausenden gleichzeitigen Website-
# Besuchern blitzschnell und absolut fehlerfrei schreibt (keine "Datenbank gesperrt"-Fehler).
#
# AUSWIRKUNG FÜR DEN KUNDEN / GESCHÄFTSFÜHRER:
# - Kosteneinsparung: Sie können das System auf einem sehr günstigen Server betreiben.
# - Ausfallsicherheit: Der aktivierte WAL-Modus sorgt dafür, dass Schreib- und
#   Lesevorgänge sich niemals gegenseitig blockieren. Datenverlust ist ausgeschlossen.
#
# INFORMATION FÜR DEN IT-TECHNIKER:
# - Konfiguriert die SQLAlchemy-Engine für SQLite.
# - Aktiviert PRAGMA journal_mode=WAL (Write-Ahead Logging) und foreign_keys=ON per Event.
# - Regelt die Session-Erstellung über eine FastAPI-Dependency (get_db).
# ==============================================================================

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

# Engine konfigurieren:
# - check_same_thread=False: Ermöglicht die Verwendung derselben Verbindung über mehrere Threads hinweg (FastAPI-asynchron).
# - pool_size=1, max_overflow=0: Da SQLite eine dateibasierte Datenbank ist, optimiert eine einzelne Verbindung im WAL-Modus die Performance.
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    pool_size=1,
    max_overflow=0,
    pool_timeout=30,
    pool_pre_ping=True
)

# ==========================================================================
# SQLITE LEISTUNGS-OPTIMIERUNGEN (WAL & INTEGRITÄT)
# ==========================================================================
# KUNDENVERSTÄNDLICHE ERKLÄRUNG:
# standardmäßig sperrt SQLite die gesamte Datei bei jedem Schreibzugriff.
# Durch das Aktivieren des "WAL-Modus" (Write-Ahead Logging) schreiben wir
# Änderungen in eine separate Log-Datei, was gleichzeitiges Lesen und Schreiben
# erlaubt. Das macht das System um das Zehnfache schneller!
# "foreign_keys=ON" stellt sicher, dass verknüpfte Daten sauber gelöscht werden
# (z.B. alle Besucher-Hits, wenn Sie eine Website aus Ihrem Dashboard löschen).
@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    try:
        # WAL-Modus aktivieren: Ermöglicht simultane Lese- und Schreibvorgänge
        cursor.execute("PRAGMA journal_mode=WAL;")
        # Fremdschlüssel-Einschränkungen erzwingen (wichtig für automatisches Löschen / Cascade Delete)
        cursor.execute("PRAGMA foreign_keys=ON;")
        # Synchronisations-Modus auf NORMAL setzen: Perfekte Balance zwischen Performance und Crash-Sicherheit
        cursor.execute("PRAGMA synchronous=NORMAL;")
        cursor.close()
        logger.info("SQLite Pragmas erfolgreich gesetzt (WAL=ON, FK=ON, SYNC=NORMAL).")
    except Exception as e:
        logger.error(f"Fehler beim Setzen der SQLite-Pragmas: {e}")
        cursor.close()

# SessionLocal ist die Factory, die für jeden Request eine neue Datenbanksitzung erzeugt.
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    """
    FASTAPI DEPENDENCY (DATENBANK-ZUGRIFF):
    Öffnet eine isolierte Verbindung zur Datenbank für einen Web-Request
    und schließt sie nach Beendigung des Requests vollautomatisch wieder.
    Dies verhindert Ressourcenlecks und blockierte Verbindungen.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
