# Security Service: IP Hashing, Key Rotation, CORS Cache & Rate Limiting
#
# Datum: 28.05.2026 | Version: 1.0 | Status: Aktiv gepflegt

import hmac
import secrets
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.user import DailyKey
from app.models.website import Website

# In-Memory-Speicher für das schnelle Preflight-Caching (LRU-Alternative)
# Format: {token: {"domain": domain_string, "track_apex": bool, "track_subdomains": bool, "active": bool}}
token_cache = {}

# In-Memory-Speicher für IP- & Token-basiertes Sliding-Window Rate-Limiting
# Format: {(ip, token): [timestamp1, timestamp2, ...]}
rate_limit_store = defaultdict(list)
RATE_LIMIT_WINDOW = 60  # 60 Sekunden
MAX_HITS_PER_WINDOW = 60  # max 60 Hits pro Minute

def hash_ip_address(client_ip: str, key_hex: str) -> str:
    """Berechnet einen datenschutzkonformen HMAC-SHA256 Hash der IP-Adresse."""
    key_bytes = bytes.fromhex(key_hex)
    return hmac.new(key_bytes, client_ip.encode(), "sha256").hexdigest()

def get_or_create_daily_hmac_key(db: Session) -> str:
    """
    Holt den HMAC-Schlüssel für den aktuellen Tag aus der Datenbank oder erstellt einen neuen.
    Sichert Forward Secrecy, da alte Schlüssel später unwiderruflich gelöscht werden.
    """
    today_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    
    # 1. Prüfen, ob der Schlüssel für heute bereits in der DB existiert
    db_key = db.query(DailyKey).filter(DailyKey.day == today_str).first()
    if db_key:
        return db_key.key_value

    # 2. Falls nicht, einen neuen, kryptografisch sicheren 32-Byte-Schlüssel generieren
    new_key_hex = secrets.token_hex(32)
    new_key = DailyKey(day=today_str, key_value=new_key_hex)
    
    try:
        db.add(new_key)
        db.commit()
        db.refresh(new_key)
        return new_key.key_value
    except Exception:
        db.rollback()
        # Fallback im Falle eines parallelen Writes durch einen anderen Worker
        fallback_key = db.query(DailyKey).filter(DailyKey.day == today_str).first()
        if fallback_key:
            return fallback_key.key_value
        raise

def rotate_daily_hmac_key(db: Session) -> None:
    """
    Löscht alle HMAC-Schlüssel, die älter als 24 Stunden sind, um Forward Secrecy zu garantieren.
    """
    yesterday = datetime.now(tz=timezone.utc) - timedelta(days=1)
    yesterday_str = yesterday.strftime("%Y-%m-%d")
    
    try:
        # Lösche alle Einträge, deren Datum älter als gestern (UTC) ist
        db.query(DailyKey).filter(DailyKey.day < yesterday_str).delete()
        db.commit()
    except Exception:
        db.rollback()
        raise

def is_rate_limited(client_ip: str, token: str) -> bool:
    """
    Prüft mittels eines in-memory sliding windows, ob das Rate-Limit für (IP, Token) erreicht wurde.
    Erlaubt maximal 60 Hits pro Minute.
    """
    now = time.time()
    key = (client_ip, token)
    timestamps = rate_limit_store[key]

    # Veraltete Timestamps außerhalb des Fensters entfernen
    while timestamps and now - timestamps[0] > RATE_LIMIT_WINDOW:
        timestamps.pop(0)

    # Prüfen, ob das Limit überschritten wurde
    if len(timestamps) >= MAX_HITS_PER_WINDOW:
        return True

    # Neuen Timestamp hinzufügen
    timestamps.append(now)
    return False

def validate_token_and_origin(db: Session, token: str, origin: str) -> bool:
    """
    Validiert das Tracking-Token und die Herkunftsdomain (CORS) in Echtzeit.
    Verwendet einen schnellen In-Memory-Cache zur massiven Reduzierung der DB-Last.
    """
    from app.config import normalize_site_url, url_matches_allowed
    
    # Normalisiere Origin für den CORS-Vergleich
    normalized_origin = normalize_site_url(origin) if origin else ""

    # 1. Schneller In-Memory-Cache-Check
    if token in token_cache:
        cached = token_cache[token]
        # Falls das verknüpfte Nutzerkonto inaktiv ist, sofort verwerfen
        if not cached["active"]:
            return False
        
        # Abgleich mit erlaubten Domains im Cache
        allowed_origins = [cached["domain"]]
        return url_matches_allowed(
            normalized_origin, 
            allowed_origins, 
            cached["track_subdomains"]
        )

    # 2. Fallback: Datenbank-Abfrage bei Cache-Miss
    website = db.query(Website).filter(Website.tracking_token == token).first()
    if not website:
        return False

    # Prüfen, ob der zugehörige User ein aktives Abo hat
    owner = website.owner
    is_active_sub = owner.subscription_status in ("active", "trial")

    # In den Cache schreiben
    token_cache[token] = {
        "domain": normalize_site_url(website.domain),
        "track_apex": website.track_apex,
        "track_subdomains": website.track_subdomains,
        "active": is_active_sub
    }

    if not is_active_sub:
        return False

    allowed_origins = [token_cache[token]["domain"]]
    return url_matches_allowed(
        normalized_origin, 
        allowed_origins, 
        website.track_subdomains
    )

def invalidate_token_cache(token: str) -> None:
    """Löscht ein bestimmtes Token aus dem Cache (wichtig bei Token-Resets)."""
    if token in token_cache:
        del token_cache[token]
