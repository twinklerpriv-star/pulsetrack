# API Router: GDPR Account Deletion
#
# Datum: 31.05.2026 | Version: 1.0 | Status: Aktiv gepflegt

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
    Loescht das Benutzerkonto und alle verknuepften Daten (Websites, Hits, Signaturen)
    unwiderruflich gemaess Art. 17 DSGVO (Recht auf Loeschung) via Cascade-Delete.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Benutzer nicht gefunden.")

    try:
        # Loeschung ausloesen (Kaskadierung ist in den Modellen als cascade="all, delete-orphan" definiert)
        db.delete(user)
        db.commit()

        # Aktive Sessions des Benutzers ungueltig machen
        sessions_to_delete = [sid for sid, s in list(sessions.items()) if s["user_id"] == user_id]
        for sid in sessions_to_delete:
            sessions.pop(sid, None)

        # Session Cookie loeschen
        response.delete_cookie(SESSION_COOKIE_NAME)
        logger.info(f"Benutzerkonto {user_id} und alle assoziierten Daten erfolgreich gemaess Art. 17 DSGVO geloescht.")
        return {"status": "success", "message": "Ihr Benutzerkonto und alle verknuepften Daten wurden unwiderruflich geloescht."}
    except Exception as e:
        db.rollback()
        logger.error(f"Fehler bei DSGVO-Konto-Loeschung von User {user_id}: {e}")
        raise HTTPException(status_code=500, detail="Interner Serverfehler bei der Kontoloeschung.")
