# Stripe Service: Checkout, Portal und Verifizierung
#
# Datum: 31.05.2026 | Version: 1.1 | Status: Aktiv gepflegt

import logging
import time

import stripe
from fastapi import HTTPException
from stripe import AuthenticationError, CardError, InvalidRequestError, RateLimitError, StripeError

from app.config import settings

logger = logging.getLogger("analytics_stripe")

# Stripe API-Schlüssel einmalig initialisieren (B-5)
stripe.api_key = settings.STRIPE_SECRET_KEY.get_secret_value()

def create_checkout_session(
    user_id: int, 
    email: str, 
    price_id: str, 
    success_url: str, 
    cancel_url: str, 
    stripe_customer_id: str | None = None
) -> stripe.checkout.Session:
    """
    Erzeugt eine Stripe Checkout-Session mit B2B USt-IdNr.-Abfrage und steuerlicher Registrierung.
    Nutzt Idempotency Keys gegen Doppel-Abbuchungen (B-2).
    """
    params = {
        "payment_method_types": ["card"],
        "line_items": [
            {
                "price": price_id,
                "quantity": 1,
            }
        ],
        "mode": "subscription",
        "success_url": success_url,
        "cancel_url": cancel_url,
        "metadata": {
            "user_id": str(user_id)
        },
        "tax_id_collection": {
            "enabled": True,  # Sammelt automatisch USt-IdNr. für EU Reverse-Charge
        },
        "automatic_tax": {
            "enabled": True,  # Automatische Steuerberechnung
        }
    }
    
    if stripe_customer_id:
        params["customer"] = stripe_customer_id
    else:
        params["customer_email"] = email
        
    # Idempotency Key generieren basierend auf User-ID, Plan-Price-ID und 60s Zeitfenster (B-2)
    idempotency_key = f"checkout_{user_id}_{price_id}_{int(time.time() // 60)}"
    
    try:
        return stripe.checkout.Session.create(**params, idempotency_key=idempotency_key)
    except CardError as e:
        logger.error(f"Kreditkartenfehler bei Checkout-Session-Erstellung fuer User {user_id}: {e.user_message}")
        raise HTTPException(status_code=400, detail=f"Zahlungsfehler: {e.user_message}")
    except RateLimitError as e:
        logger.error(f"Stripe Rate Limit Fehler fuer User {user_id}: {e}")
        raise HTTPException(status_code=429, detail="Stripe API Rate Limit überschritten. Bitte versuchen Sie es gleich erneut.")
    except InvalidRequestError as e:
        logger.error(f"Ungueltige Stripe Anfrage fuer User {user_id}: {e}")
        raise HTTPException(status_code=400, detail=f"Ungueltige Zahlungsanforderung: {e.user_message or str(e)}")
    except AuthenticationError as e:
        logger.critical(f"Stripe Authentifizierungsfehler! Bitte API-Keys prüfen: {e}")
        raise HTTPException(status_code=500, detail="Zahlungsdienstleister-Authentifizierungsfehler. Bitte wenden Sie sich an den Support.")
    except StripeError as e:
        logger.error(f"Allgemeiner Stripe-Fehler bei Checkout-Session-Erstellung fuer User {user_id}: {e}")
        raise HTTPException(status_code=502, detail="Fehler bei der Kommunikation mit dem Zahlungsdienstleister.")

def create_customer_portal(stripe_customer_id: str, return_url: str) -> stripe.billing_portal.Session:
    """
    Generiert das Stripe Customer Portal für Kreditkarten-Updates, Rechnungs-Downloads und Kündigungen.
    """
    try:
        return stripe.billing_portal.Session.create(
            customer=stripe_customer_id,
            return_url=return_url
        )
    except StripeError as e:
        logger.error(f"Fehler bei Customer-Portal Erstellung fuer Customer {stripe_customer_id}: {e}")
        raise HTTPException(status_code=502, detail="Kundenportal konnte nicht geoeffnet werden.")

def verify_checkout_session(session_id: str) -> dict:
    """
    Fragt Stripe synchron ab, um Status und Customer ID sofort zu verifizieren (Race-Condition-Schutz).
    """
    try:
        session = stripe.checkout.Session.retrieve(session_id)
        
        user_id = None
        if session.metadata and "user_id" in session.metadata:
            user_id = int(session.metadata["user_id"])
            
        return {
            "id": session.id,
            "status": session.status,
            "payment_status": session.payment_status,
            "customer": session.customer,
            "subscription": session.subscription,
            "user_id": user_id
        }
    except StripeError as e:
        logger.error(f"Fehler bei der Verifizierung der Checkout-Session {session_id}: {e}")
        raise HTTPException(status_code=400, detail="Checkout-Sitzung konnte nicht bei Stripe verifiziert werden.")
