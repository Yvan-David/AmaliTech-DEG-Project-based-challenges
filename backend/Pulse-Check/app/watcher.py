"""
watcher.py — Background thread that polls for expired timers.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo          # stdlib, Python 3.9+

import httpx

from app.mailer import send_alert_email
from app.store.redis_store import RedisStore

logger = logging.getLogger("watcher")

CAT = ZoneInfo("Africa/Kigali")        # UTC+2, no DST


def _readable_time() -> str:
    """Return current time in Rwanda as e.g. 'Monday, 23 Jun 2025 at 8:50 PM'"""
    now_cat = datetime.now(CAT)
    return now_cat.strftime("%A, %d %b %Y at %-I:%M %p")   # e.g. Monday, 23 Jun 2025 at 8:50 PM


def _fire_alert(monitor, store: RedisStore) -> None:
    alert_time = _readable_time()

    payload = {
        "ALERT": f"Device {monitor.id} is down!",
        "time": alert_time,
        "alert_email": monitor.alert_email,
        "alert_count": monitor.alert_count,
    }

    # Console log (required by spec)
    logger.critical(json.dumps(payload))

    # Real email alert
    send_alert_email(
        to=monitor.alert_email,
        device_id=monitor.id,
        alert_time=alert_time,
        alert_count=monitor.alert_count,
    )

    # Webhook (Developer's Choice)
    if monitor.webhook_url:
        try:
            httpx.post(monitor.webhook_url, json=payload, timeout=5)
            logger.info("Webhook delivered → %s", monitor.webhook_url)
        except Exception as exc:
            logger.warning("Webhook failed for %s: %s", monitor.id, exc)


def _poll(store: RedisStore) -> None:
    for id_ in store.get_expired_ids():
        monitor = store.mark_down(id_)
        if monitor:
            _fire_alert(monitor, store)


def start_watcher(store: RedisStore, interval: float = 1.0) -> threading.Thread:
    def loop() -> None:
        logger.info("Watcher started (interval=%.1fs)", interval)
        while True:
            try:
                _poll(store)
            except Exception as exc:
                logger.error("Watcher error: %s", exc)
            time.sleep(interval)

    t = threading.Thread(target=loop, daemon=True)
    t.start()
    return t
