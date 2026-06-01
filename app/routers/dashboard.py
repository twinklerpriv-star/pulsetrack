# ==============================================================================
# API-ROUTER: DASHBOARD-STATISTIKEN & MULTI-TENANT-DATENAGGREGATION
# ==============================================================================
# Datum: 01.06.2026 | Version: 1.1 | Status: Aktiv gepflegt
#
# BETRIEBSWIRTSCHAFTLICHER ZWECK DIESER DATEI:
# Diese Datei sammelt, filtert und berechnet alle Analytics-Daten, die im interaktiven
# Dashboard des Kunden angezeigt werden. Sie extrahiert die Gesamtbesucher,
# die Unique Visitors, die Live-Zahlen (letzte 5 Minuten), die beliebtesten
# Unterseiten, die Herkunftskanäle sowie Browser- und Betriebssystem-Verteilungen.
#
# MULTI-TENANCY DATENISOLIERUNG (ABSOLUTE MANDANTENFÄHIGKEIT):
# KUNDENVERSTÄNDLICHE ERKLÄRUNG:
# Bei einem SaaS-System teilen sich alle Kunden dieselbe Datenbank. Daher ist es
# lebenswichtig zu verhindern, dass ein Kunde jemals die Besucherzahlen eines
# anderen Kunden einsehen kann.
# Diese Datei garantiert eine 100%ige Datentrennung: Vor jeder Datenberechnung
# wird streng geprüft, ob die angefragte Website tatsächlich dem eingeloggten
# B2B-Konto gehört. Ist das nicht der Fall, wird der Zugriff sofort verweigert (HTTP 403).
# ==============================================================================

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.hit import Hit
from app.models.website import Website
from app.routers.auth import get_current_user_id

logger = logging.getLogger("analytics_dashboard")
router = APIRouter(tags=["Dashboard Stats"])

@router.get("/api/dashboard/stats")
def get_dashboard_stats(
    website_id: int = Query(..., description="Die ID der zu analysierenden Website"),
    period: str = Query("30d", description="Zeitfenster: '24h', '7d', '30d', '12m'"),
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id)
):
    """
    KUNDENVERSTÄNDLICHE ERKLÄRUNG (Dashboard-Zahlen aggregieren):
    Berechnet alle Statistiken für Ihre Website.
    1. Validiert den sicheren Mandantenbesitz (siehe oben).
    2. Filtert die Klicks nach dem gewünschten Zeitraum (z. B. letzte 30 Tage).
    3. Zählt die Gesamtzahl der Klicks (Pageviews).
    4. Zählt die Unique Visitors (Besucher, ermittelt durch die einzigartigen IP-Hashes).
    5. Zählt die Live-Besucher, die in den letzten 5 Minuten aktiv waren.
    6. Gruppiert und sortiert die Top-Seiten, Top-Referrer, Browser und Betriebssysteme.
    """
    # 1. Verifizieren, ob die Website existiert und dem angemeldeten User gehört (Mandantencheck)
    website = db.query(Website).filter(Website.id == website_id).first()
    if not website:
        raise HTTPException(status_code=404, detail="Website wurde nicht gefunden.")
        
    if website.user_id != user_id:
        logger.warning(f"Zugriff verweigert: User {user_id} versucht auf Website {website_id} zuzugreifen.")
        raise HTTPException(status_code=403, detail="Kein Zugriff auf diese Website-Daten gestattet.")

    # 2. Zeitfenster-Filter berechnen (ISO-Format für SQLite-Vergleich)
    now = datetime.now(tz=timezone.utc).replace(tzinfo=None)
    if period == "24h":
        start_date = now - timedelta(hours=24)
    elif period == "7d":
        start_date = now - timedelta(days=7)
    elif period == "12m":
        start_date = now - timedelta(days=365)
    else:  # Default: 30 Tage
        start_date = now - timedelta(days=30)
        
    start_date_str = start_date.isoformat()

    try:
        # Basis-Datenbankabfrage mit Zeitraumfilter
        base_query = db.query(Hit).filter(Hit.website_id == website_id, Hit.timestamp >= start_date_str)

        # 3. Gesamt-Seitenaufrufe (Hits)
        total_pageviews = base_query.count()
        
        # Einzigartige Besucher (Uniques) berechnen:
        # Zählt die einzigartigen (distinct) IP-Hashes. Dadurch wird ein wiederholter
        # Aufruf desselben Besuchers am selben Tag nur als 1 unique Visitor gezählt.
        unique_visitors = db.query(func.count(func.distinct(Hit.ip_hash))).filter(
            Hit.website_id == website_id, 
            Hit.timestamp >= start_date_str
        ).scalar() or 0

        # 4. Live-Besucher in Echtzeit (Klicks der letzten 5 Minuten)
        five_min_ago = (now - timedelta(minutes=5)).isoformat()
        live_visitors = db.query(func.count(func.distinct(Hit.ip_hash))).filter(
            Hit.website_id == website_id, 
            Hit.timestamp >= five_min_ago
        ).scalar() or 0

        # 5. Top 5 Unterseiten (gruppiert nach URL, sortiert nach Klicks)
        top_pages = db.query(
            Hit.url, 
            func.count(Hit.id).label("count")
        ).filter(
            Hit.website_id == website_id, 
            Hit.timestamp >= start_date_str
        ).group_by(Hit.url).order_by(func.count(Hit.id).desc()).limit(5).all()

        # 6. Top 5 Herkunftsquellen (Referrers)
        top_referrers = db.query(
            Hit.referrer, 
            func.count(Hit.id).label("count")
        ).filter(
            Hit.website_id == website_id, 
            Hit.timestamp >= start_date_str
        ).group_by(Hit.referrer).order_by(func.count(Hit.id).desc()).limit(5).all()

        # 7. Verteilung der Browser
        browsers = db.query(
            Hit.browser, 
            func.count(Hit.id).label("count")
        ).filter(
            Hit.website_id == website_id, 
            Hit.timestamp >= start_date_str
        ).group_by(Hit.browser).order_by(func.count(Hit.id).desc()).all()

        # 8. Verteilung der Betriebssysteme (OS)
        operating_systems = db.query(
            Hit.os, 
            func.count(Hit.id).label("count")
        ).filter(
            Hit.website_id == website_id, 
            Hit.timestamp >= start_date_str
        ).group_by(Hit.os).order_by(func.count(Hit.id).desc()).all()

        # Formatierte JSON-Rückgabe für das Frontend
        return {
            "website_id": website_id,
            "domain": website.domain,
            "total_hits": total_pageviews,
            "unique_visitors": unique_visitors,
            "live_visitors": live_visitors,
            "top_pages": [{"url": row[0], "count": row[1]} for row in top_pages],
            "top_referrers": [{"referrer": row[0] or "Direct / Bookmark", "count": row[1]} for row in top_referrers],
            "browsers": [{"browser": row[0] or "Other", "count": row[1]} for row in browsers],
            "operating_systems": [{"os": row[0] or "Other", "count": row[1]} for row in operating_systems]
        }
    except Exception as e:
        logger.error(f"Fehler bei der Datenaggregation für Website {website_id}: {e}")
        raise HTTPException(status_code=500, detail="Fehler bei der Generierung der Statistiken.")


