"""
monitor_service.py — Core business logic for the Dead Man's Switch.

Data structure rationale (CS fundamentals):
  _monitors : dict[str, Monitor]  → hash map  → O(1) avg get / set / delete
  _tasks    : dict[str, Task]     → hash map  → O(1) avg get / set / delete

Every public operation exposed to routes is O(1).
The only O(n) operation is get_all(), which is unavoidable when returning
all n monitors — you must touch each element at least once.

Timer strategy: one asyncio.Task per monitor.
  • Registration  → create_task(sleep(timeout))           O(1)
  • Heartbeat     → task.cancel() + create_task(...)      O(1)
  • Pause         → task.cancel()                         O(1)
  • Alert         → task wakes, updates status, fires      O(1)

Alternative considered: a single global polling loop over all monitors.
  That would be O(n) per tick and add unnecessary latency. Per-task approach
  is strictly better when n is large and most monitors are healthy.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import httpx

from app.models.monitor import Monitor, MonitorCreate, MonitorStatus

logger = logging.getLogger(__name__)

# ── In-memory store ────────────────────────────────────────────────────────────
# Plain dicts give O(1) amortised lookup/insert/delete (CPython hash table).
_monitors: Dict[str, Monitor] = {}
_tasks: Dict[str, asyncio.Task] = {}


# ── Private helpers ────────────────────────────────────────────────────────────

def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _expires_at(timeout: int) -> datetime:
    return datetime.fromtimestamp(_utc_now().timestamp() + timeout, tz=timezone.utc)


def _cancel_task(monitor_id: str) -> None:
    """O(1) — look up and cancel an existing timer task."""
    task = _tasks.get(monitor_id)   # O(1)
    if task and not task.done():
        task.cancel()


async def _fire_alert(monitor_id: str) -> None:
    """
    O(1) — mark device down and dispatch the alert.
    Called only by _run_timer when the sleep completes without cancellation.
    """
    monitor = _monitors.get(monitor_id)   # O(1)
    if not monitor or monitor.status != MonitorStatus.active:
        return  # Guard: already paused, deleted, or re-registered mid-flight

    monitor.status = MonitorStatus.down
    monitor.alert_count += 1

    payload = {
        "ALERT": f"Device {monitor_id} is down!",
        "time": _utc_now().isoformat(),
        "alert_email": monitor.alert_email,
        "alert_count": monitor.alert_count,
    }

    # Required by spec: log the alert
    logger.critical(payload)
    print(payload)

    # Developer's Choice — also POST to a webhook URL if one was registered
    if monitor.webhook_url:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.post(monitor.webhook_url, json=payload)
                logger.info(
                    "Webhook fired for %s → HTTP %s", monitor_id, response.status_code
                )
        except Exception as exc:
            logger.error("Webhook delivery failed for %s: %s", monitor_id, exc)


async def _run_timer(monitor_id: str, timeout: int) -> None:
    """
    O(1) coroutine — sleep, then fire alert.
    CancelledError is the normal control path (heartbeat / pause / delete);
    it is silently swallowed so it doesn't pollute logs.
    """
    try:
        await asyncio.sleep(timeout)
        await _fire_alert(monitor_id)
    except asyncio.CancelledError:
        pass  # Expected: heartbeat / pause / delete cancelled us


def _schedule(monitor_id: str, timeout: int) -> asyncio.Task:
    """O(1) — create and register a new countdown task."""
    task = asyncio.create_task(_run_timer(monitor_id, timeout))
    _tasks[monitor_id] = task   # O(1)
    return task


# ── Public service API ─────────────────────────────────────────────────────────

def register(data: MonitorCreate) -> Tuple[Monitor, bool]:
    """
    O(1) — create or replace a monitor.

    Returns (monitor, created):
      created=True  → brand-new registration
      created=False → existing monitor replaced (idempotent re-register)
    """
    existed = data.id in _monitors   # O(1)
    _cancel_task(data.id)            # O(1) — safe no-op if nothing running

    monitor = Monitor(
        id=data.id,
        timeout=data.timeout,
        alert_email=data.alert_email,
        webhook_url=data.webhook_url,
        status=MonitorStatus.active,
        created_at=_utc_now(),
        expires_at=_expires_at(data.timeout),
    )
    _monitors[data.id] = monitor     # O(1)
    _schedule(data.id, data.timeout) # O(1)

    return monitor, not existed


def heartbeat(monitor_id: str) -> Optional[Monitor]:
    """
    O(1) — reset the countdown for an existing monitor.

    Side-effects:
      • Cancels the current timer task           O(1)
      • Starts a fresh timer task                O(1)
      • Un-pauses the monitor if it was paused
      • Updates last_heartbeat and expires_at

    Returns None when the monitor does not exist or is permanently down.
    """
    monitor = _monitors.get(monitor_id)   # O(1)
    if not monitor or monitor.status == MonitorStatus.down:
        return None

    _cancel_task(monitor_id)              # O(1)

    monitor.status = MonitorStatus.active  # un-pause if paused
    monitor.last_heartbeat = _utc_now()
    monitor.expires_at = _expires_at(monitor.timeout)

    _schedule(monitor_id, monitor.timeout)  # O(1)
    return monitor


def pause(monitor_id: str) -> Optional[Monitor]:
    """
    O(1) — freeze the countdown.
    No-op (still returns monitor) if already paused.
    Returns None when the monitor does not exist.
    """
    monitor = _monitors.get(monitor_id)   # O(1)
    if not monitor:
        return None

    if monitor.status == MonitorStatus.active:
        _cancel_task(monitor_id)           # O(1)
        monitor.status = MonitorStatus.paused

    return monitor


def get_one(monitor_id: str) -> Optional[Monitor]:
    """O(1) — single-monitor lookup."""
    return _monitors.get(monitor_id)   # O(1)


def get_all() -> List[Monitor]:
    """
    O(n) — return every monitor.
    This is unavoidable: any algorithm that reads all n items is at least O(n).
    """
    return list(_monitors.values())


def delete(monitor_id: str) -> bool:
    """
    O(1) — remove a monitor and cancel its timer.
    Returns False when the monitor does not exist.
    """
    if monitor_id not in _monitors:   # O(1)
        return False

    _cancel_task(monitor_id)          # O(1)
    del _monitors[monitor_id]         # O(1)
    _tasks.pop(monitor_id, None)      # O(1)
    return True
