# API Router: Caddy CNAME Dynamic SSL Verification
#
# Datum: 31.05.2026 | Version: 1.1 | Status: Aktiv gepflegt

import logging
import os

from cachetools import TTLCache
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.config import normalize_site_url
from app.database import get_db
from app.models.website import Website

logger = logging.getLogger("analytics_caddy")
router = APIRouter(tags=["Caddy SSL Proxy"])

# Bounded Cache zur Vermeidung von Memory-Leaks und DoS-Angriffen (D-8, D-9)
# Max 1000 verifizierte Domains für maximal 1 Stunde cachen
cname_cache = TTLCache(maxsize=1000, ttl=3600)

@router.get("/api/verify-cname-domain")
def verify_cname_domain(
    request: Request,
    domain: str = Query(..., description="Die zu verifizierende Custom Domain"),
    db: Session = Depends(get_db)
):
    """
    Validiert in Echtzeit, ob eine Custom Domain (CNAME) für SSL/TLS freigegeben werden darf.
    Wird direkt vom Caddy Server via On-Demand TLS angefragt.
    Nutzt einen Bounded Cache und sichert sich ueber einen Shared Secret-Header ab (A-1, D-8).
    Faehrt synchron im Thread-Pool.
    """
    # D-8: Shared-Secret-Header-Ueberpruefung, falls konfiguriert
    caddy_secret = os.environ.get("CADDY_SECRET")
    if caddy_secret:
        client_secret = request.headers.get("X-Caddy-Secret")
        if not client_secret or client_secret != caddy_secret:
            logger.warning("Caddy TLS-Anfrage abgewiesen: Ungueltiger X-Caddy-Secret Header.")
            raise HTTPException(status_code=401, detail="Unauthorized: Invalid Caddy secret.")

    try:
        normalized_domain = normalize_site_url(domain)
    except ValueError as e:
        logger.warning(f"Caddy TLS-Anfrage abgewiesen: Ungueltiges Domain-Format '{domain}': {e}")
        raise HTTPException(status_code=400, detail="Invalid domain format.")
    
    # 1. In-Memory Bounded Cache Check
    if normalized_domain in cname_cache:
        if cname_cache[normalized_domain]:
            return {"allowed": True, "domain": domain}
        raise HTTPException(status_code=403, detail="Domain unauthorized or subscription inactive.")

    # 2. DB-Abfrage bei Cache-Miss
    # Suchen nach der Website mit dieser Custom Domain
    website = db.query(Website).filter(Website.domain == normalized_domain).first()
    if not website:
        cname_cache[normalized_domain] = False
        logger.warning(f"Caddy TLS-Anfrage abgewiesen: Domain '{normalized_domain}' ist nicht im System registriert.")
        raise HTTPException(status_code=403, detail="Domain not registered.")

    # Prüfen, ob das verknüpfte Kundenkonto ein aktives Abo besitzt
    owner = website.owner
    is_active = owner.subscription_status in ("active", "trial")
    
    cname_cache[normalized_domain] = is_active
    
    if not is_active:
        logger.warning(f"Caddy TLS-Anfrage abgewiesen: Inaktives Abo für Domain '{normalized_domain}'.")
        raise HTTPException(status_code=403, detail="Subscription inactive.")

    logger.info(f"Caddy TLS-Anfrage freigegeben: Domain '{normalized_domain}' erfolgreich zertifiziert.")
    return {"allowed": True, "domain": domain}

def invalidate_cname_cache(domain: str) -> None:
    """Löscht eine bestimmte Domain aus dem Caddy Cache (bei Löschung/Tarifsperrung)."""
    try:
        normalized_domain = normalize_site_url(domain)
        if normalized_domain in cname_cache:
            del cname_cache[normalized_domain]
    except Exception:
        pass
