# ==============================================================================
# API-ROUTER: CADDY CNAME DYNAMIC SSL VERIFICATION (ON-DEMAND TLS)
# ==============================================================================
# Datum: 01.06.2026 | Version: 1.2 | Status: Aktiv gepflegt & Produktionsbereit
#
# BETRIEBSWIRTSCHAFTLICHER ZWECK DIESER DATEI:
# Wenn B2B-Kunden eine eigene Custom Domain (z.B. "analytics.kunden-shop.at" statt
# "pulsetrack.io/kunden-shop") nutzen wollen, leitet der Caddy Webserver die
# Domainanfrage an diese Datei weiter.
# Sie verifiziert in Echtzeit, ob die Domain im System registriert ist und ob der
# Kunde ein aktives Abonnement hat. Ist dies der Fall, gibt das System grünes Licht
# und Caddy erzeugt **vollautomatisch und in Sekunden ein kostenloses SSL-Zertifikat** (Let's Encrypt).
#
# AUSWIRKUNG FÜR DEN KUNDEN / GESCHÄFTSFÜHRER:
# - Premium-Feature: Ihre Kunden können ihre eigene Marke stärken (White-Labeling).
# - Kein technischer Aufwand: Ihre Kunden müssen keine SSL-Zertifikate kaufen oder
#   manuell installieren. Alles läuft vollautomatisch.
#
# INFORMATION FÜR DEN IT-TECHNIKER:
# - On-Demand TLS Endpoint für den Caddy Reverse Proxy.
# - Sichert sich über ein Shared Secret (`CADDY_SECRET` in Umgebungsvariablen) ab.
# - Nutzt einen Bounded Cache (`TTLCache` max 1000, 1 Stunde TTL), um DB-Overhead zu vermeiden.
# ==============================================================================

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
    KUNDENVERSTÄNDLICHE ERKLÄRUNG (Dynamic SSL-Freigabe für Custom Domains):
    Caddy fragt hier an, ob für eine Custom Domain (z. B. analytics.kunden-website.at)
    ein SSL-Zertifikat ausgestellt werden darf.
    Die Funktion:
    1. Prüft, ob die Anfrage wirklich von Ihrem Caddy-Server kommt (Shared Secret Schutz).
    2. Prüft im extrem schnellen Arbeitsspeicher (Cache), ob diese Domain kürzlich verifiziert wurde.
    3. Falls nicht im Cache (Cache-Miss), wird in der Datenbank nach der Website gesucht.
    4. Prüft, ob der Betreiber der Website ein aktives Abonnement hat.
    Nur wenn die Domain existiert und bezahlt ist, wird das SSL-Zertifikat freigegeben.
    """
    # D-8: Shared-Secret-Header-Überprüfung zur Absicherung
    # Verhindert, dass fremde Personen den Endpoint abfragen und Ihren Server überlasten.
    caddy_secret = os.environ.get("CADDY_SECRET")
    if caddy_secret:
        client_secret = request.headers.get("X-Caddy-Secret")
        if not client_secret or client_secret != caddy_secret:
            logger.warning("Caddy TLS-Anfrage abgewiesen: Ungueltiger X-Caddy-Secret Header.")
            raise HTTPException(status_code=401, detail="Nicht autorisiert: Ungültiger Caddy-Schlüssel.")

    try:
        normalized_domain = normalize_site_url(domain)
    except ValueError as e:
        logger.warning(f"Caddy TLS-Anfrage abgewiesen: Ungueltiges Domain-Format '{domain}': {e}")
        raise HTTPException(status_code=400, detail="Ungültiges Domain-Format.")
    
    # 1. In-Memory Bounded Cache Check (Enorme Entlastung der Datenbank bei Traffic-Spikes)
    if normalized_domain in cname_cache:
        if cname_cache[normalized_domain]:
            return {"allowed": True, "domain": domain}
        raise HTTPException(status_code=403, detail="Domain nicht freigegeben oder Abonnement inaktiv.")

    # 2. DB-Abfrage bei Cache-Miss
    # Suchen nach der Website mit dieser Custom Domain
    website = db.query(Website).filter(Website.domain == normalized_domain).first()
    if not website:
        # Negativen Cache-Eintrag setzen, um wiederholte Angriffe auf dieselbe Domain sofort abzufangen
        cname_cache[normalized_domain] = False
        logger.warning(f"Caddy TLS-Anfrage abgewiesen: Domain '{normalized_domain}' ist nicht im System registriert.")
        raise HTTPException(status_code=403, detail="Domain nicht im System registriert.")

    # Prüfen, ob das verknüpfte Kundenkonto ein aktives Abo besitzt
    owner = website.owner
    is_active = owner.subscription_status in ("active", "trial")
    
    # Ergebnis im Cache speichern
    cname_cache[normalized_domain] = is_active
    
    if not is_active:
        logger.warning(f"Caddy TLS-Anfrage abgewiesen: Inaktives Abo für Domain '{normalized_domain}'.")
        raise HTTPException(status_code=403, detail="Abonnement inaktiv.")

    logger.info(f"Caddy TLS-Anfrage freigegeben: Domain '{normalized_domain}' erfolgreich zertifiziert.")
    return {"allowed": True, "domain": domain}

def invalidate_cname_cache(domain: str) -> None:
    """
    IT-Dienstprogramm:
    Löscht eine Domain sofort aus dem Cache.
    Wichtig, wenn ein Kunde sein Abo kündigt oder seine Domain ändert,
    damit die Änderung sofort (und nicht erst nach 1 Stunde) wirksam wird.
    """
    try:
        normalized_domain = normalize_site_url(domain)
        if normalized_domain in cname_cache:
            del cname_cache[normalized_domain]
    except Exception:
        pass
