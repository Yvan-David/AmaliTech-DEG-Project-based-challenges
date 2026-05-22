from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

from app.mailer import send_alert_email
from app.store.redis_store import RedisStore

logger = logging.getLogger("watcher")

CAT = ZoneInfo("Africa/Kigali")  # UTC+2, no DST


def _readable_time() -> str:
    now_cat = datetime.now(CAT)
    # %-I is Linux only; this works on all platforms
    hour = now_cat.strftime("%I").lstrip("0") or "12"
    return now_cat.strftime(f"%A, %d %b %Y at {hour}:%M %p")


def _fire_alert(monitor, store: RedisStore) -> None:
    alert_time = _readable_time()

    payload = {
        "ALERT": f"Device {monitor.id} is down!",
        "time": alert_time,
        "alert_email": monitor.alert_email,
        "alert_count": monitor.alert_count,
    }

    # Required by spec — always runs
    logger.critical(json.dumps(payload))

    # Email — always attempt, logs its own errors
    send_alert_email(
        to=monitor.alert_email,
        device_id=monitor.id,
        alert_time=alert_time,
        alert_count=monitor.alert_count,
    )

    # Webhook — optional, attempt only if configured
    if monitor.webhook_url:
        logger.info("Firing webhook for %s → %s", monitor.id, monitor.webhook_url)
        try:
            response = httpx.post(monitor.webhook_url, json=payload, timeout=5)
            response.raise_for_status()          # ← surface 4xx/5xx as exceptions
            logger.info("Webhook delivered → %s (HTTP %s)", monitor.webhook_url, response.status_code)
        except httpx.HTTPStatusError as exc:
            logger.error(
                "Webhook rejected for %s: HTTP %s from %s",
                monitor.id, exc.response.status_code, monitor.webhook_url,
            )
        except Exception as exc:
            logger.error("Webhook failed for %s: %s", monitor.id, exc)


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
                logger.error("Watcher poll error: %s", exc)
            time.sleep(interval)

    t = threading.Thread(target=loop, daemon=True)
    t.start()
    return t
