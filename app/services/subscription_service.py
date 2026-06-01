# Subscription Business-Service
#
# Datum: 31.05.2026 | Version: 1.0

import logging

from sqlalchemy.orm import Session

from app.models.user import User
from app.models.website import Website
from app.services.security import invalidate_token_cache

logger = logging.getLogger("analytics_subscription")

def activate_user_subscription(db: Session, user: User, customer_id: str, subscription_id: str | None) -> None:
    """
    Aktiviert oder erneuert ein Benutzerabonnement sicher (Race-Condition-Schutz / B-3 Idempotenz).
    Beseitigt Code-Duplikate und invalidiert den Ingestion-Token-Cache.
    """
    if user.subscription_status == "active" and user.stripe_customer_id == customer_id and (subscription_id is None or user.stripe_subscription_id == subscription_id):
        # Bereits aktiv, nichts zu tun (B-3 Idempotenz)
        logger.info(f"Abonnement fuer User {user.id} bereits aktiv (Idempotent uebersprungen).")
        return

    user.stripe_customer_id = customer_id
    if subscription_id:
        user.stripe_subscription_id = subscription_id
    user.subscription_status = "active"
    db.commit()

    # Cache-Preflights für alle Tracking-Tokens des Users leeren, um Ingestion sofort freizuschalten
    websites = db.query(Website).filter(Website.user_id == user.id).all()
    for website in websites:
        invalidate_token_cache(website.tracking_token)

    logger.info(f"Abonnement erfolgreich aktiviert fuer User {user.id} (Stripe Customer {customer_id}).")

def cancel_user_subscription(db: Session, user: User) -> None:
    """Kündigt das Abonnement des Benutzers und sperrt den Ingestion-Cache sofort."""
    if user.subscription_status == "canceled":
        return

    user.subscription_status = "canceled"
    db.commit()

    # Cache sofort invalidieren, damit Ingestion geblockt wird
    websites = db.query(Website).filter(Website.user_id == user.id).all()
    for website in websites:
        invalidate_token_cache(website.tracking_token)

    logger.info(f"Abonnement gekuendigt fuer User {user.id}.")
