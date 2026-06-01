# ==============================================================================
# API-ROUTER: ASYNCHRONER HIT INGESTION-KANAL (DATEN-EMPFANGSSTATION)
# ==============================================================================
# Datum: 01.06.2026 | Version: 1.2 | Status: Aktiv gepflegt & Hochperformant
#
# BETRIEBSWIRTSCHAFTLICHER ZWECK DIESER DATEI:
# Dies ist die wichtigste Schnittstelle für den Tracker: Jedes Mal, wenn ein Besucher
# eine Seite Ihrer Kundenwebsite aufruft, sendet das JavaScript-Skript im Browser
# des Besuchers ein Datenpaket an diesen Endpoint (`/api/hit`).
# Da diese API extrem oft aufgerufen wird (Millionen Aufrufe pro Tag),
# ist sie maximal auf Performance und Datenschutz getrimmt.
#
# AUSWIRKUNG FÜR DEN KUNDEN / GESCHÄFTSFÜHRER:
# - Blitzschnelle Website-Ladezeiten: Besucher bemerken den Tracker überhaupt nicht.
# - Keine Cookie-Einwilligung nötig: Personenbezogene Daten werden im RAM vor dem
#   Speichern komplett anonymisiert.
# - Schutz vor Überlastung: Das System bremst aggressive Bots aus (Rate-Limiting).
#
# INFORMATION FÜR DEN IT-TECHNIKER:
# - Verwendet Pydantic mit Längenbegrenzung gegen Buffer-Overflow / DoS.
# - Offloaded DB-Validierungen in separate Threads via `asyncio.to_thread`.
# - IP-Anonymisierung erfolgt direkt im RAM über HMAC-SHA256 mit rotierendem Schlüssel.
# ==============================================================================

import asyncio
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.queue_worker import add_hit_to_queue
from app.services.security import (
    get_or_create_daily_hmac_key,
    hash_ip_address,
    is_rate_limited,
    validate_token_and_origin,
)

logger = logging.getLogger("analytics_ingest")
router = APIRouter(tags=["Ingestion"])

class HitPayload(BaseModel):
    """
    Sicherheits-Pydantic-Modell für das ankommende Datenpaket.
    
    D-10: Strenge Längenbegrenzungen für alle Felder schützen die Datenbank
    vor böswilligen, extrem langen Datensätzen (Denial-of-Service-Angriffe).
    """
    token: str = Field(..., max_length=64)
    url: str = Field(..., max_length=2048)
    referrer: str | None = Field(None, max_length=2048)

def parse_user_agent(user_agent_string: str | None) -> tuple[str, str]:
    """
    Hilfsfunktion zur Identifizierung von Browser und OS aus dem rohen User-Agent-Header.
    Filtert z. B. 'Firefox' und 'Windows' heraus, damit wir saubere Diagramme im Dashboard zeichnen können.
    """
    if not user_agent_string:
        return "Unknown", "Unknown"

    ua = user_agent_string.lower()

    if "firefox" in ua:
        browser = "Firefox"
    elif "chrome" in ua and "safari" in ua:
        browser = "Chrome"
    elif "safari" in ua and "chrome" not in ua:
        browser = "Safari"
    elif "edge" in ua:
        browser = "Edge"
    else:
        browser = "Other"

    if "windows" in ua:
        os_name = "Windows"
    elif "macintosh" in ua or "mac os" in ua:
        os_name = "macOS"
    elif "linux" in ua:
        os_name = "Linux"
    elif "android" in ua:
        os_name = "Android"
    elif "iphone" in ua or "ipad" in ua:
        os_name = "iOS"
    else:
        os_name = "Other"

    return browser, os_name

