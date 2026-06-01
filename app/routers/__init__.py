# ==============================================================================
# PULSETRACK ANALYTICS - SYSTEM-API-ROUTER-BÜNDELUNG (ROUTERS-ZENTRALE)
# ==============================================================================
# Datum: 01.06.2026 | Version: 1.2 | Status: Aktiv gepflegt
#
# BETRIEBSWIRTSCHAFTLICHER ZWECK DIESER DATEI:
# Diese Datei bündelt alle einzelnen Funktions-Router (Nutzerkonten, Login, Stripe,
# SSL, Datenempfang, Dashboard und Webviews) des PulseTrack-Systems an einem Ort,
# damit FastAPI diese im Hauptmodul (main.py) in einem einzigen Schritt importieren
# und bereitstellen kann.
#
# INFORMATION FÜR DEN IT-TECHNIKER:
# - Sammelt und exportiert alle modularen APIRouter für die FastAPI-Instanz.
# ==============================================================================

from app.routers.account import router as account_router
from app.routers.auth import router as auth_router
from app.routers.billing import router as billing_router
from app.routers.caddy import router as caddy_router
from app.routers.dashboard import router as dashboard_router
from app.routers.ingest import router as ingest_router
from app.routers.views import router as views_router

__all__ = [
    "auth_router", 
    "billing_router", 
    "ingest_router", 
    "caddy_router", 
    "dashboard_router", 
    "views_router", 
    "account_router"
]
