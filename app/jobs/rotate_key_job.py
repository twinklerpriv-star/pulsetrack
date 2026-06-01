# app/jobs/rotate_key_job.py
"""Daily HMAC key rotation job.
Runs once per day (02:00 UTC) and calls the security service to clean
old keys. This is scheduled in the FastAPI lifespan handler.
"""
import asyncio
from datetime import datetime, time, timezone

from app.services.security import rotate_daily_hmac_key

async def schedule_daily_rotation():
    """Continuously schedule the daily rotation at 02:00 UTC.
    The coroutine sleeps until the next scheduled time, runs the rotation
    and repeats.
    """
    while True:
        now = datetime.now(tz=timezone.utc)
        target = datetime.combine(now.date(), time(2, 0, tzinfo=timezone.utc))
        if now >= target:
            # If we passed today's 02:00, schedule for tomorrow
            target = datetime.combine(now.date() + timedelta(days=1), time(2, 0, tzinfo=timezone.utc))
        await asyncio.sleep((target - now).total_seconds())
        try:
            await rotate_daily_hmac_key()
        except Exception as e:
            # Log the error; using standard logging
            import logging
            logging.getLogger("analytics_key_rotation").error(f"Key rotation failed: {e}")
