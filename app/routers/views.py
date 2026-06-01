# ==============================================================================
# API-ROUTER: UI-TEMPLATES & DASHBOARD-ANSICHTEN (SERVER-SIDE RENDERING)
# ==============================================================================
# Datum: 01.06.2026 | Version: 1.1 | Status: Aktiv gepflegt
#
# BETRIEBSWIRTSCHAFTLICHER ZWECK DIESER DATEI:
# Dieser Router ist für die visuelle Darstellung von PulseTrack zuständig.
# Er steuert, was der Besucher sieht:
# - Die verkaufsstarke Landingpage (für anonyme Besucher).
# - Das interaktive Dashboard (für eingeloggte B2B-Kunden).
# - Die Login- und Registrierungsmasken.
#
# AUSWIRKUNG FÜR DEN KUNDEN / GESCHÄFTSFÜHRER:
# - Blitzschnelle Ladezeiten: Da die Seiten direkt auf dem Server zusammengebaut
#   werden (Server-Side Rendering), fliegen die Seiten in Millisekunden auf den
#   Bildschirm des Kunden. Das steigert die Conversion-Rate und spart Ladezeit.
# - Keine dicken Client-Frameworks nötig: Funktioniert auf jedem Smartphone
#   und Tablet extrem flüssig und ressourcenschonend.
#
# INFORMATION FÜR DEN IT-TECHNIKER:
# - Verwendet Jinja2-Templates für schnelles HTML-Rendering in Python.
# - Nutzt synchrone Pfade (def statt async def), da blockierende DB-Abfragen
#   beim Laden des Dashboards (Abruf der registrierten Webseiten) stattfinden.
# ==============================================================================

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

# HTML-Templates-Verzeichnis konfigurieren (Jinja2)
templates_dir = os.path.join(os.path.dirname(__file__), "..", "templates")
templates = Jinja2Templates(directory=templates_dir)

@router.get("/", response_class=HTMLResponse)
def home_or_dashboard(request: Request, db: Session = Depends(get_db)):
    """
    KUNDENVERSTÄNDLICHE ERKLÄRUNG (Startseite oder Dashboard):
    Dieser Endpoint wird aufgerufen, wenn jemand die Hauptadresse (/) aufruft.
    Das System entscheidet:
    - Ist der Besucher nicht eingeloggt? -> Zeige die Premium-Landingpage mit dem ROI-Rechner.
    - Ist der Besucher eingeloggt? -> Lade seine registrierten Webseiten und zeige sein persönliches Dashboard.
    """
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    
    # Falls nicht eingeloggt -> Zeige verkaufsstarke Landingpage mit ROI-Rechner
    if not session_id or session_id not in sessions:
        return templates.TemplateResponse(
            name="landingpage.html",
            context={"request": request}
        )
        
    # Falls eingeloggt -> Hole User-Details und zeige Dashboard
    user_session = sessions[session_id]
    user_id = user_session["user_id"]
    
    user = db.query(User).filter(User.id == user_id).first()
    
    # Registrierte Webseiten des Kunden aus der DB abrufen
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
    """
    KUNDENVERSTÄNDLICHE ERKLÄRUNG:
    Zeigt die einheitliche und moderne Login- bzw. Registrierungsseite an,
    wo sich B2B-Kunden einloggen oder neu registrieren können.
    """
    return templates.TemplateResponse(
        name="auth.html",
        context={"request": request}
    )
