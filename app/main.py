# FastAPI Hauptanwendung
#
# Datum: 20.05.2026 | Version: 1.1 | Status: In Entwicklung
#
# Dieses Modul stellt die REST-API zur Annahme von Tracking-Daten bereit
# und steuert das Web-Dashboard unseres Analytics-Tools.


import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from app import database

# Logger-Setup
logger = logging.getLogger("analytics_main")
logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Steuert den Lebenszyklus der Anwendung (startup / shutdown)."""
    try:
        database.init_db()
        logger.info("Datenbank erfolgreich beim Start vorbereitet.")
    except Exception as e:
        logger.critical(f"Kritischer Fehler beim Anwendungsstart: {e}")
    yield  # Anwendung läuft
    # Shutdown-Logik hier einfügen falls nötig


app = FastAPI(
    title="PulseTrack",
    description="Minimalistisches, datenschutzkonformes Web-Analytics-System.",
    version="0.1.1",
    lifespan=lifespan,
)

# --- CORS-Konfiguration ---
# Notwendig damit der JS-Tracker auf fremden Domains Daten an unsere API senden darf.
# Der Browser blockiert Cross-Origin-Requests standardmäßig (Same-Origin-Policy).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],     # In Produktion auf eigene Domain einschränken
    allow_methods=["POST"],  # Nur POST auf /api/hit erlaubt
    allow_headers=["Content-Type"],
)


# Template-Pfad konfigurieren
templates_dir = os.path.join(os.path.dirname(__file__), "templates")
templates = Jinja2Templates(directory=templates_dir)

# Datenmodell für eingehende Hits
class HitPayload(BaseModel):
    url: str
    referrer: str | None = None

@app.post("/api/hit", status_code=202)
async def capture_hit(payload: HitPayload, request: Request):
    """
    Nimmt Tracking-Daten vom Client-Browser entgegen.
    Ermittelt die IP-Adresse (inkl. Support für Reverse-Proxies wie Nginx/Cloudflare)
    und speichert den Aufruf anonymisiert in der Datenbank.
    """
    user_agent = request.headers.get("user-agent")
    
    # Ermittlung der echten Client-IP (unterstützt Proxies)
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        client_ip = forwarded_for.split(",")[0].strip()
    else:
        client_ip = request.client.host if request.client else "127.0.0.1"
        
    try:
        database.save_hit(
            url=payload.url,
            referrer=payload.referrer,
            user_agent=user_agent,
            client_ip=client_ip
        )
        return {"status": "accepted"}
    except Exception as e:
        logger.error(f"Fehler bei der Hit-Erfassung: {e}")
        raise HTTPException(status_code=500, detail="Internal server error during event logging.") from e


@app.get("/tracker.js")
async def get_tracker():
    """Liefert das leichtgewichtige Tracking-Skript für den Client aus."""
    tracker_path = os.path.join(os.path.dirname(__file__), "tracker.js")
    if os.path.exists(tracker_path):
        return FileResponse(tracker_path, media_type="application/javascript")
    raise HTTPException(status_code=404, detail="Tracker script not found.")

@app.get("/", response_class=HTMLResponse)
async def get_dashboard(request: Request):
    """Serviert das interaktive, responsive Analyse-Dashboard (Jinja2 SSR)."""
    try:
        summary = database.get_analytics_summary()
        return templates.TemplateResponse(
            request=request,
            name="dashboard.html",
            context={"summary": summary}
        )

    except Exception as e:
        logger.error(f"Fehler beim Rendern des Dashboards: {e}")
        raise HTTPException(status_code=500, detail="Error generating dashboard view.") from e

