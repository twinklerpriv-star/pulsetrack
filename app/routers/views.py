# API Router: UI Templates & Dashboard Views
#
# Datum: 31.05.2026 | Version: 1.0 | Status: Aktiv gepflegt

import logging
import os

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.models.website import Website
from app.routers.auth import SESSION_COOKIE_NAME, sessions

logger = logging.getLogger("analytics_views")
router = APIRouter(tags=["UI Views"])

# Templates-Verzeichnis konfigurieren
templates_dir = os.path.join(os.path.dirname(__file__), "..", "templates")
templates = Jinja2Templates(directory=templates_dir)

@router.get("/", response_class=HTMLResponse)
def home_or_dashboard(request: Request, db: Session = Depends(get_db)):
    """
    Liefert das interaktive Dashboard (wenn eingeloggt) oder
    die verkaufsstarke Premium-Landingpage (wenn nicht eingeloggt) (A-1, E-2).
    Faehrt synchron im Thread-Pool, da DB-Abfragen durchgefuehrt werden.
    """
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    
    # Falls nicht eingeloggt -> Zeige Premium-Landingpage mit ROI-Rechner
    if not session_id or session_id not in sessions:
        return templates.TemplateResponse(
            name="landingpage.html",
            context={"request": request}
        )
        
    # Falls eingeloggt -> Hole User-Details und zeige Dashboard
    user_session = sessions[session_id]
    user_id = user_session["user_id"]
    
    user = db.query(User).filter(User.id == user_id).first()
    
    # Hole registrierte Webseiten des Kunden
    websites = db.query(Website).filter(Website.user_id == user_id).all()
    
    return templates.TemplateResponse(
        name="dashboard.html",
        context={
            "request": request,
            "email": user_session["email"],
            "websites": websites,
            "user": user
        }
    )

@router.get("/login", response_class=HTMLResponse)
@router.get("/register", response_class=HTMLResponse)
def show_auth_pages(request: Request):
    """Zeigt die einheitliche Login- & Registrierungsseite (E-2)."""
    return templates.TemplateResponse(
        name="auth.html",
        context={"request": request}
    )
