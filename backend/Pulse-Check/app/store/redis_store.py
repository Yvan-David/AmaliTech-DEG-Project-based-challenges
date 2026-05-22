"""

Key schema (two keys per monitor):
  monitor:{id}        → JSON blob, no TTL  — source of truth, survives expiry
  monitor:{id}:timer  → tiny key, TTL=timeout — its disappearance IS the alert

"""

from __future__ import annotations

from typing import Optional

import redis as _redis

from app.models.monitor import Monitor, MonitorStatus


def _mkey(id: str) -> str:
    return f"monitor:{id}"


def _tkey(id: str) -> str:
    return f"monitor:{id}:timer"


class RedisStore:
    def __init__(self, client: _redis.Redis) -> None:
        self._r = client


    def _load(self, id: str) -> Optional[Monitor]:
        raw = self._r.get(_mkey(id))
        if not raw:
            return None
        return Monitor.model_validate_json(raw)

    def _save(self, monitor: Monitor) -> None:
        self._r.set(_mkey(monitor.id), monitor.model_dump_json())

    def _arm_timer(self, id: str, timeout: int) -> None:
        """Set/reset the TTL key — when it vanishes the watcher fires."""
        self._r.setex(_tkey(id), timeout, "1")

    def _disarm_timer(self, id: str) -> None:
        self._r.delete(_tkey(id))

    def create(self, monitor: Monitor) -> None:
        self._save(monitor)
        self._arm_timer(monitor.id, monitor.timeout)

    def get(self, id: str) -> Optional[Monitor]:
        return self._load(id)

    def exists(self, id: str) -> bool:
        return bool(self._r.exists(_mkey(id)))

    def save_and_rearm(self, monitor: Monitor) -> None:
        """Persist updated monitor data and reset the countdown."""
        self._save(monitor)
        self._arm_timer(monitor.id, monitor.timeout)

    def save_and_disarm(self, monitor: Monitor) -> None:
        """Persist updated monitor data and stop the countdown (pause)."""
        self._save(monitor)
        self._disarm_timer(monitor.id)

    def mark_down(self, id: str) -> Optional[Monitor]:
        """
        Called by the watcher when a timer expires.
        Returns the updated monitor, or None if it should not alert
        (already paused, already down, or deleted).
        """
        monitor = self._load(id)
        if not monitor or monitor.status != MonitorStatus.active:
            return None
        monitor.status = MonitorStatus.down
        monitor.alert_count += 1
        self._save(monitor)
        return monitor

    def delete(self, id: str) -> bool:
        if not self.exists(id):
            return False
        self._disarm_timer(id)
        self._r.delete(_mkey(id))
        return True

    def get_expired_ids(self) -> list[str]:
        """
        scan — find active monitors whose timer key has disappeared.
        Called once per second by the watcher; n is total monitor count.
        """
        expired: list[str] = []
        # KEYS is fine for moderate n; swap for SCAN in production
        for raw_key in self._r.keys("monitor:*"):
            key = raw_key.decode()
            if ":timer" in key:
                continue                          # skip timer keys
            id_ = key[len("monitor:"):]
            monitor = self._load(id_)
            if monitor and monitor.status == MonitorStatus.active:
                if not self._r.exists(_tkey(id_)):  # timer gone → expired
                    expired.append(id_)
        return expired

    def ttl(self, id: str) -> int:
        """Seconds remaining on the countdown; -2 if key is gone."""
        return self._r.ttl(_tkey(id))
