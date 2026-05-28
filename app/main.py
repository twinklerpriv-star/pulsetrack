# FastAPI Hauptanwendung (Modular & Enterprise-Ready)
#
# Datum: 28.05.2026 | Version: 3.0 | Status: Aktiv gepflegt

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import Base, engine, get_db
from app.models.website import Website
from app.routers import auth_router, caddy_router, dashboard_router, ingest_router
from app.routers.auth import SESSION_COOKIE_NAME, sessions
from app.services.queue_worker import batch_writer_worker, write_queue_to_db
from app.services.security import get_or_create_daily_hmac_key

logger = logging.getLogger("analytics_main")
logging.basicConfig(level=logging.INFO)

# 1. Asynchroner Lifespan-Handler zur Steuerung von Queue, DB & Key-Rotation
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("PulseTrack SaaS Engine wird gestartet...")
    try:
        # DB-Tabellen automatisch erstellen, falls nicht vorhanden
        Base.metadata.create_all(bind=engine)
        logger.info("Datenbank-Schemata erfolgreich abgeglichen.")
        
        # Initiiere den HMAC-Key für heute
        db = next(get_db())
        get_or_create_daily_hmac_key(db)
        db.close()
        
        # Startet den asynchronen Queue-Schreib-Hintergrundprozess
        app.state.queue_task = asyncio.create_task(batch_writer_worker())
        
        logger.info("Start-Sequenz erfolgreich abgeschlossen.")
    except Exception as e:
        logger.critical(f"Kritischer Fehler beim Anwendungsstart: {e}")
        
    yield
    
    # Graceful Shutdown Sequence (SIGTERM Fänger)
    logger.warning("PulseTrack SaaS Engine wird gestoppt...")
    try:
        # Queue-Task abbrechen und restliche Daten flushen
        app.state.queue_task.cancel()
        await write_queue_to_db()
        logger.info("Stop-Sequenz erfolgreich abgeschlossen.")
    except Exception as e:
        logger.error(f"Fehler bei Graceful Shutdown: {e}")

# 2. FastAPI Instanz erstellen
app = FastAPI(
    title="PulseTrack SaaS",
    description="SaaS Web-Analytics - Blitzschnell, cookie-frei und 100% DSGVO-konform.",
    version="3.0.0",
    lifespan=lifespan
)

# Static-Dateien Mounten (styles.css, tracker.js etc.)
app.mount("/static", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static")), name="static")

# Statisches tracker.js bereitstellen
@app.get("/tracker.js")
async def get_tracker():
    tracker_path = os.path.join(os.path.dirname(__file__), "static", "tracker.js")
    if os.path.exists(tracker_path):
        return FileResponse(tracker_path, media_type="application/javascript")
    raise HTTPException(status_code=404, detail="Tracker script not found.")

# Templates-Verzeichnis konfigurieren
templates_dir = os.path.join(os.path.dirname(__file__), "templates")
templates = Jinja2Templates(directory=templates_dir)

# 3. CORS & Dynamic-Origin-Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Dynamic validation is done at router-level in Ingestion-API
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

# 4. Modulare API-Routers inkludieren
app.include_router(auth_router)
app.include_router(ingest_router)
app.include_router(caddy_router)
app.include_router(dashboard_router)

# 5. UI Views (GET Endpunkte für Landingpage & Dashboard)
@app.get("/", response_class=HTMLResponse)
async def home_or_dashboard(request: Request, db: Session = Depends(get_db)):
    """
    Liefert das interaktive Dashboard (wenn eingeloggt) oder
    die verkaufsstarke Premium-Landingpage (wenn nicht eingeloggt).
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
    
    # Hole registrierte Webseiten des Kunden
    websites = db.query(Website).filter(Website.user_id == user_id).all()
    
    return templates.TemplateResponse(
        name="dashboard.html",
        context={
            "request": request,
            "email": user_session["email"],
            "websites": websites
        }
    )

@app.get("/login", response_class=HTMLResponse)
@app.get("/register", response_class=HTMLResponse)
async def show_auth_pages(request: Request):
    """Zeigt die einheitliche Login- & Registrierungsseite."""
    return templates.TemplateResponse(
        name="auth.html",
        context={"request": request}
    )
