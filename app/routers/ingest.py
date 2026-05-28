# API Router: Asynchroner Hit Ingestion-Kanal (CORS & Rate-Limited)
#
# Datum: 28.05.2026 | Version: 1.0 | Status: Aktiv gepflegt

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
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
    token: str
    url: str
    referrer: str | None = None

def parse_user_agent(user_agent_string: str | None) -> tuple[str, str]:
    """Hilfsfunktion zur Identifizierung von Browser und OS aus dem User-Agent."""
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
    Asynchroner Empfangskanal für Analytics-Hits.
    Entkoppelt den Schreibvorgang von der HTTP-Response durch RAM-Pufferung.
    """
    origin = request.headers.get("origin")
    user_agent = request.headers.get("user-agent")

    # 1. IP-Adresse ermitteln
    forwarded_for = request.headers.get("x-forwarded-for")
    client_ip = forwarded_for.split(",")[0].strip() if forwarded_for else (request.client.host if request.client else "127.0.0.1")

    # 2. IP Rate-Limiting Check (Sliding Window in-memory)
    if is_rate_limited(client_ip, payload.token):
        logger.warning(f"Rate-Limit überschritten für IP {client_ip} auf Token {payload.token}.")
        raise HTTPException(status_code=429, detail="Too many tracking requests from this client.")

    # 3. CORS & Token Validierungs-Check (In-Memory-Cache / DB)
    # Erlaubt OPTIONS preflights direkt und POST-Hits nur bei gültiger Zuweisung
    if not validate_token_and_origin(db, payload.token, origin):
        logger.warning(f"CORS Validierungs-Fehlschlag für Origin: '{origin}' und Token: '{payload.token}'")
        raise HTTPException(status_code=403, detail="Unauthorized domain tracking or expired subscription.")

    # 4. Datenaufbereitung im RAM (HMAC-SHA256 Anonymisierung)
    hmac_key = get_or_create_daily_hmac_key(db)
    ip_hash = hash_ip_address(client_ip, hmac_key)
    
    browser, os_name = parse_user_agent(user_agent)
    timestamp = datetime.now(tz=timezone.utc).replace(tzinfo=None).isoformat()

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
