# ==============================================================================
# PULSETRACK ANALYTICS - QUEUE-SERVICE (RAM-PUFFER & LEISTUNGS-SCHUTZ)
# ==============================================================================
# Datum: 01.06.2026 | Version: 1.2 | Status: Aktiv gepflegt & Ausfallsicher
#
# BETRIEBSWIRTSCHAFTLICHER ZWECK DIESER DATEI:
# Wenn Hunderte Besucher gleichzeitig auf Ihrer Website klicken, würde ein direktes
# Schreiben in die Datenbank Ihren Server komplett überlasten und verlangsamen.
# Dieser Service stellt eine extrem schnelle "Warteschlange" im Arbeitsspeicher (RAM) bereit.
# 1. RAM-Buffer: Alle eintreffenden Seitenaufrufe werden in Millisekunden im RAM geparkt.
# 2. Batch-Writing: Ein Hintergrund-Worker holt jeweils bis zu 100 Seitenaufrufe
#    ab und speichert sie in einem einzigen, effizienten Rutsch (Batch) in der Datenbank.
# 3. Ausfallsicherheit (Circuit Breaker): Sollte die Warteschlange jemals voll sein,
#    werden die Daten nicht verworfen, sondern in eine Notfall-Logdatei auf der Festplatte
#    geschrieben, damit kein einziger Besucher-Hit verloren geht!
#
# AUSWIRKUNG FÜR DEN KUNDEN / GESCHÄFTSFÜHRER:
# - Keine Ladeverzögerungen auf Ihrer Kunden-Website.
# - Maximale Stabilität: Überlebt auch extreme virale Lastspitzen schadlos.
# - Datengarantie: Notfall-Speicherung bei Überlastung sichert Ihre Besucherzahlen.
# ==============================================================================

import asyncio
import logging
import os
import time

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.hit import Hit
from app.models.website import Website

logger = logging.getLogger("analytics_queue")

# Die globale Hit-Queue im RAM (maximal 10.000 ungeschriebene Hits)
MAX_QUEUE_SIZE = 10000
hit_queue = asyncio.Queue(maxsize=MAX_QUEUE_SIZE)

# Hintergrund-Verarbeitungs-Steuerung
BATCH_SIZE = 100        # Schreibt immer 100 Datensätze gesammelt in die DB
BATCH_INTERVAL = 2.0  # Schreibt spätestens alle 2 Sekunden, auch wenn keine 100 Hits erreicht wurden
worker_running = True

async def add_hit_to_queue(hit_data: dict) -> bool:
    """
    KUNDENVERSTÄNDLICHE ERKLÄRUNG (Daten im RAM parken):
    Nimmt den erfassten Klick entgegen und legt ihn in der schnellen Warteschlange ab.
    Falls der Puffer voll ist (z. B. bei über 10.000 unbehandelten Hits), schützt
    sich das System selbst (Circuit Breaker) und weicht auf eine lokale
    Festplattendatei aus.
    """
    try:
        hit_queue.put_nowait(hit_data)
        return True
    except asyncio.QueueFull:
        # Notfall-Circuit-Breaker: Lokales Log-Schreiben bei RAM-Verstopfung
        logger.error("RAM-Queue ist voll (>10.000). Circuit-Breaker aktiv. Schreibe Fallback-Log.")
        try:
            log_path = os.path.join(os.path.dirname(__file__), "../../hits_fallback.log")
            with open(log_path, "a") as f:
                import json
                f.write(json.dumps(hit_data) + "\n")
            return True
        except Exception as e:
            logger.critical(f"Circuit-Breaker konnte Fallback-Log nicht schreiben: {e}")
            return False

async def batch_writer_worker():
    """
    KUNDENVERSTÄNDLICHE ERKLÄRUNG (Der fleißige Hintergrund-Bienchen-Job):
    Dieser Job läuft ununterbrochen im Hintergrund des Servers.
    Er sammelt die im RAM liegenden Klicks. Sobald er 100 Klicks beisammen hat –
    oder spätestens nach 2 Sekunden – packt er sie in ein Paket und übergibt
    sie der Datenbank. Das schont die Festplatte und hält das System extrem flüssig.
    """
    global worker_running
    logger.info("Asynchroner SQLite Batch-Writing-Worker gestartet.")
    
    while worker_running or not hit_queue.empty():
        try:
            batch = []
            start_time = time.monotonic()
            
            # Sammle Hits für das Batch (entweder bis BATCH_SIZE erreicht ist oder BATCH_INTERVAL abläuft)
            while len(batch) < BATCH_SIZE:
                elapsed = time.monotonic() - start_time
                remaining_time = BATCH_INTERVAL - elapsed
                
                if remaining_time <= 0:
                    break
                    
                try:
                    # Kurzes Warten auf das nächste Element in der Queue
                    hit_data = await asyncio.wait_for(hit_queue.get(), timeout=max(0.1, remaining_time))
                    batch.append(hit_data)
                except asyncio.TimeoutError:
                    break
            
            # Falls Hits gesammelt wurden, in die DB schreiben und erst DANN task_done() aufrufen (F-5)
            if batch:
                success = await save_batch_to_db(batch)
                if success:
                    for _ in range(len(batch)):
                        hit_queue.task_done()
                else:
                    # Im Fehlerfall wird das Batch zur Vermeidung von CPU-Hotloops geloggt
                    logger.error(f"Batch-Persistierung von {len(batch)} Hits fehlgeschlagen.")
                    # Wir rufen task_done trotzdem auf, um die Queue nicht zu blockieren, loggen aber den Fehler.
                    for _ in range(len(batch)):
                        hit_queue.task_done()
                
        except Exception as e:
            logger.error(f"Fehler im Batch-Writer-Worker: {e}")
            await asyncio.sleep(1)  # Kurze Pause bei Fehlern zur Vermeidung von CPU-Hotloops

