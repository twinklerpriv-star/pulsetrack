# Stripe Service: Checkout, Portal und Verifizierung
#
# Datum: 28.05.2026 | Version: 1.0 | Status: Aktiv gepflegt

import stripe

from app.config import settings

# Stripe API-Schlüssel global initialisieren
stripe.api_key = settings.STRIPE_SECRET_KEY


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
    Sichert DSGVO-Konformität und B2B-Steuererleichterungen.
    """
    stripe.api_key = settings.STRIPE_SECRET_KEY
    
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
        
    return stripe.checkout.Session.create(**params)


def create_customer_portal(stripe_customer_id: str, return_url: str) -> stripe.billing_portal.Session:
    """
    Generiert das Stripe Customer Portal für Kreditkarten-Updates, Rechnungs-Downloads und Kündigungen.
    """
    stripe.api_key = settings.STRIPE_SECRET_KEY
    return stripe.billing_portal.Session.create(
        customer=stripe_customer_id,
        return_url=return_url
    )


def verify_checkout_session(session_id: str) -> dict:
    """
    Fragt Stripe synchron ab, um Status und Customer ID sofort zu verifizieren (Race-Condition-Schutz).
    """
    stripe.api_key = settings.STRIPE_SECRET_KEY
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
