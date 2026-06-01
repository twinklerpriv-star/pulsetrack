# ==============================================================================
# API-ROUTER: STRIPE-ABRECHNUNG & ABONNEMENT-VERWALTUNG
# ==============================================================================
# Datum: 01.06.2026 | Version: 1.2 | Status: Aktiv gepflegt
#
# BETRIEBSWIRTSCHAFTLICHER ZWECK DIESER DATEI:
# Diese Datei regelt die gesamte Stripe-Zahlungsabwicklung für unsere B2B-Kunden.
# Sie stellt Endpoints bereit für:
# 1. Stripe Checkout: Weiterleitung des Kunden auf die sichere, von Stripe gehostete
#    Bezahlseite zum Abschluss eines Abos (Starter oder Business).
# 2. Customer Portal: Selbstverwaltung für Kunden, um Kreditkarten zu aktualisieren,
#    Rechnungen herunterzuladen oder Abos zu kündigen.
# 3. Checkout Verifikation: Sofortige Freischaltung des Accounts bei Rückkehr.
#
# AUSWIRKUNG FÜR DEN KUNDEN / GESCHÄFTSFÜHRER:
# - Maximale Flexibilität: Keine manuelle Rechnungsstellung nötig. Stripe wickelt
#   alles automatisiert ab.
# - Komfort: B2B-Kunden können ihre Rechnungen selbständig im Portal abrufen,
#   was Ihren Kundensupport drastisch entlastet.
# ==============================================================================

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
    KUNDENVERSTÄNDLICHE ERKLÄRUNG (Abonnement abschließen):
    Wählt der Kunde einen Tarif im Pricing-Bereich (z.B. "Business") und klickt
    auf "Jetzt abonnieren", wird dieser Endpoint aufgerufen.
    Er ermittelt die entsprechende Stripe-Price-ID und leitet den Kunden direkt
    zu Stripe Checkout weiter, wo Kreditkarten- und USt-IdNr.-Daten sicher
    eingegeben werden können.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Benutzer nicht gefunden.")

    # Plan-Mapping zu Price IDs aus den Systemeinstellungen
    price_id = None
    if plan_type == "starter":
        price_id = settings.STRIPE_PRICE_STARTER
    elif plan_type == "business":
        price_id = settings.STRIPE_PRICE_BUSINESS
    elif plan_type == "enterprise":
        price_id = settings.STRIPE_PRICE_ENTERPRISE
    else:
        raise HTTPException(status_code=400, detail="Ungültiger Tarif ausgewählt.")

    # Erfolgs- und Abbruch-URLs für die Rückkehr definieren
    success_url = f"{request.base_url}api/verify-checkout?session_id={{CHECKOUT_SESSION_ID}}"
    cancel_url = f"{request.base_url}?payment=cancel"

    try:
        # Erstellt die Checkout-Session über unseren Stripe-Service
        session = stripe_service.create_checkout_session(
            user_id=user.id,
            email=user.email,
            price_id=price_id,
            success_url=success_url,
            cancel_url=cancel_url,
            stripe_customer_id=user.stripe_customer_id
        )
        # HTTP 303 Redirect leitet den Browser des Kunden direkt zu Stripe weiter
        return RedirectResponse(url=session.url, status_code=303)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Fehler bei Erstellung der Stripe Checkout Session: {e}")
        raise HTTPException(status_code=500, detail="Fehler bei der Stripe-Integration. Bitte versuchen Sie es erneut.")


