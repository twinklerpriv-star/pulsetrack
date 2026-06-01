# FastAPI Hauptanwendung (Modular & Enterprise-Ready)
#
# Datum: 31.05.2026 | Version: 3.1 | Status: Aktiv gepflegt

import asyncio
import logging
import os
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.database import Base, SessionLocal, engine
from app.routers import (
    account_router,
    auth_router,
    billing_router,
    caddy_router,
    dashboard_router,
    ingest_router,
    views_router,
)
from app.services.queue_worker import batch_writer_worker, hit_queue, write_queue_to_db
from app.services.security import get_or_create_daily_hmac_key

logger = logging.getLogger("analytics_main")
logging.basicConfig(level=logging.INFO)

async def retention_worker():
    """Periodischer Task zur Ausführung der Datenbank-Bereinigung und HMAC-Key-Rotation (C-2, E-1)."""
    from app.services.retention import prune_database
    logger.info("Periodischer Datenbank-Retention-Worker gestartet.")
    while True:
        try:
            # prune_database ist synchron, also im Thread-Pool ausführen
            await asyncio.to_thread(prune_database)
        except Exception as e:
            logger.error(f"Fehler bei periodischer Datenbank-Retention: {e}")
        # Alle 12 Stunden (43200 Sekunden) ausführen
        await asyncio.sleep(43200)

# 1. Asynchroner Lifespan-Handler zur Steuerung von Queue, DB & Key-Rotation
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("PulseTrack SaaS Engine wird gestartet...")
    try:
        # DB-Tabellen automatisch erstellen, falls nicht vorhanden
        Base.metadata.create_all(bind=engine)
        logger.info("Datenbank-Schemata erfolgreich abgeglichen.")
        
        # E-8: Sichere Initialisierung des daily HMAC-Keys über einen Context-Manager
        with SessionLocal() as db:
            get_or_create_daily_hmac_key(db)
        
        # Startet den asynchronen Queue-Schreib-Hintergrundprozess
        app.state.queue_task = asyncio.create_task(batch_writer_worker())
        
        # Start daily HMAC key rotation job (Component 2)
        from app.jobs.rotate_key_job import schedule_daily_rotation
        app.state.rotation_task = asyncio.create_task(schedule_daily_rotation())
        if "pytest" not in sys.modules:
            app.state.retention_task = asyncio.create_task(retention_worker())
        
        logger.info("Start-Sequenz erfolgreich abgeschlossen.")
    except Exception as e:
        logger.critical(f"Kritischer Fehler beim Anwendungsstart: {e}")
        
    yield
    
    # Graceful Shutdown Sequence (SIGTERM Fänger) (F-6)
    logger.warning("PulseTrack SaaS Engine wird gestoppt...")
    try:
        # Den Retention-Task beenden
        if hasattr(app.state, "retention_task"):
            app.state.retention_task.cancel()
            
        # F-6: Queue-Worker stoppen und restliche Daten sauber flushen
        await write_queue_to_db()
        
        # Den Background-Task kontrolliert und zeitbegrenzt beenden lassen
        try:
            await asyncio.wait_for(app.state.queue_task, timeout=3.0)
        except asyncio.TimeoutError:
            app.state.queue_task.cancel()
            
        logger.info("Stop-Sequenz erfolgreich abgeschlossen.")
    except Exception as e:
        logger.error(f"Fehler bei Graceful Shutdown: {e}")

# 2. FastAPI Instanz erstellen
app = FastAPI(
    title="PulseTrack SaaS",
    description="SaaS Web-Analytics - Blitzschnell, cookie-frei und 100% DSGVO-konform.",
    version="3.1.0",
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

# 3. CORS & Dynamic-Origin-Middleware (D-1)
# Whitelist fuer credential-basierte B2B-API-Abfragen (CSRF-Schutz)
allowed_origins = [
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "https://pulsetrack.io",  # Beispiel-Produktionsdomain
]

import yaml
from pathlib import Path

# Load CORS whitelist from config.yaml if present
config_path = Path(__file__).parent.parent / "config.yaml"
if config_path.is_file():
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    allowed_origins = cfg.get("cors", {}).get("whitelist", [
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "https://pulsetrack.io",
    ])
else:
    # Fallback default whitelist
    allowed_origins = [
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "https://pulsetrack.io",
    ]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type", "X-Caddy-Secret"],
)

# 4. Modulare API-Routers inkludieren (E-2)
app.include_router(views_router)       # UI Templates (E-2)
app.include_router(auth_router)        # Authentifizierung
app.include_router(account_router)     # DSGVO Konto-Loeschung (C-5)
app.include_router(billing_router)     # Stripe Billing & Webhooks
app.include_router(ingest_router)      # Analytics Hit Ingestion
app.include_router(caddy_router)       # Caddy Dynamic SSL Proxy
app.include_router(dashboard_router)   # Dashboard Statistiken

@app.get("/api/health")
async def health_check():
    """
    System-Health Check zur Echtzeit-Überwachung.
    Liefert den aktuellen Füllstand der RAM-Ingestion-Queue.
    """
    queue_size = hit_queue.qsize()
    status = "healthy"
    if queue_size >= 9000:
        status = "warning"
    
    return {
        "status": status,
        "queue_size": queue_size,
        "max_queue_size": 10000
    }