@router.get("/api/demo/stats")
def get_demo_stats():
    """
    KUNDENVERSTÄNDLICHE ERKLÄRUNG (Realistische Demo-Statistiken):
    Dieser Endpoint wird für die öffentliche Live-Demo auf der Landingpage verwendet.
    Er greift nicht auf Ihre echten Kundendaten zu, sondern simuliert dynamische
    Besucherzahlen mit realistischen, leichten Schwankungen basierend auf der aktuellen Sekunde.
    Dies ermöglicht es Interessenten, das PulseTrack-Dashboard sofort live auszuprobieren,
    ohne dass wir eine Test-Website verkabeln oder echten Traffic erzeugen müssen.
    """
    import random
    from datetime import datetime, timezone
    
    # Basiswerte für die Simulation
    base_hits = 12450
    base_uniques = 3820
    
    # Kleine zufällige Schwankungen basierend auf der aktuellen Sekunde erzeugen
    sec = datetime.now(tz=timezone.utc).second
    hits_variation = int(random.uniform(5, 50) * (sec + 1))
    uniques_variation = int(hits_variation * 0.3)
    
    # Live-Besucher dynamisch schwanken lassen (12 bis ca. 55 Besucher online)
    live_visitors = int(random.uniform(12, 45) + (sec % 10))
    
    # Top Seiten simulieren
    top_pages = [
        {"url": "https://demo.pulsetrack.io/", "count": int(random.uniform(3000, 4000))},
        {"url": "https://demo.pulsetrack.io/blog/cookie-free-tracking", "count": int(random.uniform(1500, 2000))},
        {"url": "https://demo.pulsetrack.io/pricing", "count": int(random.uniform(800, 1200))},
        {"url": "https://demo.pulsetrack.io/setup", "count": int(random.uniform(500, 700))},
        {"url": "https://demo.pulsetrack.io/demo", "count": int(random.uniform(300, 500))}
    ]
    top_pages.sort(key=lambda x: x["count"], reverse=True)

    # Top Herkunftsquellen simulieren
    top_referrers = [
        {"referrer": "Direct / Bookmark", "count": int(random.uniform(4000, 5000))},
        {"referrer": "https://google.com", "count": int(random.uniform(2500, 3500))},
        {"referrer": "https://github.com", "count": int(random.uniform(1200, 1800))},
        {"referrer": "https://twitter.com", "count": int(random.uniform(800, 1200))},
        {"referrer": "https://news.ycombinator.com", "count": int(random.uniform(500, 900))}
    ]
    top_referrers.sort(key=lambda x: x["count"], reverse=True)

    # Browser simulieren
    browsers = [
        {"browser": "Chrome", "count": int(random.uniform(5000, 6000))},
        {"browser": "Firefox", "count": int(random.uniform(2000, 2500))},
        {"browser": "Safari", "count": int(random.uniform(1500, 2000))},
        {"browser": "Edge", "count": int(random.uniform(800, 1200))},
        {"browser": "Other", "count": int(random.uniform(200, 500))}
    ]
    browsers.sort(key=lambda x: x["count"], reverse=True)

    # Betriebssysteme simulieren
    operating_systems = [
        {"os": "Windows", "count": int(random.uniform(4000, 5000))},
        {"os": "macOS", "count": int(random.uniform(2500, 3500))},
        {"os": "Linux", "count": int(random.uniform(1200, 1800))},
        {"os": "iOS", "count": int(random.uniform(800, 1200))},
        {"os": "Android", "count": int(random.uniform(700, 1100))}
    ]
    operating_systems.sort(key=lambda x: x["count"], reverse=True)

    return {
        "website_id": 999,
        "domain": "https://demo.pulsetrack.io",
        "total_hits": base_hits + hits_variation,
        "unique_visitors": base_uniques + uniques_variation,
        "live_visitors": live_visitors,
        "top_pages": top_pages,
        "top_referrers": top_referrers,
        "browsers": browsers,
        "operating_systems": operating_systems
    }
