# Datenbank- & Analyse-Logik (SQLite)
#
# Datum: 20.05.2026 | Version: 1.1 | Status: In Entwicklung
#
# Dieses Modul verwaltet die SQLite-Datenbank für unser Web-Analytics-Tool.
# Es speichert Zugriffe datenschutzkonform und aggregiert Statistiken für das Dashboard.


import hashlib
import logging
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any

# Logger-Setup zur Vermeidung stiller Fehler (gemäß Zusammenarbeits-Regeln)
logger = logging.getLogger("analytics_db")
logging.basicConfig(level=logging.INFO)

DATABASE_FILE = "analytics.db"

def get_db_connection() -> sqlite3.Connection:
    """
    Erstellt eine Verbindung zur SQLite-Datenbank und aktiviert 
    den WAL-Modus (Write-Ahead Logging) für parallele Schreib-/Lesevorgänge.
    """
    try:
        conn = sqlite3.connect(DATABASE_FILE)
        conn.row_factory = sqlite3.Row
        # WAL-Modus aktivieren
        conn.execute("PRAGMA journal_mode=WAL;")
        return conn
    except sqlite3.Error as e:
        logger.error(f"Fehler bei der DB-Verbindung: {e}")
        raise


def init_db() -> None:
    """Initialisiert die Datenbanktabellen, falls diese noch nicht existieren."""
    query = """
    CREATE TABLE IF NOT EXISTS hits (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT NOT NULL,
        url TEXT NOT NULL,
        referrer TEXT,
        user_agent TEXT,
        ip_hash TEXT NOT NULL,
        browser TEXT,
        os TEXT
    );
    """
    try:
        with get_db_connection() as conn:
            conn.execute(query)
            conn.commit()
            logger.info("Datenbank erfolgreich initialisiert.")
    except sqlite3.Error as e:
        logger.error(f"Fehler bei der Datenbank-Initialisierung: {e}")
        raise

def parse_user_agent(user_agent_string: str | None) -> tuple[str, str]:
    """Analysiert den User Agent String auf einfache Weise (Browser, OS)."""
    if not user_agent_string:
        return "Unknown", "Unknown"
    
    ua = user_agent_string.lower()
    
    # Einfache Browser-Erkennung
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
        
    # Einfache OS-Erkennung
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

def save_hit(url: str, referrer: str | None, user_agent: str | None, client_ip: str) -> None:
    """
    Speichert einen Seitenaufruf. 
    IP-Adressen werden zur Einhaltung der DSGVO mit einem Salt gehasht und niemals im Klartext gespeichert.
    """
    # IP-Hashing zur Anonymisierung (DSGVO-konform).
    # Der Salt rotiert täglich, um Brute-Force-Angriffe auf die Datenbank zu erschweren.
    # In Produktion: ANALYTICS_SALT_SECRET als Umgebungsvariable setzen.
    base_secret = os.environ.get("ANALYTICS_SALT_SECRET", "pulsetrack-fallback-secret")
    daily_date = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    rotating_salt = f"{base_secret}:{daily_date}"
    ip_salted = f"{client_ip}{rotating_salt}".encode()
    ip_hash = hashlib.sha256(ip_salted).hexdigest()
    
    browser, os_name = parse_user_agent(user_agent)
    timestamp = datetime.utcnow().isoformat()
    
    query = """
    INSERT INTO hits (timestamp, url, referrer, user_agent, ip_hash, browser, os)
    VALUES (?, ?, ?, ?, ?, ?, ?);
    """
    
    try:
        with get_db_connection() as conn:
            conn.execute(query, (timestamp, url, referrer, user_agent, ip_hash, browser, os_name))
            conn.commit()
    except sqlite3.Error as e:
        logger.error(f"Fehler beim Speichern des Hits: {e}")
        raise

def get_analytics_summary() -> dict[str, Any]:
    """Aggregiert Statistiken aus der Datenbank für das Dashboard."""
    try:
        with get_db_connection() as conn:
            # 1. Pageviews & Uniques (Gesamt)
            row = conn.execute("SELECT COUNT(*) as pv, COUNT(DISTINCT ip_hash) as uv FROM hits;").fetchone()
            pageviews = row["pv"] if row else 0
            uniques = row["uv"] if row else 0
            
            # 2. Top Pages
            top_pages = conn.execute(
                "SELECT url, COUNT(*) as count FROM hits GROUP BY url ORDER BY count DESC LIMIT 5;"
            ).fetchall()
            
            # 3. Top Referrers
            top_referrers = conn.execute(
                "SELECT COALESCE(referrer, 'Direct') as ref, COUNT(*) as count FROM hits GROUP BY ref ORDER BY count DESC LIMIT 5;"
            ).fetchall()
            
            # 4. Browsers
            browsers = conn.execute(
                "SELECT browser, COUNT(*) as count FROM hits GROUP BY browser ORDER BY count DESC;"
            ).fetchall()
            
            # 5. OS
            operating_systems = conn.execute(
                "SELECT os, COUNT(*) as count FROM hits GROUP BY os ORDER BY count DESC;"
            ).fetchall()
            
            return {
                "total_pageviews": pageviews,
                "total_uniques": uniques,
                "top_pages": [dict(r) for r in top_pages],
                "top_referrers": [dict(r) for r in top_referrers],
                "browsers": [dict(r) for r in browsers],
                "operating_systems": [dict(r) for r in operating_systems]
            }
    except sqlite3.Error as e:
        logger.error(f"Fehler bei der Datenaggregation: {e}")
        raise