@router.post("/api/hit", status_code=202)
async def capture_hit(payload: HitPayload, request: Request, db: Session = Depends(get_db)):
    """
    KUNDENVERSTÄNDLICHE ERKLÄRUNG (Seitenaufruf-Erfassung):
    Dies ist die "Empfangsstation" für jeden Klick. Sie durchläuft 5 Schritte:
    
    Schritt 1: IP-Adresse ermitteln
    - Der Server liest die IP-Adresse des Website-Besuchers. Im Logbuch wird
      aus Datenschutzgründen NUR eine maskierte IP eingetragen (z.B. 192.168.1.0).
      
    Schritt 2: Rate-Limiting Check
    - Schützt vor Spam. Versendet dieselbe IP mehr als 60 Hits pro Minute, wird sie blockiert.
    
    Schritt 3: CORS & Token Validierungs-Check
    - Prüft in Sekundenbruchteilen im In-Memory-Cache, ob das Token gültig ist
      und ob der Besucher sich auf der echten Kundenwebsite befindet.
      
    Schritt 4: Datenaufbereitung im RAM (Anonymisierung)
    - Die IP-Adresse wird mit dem heutigen geheimen Schlüssel zu einem anonymen
      Hashwert verschlüsselt. Die echte IP-Adresse wird **niemals** auf der Festplatte gespeichert.
      
    Schritt 5: Übergabe an die asynchrone RAM-Queue
    - Um die Datenbank nicht zu überlasten, legen wir den Hit in eine schnelle
      Warteschlange (Queue) im Arbeitsspeicher. Der Server meldet sofort "akzeptiert" (HTTP 202).
      Ein Hintergrund-Worker schreibt die Hits später gesammelt in die DB.
    """
    origin = request.headers.get("origin")
    user_agent = request.headers.get("user-agent")

    # 1. IP-Adresse ermitteln
    forwarded_for = request.headers.get("x-forwarded-for")
    client_ip = forwarded_for.split(",")[0].strip() if forwarded_for else (request.client.host if request.client else "127.0.0.1")

    # Maskierte IP-Adresse für datenschutzkonformes Logging (C-1)
    if "." in client_ip:
        ip_parts = client_ip.split(".")
        masked_ip = f"{ip_parts[0]}.{ip_parts[1]}.{ip_parts[2]}.0"
    else:
        masked_ip = "IPv6"

    # 2. IP Rate-Limiting Check (Sliding Window in-memory)
    if is_rate_limited(client_ip, payload.token):
        logger.warning(f"Rate-Limit ueberschritten fuer IP {masked_ip} auf Token {payload.token}.")
        raise HTTPException(status_code=429, detail="Too many tracking requests from this client.")

    # 3. CORS & Token Validierungs-Check (In-Memory-Cache / DB)
    # Offloading in Thread: Verhindert das Blockieren des Event-Loops bei DB-Zugriff
    is_valid = await asyncio.to_thread(validate_token_and_origin, db, payload.token, origin)
    if not is_valid:
        logger.warning(f"CORS Validierungs-Fehlschlag fuer Origin: '{origin}' und Token: '{payload.token}'")
        raise HTTPException(status_code=403, detail="Unauthorized domain tracking or expired subscription.")

    # 4. Datenaufbereitung im RAM (HMAC-SHA256 Anonymisierung)
    hmac_key = await asyncio.to_thread(get_or_create_daily_hmac_key, db)
    ip_hash = hash_ip_address(client_ip, hmac_key)
    
    browser, os_name = parse_user_agent(user_agent)
    timestamp = datetime.now(tz=timezone.utc).replace(tzinfo=None)

    hit_data = {
        "token": payload.token,
        "timestamp": timestamp,
        "url": payload.url,
        "referrer": payload.referrer,
        "user_agent": user_agent,
        "ip_hash": ip_hash,
        "browser": browser,
        "os": os_name
    }

    # 5. Übergabe an asynchrone Queue
    queued = await add_hit_to_queue(hit_data)
    if not queued:
        raise HTTPException(status_code=500, detail="Server queue failure. Logging aborted.")

    return {"status": "accepted"}
