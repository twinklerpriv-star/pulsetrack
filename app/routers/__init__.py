# API Routers Initialisierung
#
# Datum: 28.05.2026 | Version: 1.0

from app.routers.auth import router as auth_router
from app.routers.caddy import router as caddy_router
from app.routers.dashboard import router as dashboard_router
from app.routers.ingest import router as ingest_router

__all__ = ["auth_router", "ingest_router", "caddy_router", "dashboard_router"]
