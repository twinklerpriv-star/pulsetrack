# API Router: Stripe Billing & Webhooks
#
# Datum: 28.05.2026 | Version: 1.0 | Status: Aktiv gepflegt

import logging

import stripe
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.user import User
from app.models.website import Website
from app.routers.auth import get_current_user_id
from app.services import stripe_service
from app.services.security import invalidate_token_cache

logger = logging.getLogger("analytics_billing")
router = APIRouter(tags=["Billing & Subscriptions"])


@router.post("/api/billing/checkout")
async def billing_checkout(
    request: Request,
    plan_type: str = Form(...),
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id)
):
    """
    Erstellt eine Stripe Checkout Session für den gewählten Tarif
    und leitet den Nutzer zum Stripe Hosted Checkout weiter.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    # Plan-Mapping zu Price IDs
    price_id = None
    if plan_type == "starter":
        price_id = settings.STRIPE_PRICE_STARTER
    elif plan_type == "business":
        price_id = settings.STRIPE_PRICE_BUSINESS
    elif plan_type == "enterprise":
        price_id = settings.STRIPE_PRICE_ENTERPRISE
    else:
        raise HTTPException(status_code=400, detail="Invalid plan type chosen.")

    success_url = f"{request.base_url}api/verify-checkout?session_id={{CHECKOUT_SESSION_ID}}"
    cancel_url = f"{request.base_url}?payment=cancel"

    try:
        session = stripe_service.create_checkout_session(
            user_id=user.id,
            email=user.email,
            price_id=price_id,
            success_url=success_url,
            cancel_url=cancel_url,
            stripe_customer_id=user.stripe_customer_id
        )
        return RedirectResponse(url=session.url, status_code=303)
    except Exception as e:
        logger.error(f"Fehler bei Erstellung der Stripe Checkout Session: {e}")
        raise HTTPException(status_code=500, detail="Stripe integration error. Please try again.")


@router.get("/api/billing/portal")
async def billing_portal(
    request: Request,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id)
):
    """
    Erstellt eine Stripe Customer Portal Session zur Abo-Selbstverwaltung
    und leitet den Kunden direkt dorthin weiter.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user or not user.stripe_customer_id:
        raise HTTPException(
            status_code=400, 
            detail="Kein Stripe-Kundenkonto gefunden. Bitte schließen Sie zuerst ein Abonnement ab."
        )

    return_url = f"{request.base_url}"

    try:
        session = stripe_service.create_customer_portal(
            stripe_customer_id=user.stripe_customer_id,
            return_url=return_url
        )
        return RedirectResponse(url=session.url, status_code=303)
    except Exception as e:
        logger.error(f"Fehler bei Erstellung der Stripe Portal Session: {e}")
        raise HTTPException(status_code=500, detail="Stripe Portal integration error.")


@router.get("/api/verify-checkout")
async def verify_checkout(
    session_id: str,
    db: Session = Depends(get_db)
):
    """
    Verifiziert den Checkout synchron bei Redirect von Stripe (Race-Condition-Schutz).
    Schaltet den Account sofort frei und leitet zum Dashboard zurück.
    """
    try:
        session_details = stripe_service.verify_checkout_session(session_id)
        user_id = session_details["user_id"]

        if not user_id:
            logger.error("Stripe Checkout-Metadaten enthalten keine user_id.")
            raise HTTPException(status_code=400, detail="Invalid session metadata.")

        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User associated with payment not found.")

        # Statusaktualisierung
        if session_details["payment_status"] == "paid" or session_details["status"] == "complete":
            user.stripe_customer_id = session_details["customer"]
            user.stripe_subscription_id = session_details["subscription"]
            user.subscription_status = "active"
            db.commit()

            # Cache-Preflights ungültig machen, um Ingestion sofort freizuschalten
            websites = db.query(Website).filter(Website.user_id == user.id).all()
            for website in websites:
                invalidate_token_cache(website.tracking_token)

            logger.info(f"Abonnement synchron aktiviert für User {user.id} (Stripe Customer {user.stripe_customer_id}).")
            return RedirectResponse(url="/?payment=success", status_code=303)
        
        logger.warning(f"Checkout-Verifizierung fehlgeschlagen: Status {session_details['status']}, Payment {session_details['payment_status']}")
        return RedirectResponse(url="/?payment=failed", status_code=303)
        
    except Exception as e:
        logger.error(f"Fehler bei der synchronen Checkout-Verifizierung: {e}")
        return RedirectResponse(url="/?payment=error", status_code=303)


@router.post("/api/webhooks/stripe")
async def stripe_webhook(
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Asynchroner Webhook-Handler für Stripe-Events.
    Sichert das System gegen Ausfälle und verarbeitet Updates im Hintergrund.
    """
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    if not sig_header:
        logger.error("Webhook aufgerufen ohne 'stripe-signature' Header.")
        raise HTTPException(status_code=400, detail="Missing signature header.")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
        )
    except ValueError:
        logger.error("Ungültiges Webhook-Payload.")
        raise HTTPException(status_code=400, detail="Invalid payload.")
    except stripe.error.SignatureVerificationError as e:
        logger.error(f"Webhook Signatur-Verifizierung fehlgeschlagen: {e}")
        raise HTTPException(status_code=400, detail="Invalid signature.")

    event_type = event["type"]
    data_object = event["data"]["object"]

    logger.info(f"Stripe Webhook empfangen: {event_type}")

    # 1. Erfolgreiche Zahlung oder fertiger Checkout
    if event_type in ("checkout.session.completed", "invoice.paid"):
        customer_id = data_object.get("customer")
        subscription_id = data_object.get("subscription")

        # user_id aus Checkout Metadata holen (falls checkout.session.completed)
        metadata = data_object.get("metadata") or {}
        user_id = metadata.get("user_id")

        user = None
        if user_id:
            user = db.query(User).filter(User.id == int(user_id)).first()
        
        if not user and customer_id:
            user = db.query(User).filter(User.stripe_customer_id == customer_id).first()

        if user:
            user.stripe_customer_id = customer_id
            if subscription_id:
                user.stripe_subscription_id = subscription_id
            user.subscription_status = "active"
            db.commit()

            # Cache für alle Tracking-Tokens des Users leeren
            websites = db.query(Website).filter(Website.user_id == user.id).all()
            for website in websites:
                invalidate_token_cache(website.tracking_token)

            logger.info(f"Webhook verarbeitet: Abo aktiviert/erneuert für User {user.id}")
        else:
            logger.warning(f"Webhook-Zahlung empfangen, aber kein User gefunden für Customer ID {customer_id}")

    # 2. Abonnement gekündigt / beendet
    elif event_type == "customer.subscription.deleted":
        subscription_id = data_object.get("id")
        customer_id = data_object.get("customer")

        user = db.query(User).filter(
            (User.stripe_subscription_id == subscription_id) | 
            (User.stripe_customer_id == customer_id)
        ).first()

        if user:
            user.subscription_status = "canceled"
            db.commit()

            # Cache sofort invalidieren, damit Ingestion geblockt wird
            websites = db.query(Website).filter(Website.user_id == user.id).all()
            for website in websites:
                invalidate_token_cache(website.tracking_token)

            logger.info(f"Webhook verarbeitet: Abo gekündigt für User {user.id}")
        else:
            logger.warning(f"Abonnement-Kündigung empfangen, aber kein passender User in DB für Sub {subscription_id}")

    return {"status": "success"}
