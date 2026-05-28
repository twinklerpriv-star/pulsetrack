# API Router: Caddy CNAME Dynamic SSL Verification
#
# Datum: 28.05.2026 | Version: 1.0 | Status: Aktiv gepflegt

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.config import normalize_site_url
from app.database import get_db
from app.models.website import Website

logger = logging.getLogger("analytics_caddy")
router = APIRouter(tags=["Caddy SSL Proxy"])

# In-Memory-Speicher für verifizierte Domains, um Caddy-Preflight-Abfragen zu beschleunigen
# Format: {domain_string: is_allowed_boolean}
cname_cache = {}

@router.get("/api/verify-cname-domain")
async def verify_cname_domain(
    domain: str = Query(..., description="Die zu verifizierende Custom Domain"),
    db: Session = Depends(get_db)
):
    """
    Validiert in Echtzeit, ob eine Custom Domain (CNAME) für SSL/TLS freigegeben werden darf.
    Wird direkt vom Caddy Server via On-Demand TLS angefragt.
    """
    normalized_domain = normalize_site_url(domain)
    
    # 1. In-Memory Cache Check
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
    normalized_domain = normalize_site_url(domain)
    if normalized_domain in cname_cache:
        del cname_cache[normalized_domain]
