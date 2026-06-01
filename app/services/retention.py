# Aufbewahrungsbereinigung (Retention Service)
#
# Datum: 31.05.2026 | Version: 1.1 | Status: Aktiv gepflegt

import logging
from datetime import datetime, timedelta, timezone

from app.models.hit import Hit
from app.models.user import User
from app.models.website import Website
from app.services.security import rotate_daily_hmac_key

logger = logging.getLogger("analytics_retention")

def prune_database() -> None:
    """
    Führt die automatische Aufbewahrungsbereinigung (Retention) gemäß der Tarife durch
    und rotiert taeglich die HMAC-Keys zur Gewaehrleistung der Forward Secrecy (C-2).
    Schont Speicherplatz und gewährt die DSGVO-Datenminimierung.
    """
    # Lokaler Import zur Vermeidung zirkulärer Importe (Circular Import Break)
    from app.database import SessionLocal
    
    db = SessionLocal()
    try:
        logger.info("Datenbank-Pruning-Prozess wird gestartet...")
        now = datetime.now(tz=timezone.utc).replace(tzinfo=None)
        
        # 1. Trial- und Starter-Accounts bereinigen (14 Tage Aufbewahrung)
        fourteen_days_ago = (now - timedelta(days=14)).isoformat()
        
        starter_users = db.query(User.id).filter(
            (User.subscription_status == "trial") | 
            (User.subscription_status == "canceled")
        ).all()
        starter_user_ids = [u[0] for u in starter_users]
        
        if starter_user_ids:
            starter_websites = db.query(Website.id).filter(Website.user_id.in_(starter_user_ids)).all()
            starter_website_ids = [w[0] for w in starter_websites]
            
            if starter_website_ids:
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
                
        # C-2: Rotationsaufruf für alte HMAC-Keys direkt integrieren zur taeglichen Ausfuehrung
        logger.info("HMAC-Key-Rotationsprozess wird gestartet...")
        rotate_daily_hmac_key(db)
        
        db.commit()
        logger.info("Datenbank-Pruning- und Key-Rotationsprozess erfolgreich abgeschlossen.")
    except Exception as e:
        db.rollback()
        logger.error(f"Fehler beim Datenbank-Pruning oder Key-Rotation: {e}")
    finally:
        db.close()
