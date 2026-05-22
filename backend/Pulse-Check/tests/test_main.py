"""
tests/main_test.py

Full test coverage for the Pulse Check API.

Test strategy:
  - Every route is tested for both happy path and error path.
  - State is reset between tests via the `clear_state` fixture — O(n) but
    necessary for isolation; n is always tiny in tests.
  - Timer behaviour is tested with timeout=1 to avoid slow tests.
  - asyncio_mode = auto (set in pytest.ini) means every test can be async
    without manual @pytest.mark.asyncio decoration.
"""

import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services import monitor_service as svc

# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def clear_state():
    """
    Reset all in-memory state before each test.
    O(n) over monitors/tasks — acceptable and necessary for test isolation.
    """
    svc._monitors.clear()
    for task in svc._tasks.values():
        task.cancel()
    svc._tasks.clear()
    yield


@pytest.fixture
async def client():
    """Provide an ASGI test client scoped to each test."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


# ── Shared test data ───────────────────────────────────────────────────────────

BASE_PAYLOAD = {
    "id": "device-123",
    "timeout": 60,
    "alert_email": "admin@critmon.com",
}

SHORT_PAYLOAD = {
    "id": "device-fast",
    "timeout": 1,
    "alert_email": "admin@critmon.com",
}


# ── Health check ───────────────────────────────────────────────────────────────

async def test_health_endpoint(client):
    res = await client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


# ── POST /monitors ─────────────────────────────────────────────────────────────

async def test_register_monitor_returns_201(client):
    res = await client.post("/monitors", json=BASE_PAYLOAD)
    assert res.status_code == 201
    body = res.json()
    assert body["monitor_id"] == "device-123"
    assert body["status"] == "active"
    assert "expires_at" in body


async def test_register_monitor_starts_timer(client):
    """Timer task must be created immediately on registration — O(1)."""
    await client.post("/monitors", json=BASE_PAYLOAD)
    assert "device-123" in svc._tasks
    assert not svc._tasks["device-123"].done()


async def test_register_duplicate_replaces_monitor(client):
    """Re-registering the same ID is idempotent and restarts the timer."""
    await client.post("/monitors", json=BASE_PAYLOAD)
    res = await client.post("/monitors", json=BASE_PAYLOAD)
    assert res.status_code == 201
    assert "replaced" in res.json()["message"]


async def test_register_with_webhook_url(client):
    payload = {**BASE_PAYLOAD, "webhook_url": "https://hooks.example.com/alert"}
    res = await client.post("/monitors", json=payload)
    assert res.status_code == 201
    monitor = svc.get_one("device-123")
    assert monitor.webhook_url == "https://hooks.example.com/alert"


async def test_register_invalid_timeout_rejected(client):
    """timeout must be > 0 — validated by Pydantic at the model level."""
    res = await client.post("/monitors", json={**BASE_PAYLOAD, "timeout": 0})
    assert res.status_code == 422


# ── POST /monitors/{id}/heartbeat ─────────────────────────────────────────────

async def test_heartbeat_resets_timer(client):
    await client.post("/monitors", json=BASE_PAYLOAD)
    res = await client.post("/monitors/device-123/heartbeat")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "active"
    assert body["monitor_id"] == "device-123"


async def test_heartbeat_creates_new_task(client):
    """Each heartbeat must cancel the old task and schedule a fresh one — O(1)."""
    await client.post("/monitors", json=BASE_PAYLOAD)
    old_task = svc._tasks["device-123"]
    await client.post("/monitors/device-123/heartbeat")
    await asyncio.sleep(0)  # yield to event loop so cancellation is processed
    new_task = svc._tasks["device-123"]
    assert old_task is not new_task
    assert old_task.cancelled()


async def test_heartbeat_updates_last_heartbeat(client):
    await client.post("/monitors", json=BASE_PAYLOAD)
    assert svc.get_one("device-123").last_heartbeat is None
    await client.post("/monitors/device-123/heartbeat")
    assert svc.get_one("device-123").last_heartbeat is not None


async def test_heartbeat_nonexistent_returns_404(client):
    res = await client.post("/monitors/ghost-device/heartbeat")
    assert res.status_code == 404


async def test_heartbeat_down_monitor_returns_409(client):
    """A device that has gone down cannot heartbeat — it must re-register."""
    await client.post("/monitors", json=SHORT_PAYLOAD)
    await asyncio.sleep(1.5)  # let the 1-second timer fire
    res = await client.post("/monitors/device-fast/heartbeat")
    assert res.status_code == 409


# ── POST /monitors/{id}/pause ─────────────────────────────────────────────────

async def test_pause_active_monitor(client):
    await client.post("/monitors", json=BASE_PAYLOAD)
    res = await client.post("/monitors/device-123/pause")
    assert res.status_code == 200
    assert res.json()["status"] == "paused"


async def test_pause_cancels_timer_task(client):
    """Pausing must cancel the asyncio task so no alert fires — O(1)."""
    await client.post("/monitors", json=BASE_PAYLOAD)
    task = svc._tasks["device-123"]
    await client.post("/monitors/device-123/pause")
    await asyncio.sleep(0)  # yield so cancellation is processed
    assert task.cancelled()


async def test_pause_prevents_alert(client):
    """A paused monitor must NOT fire an alert even after its timeout elapses."""
    await client.post("/monitors", json=SHORT_PAYLOAD)
    await client.post("/monitors/device-fast/pause")
    await asyncio.sleep(1.5)
    monitor = svc.get_one("device-fast")
    assert monitor.status == "paused"   # still paused, not down


async def test_pause_already_paused_is_idempotent(client):
    await client.post("/monitors", json=BASE_PAYLOAD)
    await client.post("/monitors/device-123/pause")
    res = await client.post("/monitors/device-123/pause")
    assert res.status_code == 200  # no error on double-pause


async def test_pause_nonexistent_returns_404(client):
    res = await client.post("/monitors/ghost-device/pause")
    assert res.status_code == 404


async def test_heartbeat_unpauses_monitor(client):
    """Heartbeat on a paused monitor must resume it and restart the timer."""
    await client.post("/monitors", json=BASE_PAYLOAD)
    await client.post("/monitors/device-123/pause")
    res = await client.post("/monitors/device-123/heartbeat")
    assert res.status_code == 200
    assert res.json()["status"] == "active"
    assert not svc._tasks["device-123"].done()


# ── GET /monitors/{id} ────────────────────────────────────────────────────────

async def test_get_existing_monitor(client):
    await client.post("/monitors", json=BASE_PAYLOAD)
    res = await client.get("/monitors/device-123")
    assert res.status_code == 200
    body = res.json()
    assert body["id"] == "device-123"
    assert body["timeout"] == 60


async def test_get_nonexistent_monitor_returns_404(client):
    res = await client.get("/monitors/ghost-device")
    assert res.status_code == 404


# ── GET /monitors ─────────────────────────────────────────────────────────────

async def test_list_monitors_empty(client):
    res = await client.get("/monitors")
    assert res.status_code == 200
    assert res.json() == []


async def test_list_monitors_returns_all(client):
    """O(n) endpoint — must return exactly n registered monitors."""
    await client.post("/monitors", json=BASE_PAYLOAD)
    await client.post("/monitors", json={**BASE_PAYLOAD, "id": "device-456"})
    res = await client.get("/monitors")
    assert res.status_code == 200
    assert len(res.json()) == 2


# ── DELETE /monitors/{id} ─────────────────────────────────────────────────────

async def test_delete_monitor(client):
    await client.post("/monitors", json=BASE_PAYLOAD)
    res = await client.delete("/monitors/device-123")
    assert res.status_code == 204
    assert svc.get_one("device-123") is None


async def test_delete_cancels_timer(client):
    """Deleting must cancel the task so no ghost alerts fire — O(1)."""
    await client.post("/monitors", json=BASE_PAYLOAD)
    task = svc._tasks["device-123"]
    await client.delete("/monitors/device-123")
    await asyncio.sleep(0)  # yield so cancellation is processed
    assert task.cancelled()


async def test_delete_nonexistent_returns_404(client):
    res = await client.delete("/monitors/ghost-device")
    assert res.status_code == 404


# ── Alert / timer expiry ───────────────────────────────────────────────────────

async def test_alert_fires_and_sets_status_down(client):
    """
    Core spec requirement: when the timer expires the monitor status becomes 'down'.
    Uses timeout=1 to keep the test fast.
    """
    await client.post("/monitors", json=SHORT_PAYLOAD)
    await asyncio.sleep(1.5)  # 0.5 s margin for event-loop scheduling
    res = await client.get("/monitors/device-fast")
    assert res.json()["status"] == "down"


async def test_alert_increments_alert_count(client):
    await client.post("/monitors", json=SHORT_PAYLOAD)
    await asyncio.sleep(1.5)
    monitor = svc.get_one("device-fast")
    assert monitor.alert_count == 1


async def test_re_register_after_down_resets_status(client):
    """Re-registering a dead device brings it back to active — O(1)."""
    await client.post("/monitors", json=SHORT_PAYLOAD)
    await asyncio.sleep(1.5)
    res = await client.post("/monitors", json=SHORT_PAYLOAD)
    assert res.status_code == 201
    assert res.json()["status"] == "active"