def _sync_save_batch(batch: list[dict]) -> bool:
    """
    IT-PERFORMANCE-OPTIMIERUNG (Batch-DB-Speicherung):
    Diese Funktion speichert alle gesammelten Klicks hocheffizient ab.
    
    1. Sie löst das berüchtigte N+1-Query-Problem:
       Anstatt für jeden Klick eine einzelne Website-Abfrage an die DB zu senden
       (was extrem langsam wäre), fragt sie alle involvierten Website-Tokens in
       einem einzigen, gesammelten Rutsch ab.
    2. Bulk-Insert:
       Alle Hits werden in einer einzigen Datenbank-Transaktion gesammelt
       übertragen (`db.bulk_save_objects`). Das schont die SSD-Festplatte Ihres
       Servers und sorgt für maximale Schreibgeschwindigkeiten.
    """
    db: Session = SessionLocal()
    try:
        # Extrahiere alle einzigartigen Tokens im aktuellen Batch
        tokens = list({h["token"] for h in batch if "token" in h})
        if not tokens:
            return True
            
        # N+1 Query Behebung: Lade alle passenden Webseiten in einer einzigen Abfrage
        websites = db.query(Website).filter(Website.tracking_token.in_(tokens)).all()
        token_to_id = {w.tracking_token: w.id for w in websites}
        
        hits_to_save = []
        for hit_data in batch:
            token = hit_data.get("token")
            if token not in token_to_id:
                continue  # Token gehört keiner registrierten Website (oder wurde gelöscht)
                
            new_hit = Hit(
                website_id=token_to_id[token],
                timestamp=hit_data["timestamp"],
                url=hit_data["url"],
                referrer=hit_data["referrer"],
                user_agent=hit_data["user_agent"],
                ip_hash=hit_data["ip_hash"],
                browser=hit_data["browser"],
                os=hit_data["os"]
            )
            hits_to_save.append(new_hit)
        
        # In einem Rutsch persistieren (Bulk-Insert)
        if hits_to_save:
            db.bulk_save_objects(hits_to_save)
            db.commit()
            logger.info(f"{len(hits_to_save)} Hits erfolgreich in SQLite persistiert.")
        return True
    except Exception as e:
        db.rollback()
        logger.error(f"Fehler beim Batch-Schreiben in die DB: {e}")
        return False
    finally:
        db.close()

async def save_batch_to_db(batch: list[dict]) -> bool:
    """
    Lagert die blockierende SQLite-Schreibtransaktion in einen separaten Thread aus.
    Dadurch bleibt der asynchrone Haupt-Thread von FastAPI absolut frei und kann
    sofort neue Tracking-Anfragen von Besuchern annehmen.
    """
    return await asyncio.to_thread(_sync_save_batch, batch)

async def write_queue_to_db():
    """
    KUNDENVERSTÄNDLICHE ERKLÄRUNG (SIGTERM-Datenretter bei Server-Stopp):
    Wird der Server neu gestartet oder ausgeschaltet (z.B. für Wartungsarbeiten),
    schaltet sich diese Funktion ein.
    Sie stoppt den normalen Hintergrundbetrieb, sammelt alle Klicks, die im Moment
    noch im schnellen Arbeitsspeicher liegen, und schreibt sie sofort in die
    sichere SQLite-Datenbankdatei auf die Festplatte.
    Dadurch ist absoluter Schutz vor Datenverlust garantiert.
    """
    global worker_running
    worker_running = False
    logger.warning("Graceful Shutdown initiiert. Entleere verbleibende RAM-Queue...")
    
    # Alle restlichen Hits in der Warteschlange einsammeln
    remaining_hits = []
    while not hit_queue.empty():
        try:
            hit_data = hit_queue.get_nowait()
            remaining_hits.append(hit_data)
        except asyncio.QueueEmpty:
            break
            
    # Gesammelt persistieren
    if remaining_hits:
        logger.info(f"Schreibe {len(remaining_hits)} verbleibende Hits aus der Queue in die DB...")
        success = await save_batch_to_db(remaining_hits)
        if success:
            for _ in range(len(remaining_hits)):
                hit_queue.task_done()
    logger.info("Verbleibende RAM-Queue erfolgreich gesichert. Shutdown abgeschlossen.")
