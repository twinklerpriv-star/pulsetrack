# ==============================================================================
# PULSETRACK ANALYTICS - AUTOMATISCHE DATEN- retention (RETENTION SERVICE)
# ==============================================================================
# Datum: 01.06.2026 | Version: 1.2 | Status: Aktiv gepflegt & DSGVO-konform
#
# BETRIEBSWIRTSCHAFTLICHER ZWECK DIESER DATEI:
# Diese Datei sorgt dafür, dass die gespeicherten Analytics-Klicks nicht ins
# Unendliche wachsen. Sie löscht vollautomatisch veraltete Daten und setzt damit
# das DSGVO-Prinzip der Datenminimierung konsequent um.
#
# REGELN DER DATENAUFBEWAHRUNG (TARIFFILTER):
# KUNDENVERSTÄNDLICHE ERKLÄRUNG:
# Je nach gewähltem Tarif werden Daten unterschiedlich lange aufbewahrt:
# 1. Trial- (Testphase) und gekündigte Konten:
#    Besucherdaten werden bereits nach 14 Tagen unwiderruflich gelöscht.
# 2. Bezahlte B2B-Kundenkonten (Aktiv):
#    Besucherdaten werden nach 365 Tagen (1 Jahr) gelöscht.
#
# Zusätzlich wird bei jedem Durchlauf dieser Funktion der gestrige geheime
# HMAC-Schlüssel gelöscht. Dadurch sind alte Besucher-IP-Hashes rückwirkend
# nie wieder entschlüsselbar (Forward Secrecy).
# ==============================================================================

import logging
from datetime import datetime, timedelta, timezone

from app.models.hit import Hit
from app.models.user import User
from app.models.website import Website
from app.services.security import rotate_daily_hmac_key

logger = logging.getLogger("analytics_retention")

def prune_database() -> None:
    """
    KUNDENVERSTÄNDLICHE ERKLÄRUNG (Datenbereinigungs-Job):
    Wird alle 12 Stunden vom System aufgerufen.
    Er ermittelt, welche Hits das jeweilige Verfallsdatum (14 Tage oder 365 Tage)
    überschritten haben, und löscht diese physisch aus der SQLite-Datenbank.
    Anschließend löscht er alle abgelaufenen IP-Schlüssel von gestern.
    """
    # Lokaler Import zur Vermeidung zirkulärer Importe (Circular Import Break)
    from app.database import SessionLocal
    
    db = SessionLocal()
    try:
        logger.info("Datenbank-Pruning-Prozess wird gestartet...")
        now = datetime.now(tz=timezone.utc).replace(tzinfo=None)
        
        # ======================================================================
        # 1. Trial- und Starter-Accounts bereinigen (14 Tage Aufbewahrung)
        # ======================================================================
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

        # ======================================================================
        # 2. Business-Accounts bereinigen (365 Tage Aufbewahrung)
        # ======================================================================
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
                
        # ======================================================================
        # 3. HMAC-Key-Rotation (Forward Secrecy für Besucherschutz)
        # ======================================================================
        # Löscht alle temporären IP-Hashing-Schlüssel, die älter als 24 Stunden sind.
        logger.info("HMAC-Key-Rotationsprozess wird gestartet...")
        rotate_daily_hmac_key(db)
        
        db.commit()
        logger.info("Datenbank-Pruning- und Key-Rotationsprozess erfolgreich abgeschlossen.")
    except Exception as e:
        db.rollback()
        logger.error(f"Fehler beim Datenbank-Pruning oder Key-Rotation: {e}")
    finally:
        db.close()
