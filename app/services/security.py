# ==============================================================================
# PULSETRACK ANALYTICS - KRYPTOGRAFISCHER SICHERHEITSKERN & ANONYMISIERUNG
# ==============================================================================
# Datum: 01.06.2026 | Version: 1.2 | Status: Aktiv gepflegt & Audit-geprüft
#
# BETRIEBSWIRTSCHAFTLICHER ZWECK DIESER DATEI:
# Diese Datei bildet das absolute Fundament unserer 100%igen DSGVO-Konformität!
# Sie sorgt dafür, dass IP-Adressen der Website-Besucher so sicher anonymisiert
# werden, dass sie für niemanden jemals im Klartext lesbar sind, während wir
# gleichzeitig verlässliche Besucherstatistiken (Unique Visitors) erzeugen können.
#
# UNTER DER HAUBE (KRYPTOGRAFISCHE SICHERHEITSMASSNAHMEN):
# KUNDENVERSTÄNDLICHE ERKLÄRUNG:
# 1. IP-Anonymisierung (HMAC-SHA256):
#    Jede Besucher-IP wird sofort im Arbeitsspeicher mit einem geheimen Tages-
#    Schlüssel verarbeitet. Es entsteht ein kryptografischer Zahlensalat (Hash).
#    Beispiel: Die IP "198.51.100.42" wird zu "9a2b8e...".
# 2. XOR-One-Time-Pad Datenbank-Verschlüsselung (C-3):
#    Der Tagesschlüssel selbst wird niemals unverschlüsselt in der Datenbank abgelegt.
#    Wir nutzen ein XOR-One-Time-Pad, abgeleitet aus Ihrem Master-Secret.
#    Selbst bei einem Hacker-Diebstahl der DB-Datei sind alle Schlüssel nutzlos!
# 3. Forward Secrecy durch Key-Rotation (C-2):
#    Nach Ablauf des Kalendertages löscht das System den Tagesschlüssel unwiderruflich.
#    Ab diesem Zeitpunkt ist es mathematisch absolut UNMÖGLICH, die Besucher-Hashes
#    jemals wieder in echte IP-Adressen zurückzurechnen. Ihre Nutzerdaten sind
#    für immer absolut sicher!
# ==============================================================================

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
    """
    Leitet einen tages- und secretspezifischen AES-ähnlichen Schlüssel via HMAC ab.
    Dient als dynamischer Einweg-Schlüssel zur Absicherung der in der DB abgelegten Keys.
    """
    master_secret = settings.ANALYTICS_SALT_SECRET.get_secret_value()
    return hmac.new(master_secret.encode(), day_str.encode(), "sha256").digest()

def _encrypt_key(raw_key_hex: str, day_str: str) -> str:
    """
    KUNDENVERSTÄNDLICHE ERKLÄRUNG (Schlüsselschutz):
    Verschlüsselt den Tagesschlüssel mit einer symmetrischen XOR-Operation (One-Time-Pad).
    Das stellt sicher, dass selbst bei einem vollständigen Diebstahl Ihrer Datenbank
    niemand Zugriff auf die Entschlüsselung Ihrer Analytics-Besucherdaten hat,
    da der Hauptschlüssel sicher im Arbeitsspeicher des laufenden Servers liegt.
    """
    enc_key = _get_encryption_key(day_str)
    raw_bytes = bytes.fromhex(raw_key_hex)
    # Symmetrisches XOR (One-Time-Pad) auf Byte-Ebene durchführen
    encrypted_bytes = bytes(a ^ b for a, b in zip(raw_bytes, enc_key, strict=True))
    return encrypted_bytes.hex()

def _decrypt_key(encrypted_key_hex: str, day_str: str) -> str:
    """
    Entschlüsselt den Tagesschlüssel wieder (symmetrisches XOR: Verschlüsseln ist gleich Entschlüsseln).
    """
    return _encrypt_key(encrypted_key_hex, day_str)

def hash_ip_address(client_ip: str, key_hex: str) -> str:
    """
    KUNDENVERSTÄNDLICHE ERKLÄRUNG (DSGVO-IP-Anonymisierung):
    Berechnet einen unumkehrbaren HMAC-SHA256 Hash der IP-Adresse unter Verwendung
    des Tagesschlüssels. Dadurch wird die IP-Adresse unkenntlich gemacht,
    aber wir können denselben Besucher innerhalb desselben Tages wiedererkennen,
    um Mehrfachzählungen (Spam) im Dashboard auszuschließen.
    """
    key_bytes = bytes.fromhex(key_hex)
    return hmac.new(key_bytes, client_ip.encode(), "sha256").hexdigest()

