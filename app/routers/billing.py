# API Router: Stripe Billing & Webhooks
#
# Datum: 31.05.2026 | Version: 1.1 | Status: Aktiv gepflegt

import logging

import stripe
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.user import User
from app.routers.auth import get_current_user_id
from app.services import stripe_service, subscription_service

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
    except HTTPException:
        raise
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
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Fehler bei Erstellung der Stripe Portal Session: {e}")
        raise HTTPException(status_code=500, detail="Stripe Portal integration error.")


@router.get("/api/verify-checkout")
async def verify_checkout(
    session_id: str,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id)  # B-1: Authentifizierung hinzugefügt
):
    """
    Verifiziert den Checkout synchron bei Redirect von Stripe (Race-Condition-Schutz).
    Schaltet den Account sofort frei und leitet zum Dashboard zurück.
    """
    try:
        session_details = stripe_service.verify_checkout_session(session_id)
        user_id = session_details["user_id"]

        # B-1: Validierung der user_id gegen den aktuell eingegloggten Benutzer
        if not user_id or user_id != current_user_id:
            logger.error(f"Stripe Checkout-Metadaten User ID {user_id} stimmt nicht mit aktuellem User {current_user_id} ueberein.")
            raise HTTPException(status_code=403, detail="Unberechtigter Zugriff: Sitzung stimmt nicht mit Ihrem Benutzerkonto ueberein.")

        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User associated with payment not found.")

        # Statusaktualisierung über den zentralen Subscription-Service (E-4, B-3)
        if session_details["payment_status"] == "paid" or session_details["status"] == "complete":
            subscription_service.activate_user_subscription(
                db, 
                user, 
                session_details["customer"], 
                session_details["subscription"]
            )
            return RedirectResponse(url="/?payment=success", status_code=303)
        
        logger.warning(f"Checkout-Verifizierung fehlgeschlagen: Status {session_details['status']}, Payment {session_details['payment_status']}")
        return RedirectResponse(url="/?payment=failed", status_code=303)
        
    except HTTPException:
        raise  # B-4: Keine echten HTTPExceptions verschlucken
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
            payload, sig_header, settings.STRIPE_WEBHOOK_SECRET.get_secret_value()
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
        metadata = data_object.get("metadata") or {}
        user_id = metadata.get("user_id")

        user = None
        if user_id:
            user = db.query(User).filter(User.id == int(user_id)).first()
        
        if not user and customer_id:
            user = db.query(User).filter(User.stripe_customer_id == customer_id).first()

        if user and customer_id:
            subscription_service.activate_user_subscription(db, user, customer_id, subscription_id)
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
            subscription_service.cancel_user_subscription(db, user)
            logger.info(f"Webhook verarbeitet: Abo gekündigt für User {user.id}")
        else:
            logger.warning(f"Abonnement-Kündigung empfangen, aber kein passender User in DB für Sub {subscription_id}")

    return {"status": "success"}
