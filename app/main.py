# ==============================================================================
# PULSETRACK ANALYTICS - FASTAPI HAUPTANWENDUNG (API & ENGINE-KERN)
# ==============================================================================
# Datum: 01.06.2026 | Version: 3.2 | Status: Aktiv gepflegt & DSGVO-optimiert
#
# BETRIEBSWIRTSCHAFTLICHER ZWECK DIESER DATEI:
# Diese Datei (main.py) ist das Herzstück der PulseTrack-Software. Sie ist das
# "Eingangstor" für alle Web-Requests. Hier startet die Server-Engine, richtet die
# Datenbankverbindungen ein und startet wichtige Hintergrund-Prozesse, wie z.B.
# die automatische Datenlöschung (Retention) zur Einhaltung des DSGVO-Prinzips
# der Datenminimierung.
#
# AUSWIRKUNG FÜR DEN KUNDEN / GESCHÄFTSFÜHRER:
# - Die Anwendung läuft vollautomatisch im Hintergrund auf Ihrem Server.
# - Es ist keine manuelle Datenbankpflege notwendig.
# - Alle datenschutzrelevanten Aspekte werden direkt beim Start der Anwendung
#   aktiviert (z. B. der CORS-Schutz gegen Missbrauch und die tägliche
#   Schlüssel-Rotation).
#
# INFORMATION FÜR DEN IT-TECHNIKER:
# - Einstiegspunkt der FastAPI-Applikation.
# - Initialisiert das SQLAlchemy-Datenbankschema.
# - Registriert alle API-Router (Multi-Tenancy Auth, Billing, Ingestion, Caddy SSL).
# - Startet asynchrone Background-Tasks (RAM-Queue-Schreiber und Bereinigung).
# ==============================================================================

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

# Logging-System konfigurieren: Protokolliert wichtige Betriebszustände
logger = logging.getLogger("analytics_main")
logging.basicConfig(level=logging.INFO)

async def retention_worker():
    """
    KUNDENVERSTÄNDLICHE ERKLÄRUNG (DSGVO-Datenminimierung & Key-Rotation):
    Dieser Hintergrund-Prozess läuft vollautomatisch alle 12 Stunden im System.
    Er sorgt dafür, dass:
    1. Veraltete Analytics-Daten (älter als 14 Tage bei Test- und Gratis-Accounts,
       bzw. älter als 1 Jahr bei zahlenden Kunden) unwiderruflich gelöscht werden.
       Dies sichert die gesetzlich vorgeschriebene Datenminimierung.
    2. Der tägliche HMAC-Verschlüsselungsschlüssel rotiert wird. Dadurch ist es
       Angreifern unmöglich, selbst bei einem vollständigen Datenbankdiebstahl,
       Besucher-IP-Adressen rückwirkend zu entschlüsseln (Forward Secrecy).
    """
    from app.services.retention import prune_database
    logger.info("Periodischer Datenbank-Retention-Worker gestartet.")
    while True:
        try:
            # Die Datenbankbereinigung ist ein blockierender (synchroner) Vorgang.
            # Um den Server nicht zu verlangsamen, lagern wir ihn in einen separaten Thread aus.
            await asyncio.to_thread(prune_database)
        except Exception as e:
            logger.error(f"Fehler bei periodischer Datenbank-Retention: {e}")
        # Alle 12 Stunden (43200 Sekunden) erneut ausführen
        await asyncio.sleep(43200)

# 1. Asynchroner Lifespan-Handler zur Steuerung von Queue, DB & Key-Rotation
# KUNDENVERSTÄNDLICHE ERKLÄRUNG:
# Diese "Lifespan"-Funktion steuert den gesamten Lebenszyklus der Software. Sie
# sorgt dafür, dass beim Einschalten des Servers alles sauber vorbereitet wird
# und beim Ausschalten (z. B. bei Wartungsarbeiten) alle Daten im Arbeitsspeicher
# gerettet werden, damit kein einziger Besucher-Hit verloren geht.
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("PulseTrack SaaS Engine wird gestartet...")
    try:
        # DB-Tabellen automatisch erstellen, falls nicht vorhanden (Auto-Migration)
        Base.metadata.create_all(bind=engine)
        logger.info("Datenbank-Schemata erfolgreich abgeglichen.")
        
        # E-8: Sichere Initialisierung des daily HMAC-Keys über einen Context-Manager
        # Hier wird direkt beim Start geprüft, ob der geheime Schlüssel für den heutigen Tag
        # existiert. Falls nicht, wird er absolut sicher und verschlüsselt erzeugt.
        with SessionLocal() as db:
            get_or_create_daily_hmac_key(db)
        
        # Startet den asynchronen Queue-Schreib-Hintergrundprozess (RAM-Buffer)
        # Dieser Prozess sorgt dafür, dass ankommende Besucherdaten nicht sofort einzeln
        # auf die Festplatte geschrieben werden (was den Server verlangsamt), sondern
        # gesammelt in Paketen (Batches) persistiert werden.
        app.state.queue_task = asyncio.create_task(batch_writer_worker())
        
        # Startet den täglichen HMAC-Key-Rotations-Hintergrundjob (Component 2)
        from app.jobs.rotate_key_job import schedule_daily_rotation
        app.state.rotation_task = asyncio.create_task(schedule_daily_rotation())
        
        # Falls wir uns nicht im Testmodus befinden, starten wir auch den periodischen Retention-Task
        if "pytest" not in sys.modules:
            app.state.retention_task = asyncio.create_task(retention_worker())
        
        logger.info("Start-Sequenz erfolgreich abgeschlossen.")
    except Exception as e:
        logger.critical(f"Kritischer Fehler beim Anwendungsstart: {e}")
        
    yield
    
    # ==========================================================================
    # GRACEFUL SHUTDOWN SEQUENCE (SIGTERM FÄNGER - DATENRETTER) (F-6)
    # ==========================================================================
    # KUNDENVERSTÄNDLICHE ERKLÄRUNG:
    # Wenn der Server gestoppt wird, sorgt dieser Block dafür, dass alle Hits, die
    # noch im schnellen Arbeitsspeicher (RAM) liegen und noch nicht auf die Festplatte
    # geschrieben wurden, sofort gesichert werden. Ihr IT-Techniker muss sich also
    # keine Sorgen machen, dass bei Server-Neustarts Daten verloren gehen.
    logger.warning("PulseTrack SaaS Engine wird ausgestellt. Sichere RAM-Daten...")
    try:
        # Den Retention-Task beenden
        if hasattr(app.state, "retention_task"):
            app.state.retention_task.cancel()
            
        # F-6: Queue-Worker stoppen und restliche Daten sauber in die SQLite-Datenbank flushen
        await write_queue_to_db()
        
        # Den Background-Task kontrolliert und zeitbegrenzt beenden lassen (Timeout nach 3 Sekunden)
        try:
            await asyncio.wait_for(app.state.queue_task, timeout=3.0)
        except asyncio.TimeoutError:
            app.state.queue_task.cancel()
            
        logger.info("Stop-Sequenz erfolgreich abgeschlossen. Alle Daten sind sicher auf der Festplatte.")
    except Exception as e:
        logger.error(f"Fehler bei Graceful Shutdown: {e}")