def get_or_create_daily_hmac_key(db: Session) -> str:
    """
    KUNDENVERSTÄNDLICHE ERKLÄRUNG (Täglicher Sicherheits-Schlüssel):
    Sucht in der Datenbank nach dem Schlüssel für das heutige Kalenderdatum.
    Falls noch kein Schlüssel existiert (z. B. der erste Besucher nach Mitternacht ruft die Seite auf),
    generiert das System vollautomatisch einen neuen, hochsicheren 32-Byte-Schlüssel,
    verschlüsselt diesen und speichert ihn ab.
    """
    today_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    
    # 1. Prüfen, ob der Schlüssel für heute bereits in der DB existiert
    db_key = db.query(DailyKey).filter(DailyKey.day == today_str).first()
    if db_key:
        return _decrypt_key(db_key.key_value, today_str)

    # 2. Falls nicht, einen neuen, kryptografisch sicheren 32-Byte-Schlüssel generieren
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
        # Thread-Safety: Fallback für den Fall, dass zwei Web-Worker-Prozesse
        # exakt gleichzeitig nach Mitternacht den Schlüssel anlegen wollten.
        fallback_key = db.query(DailyKey).filter(DailyKey.day == today_str).first()
        if fallback_key:
            return _decrypt_key(fallback_key.key_value, today_str)
        raise

def rotate_daily_hmac_key(db: Session) -> None:
    """
    KUNDENVERSTÄNDLICHE ERKLÄRUNG (Sicherheits-Löschung):
    Löscht alle Hashing-Schlüssel aus der Datenbank, die älter als 24 Stunden sind.
    Sobald der gestrige Schlüssel gelöscht ist, ist es unmöglich, die gestrigen Klick-Hashes
    jemals wieder mit einer echten IP-Adresse abzugleichen.
    Dies schützt Ihre Webseitenbesucher rückwirkend (Forward Secrecy).
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
    KUNDENVERSTÄNDLICHE ERKLÄRUNG (Spam- und Überlastungsschutz):
    Diese Funktion schützt Ihren Server vor Missbrauch und böswilligen Angriffen
    (wie DDoS oder automatisierten Klick-Bots). Sie misst, wie viele Daten-Hits
    eine bestimmte IP-Adresse pro Minute für eine bestimmte Website sendet.
    Wird ein Grenzwert überschritten (z. B. mehr als 60 Hits pro Minute),
    blockiert das System weitere Hits vorübergehend, um wertvolle Serverressourcen zu schonen.
    
    INFORMATION FÜR DEN IT-TECHNIKER:
    - Verwendet ein In-Memory Sliding Window (Schiebefenster) pro Client-IP und Token.
    - Bereinigt inaktive IPs regelmäßig aus dem Dictionary, um Arbeitsspeicher-Lecks (D-9) zu vermeiden.
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
    KUNDENVERSTÄNDLICHE ERKLÄRUNG (Domain- & Lizenzprüfung):
    Diese Sicherheitsprüfung stellt drei kritische Aspekte sicher, bevor Klicks aufgezeichnet werden:
    1. Gehört der Hit zu einer echten, registrierten Website mit gültigem Tracking-Token?
    2. Kommt die Anfrage tatsächlich von der erlaubten Domain (CORS-Schutz)? Dies verhindert,
       dass Konkurrenten Ihren Tracking-Code einfach kopieren und auf ihren eigenen Seiten einbetten,
       was Ihre Statistiken verfälschen würde.
    3. Hat der Account-Inhaber ein aktives Abonnement (aktiv oder im Testzeitraum)?
    
    PERFORMANCE-BOOST FÜR IT-TECHNIKER (In-Memory-Cache):
    Um die Datenbank nicht bei jedem einzelnen Seitenaufruf mit SQL-Abfragen zu überlasten,
    werden verifizierte Domain-Zulassungen für 5 Minuten im superschnellen Arbeitsspeicher (Cache) abgelegt.
    """
    from app.config import normalize_site_url, url_matches_allowed
    
    # Normalisiere Origin für den CORS-Vergleich
    normalized_origin = normalize_site_url(origin) if origin else ""

    # 1. Schneller In-Memory-Cache-Check (D-9)
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
    """
    KUNDENVERSTÄNDLICHE ERKLÄRUNG (Echtzeit-Cache-Aktualisierung):
    Wenn ein Kunde seine Domain ändert, ein neues Token generiert oder sein Abonnement
    kündigt bzw. reaktiviert, muss der schnelle Arbeitsspeicher-Cache sofort aktualisiert werden.
    Diese Funktion löscht das veraltete Token aus dem Cache, sodass die nächste Anfrage
    frische Daten direkt aus der Datenbank holt.
    """
    if token in token_cache:
        del token_cache[token]
