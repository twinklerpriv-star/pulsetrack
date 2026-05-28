# Queue Service: Asynchrones Batch-Writing & Graceful Shutdown
#
# Datum: 28.05.2026 | Version: 1.0 | Status: Aktiv gepflegt

import asyncio
import logging
import os

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.hit import Hit
from app.models.website import Website

logger = logging.getLogger("analytics_queue")

# Die globale Hit-Queue im RAM (maximal 10.000 ungeschriebene Hits)
MAX_QUEUE_SIZE = 10000
hit_queue = asyncio.Queue(maxsize=MAX_QUEUE_SIZE)

# Hintergrund-Verarbeitungs-Steuerung
BATCH_SIZE = 100
BATCH_INTERVAL = 2.0  # Sekunden
worker_running = True

async def add_hit_to_queue(hit_data: dict) -> bool:
    """
    Reiht einen Hit in die RAM-Queue ein.
    Falls die Queue voll ist, schaltet der Circuit-Breaker aktiv und schreibt in ein Fallback-Log.
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
    Asynchroner Hintergrund-Worker.
    Liest kontinuierlich Hits aus der Queue und schreibt sie gesammelt in SQLite-Batches.
    """
    global worker_running
    logger.info("Asynchroner SQLite Batch-Writing-Worker gestartet.")
    
    while worker_running or not hit_queue.empty():
        try:
            batch = []
            start_time = asyncio.get_event_loop().time()
            
            # Sammle Hits für das Batch (entweder bis BATCH_SIZE erreicht ist oder BATCH_INTERVAL abläuft)
            while len(batch) < BATCH_SIZE:
                elapsed = asyncio.get_event_loop().time() - start_time
                remaining_time = BATCH_INTERVAL - elapsed
                
                if remaining_time <= 0:
                    break
                    
                try:
                    # Kurzes Warten auf das nächste Element in der Queue
                    hit_data = await asyncio.wait_for(hit_queue.get(), timeout=max(0.1, remaining_time))
                    batch.append(hit_data)
                    hit_queue.task_done()
                except asyncio.TimeoutError:
                    break
            
            # Falls Hits gesammelt wurden, in einer einzigen Transaktion in die DB schreiben
            if batch:
                await save_batch_to_db(batch)
                
        except Exception as e:
            logger.error(f"Fehler im Batch-Writer-Worker: {e}")
            await asyncio.sleep(1)  # Kurze Pause bei Fehlern zur Vermeidung von CPU-Hotloops

async def save_batch_to_db(batch: list[dict]):
    """Schreibt ein Hit-Batch über eine einzige transaktionale Session in die DB."""
    db: Session = SessionLocal()
    try:
        # Optimierter Batch-Import
        hits_to_save = []
        for hit_data in batch:
            # Website ID über das Token ermitteln
            website = db.query(Website).filter(Website.tracking_token == hit_data["token"]).first()
            if not website:
                continue  # Token existiert nicht mehr

            new_hit = Hit(
                website_id=website.id,
                timestamp=hit_data["timestamp"],
                url=hit_data["url"],
                referrer=hit_data["referrer"],
                user_agent=hit_data["user_agent"],
                ip_hash=hit_data["ip_hash"],
                browser=hit_data["browser"],
                os=hit_data["os"]
            )
            hits_to_save.append(new_hit)
        
        if hits_to_save:
            db.bulk_save_objects(hits_to_save)
            db.commit()
            logger.info(f"{len(hits_to_save)} Hits erfolgreich in SQLite persistiert.")
    except Exception as e:
        db.rollback()
        logger.error(f"Fehler beim Batch-Schreiben in die DB: {e}")
    finally:
        db.close()

async def write_queue_to_db():
    """
    Graceful Shutdown Logik (SIGTERM-Datenretter).
    Flusht bei Server-Stopp alle verbleibenden Hits restlos in die SQLite-Datenbank.
    """
    global worker_running
    worker_running = False
    logger.warning("Graceful Shutdown initiiert. Entleere verbleibende RAM-Queue...")
    
    # Restliche Hits einsammeln
    remaining_hits = []
    while not hit_queue.empty():
        try:
            hit_data = hit_queue.get_nowait()
            remaining_hits.append(hit_data)
            hit_queue.task_done()
        except asyncio.QueueEmpty:
            break
            
    if remaining_hits:
        logger.info(f"Schreibe {len(remaining_hits)} verbleibende Hits aus der Queue in die DB...")
        await save_batch_to_db(remaining_hits)
    logger.info("Verbleibende RAM-Queue erfolgreich gesichert. Shutdown abgeschlossen.")
