"""
watcher.py — Background thread that polls for expired timers.

Runs as a daemon thread started at application startup.
One iteration per second; each iteration is O(n) in monitor count
but does only lightweight Redis key checks — negligible in practice.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timezone

import httpx

from app.store.redis_store import RedisStore

logger = logging.getLogger("watcher")


def _fire_alert(monitor, store: RedisStore) -> None:
    payload = {
        "ALERT": f"Device {monitor.id} is down!",
        "time": datetime.now(timezone.utc).isoformat(),
        "alert_email": monitor.alert_email,
        "alert_count": monitor.alert_count,
    }
    # Required by spec
    logger.critical(json.dumps(payload))

    # Developer's Choice: push to webhook if configured
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
