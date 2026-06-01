# Security Service: IP Hashing, Key Rotation, CORS Cache & Rate Limiting
#
# Datum: 31.05.2026 | Version: 1.1 | Status: Aktiv gepflegt

import hmac
import secrets
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from cachetools import TTLCache
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.models.user import DailyKey
from app.models.website import Website

# Bounded TTL-Cache zur drastischen Reduzierung der DB-Last (max 1000 Eintraege, 5 Minuten Gültigkeit) (D-9)
token_cache = TTLCache(maxsize=1000, ttl=300)

# In-Memory-Speicher für IP- & Token-basiertes Sliding-Window Rate-Limiting
rate_limit_store = defaultdict(list)
RATE_LIMIT_WINDOW = 60  # 60 Sekunden
MAX_HITS_PER_WINDOW = 60  # max 60 Hits pro Minute

def _get_encryption_key(day_str: str) -> bytes:
    """Leitet einen tages- und secretspezifischen AES-ähnlichen Schlüssel via HMAC ab."""
    master_secret = settings.ANALYTICS_SALT_SECRET.get_secret_value()
    return hmac.new(master_secret.encode(), day_str.encode(), "sha256").digest()

def _encrypt_key(raw_key_hex: str, day_str: str) -> str:
    """Verschluesselt den Tagesschluessel mit einer One-Time-Pad XOR-Operation (C-3)."""
    enc_key = _get_encryption_key(day_str)
    raw_bytes = bytes.fromhex(raw_key_hex)
    encrypted_bytes = bytes(a ^ b for a, b in zip(raw_bytes, enc_key, strict=True))
    return encrypted_bytes.hex()

def _decrypt_key(encrypted_key_hex: str, day_str: str) -> str:
    """Entschluesselt den Tagesschluessel (symmetrisches XOR)."""
    return _encrypt_key(encrypted_key_hex, day_str)

def hash_ip_address(client_ip: str, key_hex: str) -> str:
    """Berechnet einen datenschutzkonformen HMAC-SHA256 Hash der IP-Adresse."""
    key_bytes = bytes.fromhex(key_hex)
    return hmac.new(key_bytes, client_ip.encode(), "sha256").hexdigest()

def get_or_create_daily_hmac_key(db: Session) -> str:
    """
    Holt den verschlüsselten HMAC-Schlüssel für den aktuellen Tag aus der DB oder erstellt einen neuen.
    Sichert Forward Secrecy, da alte Schlüssel spaeter unwiderruflich geloescht werden.
    """
    today_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    
    # 1. Prüfen, ob der Schlüssel für heute bereits in der DB existiert
    db_key = db.query(DailyKey).filter(DailyKey.day == today_str).first()
    if db_key:
        return _decrypt_key(db_key.key_value, today_str)

    # 2. Falls nicht, einen neuen, kryptografisch sicheren 32-Byte-Schlüssel generieren und verschlüsselt ablegen
    new_key_hex = secrets.token_hex(32)
    encrypted_key = _encrypt_key(new_key_hex, today_str)
    new_key = DailyKey(day=today_str, key_value=encrypted_key)
    
    try:
        db.add(new_key)
        db.commit()
        db.refresh(new_key)
        return new_key_hex
    except IntegrityError:
        db.rollback()
        # Fallback im Falle eines parallelen Writes durch einen anderen Worker (Thread-Safety)
        fallback_key = db.query(DailyKey).filter(DailyKey.day == today_str).first()
        if fallback_key:
            return _decrypt_key(fallback_key.key_value, today_str)
        raise

def rotate_daily_hmac_key(db: Session) -> None:
    """
    Loescht alle HMAC-Schluessel, die aelter als 24 Stunden sind, um Forward Secrecy zu garantieren.
    """
    yesterday = datetime.now(tz=timezone.utc) - timedelta(days=1)
    yesterday_str = yesterday.strftime("%Y-%m-%d")
    
    try:
        db.query(DailyKey).filter(DailyKey.day < yesterday_str).delete()
        db.commit()
    except Exception:
        db.rollback()
        raise

def is_rate_limited(client_ip: str, token: str) -> bool:
    """
    Prüft mittels eines in-memory sliding windows, ob das Rate-Limit fuer (IP, Token) erreicht wurde.
    Bereinigt abgelaufene Eintraege zur Vermeidung von Speicherlecks (D-9).
    """
    now = time.time()
    key = (client_ip, token)
    
    # Bounded Cleanup: Abgelaufene Einträge periodisch bereinigen, falls Store wächst (D-9)
    if len(rate_limit_store) > 1000:
        for k in list(rate_limit_store.keys()):
            ts = rate_limit_store[k]
            if not ts or now - ts[-1] > RATE_LIMIT_WINDOW:
                rate_limit_store.pop(k, None)

    timestamps = rate_limit_store[key]

    # Veraltete Timestamps ausserhalb des Fensters entfernen
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
    Verwendet einen schnellen Bounded In-Memory-Cache zur massiven Reduzierung der DB-Last.
    """
    from app.config import normalize_site_url, url_matches_allowed
    
    # Normalisiere Origin für den CORS-Vergleich
    normalized_origin = normalize_site_url(origin) if origin else ""

    # 1. Schneller In-Memory-Cache-Check
    if token in token_cache:
        cached = token_cache[token]
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
    """Loescht ein bestimmtes Token aus dem Cache (wichtig bei Token-Resets)."""
    if token in token_cache:
        del token_cache[token]
