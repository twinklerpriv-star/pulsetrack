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


def prune_database() -> None:
    """
    Führt die automatische Aufbewahrungsbereinigung (Retention) gemäß der Tarife durch.
    Schont Speicherplatz und gewährt die DSGVO-Datenminimierung.
    """
    from datetime import datetime, timedelta, timezone

    from app.models.hit import Hit
    from app.models.user import User
    from app.models.website import Website
    
    db = SessionLocal()
    try:
        logger.info("Datenbank-Pruning-Prozess wird gestartet...")
        now = datetime.now(tz=timezone.utc).replace(tzinfo=None)
        
        # 1. Trial- und Starter-Accounts bereinigen (14 Tage Aufbewahrung)
        fourteen_days_ago = (now - timedelta(days=14)).isoformat()
        
        # Finde alle User mit 'trial' oder 'canceled' (oder Starter, falls wir ihn bereinigen wollen)
        starter_users = db.query(User.id).filter(
            (User.subscription_status == "trial") | 
            (User.subscription_status == "canceled")
        ).all()
        starter_user_ids = [u[0] for u in starter_users]
        
        if starter_user_ids:
            # Finde alle Webseiten dieser User
            starter_websites = db.query(Website.id).filter(Website.user_id.in_(starter_user_ids)).all()
            starter_website_ids = [w[0] for w in starter_websites]
            
            if starter_website_ids:
                # Lösche Hits dieser Webseiten, die älter als 14 Tage sind
                deleted_starter_hits = db.query(Hit).filter(
                    Hit.website_id.in_(starter_website_ids),
                    Hit.timestamp < fourteen_days_ago
                ).delete(synchronize_session=False)
                logger.info(f"{deleted_starter_hits} veraltete Hits von Trial/Canceled-Accounts gelöscht.")

        # 2. Business-Accounts bereinigen (365 Tage Aufbewahrung)
        one_year_ago = (now - timedelta(days=365)).isoformat()
        
        business_users = db.query(User.id).filter(User.subscription_status == "active").all()
        business_user_ids = [u[0] for u in business_users]
        
        if business_user_ids:
            business_websites = db.query(Website.id).filter(Website.user_id.in_(business_user_ids)).all()
            business_website_ids = [w[0] for w in business_websites]
            
            if business_website_ids:
                deleted_business_hits = db.query(Hit).filter(
                    Hit.website_id.in_(business_website_ids),
                    Hit.timestamp < one_year_ago
                ).delete(synchronize_session=False)
                logger.info(f"{deleted_business_hits} veraltete Hits von Business-Accounts gelöscht (älter als 1 Jahr).")
                
        db.commit()
        logger.info("Datenbank-Pruning-Prozess erfolgreich abgeschlossen.")
    except Exception as e:
        db.rollback()
        logger.error(f"Fehler beim Datenbank-Pruning: {e}")
    finally:
        db.close()