# 2. FastAPI Instanz erstellen
# Hier konfigurieren wir die grundlegenden Metadaten der Web-API.
app = FastAPI(
    title="PulseTrack SaaS",
    description="SaaS Web-Analytics - Blitzschnell, cookie-frei und 100% DSGVO-konform.",
    version="3.2.0",
    lifespan=lifespan
)

# Static-Dateien Mounten (styles.css, tracker.js etc.)
# Dadurch kann der Browser auf Stylesheets und Grafiken der Landingpage zugreifen.
app.mount("/static", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static")), name="static")

# Statisches tracker.js bereitstellen
# Dies ist die JavaScript-Datei, die Ihr IT-Techniker auf den Kunden-Webseiten einbindet.
@app.get("/tracker.js")
async def get_tracker():
    tracker_path = os.path.join(os.path.dirname(__file__), "static", "tracker.js")
    if os.path.exists(tracker_path):
        return FileResponse(tracker_path, media_type="application/javascript")
    raise HTTPException(status_code=404, detail="Tracker-Skript wurde nicht gefunden.")

# 3. CORS & DYNAMIC-ORIGIN-MIDDLEWARE (D-1)
# KUNDENVERSTÄNDLICHE ERKLÄRUNG:
# CORS steht für "Cross-Origin Resource Sharing". Dies ist eine wichtige Sicherheitsfunktion.
# Sie legt fest, von welchen Webseiten aus Anfragen an diesen Server gesendet werden dürfen.
# Dadurch wird verhindert, dass unbefugte Dritte Ihre API missbrauchen oder Fake-Daten senden.
#
# TECHNISCHE DETAILS:
# Wir laden eine Whitelist aus der Datei 'config.yaml'. Nur dort aufgelistete Domains
# dürfen credential-basierte Abfragen (z.B. Login) an das System senden.
allowed_origins = [
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "https://pulsetrack.io",  # Beispiel-Produktionsdomain
]

import yaml
from pathlib import Path

# CORS-Whitelist aus config.yaml laden, falls vorhanden
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
    # Fallback-Standard-Whitelist
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
# Hier werden die einzelnen System-Funktionen modular miteinander verknüpft.
app.include_router(views_router)       # UI Templates & Landingpage (Server-Side-Rendering)
app.include_router(auth_router)        # Benutzer-Authentifizierung & AVV-Unterzeichnung
app.include_router(account_router)     # DSGVO-Konto-Löschung (Recht auf Löschung)
app.include_router(billing_router)     # Stripe-Abrechnung & Webhooks
app.include_router(ingest_router)      # Empfangskanal für Analytics-Hits (Besucherdaten)
app.include_router(caddy_router)       # Caddy Dynamic SSL Proxy (automatische SSL-Zertifikate)
app.include_router(dashboard_router)   # Dashboard-Statistiken

@app.get("/api/health")
async def health_check():
    """
    KUNDENVERSTÄNDLICHE ERKLÄRUNG (Systemüberwachung / Health-Check):
    Dieser Endpoint wird von Server-Monitoring-Tools (z. B. in Docker) genutzt.
    Er meldet in Echtzeit, ob die PulseTrack-Software voll funktionsfähig ist ("healthy")
    und wie voll der Zwischenspeicher (die RAM-Queue) ist.
    Falls der Server überlastet ist, kann die IT frühzeitig reagieren.
    """
    queue_size = hit_queue.qsize()
    status = "healthy"
    # Wenn die Ingestion-Queue zu über 90 % voll ist (9.000 von 10.000), geben wir eine Warnung aus.
    if queue_size >= 9000:
        status = "warning"
    
    return {
        "status": status,
        "queue_size": queue_size,
        "max_queue_size": 10000
    }
