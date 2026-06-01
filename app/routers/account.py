# ==============================================================================
# API-ROUTER: DSGVO-KONTO-LÖSCHUNG (RECHT AUF LÖSCHUNG - ART. 17 DSGVO)
# ==============================================================================
# Datum: 01.06.2026 | Version: 1.1 | Status: Aktiv gepflegt & DSGVO-konform
#
# BETRIEBSWIRTSCHAFTLICHER ZWECK DIESER DATEI:
# Dieser Router stellt die Schnittstelle bereit, über die B2B-Kunden ihr Konto
# und alle verknüpften Daten unwiderruflich löschen können.
#
# DSGVO-RELEVANZ (RECHT AUF VERGESSENWERDEN):
# Gemäß Art. 17 der DSGVO hat jeder Nutzer das Recht auf sofortige Löschung
# seiner personenbezogenen Daten. Diese Funktion stellt sicher, dass wir dieser
# gesetzlichen Pflicht in Sekundenschnelle und absolut vollständig nachkommen.
#
# AUSWIRKUNG FÜR DEN KUNDEN / GESCHÄFTSFÜHRER:
# - Vertrauen: Ihre Kunden können sich darauf verlassen, dass keine Datenleichen
#   auf Ihrem Server zurückbleiben.
# - Automatisierung: Die Löschung erfolgt vollautomatisch, ohne dass Sie manuell
#   in der Datenbank aufräumen müssen.
# ==============================================================================

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.routers.auth import SESSION_COOKIE_NAME, get_current_user_id, sessions

logger = logging.getLogger("analytics_account")
router = APIRouter(tags=["Account Management"])

@router.delete("/api/account")
def delete_account(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id)
):
    """
    KUNDENVERSTÄNDLICHE ERKLÄRUNG (Kontolöschung):
    Wenn ein Kunde sein Konto löscht, wird dieser Endpoint aufgerufen.
    Er löscht:
    1. Den Benutzerdatensatz (E-Mail, Passwort).
    2. Alle vom Kunden registrierten Webseiten.
    3. Alle jemals für diese Webseiten erfassten Klicks/Hits.
    4. Die digital signierten AVV-Verträge.
    Zusätzlich wird er sofort abgemeldet (Session-Cookie wird gelöscht).
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Benutzer nicht gefunden.")

    try:
        # Löschung auslösen: Die Kaskadierung (automatische Mitlöschung aller Webseiten, Hits etc.)
        # ist in den ORM-Modellen über cascade="all, delete-orphan" und FOREIGN KEYS definiert.
        db.delete(user)
        db.commit()

        # Aktive Logins/Sitzungen des Benutzers im Arbeitsspeicher ungültig machen
        sessions_to_delete = [sid for sid, s in list(sessions.items()) if s["user_id"] == user_id]
        for sid in sessions_to_delete:
            sessions.pop(sid, None)

        # Das Session-Cookie im Browser des Kunden löschen (sofortige Abmeldung)
        response.delete_cookie(SESSION_COOKIE_NAME)
        
        logger.info(f"Benutzerkonto {user_id} und alle assoziierten Daten erfolgreich gemäss Art. 17 DSGVO geloescht.")
        return {"status": "success", "message": "Ihr Benutzerkonto und alle verknuepften Daten wurden unwiderruflich geloescht."}
    except Exception as e:
        db.rollback()
        logger.error(f"Fehler bei DSGVO-Konto-Loeschung von User {user_id}: {e}")
        raise HTTPException(status_code=500, detail="Interner Serverfehler bei der Kontoloeschung.")
