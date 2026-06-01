# API Routers Initialisierung
#
# Datum: 31.05.2026 | Version: 1.1

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