@router.get("/api/billing/portal")
async def billing_portal(
    request: Request,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id)
):
    """
    KUNDENVERSTÄNDLICHE ERKLÄRUNG (Kundenportal für Rechnungen & Kündigung):
    Wenn ein bereits zahlender Kunde in seinen Dashboard-Einstellungen auf
    "Abonnement verwalten" klickt, leitet diese Funktion ihn direkt auf die sichere
    Abrechnungsseite von Stripe weiter. Dort kann er Kreditkarten ändern,
    bisherige Rechnungen herunterladen oder sein Abo mit einem Klick kündigen.
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
        raise HTTPException(status_code=500, detail="Stripe Portal konnte nicht initialisiert werden.")


@router.get("/api/verify-checkout")
async def verify_checkout(
    session_id: str,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id)
):
    """
    KUNDENVERSTÄNDLICHE ERKLÄRUNG (Sofort-Freischaltung nach Kauf):
    Wenn der Kunde erfolgreich bezahlt hat und von Stripe auf Ihre Webseite
    zurückgeleitet wird, holt diese Funktion im Hintergrund sofort die Zahlungsbestätigung.
    Der Kunde wird unverzüglich freigeschaltet und sieht sofort sein Dashboard.
    Das verhindert Verzögerungen und Frust beim Kunden.
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
    KUNDENVERSTÄNDLICHE ERKLÄRUNG (Automatisches Abo-Update per Webhook):
    Stripe sendet vollautomatisch verschlüsselte Benachrichtigungen (Webhooks)
    an diese Funktion, sobald Ereignisse im Finanzbereich eintreten.
    Beispiele:
    - Die monatliche Abbuchung war erfolgreich -> Das Abo wird verlängert.
    - Die Kreditkarte ist abgelaufen oder die Zahlung scheitert -> Der Account wird gesperrt.
    - Der Kunde kündigt sein Abonnement -> Das System blockiert das Tracking am Ende der Laufzeit.
    
    Dieser asynchrone Handler sorgt dafür, dass Ihr System 24/7 absolut autark läuft
    und Sie sich um keinerlei manuelle Lizenzverwaltung kümmern müssen.
    """
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    if not sig_header:
        logger.error("Webhook aufgerufen ohne 'stripe-signature' Header.")
        raise HTTPException(status_code=400, detail="Sicherheits-Header fehlt.")

    try:
        # Die Webhook-Signatur verifizieren, um sicherzustellen, dass die Anfrage wirklich von Stripe kommt
        # und nicht von einem böswilligen Angreifer, der versucht, sich gratis freizuschalten.
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.STRIPE_WEBHOOK_SECRET.get_secret_value()
        )
    except ValueError:
        logger.error("Ungültiges Webhook-Payload.")
        raise HTTPException(status_code=400, detail="Ungueltige Anfrage.")
    except stripe.error.SignatureVerificationError as e:
        logger.error(f"Webhook Signatur-Verifizierung fehlgeschlagen: {e}")
        raise HTTPException(status_code=400, detail="Ungueltige Absender-Verifizierung.")

    event_type = event["type"]
    data_object = event["data"]["object"]

    logger.info(f"Stripe Webhook empfangen: {event_type}")

    # 1. Erfolgreiche Zahlung oder fertig abgeschlossener Checkout
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
            # Aktiviert das Abonnement in unserer DB über den Subscription Service
            subscription_service.activate_user_subscription(db, user, customer_id, subscription_id)
            logger.info(f"Webhook verarbeitet: Abo aktiviert/erneuert für User {user.id}")
        else:
            logger.warning(f"Webhook-Zahlung empfangen, aber kein User gefunden für Customer ID {customer_id}")

    # 2. Abonnement gekündigt / beendet (z.B. nach Ablauf des bezahlten Monats)
    elif event_type == "customer.subscription.deleted":
        subscription_id = data_object.get("id")
        customer_id = data_object.get("customer")

        user = db.query(User).filter(
            (User.stripe_subscription_id == subscription_id) | 
            (User.stripe_customer_id == customer_id)
        ).first()

        if user:
            # Sperrt den Ingestion-Cache des Benutzers sofort und blockiert das Tracking
            subscription_service.cancel_user_subscription(db, user)
            logger.info(f"Webhook verarbeitet: Abo gekündigt für User {user.id}")
        else:
            logger.warning(f"Abonnement-Kündigung empfangen, aber kein passender User in DB für Sub {subscription_id}")

    return {"status": "success"}
