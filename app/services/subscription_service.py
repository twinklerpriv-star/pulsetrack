# ==============================================================================
# PULSETRACK ANALYTICS - MITGLIEDSCHAFTS- & ABONNEMENTS-VERWALTUNG (SUBSCRIPTIONS)
# ==============================================================================
# Datum: 01.06.2026 | Version: 1.1 | Status: Aktiv gepflegt
#
# BETRIEBSWIRTSCHAFTLICHER ZWECK DIESER DATEI:
# Diese Komponente übersetzt Zahlungserfolge von Stripe in tatsächliche Zugriffsrechte.
# Sie steuert die Aktivierung, Verlängerung und Sperrung von Kunden-Accounts und sorgt
# dafür, dass Systemressourcen und Analytics-Kapazitäten nur von zahlenden Kunden
# genutzt werden können.
#
# WICHTIGE FUNKTIONEN FÜR DEN KUNDEN / GESCHÄFTSFÜHRER:
# 1. Echtzeit-Freischaltung (Instant Activation):
#    Sobald die Zahlung durchgeht, wird der Tracking-Schutz für die Webseiten des Kunden
#    sofort aufgehoben. Seine Webseitenbesucher werden ab der ersten Sekunde erfasst.
# 2. Sofortige Sperrung bei Kündigung / Zahlungsausfall (Instant Invalidation):
#    Läuft ein Abonnement ab oder wird es gekündigt, sperrt das System den Datenempfang
#    für alle registrierten Webseiten dieses Nutzers in Echtzeit. Es werden keine unbezahlten
#    Statistiken mehr erfasst.
# ==============================================================================

import logging

from sqlalchemy.orm import Session

from app.models.user import User
from app.models.website import Website
from app.services.security import invalidate_token_cache

# Logger initialisieren, um Freischaltungen und Sperrungen zu dokumentieren
logger = logging.getLogger("analytics_subscription")

def activate_user_subscription(db: Session, user: User, customer_id: str, subscription_id: str | None) -> None:
    """
    KUNDENVERSTÄNDLICHE ERKLÄRUNG (Abonnement freischalten):
    Aktiviert das Abonnement eines Benutzers in der Datenbank und schaltet dessen
    Websites sofort für das Tracking frei.
    
    TECHNISCHE DETAILS:
    - Verhindert Mehrfachverarbeitung (Idempotenz / B-3).
    - Löscht den Ingestion-Cache für alle Webseiten-Tokens dieses Benutzers, damit
      der Daten-Empfangskanal (Ingest-API) sofort merkt, dass der Account aktiv ist.
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
    # Dadurch fragt der nächste Besucher-Hit die DB ab und findet den aktiven Abo-Status.
    websites = db.query(Website).filter(Website.user_id == user.id).all()
    for website in websites:
        invalidate_token_cache(website.tracking_token)

    logger.info(f"Abonnement erfolgreich aktiviert fuer User {user.id} (Stripe Customer {customer_id}).")

def cancel_user_subscription(db: Session, user: User) -> None:
    """
    KUNDENVERSTÄNDLICHE ERKLÄRUNG (Abonnement sperren):
    Setzt den Abonnement-Status des Benutzers auf "gekündigt" (canceled) und sperrt
    sofort alle seine Tracking-Tokens, damit keine weiteren Besucherdaten mehr erfasst werden.
    
    TECHNISCHE DETAILS:
    - Invalidiert die Tokens im schnellen Arbeitsspeicher (Cache) in Echtzeit.
    """
    if user.subscription_status == "canceled":
        return

    user.subscription_status = "canceled"
    db.commit()

    # Cache sofort invalidieren, damit Ingestion geblockt wird
    # Zukünftige Ingestion-Anfragen für diese Websites werden sofort mit 403 Forbidden abgewiesen.
    websites = db.query(Website).filter(Website.user_id == user.id).all()
    for website in websites:
        invalidate_token_cache(website.tracking_token)

    logger.info(f"Abonnement gekuendigt fuer User {user.id}.")
