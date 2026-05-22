"""
two-key Redis
scheme (data key + TTL key). The watcher thread plays the role that
CancelledError + sleep() played before — detecting expiry and firing alerts.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional, Tuple

from app.models.monitor import Monitor, MonitorCreate, MonitorStatus
from app.store.redis_store import RedisStore

_store: RedisStore | None = None


def init(store: RedisStore) -> None:
    """Call once at startup to inject the store."""
    global _store
    _store = store


def _store_or_raise() -> RedisStore:
    if _store is None:
        raise RuntimeError("monitor_service not initialised — call init() first")
    return _store


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _expires_at(timeout: int) -> datetime:
    return datetime.fromtimestamp(_utc_now().timestamp() + timeout, tz=timezone.utc)


def register(data: MonitorCreate) -> Tuple[Monitor, bool]:
    """ — create or replace a monitor."""
    store = _store_or_raise()
    existed = store.exists(data.id)

    monitor = Monitor(
        id=data.id,
        timeout=data.timeout,
        alert_email=data.alert_email,
        webhook_url=data.webhook_url,
        status=MonitorStatus.active,
        created_at=_utc_now(),
        expires_at=_expires_at(data.timeout),
    )
    store.create(monitor)
    return monitor, not existed


def heartbeat(monitor_id: str) -> Optional[Monitor]:
    """
     — reset the countdown.
    Un-pauses a paused monitor automatically.
    Returns None when the monitor is down or doesn't exist.
    """
    store = _store_or_raise()
    monitor = store.get(monitor_id)

    if not monitor or monitor.status == MonitorStatus.down:
        return None

    monitor.status = MonitorStatus.active
    monitor.last_heartbeat = _utc_now()
    monitor.expires_at = _expires_at(monitor.timeout)
    store.save_and_rearm(monitor)
    return monitor


def pause(monitor_id: str) -> Optional[Monitor]:
    """ — freeze the countdown. No-op if already paused."""
    store = _store_or_raise()
    monitor = store.get(monitor_id)

    if not monitor:
        return None

    if monitor.status == MonitorStatus.active:
        monitor.status = MonitorStatus.paused
        store.save_and_disarm(monitor)

    return monitor


def get_one(monitor_id: str) -> Optional[Monitor]:
    """ — single lookup."""
    return _store_or_raise().get(monitor_id)


def get_all() -> List[Monitor]:
    """ — full scan, unavoidable."""
    store = _store_or_raise()
    result = []
    for raw_key in store._r.keys("monitor:*"):
        key = raw_key.decode()
        if ":timer" in key:
            continue
        id_ = key[len("monitor:"):]
        m = store.get(id_)
        if m:
            result.append(m)
    return result


def delete(monitor_id: str) -> bool:
    """ — remove monitor and cancel its timer."""
    return _store_or_raise().delete(monitor_id)

def reset(monitor_id: str) -> Optional[Monitor]:
    """
    O(1) — recover a downed monitor.
    Restarts the timer and sets status back to active.
    Preserves all config and keeps alert_count as historical record.
    Only valid when status is 'down'.
    """
    store = _store_or_raise()
    monitor = store.get(monitor_id)

    if not monitor or monitor.status != MonitorStatus.down:
        return None

    monitor.status = MonitorStatus.active
    monitor.last_heartbeat = None       # device hasn't proven itself yet
    monitor.expires_at = _expires_at(monitor.timeout)
    store.save_and_rearm(monitor)
    return monitor

def get_ttl(monitor_id: str) -> int:
    """ — seconds remaining; -2 if expired/gone."""
    return _store_or_raise().ttl(monitor_id)
