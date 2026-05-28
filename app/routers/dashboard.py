# API Router: Dashboard Statistiken & Multi-Tenant-Datenaggregation
#
# Datum: 28.05.2026 | Version: 1.0 | Status: Aktiv gepflegt

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
async def get_dashboard_stats(
    website_id: int = Query(..., description="Die ID der zu analysierenden Website"),
    period: str = Query("30d", description="Zeitfenster: '24h', '7d', '30d', '12m'"),
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id)
):
    """
    Aggregiert die Analytics-Daten für das Dashboard des Nutzers.
    Sichert über get_current_user_id die strenge Multi-Tenant-Datenisolierung ab.
    """
    # 1. Verifizieren, ob die Website existiert und dem angemeldeten User gehört
    website = db.query(Website).filter(Website.id == website_id).first()
    if not website:
        raise HTTPException(status_code=404, detail="Website not found.")
        
    if website.user_id != user_id:
        logger.warning(f"Zugriff verweigert: User {user_id} versucht auf Website {website_id} von User {website.user_id} zuzugreifen.")
        raise HTTPException(status_code=403, detail="Access denied to website data.")

    # 2. Zeitfenster-Filter berechnen (UTC ISO-Format)
    now = datetime.now(tz=timezone.utc).replace(tzinfo=None)
    if period == "24h":
        start_date = now - timedelta(hours=24)
    elif period == "7d":
        start_date = now - timedelta(days=7)
    elif period == "12m":
        start_date = now - timedelta(days=365)
    else:  # Default: 30d
        start_date = now - timedelta(days=30)
        
    start_date_str = start_date.isoformat()

    try:
        # Base-Query mit Zeitfilter
        base_query = db.query(Hit).filter(Hit.website_id == website_id, Hit.timestamp >= start_date_str)

        # 3. Total Pageviews & Uniques (Distinct IP hashes)
        total_pageviews = base_query.count()
        unique_visitors = db.query(func.count(func.distinct(Hit.ip_hash))).filter(
            Hit.website_id == website_id, 
            Hit.timestamp >= start_date_str
        ).scalar() or 0

        # 4. Live Besucher (Hits der letzten 5 Minuten)
        five_min_ago = (now - timedelta(minutes=5)).isoformat()
        live_visitors = db.query(func.count(func.distinct(Hit.ip_hash))).filter(
            Hit.website_id == website_id, 
            Hit.timestamp >= five_min_ago
        ).scalar() or 0

        # 5. Top Pages (Gruppiert und sortiert)
        top_pages = db.query(
            Hit.url, 
            func.count(Hit.id).label("count")
        ).filter(
            Hit.website_id == website_id, 
            Hit.timestamp >= start_date_str
        ).group_by(Hit.url).order_by(func.count(Hit.id).desc()).limit(5).all()

        # 6. Top Referrers
        top_referrers = db.query(
            Hit.referrer, 
            func.count(Hit.id).label("count")
        ).filter(
            Hit.website_id == website_id, 
            Hit.timestamp >= start_date_str
        ).group_by(Hit.referrer).order_by(func.count(Hit.id).desc()).limit(5).all()

        # 7. Browser-Verteilung
        browsers = db.query(
            Hit.browser, 
            func.count(Hit.id).label("count")
        ).filter(
            Hit.website_id == website_id, 
            Hit.timestamp >= start_date_str
        ).group_by(Hit.browser).order_by(func.count(Hit.id).desc()).all()

        # 8. OS-Verteilung
        operating_systems = db.query(
            Hit.os, 
            func.count(Hit.id).label("count")
        ).filter(
            Hit.website_id == website_id, 
            Hit.timestamp >= start_date_str
        ).group_by(Hit.os).order_by(func.count(Hit.id).desc()).all()

        # Rückgabe des formatierten JSONs
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
        raise HTTPException(status_code=500, detail="Error generating website statistics.")


@router.get("/api/demo/stats")
async def get_demo_stats():
    """
    Öffentlicher Demo-Endpoint.
    Liefert dynamische, realistische Besucherstatistiken zur Demonstration.
    """
    import random
    from datetime import datetime, timezone
    
    # Simuliere dynamisch schwankende Werte
    base_hits = 12450
    base_uniques = 3820
    
    # Kleine zufällige Schwankungen basierend auf der aktuellen Sekunde
    sec = datetime.now(tz=timezone.utc).second
    hits_variation = int(random.uniform(5, 50) * (sec + 1))
    uniques_variation = int(hits_variation * 0.3)
    
    live_visitors = int(random.uniform(12, 45) + (sec % 10))
    
    # Top Pages
    top_pages = [
        {"url": "https://demo.pulsetrack.io/", "count": int(random.uniform(3000, 4000))},
        {"url": "https://demo.pulsetrack.io/blog/cookie-free-tracking", "count": int(random.uniform(1500, 2000))},
        {"url": "https://demo.pulsetrack.io/pricing", "count": int(random.uniform(800, 1200))},
        {"url": "https://demo.pulsetrack.io/setup", "count": int(random.uniform(500, 700))},
        {"url": "https://demo.pulsetrack.io/demo", "count": int(random.uniform(300, 500))}
    ]
    top_pages.sort(key=lambda x: x["count"], reverse=True)

    # Top Referrers
    top_referrers = [
        {"referrer": "Direct / Bookmark", "count": int(random.uniform(4000, 5000))},
        {"referrer": "https://google.com", "count": int(random.uniform(2500, 3500))},
        {"referrer": "https://github.com", "count": int(random.uniform(1200, 1800))},
        {"referrer": "https://twitter.com", "count": int(random.uniform(800, 1200))},
        {"referrer": "https://news.ycombinator.com", "count": int(random.uniform(500, 900))}
    ]
    top_referrers.sort(key=lambda x: x["count"], reverse=True)

    # Browsers
    browsers = [
        {"browser": "Chrome", "count": int(random.uniform(5000, 6000))},
        {"browser": "Firefox", "count": int(random.uniform(2000, 2500))},
        {"browser": "Safari", "count": int(random.uniform(1500, 2000))},
        {"browser": "Edge", "count": int(random.uniform(800, 1200))},
        {"browser": "Other", "count": int(random.uniform(200, 500))}
    ]
    browsers.sort(key=lambda x: x["count"], reverse=True)

    # OS
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
