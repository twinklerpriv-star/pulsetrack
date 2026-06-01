# ==============================================================================
# PULSETRACK ANALYTICS - HINTERGRUNDJOB: TÄGLICHE SCHLÜSSEL-ROTATION (KEY ROTATION)
# ==============================================================================
# Datum: 01.06.2026 | Version: 1.2 | Status: Aktiv gepflegt & Bugfixed
#
# BETRIEBSWIRTSCHAFTLICHER ZWECK DIESER DATEI:
# Dieser Hintergrundjob ist das automatische Sicherheits-Uhrwerk von PulseTrack.
# Er sorgt dafür, dass tagesbezogene Verschlüsselungsschlüssel nach Ablauf des Tages
# unwiderruflich aus der Datenbank gelöscht werden (Art. 5 Abs. 1 e DSGVO - Speicherbegrenzung).
# Dies geschieht vollautomatisch in den frühen Morgenstunden ohne manuelle Pflege.
# ==============================================================================

import asyncio
from datetime import datetime, time, timezone, timedelta
import logging

from app.database import SessionLocal
from app.services.security import rotate_daily_hmac_key

# Logger initialisieren, um die nächtlichen Löschvorgänge zu überwachen
logger = logging.getLogger("analytics_key_rotation")

async def schedule_daily_rotation():
    """
    KUNDENVERSTÄNDLICHE ERKLÄRUNG (Tägliche Sicherheits-Schlüssel-Rotation):
    Dieser Hintergrund-Job läuft vollautomatisch einmal täglich um 02:00 Uhr UTC
    (nachts, wenn die Serverlast am geringsten ist).
    Er löscht alle alten Entschlüsselungsschlüssel aus der Datenbank, die älter als 24 Stunden sind.
    Dadurch wird sichergestellt, dass selbst bei einem Cyberangriff die alten Tracking-Hashes
    niemals wieder entschlüsselt werden können (Forward Secrecy / C-2).
    
    TECHNISCHE DETAILS FÜR IT-TECHNIKER:
    - Berechnet die Wartezeit bis zum nächsten Laufzeitpunkt (02:00 Uhr UTC) dynamisch.
    - Läuft asynchron im Hintergrund, blockiert also nicht den Hauptserver.
    - Führt den Datenbank-Löschvorgang thread-safe über SessionLocal und in einem separaten Thread aus (asyncio.to_thread).
    """
    while True:
        now = datetime.now(tz=timezone.utc)
        target = datetime.combine(now.date(), time(2, 0, tzinfo=timezone.utc))
        if now >= target:
            # Wenn 02:00 Uhr heute bereits vorbei ist, planen wir für morgen
            target = datetime.combine(now.date() + timedelta(days=1), time(2, 0, tzinfo=timezone.utc))
        
        # Berechnet die Sekunden bis zum nächsten Lauf und schläft asynchron
        seconds_to_sleep = (target - now).total_seconds()
        await asyncio.sleep(seconds_to_sleep)
        
        try:
            # Sichere DB-Session für den Hintergrund-Thread öffnen
            with SessionLocal() as db:
                await asyncio.to_thread(rotate_daily_hmac_key, db)
            logger.info("Tägliche HMAC-Key-Rotation erfolgreich durchgeführt.")
        except Exception as e:
            logger.error(f"Kritischer Fehler bei der täglichen Key-Rotation: {e}")
